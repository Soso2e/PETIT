# PETIT Wake Model Card

## Identity

- Model: `hey_petit`
- Version: not trained yet
- Wake phrase: `Hey PETIT / ヘイプティ / へいプティ`
- Framework: openWakeWord
- Canonical artifact: `hey_petit.onnx`

## Training

- Synthetic positives: TBD
- Real PETIT-user recordings: TBD
- Negative corpus: TBD
- Custom hard negatives: `hey siri`, `ペット`, `プチ` + observed false activations
- Augmentation/noise conditions: TBD

## Runtime thresholds

- Windows threshold: TBD
- macOS threshold: TBD
- iOS threshold: TBD
- Trigger/debounce policy: TBD

## Evaluation

| Platform | Device | Recall | False accepts/hour | Median latency | p95 latency | Idle CPU | RAM | Power/Battery | Runtime+model size |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Windows | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| macOS | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| iOS foreground/native | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |

## Scenario tests

- Quiet room: TBD
- 1–3 m distance: TBD
- Music playing: TBD
- TV / YouTube voices: TBD
- PC fan / air conditioner: TBD
- Different speakers: TBD
- User voice: TBD

## Decision

Do not mark this model as PETIT default until the measured quality gate in `../README.md` is met.
