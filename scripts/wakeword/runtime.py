"""Local openWakeWord microphone runtime for PETIT Desktop."""
import argparse, json, signal, sys
import numpy as np
import sounddevice as sd
from openwakeword.model import Model
running = True
def stop(*_args):
    global running; running = False
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--model', required=True); parser.add_argument('--backbone', required=True)
    parser.add_argument('--threshold', type=float, default=0.45); parser.add_argument('--device', type=int)
    args = parser.parse_args(); signal.signal(signal.SIGTERM, stop); signal.signal(signal.SIGINT, stop)
    detector = Model(wakeword_models=[args.model], inference_framework='onnx',
        melspec_model_path=f'{args.backbone}/melspectrogram.onnx',
        embedding_model_path=f'{args.backbone}/embedding_model.onnx')
    print(json.dumps({'type': 'ready'}), flush=True)
    with sd.RawInputStream(samplerate=16000, blocksize=1280, channels=1, dtype='int16', device=args.device) as stream:
        while running:
            data, _ = stream.read(1280)
            score = float(detector.predict(np.frombuffer(data, dtype=np.int16)).get('hey_petit', 0.0))
            if score >= args.threshold:
                print(json.dumps({'type': 'wake'}), flush=True); return
if __name__ == '__main__':
    try: main()
    except Exception: print(json.dumps({'type': 'error', 'code': 'microphone'}), flush=True); sys.exit(1)
