"""Score a local mono PCM16 / 16 kHz WAV without opening a microphone."""
import argparse
import json
from pathlib import Path

import numpy as np
from openwakeword.model import Model
from scipy.io import wavfile


def main():
    root = Path(__file__).resolve().parents[2] / "storage/wakeword"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wav", type=Path)
    parser.add_argument("--model", type=Path, default=root / "models/v0.1/hey_petit.onnx")
    parser.add_argument("--backbone", type=Path, default=root / "backbone")
    parser.add_argument("--threshold", type=float)
    args = parser.parse_args()
    threshold = args.threshold
    if threshold is None:
        report = json.loads((args.model.parent / "report.json").read_text(encoding="utf-8"))
        threshold = report["validation"]["threshold"]
    if not 0 < threshold < 1:
        parser.error("threshold must be between 0 and 1")
    sr, audio = wavfile.read(args.wav)
    if sr != 16000 or audio.dtype != np.int16 or audio.ndim != 1:
        parser.error("WAV must be mono PCM16 at 16000 Hz")
    if not len(audio):
        parser.error("WAV is empty")
    model = Model(wakeword_models=[str(args.model)], inference_framework="onnx",
                  melspec_model_path=str(args.backbone / "melspectrogram.onnx"),
                  embedding_model_path=str(args.backbone / "embedding_model.onnx"))
    audio = np.pad(audio, (0, (-len(audio)) % 1280))
    events, scores = [], []
    last_event = -2.
    for offset in range(0, len(audio), 1280):
        score = float(model.predict(audio[offset:offset+1280])[args.model.stem])
        scores.append(score)
        seconds = (offset+1280)/16000
        if score >= threshold and seconds-last_event >= 2:
            events.append(round(seconds, 2))
            last_event = seconds
    print(json.dumps({"maximum": max(scores), "threshold": threshold,
                      "events_seconds": events, "debounce_seconds": 2}, indent=2))


if __name__ == "__main__":
    main()
