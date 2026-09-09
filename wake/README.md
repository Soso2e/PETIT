# PETIT Wake Word

PETIT の最終的な Wake Word 基盤は、外部 AccessKey に依存しない完全ローカル方式を目標とする。

## Target

- Default phrase: `Hey PETIT / ヘイプティ / へいプティ`
- No account / AccessKey / cloud dependency at runtime
- Model artifact is shared across Windows / macOS / iOS where possible
- Waiting audio stays on-device and is not saved or uploaded
- Runtime must be replaceable behind a small Wake Engine interface

## Model strategy

The canonical PETIT classifier is trained with openWakeWord and exported as ONNX. A TFLite export may also be kept when a platform runtime benefits from it.

Tracked artifacts should be small deployable models only. Generated audio, negative corpora, feature caches and training datasets must not be committed to Git.

Planned model files:

- `models/hey_petit.onnx` — canonical classifier
- `models/hey_petit.tflite` — optional mobile/runtime export
- `models/model-card.md` — phrase, dataset recipe, thresholds and measured quality

## Runtime plan

### Windows

Use the PETIT wake classifier with a local native/ONNX runtime helper. Keep microphone capture outside the Electron renderer and emit only `ready`, `wake`, and generic error/status events to Electron.

### macOS

Use the same classifier. Prefer a native helper capable of CoreML/Apple acceleration rather than a permanent Python dependency. The existing Electron utility-process boundary remains the integration point.

### iPhone / iOS

Reuse the same classifier in a native iOS companion/runtime. openWakeWord-compatible native implementations can run the classifier locally. A PWA cannot be treated as a reliable Siri-like always-listening background runtime; foreground wake detection or Siri/Shortcut activation remains the PWA fallback.

## Migration from Porcupine

Current `feat/petit-desktop` uses Picovoice Porcupine and requires an AccessKey, `.ppn`, and `.pv`. Migration must preserve the current wake lifecycle (pause while PETIT is visible/settings are open/locked/asleep, resume when appropriate) while replacing Porcupine-specific configuration.

Do not remove the Porcupine path until the openWakeWord model passes the quality gate below.

## Quality gate

A model is not promoted to default only because it detects the phrase once. Record at least:

- intended wake recall
- false accepts per hour
- median / p95 wake latency
- idle CPU
- idle memory
- battery/power impact where measurable
- model/runtime size added to the app
- Windows and macOS results separately
- noisy-room / TV / music / distant-mic cases

Initial acceptance target:

- >= 95% recall in ordinary near-field use
- <= 0.2 false accepts/hour in representative background audio
- no cloud/network requirement

Thresholds may be tuned per platform while keeping the classifier shared.

## Personal verifier

A later optional phase may add a user-specific verifier to reduce wake-ups from TV or other people. This must be optional; generic `Hey PETIT` detection remains usable without enrollment.
