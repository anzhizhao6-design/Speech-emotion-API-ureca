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

Create the output directory before downloading a response; local sample inputs and generated files are described in the [directory guide](#local-data). On failure, the response is JSON rather than XML, so check its HTTP status. For tool requirements, checkpoint provenance and startup caveats, use the [environment guides](#docs).

## Processing contract and limits

`/predict_multi` accepts one unnamespaced `AudioDoc` root with exactly one direct `SegmentList` and 1–1000 direct `SpeechSegment` children. `stime` and `dur` are seconds: `end = stime + dur`; intervals are `[start, end)` relative to the first decoded audio sample. All times and decoded ranges are checked before inference. XML order is preserved even when segments are not chronological.

Only `SpeechSegment.emotion` is added or replaced. Other attributes, including `score`, text/tails, Words and image/sound captions are preserved semantically. In-root comments/PIs are retained; formatting, quotes and equivalent escaping may change. `<unk>` is serialized as `&lt;unk&gt;`. Existing emotions are not ground truth. DTD/entity declarations and external entity resolution are rejected. XML `channel="1"` is metadata, not an instruction to select the left stereo channel.

Both routes share the loaded CPU model, request gate and inference lock, with blocking work in a threadpool. The [English function index](docs/function-index.md) follows the two routes through their workers and shared inference; the [call flows](docs/api-flows.md) include the framework and media-tool steps.

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

[predict_segment(state, source, start, end, filename=None)](app.py#L261) is a synchronous Python helper, not an HTTP route: it extracts and predicts one 0.25–30 second interval from a local file using the initialized model and lock. Its repeated-extraction strategy is separate from `/predict_multi`; see the [direct-helper flow](docs/api-flows.md#direct-python-segment-helper) for extraction, cleanup and async-caller details.

## Errors

**One lookup for both endpoints:** [API error reference](docs/api-errors.md), covering shared failures, route-specific conditions, original messages and status codes, and startup or direct-Python exceptions.

## Verification

Run the existing [generated-media and fake-model tests](#tests) from the repository root in the environment with FFmpeg; no server or real model is needed:

```powershell
python -m unittest discover -s tests -t . -v
```

To use the [HTTP verification client](#scripts), first [start the server](#start-and-send-a-request), then provide real speech:

```powershell
python -m scripts.verify_predict_http "path/to/real-speech.wav" --url http://127.0.0.1:8000
```

The retained results are **26 generated-media/fake-model tests** and **18 `/predict` HTTP cases** passing, plus a real `/predict_multi` request returning **HTTP 200 for all 65 segments in 43.373 seconds excluding startup**, with one decode, XML preservation and cleanup confirmed. The incomplete-download failure was resolved by re-downloading the video without relaxing validation. See the [report guide](#reports) for the individual runs and raw evidence; the final local XML is listed under [local data](#local-data).

**Functional verification is not classification accuracy evaluation.** There is no independently labeled test set, accuracy/F1/confusion matrix, calibration study or systematic performance benchmark. Fake-model tests do not establish real-model correctness, and one request duration is not a throughput guarantee.

## Code and documentation map

All module commands above run from the repository root; `scripts/` and `tests/` are packages, so use `python -m ...` rather than running their files directly.

### Root files

- [app.py](app.py): the FastAPI application, shared startup/state, and audio/XML processing used by both routes.
- [README.zh-CN.md](README.zh-CN.md): the Chinese usage guide and repository navigation.
- [requirements.txt](requirements.txt): pinned API additions, not a complete model environment.
- [.gitignore](.gitignore): excludes samples, generated media, logs, caches, weights and temporary files from Git.

<a id="docs"></a>
### docs/

Reference material and learning guides:

- [api-flows.md](docs/api-flows.md): each prediction request's full path through routing, media tools, inference, cleanup and response.
- [api-errors.md](docs/api-errors.md): shared and endpoint-specific failures with triggers, status codes and original messages.
- [function-index.md](docs/function-index.md): a short English index of the key `app.py` functions in request order, with shared inference explained once.
- [function-index.zh-CN.md](docs/function-index.zh-CN.md): the complete Chinese function/method reference, including internal helpers, tests and the verification client.
- [01-single-file-api-learning.zh-CN.md](docs/01-single-file-api-learning.zh-CN.md): beginner notes on Python, HTTP uploads and the single-file API, with annotations for current code.
- [02-segment-xml-api-learning.zh-CN.md](docs/02-segment-xml-api-learning.zh-CN.md): a Chinese walkthrough of timestamp validation, sample offsets, shared inference and XML updates.
- [environment.md](docs/environment.md): English setup and model-startup requirements, recorded checkpoint details and offline-startup limitations.
- [environment.zh-CN.md](docs/environment.zh-CN.md): Chinese environment instructions and recorded setup history.

<a id="tests"></a>
### tests/

Generated-media tests with fake inference, requiring no model weights:

- [test_audio_segments.py](tests/test_audio_segments.py): checks waveform extraction, mono/16 kHz/PCM16 output, timestamps/ranges, label-score alignment and cleanup.
- [test_predict_multi.py](tests/test_predict_multi.py): checks XML preservation/replacement/escaping, invalid inputs and limits, one decode, per-segment predictions, gate/threading and failure cleanup.
- [__init__.py](tests/__init__.py): identifies the unittest package for discovery and module imports.

<a id="scripts"></a>
### scripts/

Command-line verification tools:

- [verify_predict_http.py](scripts/verify_predict_http.py): use the [verification command](#verification) against an already-running `/predict` server; it converts real speech, checks responses and saves generated media plus `test-artifacts/results.json`, without testing `/predict_multi` or overwriting retained reports.
- [__init__.py](scripts/__init__.py): identifies the package used by `python -m scripts.verify_predict_http`.

<a id="reports"></a>
### reports/

Preserved functional verification records:

- [functional-verification.md](reports/functional-verification.md): explains the historical single-file HTTP responses supplied with the project and their evaluation scope.
- [http-functional-results.json](reports/http-functional-results.json): the original raw responses for that historical run, retaining its bilingual labels.
- [real-model-segment-verification-2026-10-31.md](reports/real-model-segment-verification-2026-10-31.md): records the cached real model's two-interval helper check and original API HTTP regression on October 31.
- [predict-multi-verification-2026-11-02.md](reports/predict-multi-verification-2026-11-02.md): records the November 2 full-video/XML acceptance run, input hashes and XML comparison, including the resolved partial-download failure.

### environment/

- [pip-snapshot.txt](environment/pip-snapshot.txt): the recorded pip environment snapshot, not a portable Conda lockfile.

<a id="local-data"></a>
### Local data (Git-ignored)

- `samples/`: local supervisor media/XML inputs, not bundled with a Git checkout and never overwritten by the service.
- `test-artifacts/`: generated media, logs, fresh verification results and saved response XML; the completed supervisor run is [supervisor-complete-emotions.xml](test-artifacts/supervisor-complete-emotions.xml), which is available only where that local artifact exists.
- `.tmp/`: per-request working files, cleaned up when request contexts exit.
