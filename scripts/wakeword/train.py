"""Train an experimental Japanese head on openWakeWord's frozen embeddings.

Local SAPI data only; not the upstream large-corpus training recipe.
Speaker splits are fixed before augmentation. No microphone is opened.
"""
import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import warnings

import numpy as np
import onnx
from onnx import TensorProto, helper, numpy_helper
import onnxruntime as ort
from openwakeword.model import Model
from openwakeword.utils import AudioFeatures
import requests
from scipy.io import wavfile
from sklearn.neural_network import MLPClassifier
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / "storage/wakeword"
FRAMES = 16
SEED = 258


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def feature_models():
    directory = WORK / "backbone"
    directory.mkdir(parents=True, exist_ok=True)
    for name in ("melspectrogram", "embedding_model"):
        dest = directory / f"{name}.onnx"
        if not dest.exists():
            url = f"https://github.com/dscripka/openWakeWord/releases/download/v0.5.1/{dest.name}"
            response = requests.get(url, timeout=180)
            response.raise_for_status()
            temporary = dest.with_suffix(".part")
            temporary.write_bytes(response.content)
            onnx.checker.check_model(str(temporary))
            temporary.replace(dest)
        onnx.checker.check_model(str(dest))
    return dict(melspec_model_path=str(directory / "melspectrogram.onnx"),
                embedding_model_path=str(directory / "embedding_model.onnx"))


def read_audio(path):
    sr, x = wavfile.read(path)
    if sr != 16000 or x.dtype != np.int16 or x.ndim != 1:
        raise ValueError(f"Expected mono 16 kHz PCM16: {path}")
    active = np.flatnonzero(np.abs(x.astype(np.float32)) > 100)
    if not len(active):
        raise ValueError(f"Silent source: {path}")
    return x[max(0, active[0] - 160):active[-1] + 161]


def augment(x, rng, noisy=True):
    audio = np.pad(x.astype(np.float32), (24000, 12800))
    if noisy:
        audio *= rng.uniform(.35, 1.2)
        delay = int(rng.uniform(.02, .12) * 16000)
        audio[delay:] += rng.uniform(0, .18) * audio[:-delay].copy()
        audio += rng.normal(0, rng.uniform(0, 160), len(audio))
    return np.clip(audio, -32768, 32767).astype(np.int16)


def dataset(rows, audio_dir, extractor, rng):
    features, labels = [], []
    for index, row in enumerate(rows):
        x = read_audio(audio_dir / row["file"])
        positive = row["label"] == "positive"
        for _ in range(10 if positive else 2):
            audio = augment(x, rng)
            emb = extractor._get_embeddings(audio)
            # Embedding i ends at ~0.76 + i*0.08 seconds.
            end_time = (24000 + len(x)) / 16000
            for end in range(FRAMES, len(emb) + 1):
                t = .76 + (end - 1) * .08
                if positive:
                    if not (end_time <= t <= end_time + .32):
                        continue
                elif rng.random() > .3:
                    continue
                features.append(emb[end-FRAMES:end])
                labels.append(int(positive))
        if index % 100 == 0:
            print(f"features {index}/{len(rows)}", flush=True)
    # Noise and silence are additional negatives, not substitutes for speech.
    for level in (0, 50, 200, 1000, 4000):
        for _ in range(16):
            audio = np.clip(rng.normal(0, level, 64000), -32768, 32767).astype(np.int16)
            emb = extractor._get_embeddings(audio)
            features.extend(emb[i-FRAMES:i] for i in range(FRAMES, len(emb)+1, 4))
            labels.extend([0] * len(range(FRAMES, len(emb)+1, 4)))
    return np.asarray(features, dtype=np.float32), np.asarray(labels)


def export(scaler, classifier, path):
    nodes = [helper.make_node("Flatten", ["input"], ["flat"], axis=1),
             helper.make_node("Sub", ["flat", "mean"], ["centered"]),
             helper.make_node("Div", ["centered", "scale"], ["scaled"])]
    initializers = [numpy_helper.from_array(scaler.mean_.astype(np.float32), "mean"),
                    numpy_helper.from_array(scaler.scale_.astype(np.float32), "scale")]
    previous = "scaled"
    for i, (weight, bias) in enumerate(zip(classifier.coefs_, classifier.intercepts_)):
        last = i == len(classifier.coefs_) - 1
        output = "score" if last else f"hidden{i}"
        initializers.extend([numpy_helper.from_array(weight.astype(np.float32), f"w{i}"),
                             numpy_helper.from_array(bias.astype(np.float32), f"b{i}")])
        nodes.extend([helper.make_node("Gemm", [previous, f"w{i}", f"b{i}"], [f"linear{i}"]),
                      helper.make_node("Sigmoid" if last else "Relu", [f"linear{i}"], [output])])
        previous = output
    graph = helper.make_graph(nodes, "hey_petit_v0.1",
        [helper.make_tensor_value_info("input", TensorProto.FLOAT, [None, FRAMES, 96])],
        [helper.make_tensor_value_info("score", TensorProto.FLOAT, [None, 1])], initializers)
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 13)], ir_version=10)
    helper.set_model_props(model, {"version": "0.1", "phrase": "へいプティ",
        "status": "experimental-synthetic-only", "openwakeword": "0.6.0"})
    onnx.checker.check_model(model)
    onnx.save(model, path)


def score_clips(rows, audio_dir, model_path, backbone):
    detector = Model(wakeword_models=[str(model_path)], inference_framework="onnx", **backbone)
    results = []
    for row in rows:
        audio = augment(read_audio(audio_dir / row["file"]), np.random.default_rng(SEED), noisy=False)
        detector.reset()
        scores = [float(detector.predict(audio[i:i+1280])["hey_petit"])
                  for i in range(0, len(audio)-1279, 1280)]
        results.append(dict(file=row["file"], label=row["label"], phrase=row["phrase"],
                            maximum=max(scores), seconds=len(audio)/16000))
    return results


def metrics(results, threshold):
    threshold = float(threshold)
    pos = [r for r in results if r["label"] == "positive"]
    neg = [r for r in results if r["label"] == "negative"]
    return {"threshold": float(threshold), "positive_clips": len(pos), "negative_clips": len(neg),
            "detected_positive_clips": sum(r["maximum"] >= threshold for r in pos),
            "false_positive_clips": sum(r["maximum"] >= threshold for r in neg),
            "recall": sum(r["maximum"] >= threshold for r in pos)/len(pos),
            "negative_clip_fpr": sum(r["maximum"] >= threshold for r in neg)/len(neg)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download-only", action="store_true")
    parser.add_argument("--audio", type=Path, default=WORK / "audio")
    parser.add_argument("--output", type=Path, default=WORK / "models/v0.1")
    args = parser.parse_args()
    backbone = feature_models()
    if args.download_only:
        print("Backbone ONNX models verified")
        return
    if args.output.exists():
        raise SystemExit("Output already exists; use a new --output directory to preserve artifacts.")
    manifest = args.audio / "manifest.json"
    rows = json.loads(manifest.read_text(encoding="utf-8-sig"))
    splits = {s: [r for r in rows if r["split"] == s] for s in ("train", "validation", "test")}
    for s, items in splits.items():
        if {r["label"] for r in items} != {"positive", "negative"}:
            raise ValueError(f"Both classes required in {s}")
    speakers = {s: {r["voice"] for r in items} for s, items in splits.items()}
    if any(speakers[a] & speakers[b] for a, b in (("train", "validation"), ("train", "test"), ("validation", "test"))):
        raise ValueError("Speaker leakage between splits")
    np.random.seed(SEED)
    extractor = AudioFeatures(inference_framework="onnx", **backbone)
    x, y = dataset(splits["train"], args.audio, extractor, np.random.default_rng(SEED))
    flat = x.reshape(len(x), -1)
    scaler = StandardScaler().fit(flat)
    classifier = MLPClassifier(hidden_layer_sizes=(64,), batch_size=128, max_iter=100,
                               random_state=SEED, early_stopping=False, alpha=.01)
    with warnings.catch_warnings(record=True) as captured, threadpool_limits(limits=4):
        classifier.fit(scaler.transform(flat), y)
    args.output.mkdir(parents=True)
    path = args.output / "hey_petit.onnx"
    export(scaler, classifier, path)
    session = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
    actual = session.run(None, {"input": x[:32]})[0][:, 0]
    expected = classifier.predict_proba(scaler.transform(flat[:32]))[:, 1]
    np.testing.assert_allclose(actual, expected, atol=2e-5, rtol=2e-5)
    validation = score_clips(splits["validation"], args.audio, path, backbone)
    candidates = [metrics(validation, t) for t in np.arange(.1, 1., .05)]
    chosen = min(candidates, key=lambda m: 1-m["recall"] + 2*m["negative_clip_fpr"])
    test = score_clips(splits["test"], args.audio, path, backbone)
    report = {"version": "0.1", "status": "experimental-synthetic-only", "seed": SEED,
        "training_windows": len(x), "positive_windows": int(y.sum()),
        "speaker_splits": {s: sorted(v) for s,v in speakers.items()},
        "validation": chosen, "test": metrics(test, chosen["threshold"]),
        "validation_thresholds": candidates, "validation_clips": validation, "test_clips": test,
        "export_max_error": float(np.max(np.abs(actual-expected))),
        "warnings": [str(w.message) for w in captured],
        "sha256": {"hey_petit.onnx": digest(path), "manifest.json": digest(manifest),
                   **{Path(p).name: digest(Path(p)) for p in backbone.values()}},
        "packages": {p: importlib.metadata.version(p) for p in
                     ("openwakeword", "onnx", "onnxruntime", "numpy", "scipy", "scikit-learn")},
        "limitations": ["Synthetic SAPI voices only; not independent human speakers.",
            "No microphone, far-field, TV/music or long-duration negative evaluation.",
            "Negative clip FPR is not false activations per hour.",
            "Japanese is outside openWakeWord's officially supported language.",
            "Desktop still uses Porcupine; this model is not integrated."]}
    (args.output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"model": str(path), "validation": chosen, "test": report["test"]}, indent=2))


if __name__ == "__main__":
    main()
