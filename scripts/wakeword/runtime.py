"""Local openWakeWord microphone runtime for PETIT Desktop."""
import argparse
import json
import signal
import sys

import numpy as np
import sounddevice as sd
from openwakeword.model import Model

running = True


def stop(*_args):
    global running
    running = False


def emit(message_type, code=None):
    payload = {"type": message_type}
    if code:
        payload["code"] = code
    print(json.dumps(payload), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--model', required=True)
    parser.add_argument('--backbone', required=True)
    parser.add_argument('--threshold', type=float, default=0.45)
    parser.add_argument('--device', type=int)
    parser.add_argument('--diagnose', action='store_true', help='Validate runtime/model assets without opening a microphone.')
    args = parser.parse_args()
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    try:
        detector = Model(
            wakeword_models=[args.model],
            inference_framework='onnx',
            melspec_model_path=f'{args.backbone}/melspectrogram.onnx',
            embedding_model_path=f'{args.backbone}/embedding_model.onnx',
        )
    except Exception:
        emit('error', 'model')
        return 2

    if args.diagnose:
        emit('ready')
        return 0

    try:
        with sd.RawInputStream(
            samplerate=16000,
            blocksize=1280,
            channels=1,
            dtype='int16',
            device=args.device,
        ) as stream:
            emit('ready')
            while running:
                data, _ = stream.read(1280)
                score = float(detector.predict(np.frombuffer(data, dtype=np.int16)).get('hey_petit', 0.0))
                if score >= args.threshold:
                    emit('wake')
                    return 0
    except Exception:
        emit('error', 'microphone')
        return 3
    return 0


if __name__ == '__main__':
    sys.exit(main())
