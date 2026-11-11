# Speech Emotion API — two prediction entry points

[简体中文](README.zh-CN.md)

A local Windows CPU FastAPI service using `iic/emotion2vec_plus_seed` through FunASR. Start one server for both endpoints, then choose the matching workflow:

| | `POST /predict` | `POST /predict_multi` |
| --- | --- | --- |
| Input | Exactly one multipart file field: `file` | Exactly two multipart **file** fields: `file` (media) and `xml` (transcript) |
| Media | WAV, MP3, MP4, M4A; case-insensitive extensions | Same formats; the first audio track is mixed to mono |
| Output | JSON with `filename`, `model`, English `emotion`/`score`, and nine aligned `labels`/`scores` | UTF-8 `application/xml` attachment, `predicted-transcript.xml` |
| Processing | Predict the complete 0.25–30 second recording | Decode media once; predict each XML speech interval and update its `emotion` |
| Run | `/docs` → `/predict` → upload `file` → Execute | `/docs` → `/predict_multi` → upload both files → Execute |
| Follow the code | [Single-file call flow](docs/api-flows.md#post-predict) | [XML call flow](docs/api-flows.md#post-predict-multi) |
| Find failures/results | [Errors](#errors) · [Verification](#verification) | [Errors](#errors) · [Verification](#verification) |

## Start and send a request

Run from the repository root in the existing environment:

```powershell
conda activate emotion2vec
python -m uvicorn app:app --host 127.0.0.1 --port 8000 --workers 1
```

Wait for `Application startup complete`, then open <http://127.0.0.1:8000/docs>. Keep that terminal running; stop with Ctrl+C. Use one worker and omit `--reload` to avoid extra model loads. If port 8000 is occupied, choose another available port and use its URL. `/health` reports readiness without inference. Importing `app.py` alone does not load weights.

```powershell
curl.exe -X POST http://127.0.0.1:8000/predict -F "file=@path/to/speech.wav"
curl.exe -X POST http://127.0.0.1:8000/predict_multi -F "file=@samples/news-video-with-captions 2.mp4" -F "xml=@samples/news-video-with-captions 1.xml" --output test-artifacts/predicted-transcript.xml
```

Create `test-artifacts/` before saving output there. The sample files are local and Git-ignored; they are not bundled with a checkout. On failure, the response is JSON rather than XML, so check the HTTP status before treating the downloaded body as a transcript.

[Environment and model startup details](docs/environment.md) include Python/tool requirements, environment limitations and checkpoint provenance. `requirements.txt` contains API additions, not a complete environment. Model startup may contact the hub even with cached weights; the historical offline verification launcher is not a public app setting. This project performs inference, not training.

## Processing contract and limits

`/predict_multi` accepts one unnamespaced `AudioDoc` root with exactly one direct `SegmentList` and 1–1000 direct `SpeechSegment` children. `stime` and `dur` are seconds: `end = stime + dur`; intervals are `[start, end)` relative to the first decoded audio sample. All times and decoded ranges are checked before inference. XML order is preserved even when segments are not chronological.

Only `SpeechSegment.emotion` is added or replaced. Other attributes, including `score`, text/tails, Words and image/sound captions are preserved semantically. In-root comments/PIs are retained; formatting, quotes and equivalent escaping may change. `<unk>` is serialized as `&lt;unk&gt;`. Existing emotions are not ground truth. DTD/entity declarations and external entity resolution are rejected. XML `channel="1"` is metadata, not an instruction to select the left stereo channel.

Both routes share the loaded CPU model, request gate and inference lock. Blocking work runs in a threadpool. `/predict` probes with FFprobe before conversion; `/predict_multi` directly decodes the first audio track once with FFmpeg, reads segments by sample offsets and calls **`predict_samples()`**, not `predict_segment()` and not an internal HTTP endpoint. Standard audio is mono, 16 kHz, PCM16 WAV; inference receives float32 NumPy samples.

| Limit | `/predict` | `/predict_multi` |
| --- | --- | --- |
| Media file | 25 MiB | 128 MiB |
| XML file | Not accepted | 2 MiB |
| Total body including multipart | 26 MiB | 131 MiB |
| Complete decoded audio | 0.25–30 s | At most 1800 s |
| Each speech segment | Whole recording is one input | 0.25–30 s |
| Segment count | Not applicable | 1–1000 |
| FFprobe timeout | 20 s | Not called in this route |
| FFmpeg timeout | 45 s | 120 s |
| Decoder duration cap | 31 s, then reject audio over 30 s | 1801 s, then reject audio over 1800 s |
| Decoder output cap | Duration/format bounded | 57,697,536 bytes |
| XML nesting / response size | Not applicable | 128 levels / 16 MiB |

Subprocess timeouts are not inference, queue-wait or whole-request timeouts. Multi-segment requests return XML only after every segment succeeds; no partial output, truncated clip or silence padding is returned. Request temporary directories are removed on success/errors; forced process termination can leave files.

English labels retain score alignment: `angry`, `disgusted`, `fearful`, `happy`, `neutral`, `other`, `sad`, `surprised`, `<unk>`. `/predict` selects the maximum score using the model's returned order. Scores are model outputs, not accuracy measurements or calibrated correctness guarantees.

## Python segment function

`predict_segment(state, source, start, end, filename=None)` is a directly callable synchronous Python function in [app.py](app.py), not an HTTP endpoint. Pass the initialized application state to reuse its model and lock. It extracts a temporary mono/16 kHz/PCM16 WAV through `extract_audio_segment()` and returns a `Prediction`; it cleans up on either outcome. Each selected segment must be 0.25–30 seconds; there is no 30-second source-media limit. Extraction has a 45-second timeout and starts decoding from the beginning, so repeated calls are not the multi-endpoint strategy. Async callers should use `run_in_threadpool`.

[Function details and callers](docs/function-index.zh-CN.md#app-predict-segment) · [Shared inference](docs/function-index.zh-CN.md#app-predict-samples)

## Errors

**One lookup for both endpoints:** [API error reference](docs/api-errors.md). It lists shared errors once, then route-specific triggers, status codes, message examples and source functions. Segment errors use the **1-based XML element index**, not chronological order. Startup failures are distinguished from HTTP responses. Invalid media metadata is not proof of decodable content.

## Verification

Run existing generated-media/fake-model tests from the repository root; no server, weights or new dependencies are required beyond the existing environment and FFmpeg:

```powershell
python -m unittest discover -s tests -t . -v
# Targeted modules:
python -m unittest -v tests.test_audio_segments tests.test_predict_multi
```

To check a separately running `/predict` service with real speech:

```powershell
python -m scripts.verify_predict_http "path/to/real-speech.wav" --url http://127.0.0.1:8000
```

This tool does not start a server or test `/predict_multi`. It converts actual speech into test formats and writes fresh media plus `test-artifacts/results.json`; it does not overwrite historical reports. Its `--help` entry point does not run inference.

| Scope | Code / retained evidence | What it establishes |
| --- | --- | --- |
| Single segment preprocessing | [tests/test_audio_segments.py](tests/test_audio_segments.py), 10 tests | Waveform/timestamp accuracy, mono/16 kHz/PCM16, rejection paths, fake inference wiring and cleanup |
| XML endpoint | [tests/test_predict_multi.py](tests/test_predict_multi.py), 16 tests | 65 generated intervals, English updates/escaping and semantic preservation; invalid uploads/XML/ranges; one decode; gate/threading and cleanup |
| `/predict` real HTTP regression | [scripts/verify_predict_http.py](scripts/verify_predict_http.py); [historical report](reports/functional-verification.md), [raw responses](reports/http-functional-results.json), [real-model rerun](reports/real-model-segment-verification-2026-10-31.md) | 18 POST cases plus health/docs/schema and label/score checks; original records remain retained |
| `/predict_multi` real HTTP acceptance | [Full verification report](reports/predict-multi-verification-2026-11-02.md) | HTTP 200, 65 actual model calls, **43.373 s excluding startup**, one decode, XML preservation and cleanup |

The incomplete-download failure remains in the full report as resolved history: replacing the 55,062,440-byte partial video with the verified 71,215,895-byte complete copy fixed the input without relaxed validation. Final local XML: `test-artifacts/supervisor-complete-emotions.xml`. Historical raw responses may contain bilingual labels; current output is English.

**Functional verification is not classification accuracy evaluation.** There is no independently labeled test set, accuracy/F1/confusion matrix, calibration study or systematic performance benchmark. Fake-model tests do not establish real-model correctness. One observed request duration is not a throughput guarantee.

## Code and documentation map

```text
app.py                       FastAPI entry points, startup and shared processing
scripts/verify_predict_http.py  Real-HTTP verification CLI for /predict
tests/                      Generated-media/fake-model unittest package
docs/                       Call flows, error lookup, function index, learning
reports/                    Retained functional verification records
environment/                Recorded dependency snapshot
samples/                    Local input media/XML (ignored)
test-artifacts/             Generated outputs/logs (ignored)
.tmp/                       Per-request working files (ignored)
```

Both `scripts/` and `tests/` have package entry points; use `python -m ...` or unittest discovery from the root rather than executing their files directly. All three callers import the shared `app` module; moving its state into separate modules would add indirection to the current small application.

- [Call flows for both endpoints](docs/api-flows.md) → [all project-defined functions and methods](docs/function-index.zh-CN.md), including internal helpers and tests.
- [01 — Single-file foundations (Chinese)](docs/01-single-file-api-learning.zh-CN.md).
- [02 — Segment/XML request walkthrough (Chinese)](docs/02-segment-xml-api-learning.zh-CN.md).
- [Environment details](docs/environment.md); [dependency additions](requirements.txt); [recorded pip snapshot](environment/pip-snapshot.txt), not a portable lockfile.
