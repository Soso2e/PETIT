"""Focused regression checks for evaluation and ONNX deployment boundaries."""
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
import onnxruntime as ort
from sklearn.neural_network import MLPClassifier
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

from train import export, metrics


class TrainingTests(unittest.TestCase):
    def test_numpy_threshold_serializes_and_counts_boundary(self):
        rows = [{"label": "positive", "maximum": .5},
                {"label": "negative", "maximum": .49}]
        report = json.loads(json.dumps(metrics(rows, np.float64(.5))))
        self.assertEqual(report["detected_positive_clips"], 1)
        self.assertEqual(report["false_positive_clips"], 0)

    def test_onnx_dynamic_batch_matches_classifier(self):
        rng = np.random.default_rng(7)
        x = rng.normal(size=(48, 16, 96)).astype(np.float32)
        y = np.arange(len(x)) % 2
        scaler = StandardScaler().fit(x.reshape(len(x), -1))
        model = MLPClassifier(hidden_layer_sizes=(4,), solver="lbfgs", random_state=7, max_iter=100)
        with threadpool_limits(limits=2):
            model.fit(scaler.transform(x.reshape(len(x), -1)), y)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "hey_petit.onnx"
            export(scaler, model, path)
            session = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
            for batch_size in (1, 7, 48):
                values = x[:batch_size]
                result = session.run(None, {"input": values})[0]
                self.assertEqual(result.shape, (batch_size, 1))
                np.testing.assert_allclose(result[:, 0], model.predict_proba(
                    scaler.transform(values.reshape(batch_size, -1)))[:, 1], atol=2e-5, rtol=2e-5)
            del session


if __name__ == "__main__":
    unittest.main()
