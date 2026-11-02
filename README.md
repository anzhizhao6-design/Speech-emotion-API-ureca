# Local Speech Emotion Recognition API

[简体中文](README.zh-CN.md)

A Windows CPU service built with FastAPI and Uvicorn, using the fine-tuned `iic/emotion2vec_plus_seed` model through FunASR. The `/predict` endpoint accepts one WAV, MP3, MP4, or M4A file and returns English labels with the model's native nine-class scores. `/predict_multi` accepts media plus an XML transcript and returns XML with English segment emotions. The API does not use IEMOCAP or train a model.

## Project files

| File | Responsibility |
| --- | --- |
| `app.py` | Loads the model at startup; validates uploads; converts media; runs serialized CPU inference; returns JSON; cleans up temporary files. |
| `verify_api.py` | Tests an already running service through real HTTP requests. Converts a supplied speech recording into test formats, checks responses, and saves results. It neither starts the service nor measures recognition accuracy. |
| `requirements.txt` | Pinned API additions, not a complete environment specification. |
| `environment/pip-snapshot.txt` | Recorded pip snapshot, not a portable Conda lockfile. |
| `reports/http-functional-results.json` | Saved responses from the previous 18-case POST run. The historical JSON report is committed; generated media remain Git-ignored. |

## Environment and startup

Use a Python 3.10 environment with compatible PyTorch, torchaudio, FunASR and ModelScope installations. The supplied `requirements.txt` contains API additions only. `environment/pip-snapshot.txt` records the original Windows environment and is not a portable lockfile or a clean-install guarantee.

```powershell
conda activate emotion2vec
python -m pip install -r requirements.txt
```

Install FFmpeg and FFprobe in this environment or make them available on PATH. The original environment used FFmpeg 6.1.1. Run from this repository root:

```powershell
python -m uvicorn app:app --host 127.0.0.1 --port 8000 --workers 1
```

Wait for `Application startup complete`. Keep one worker and omit `--reload` to avoid extra model loads. Stop with Ctrl+C. The service searches the environment's `Library/bin` first, then PATH.

## Model and processing

The model loads once per process at startup with `hub="ms"`, `device="cpu"`, and `disable_update=True`. First use downloads official weights; cached startup may still contact the hub. Fully offline startup has not been verified. The default model revision is used, not an immutable pinned revision.

Recorded `model.pt` SHA256: `327e861049c7105a3f8589edfd16543a7cdc0c1926f1b64de975d98e0650cdd3`. Loading emitted missing `AUDIO.decoder` key warnings; subsequent classification requests succeeded.

FFprobe checks the first audio track. FFmpeg converts it to mono 16 kHz PCM16 WAV, then the service passes float32 NumPy samples to the reused model. MP4 video is not analyzed. A semaphore serializes request processing and a lock protects inference; torch uses at most four CPU threads. Inference uses `granularity="utterance", extract_embedding=False`.

## Upload and response

Open <http://127.0.0.1:8000/docs> → **POST /predict** → **Try it out** → choose a file in `file` → **Execute**. Upload exactly one multipart file field named `file`, without extra fields. Supported extensions: `.wav`, `.mp3`, `.mp4`, `.m4a`, case-insensitive. Actual content must decode successfully; speech presence is not checked.

<http://127.0.0.1:8000/health> reports readiness, model, and CPU device; it does not perform an inference check. After generating verification artifacts, an upload example is:

```powershell
curl.exe -X POST http://127.0.0.1:8000/predict -F "file=@test-artifacts/speech.wav"
```

| JSON field | Meaning |
| --- | --- |
| `filename` | Uploaded filename with directory components removed. |
| `model` | `iic/emotion2vec_plus_seed`. |
| `emotion`, `score` | Label and score at the maximum-scoring position. |
| `labels`, `scores` | All nine labels and corresponding scores, in the actual model output order. |

Labels retain the model output order. Bilingual labels such as `吃惊/surprised` are returned as `surprised` in both `labels` and `emotion`. The nine API labels are `angry`, `disgusted`, `fearful`, `happy`, `neutral`, `other`, `sad`, `surprised`, and `<unk>`. Scores are unchanged model softmax outputs, not measured accuracy or calibrated guarantees. Historical results in `reports/` retain the original bilingual responses.


## `/predict` limits and errors

| Limit | Implementation |
| --- | --- |
| File size | At most 25 MiB |
| Request body, including multipart overhead | At most 26 MiB; counted while receiving |
| Decoded duration | 0.25–30 seconds inclusive |
| FFprobe / FFmpeg timeout | 20 / 45 seconds |
| Decode cap for duration checking | 31 seconds; audio over 30 seconds is rejected |

These subprocess timeouts do not impose an inference or whole-request timeout.

| Status | Meaning |
| --- | --- |
| 400 | Multipart parsing errors, including multiple files or disallowed extra fields. |
| 413 | File/body size limit exceeded. |
| 415 | Unsupported extension. |
| 422 | Missing/incorrect file field, empty/invalid media, no audio, decoding failure, media-processing timeout, or duration outside limits. |
| 500 | Internal prediction failure; details are logged server-side. |

Application upload/conversion files use per-request `.tmp/ser-*` directories, cleaned up on normal completion and handled exceptions. Forced termination may leave files. The service is intended for local, single-worker use; authentication and an accuracy-evaluation endpoint are not implemented.

## Functional verification and evaluation scope

The previous run used real speech from the official model's `example/test.wav`. The client generates up to eight seconds of 44.1 kHz stereo WAV, MP3, MP4 with video/AAC audio, and AAC M4A. The M4A is encoded media, not a renamed file; the user's original Windows recording was not tested.

Start the service first, then run from the project directory:

```powershell
python verify_api.py "path/to/real-speech.wav"
```

You can supply another real speech path. `--url` overrides `http://127.0.0.1:8000`. The client overwrites generated media and writes `test-artifacts/results.json` after a successful run.

| Saved POST cases (18 total) | Status |
| --- | --- |
| WAV, MP3, MP4, M4A; uppercase `.M4A`; three consecutive WAV requests | 200 (8 cases) |
| Damaged WAV/M4A; no-audio MP4; empty file; too-short/too-long audio | 422 (6 cases) |
| Unsupported extension | 415 |
| Multiple files | 400 |
| Oversized file / body | 413 (2 cases) |

Successful responses passed checks for nine corresponding labels/scores, score sum approximately one, and consistent maximum label/score fields. `/health`, `/docs`, and the OpenAPI multipart schema also passed; `.tmp` was empty after the run. Recorded WAV result: `生气/angry`, score `0.9999990463256836`. Full responses are in `reports/http-functional-results.json`. Silence was used only for duration rejection tests.

**These verify interface behavior and actual model inference, not emotion recognition accuracy.** No independently labeled test set, accuracy metric, or calibration study has been evaluated. A high score on one sample does not establish correctness or generalization. This documentation-only update is based on source inspection and saved results, not a new service test run.

## Documentation and next work

- [Functional verification report](reports/functional-verification.md)
- [Recorded HTTP responses](reports/http-functional-results.json)
- [Chinese learning notes](docs/LEARNING.zh-CN.md)

The XML segment endpoint `/predict_multi` supports the supplied AudioDoc transcript structure; see the endpoint details below. Supervisor samples remain Git-ignored.

## Reusable segment processing

`predict_segment(state, source, start, end, filename=None)` accepts a local
media path and numeric start/end times in seconds and returns a `Prediction`
with English labels and aligned scores. Pass the initialized `app.state` to
reuse the loaded model and inference lock. It makes no internal HTTP requests.
Async callers should run it through `run_in_threadpool`.

For extraction alone, use the context manager:

```python
with extract_audio_segment(app.state, media_path, start=12.5, end=15.0) as wav_path:
    # wav_path is mono, 16 kHz, PCM16 WAV; consume it inside this block.
    ...
```

Timestamps must be finite real numbers (excluding booleans), with
`0 <= start < end`. Intervals are `[start, end)`, relative to the first decoded
sample of the first audio track. Boundaries round up to the next 16 kHz sample
(less than 62.5 microseconds). The decoded frame count must match the requested
interval; partial clips and intervals beyond the available audio raise HTTP 422.
No silence is padded to satisfy a requested end time.

Each segment retains the existing 0.25-30 second inference limit. Source media
may exceed 30 seconds and is not subject to `/predict`'s upload-size limits.
Extraction decodes from the beginning for accurate compressed-media boundaries,
with a 45-second FFmpeg timeout; long sources or late segments may time out.
Temporary segment files are removed after success, decoding failure, model
failure, or an exception in the caller's context. Forced process termination
can still leave files. Model/output errors propagate to the caller for future
endpoint error handling. Existing `/predict` behavior and limits are unchanged.

Run the focused checks without starting the API or loading a model:

```powershell
conda activate emotion2vec
python -m unittest -v test_segments
```

These tests use generated WAV/MP4 media for extraction and a fake model for
inference wiring, lock use, English-label alignment, and failure cleanup. They
also check existing upload duration rejection. They do not validate real-model
inference or emotion accuracy; `verify_api.py` remains the separate real-speech
HTTP check.

`predict_segment` remains available for individual local-file intervals. The
multi-segment endpoint instead decodes once and calls the shared
`predict_samples` function for each interval.

## `POST /predict_multi`

Upload exactly two multipart **file** fields: `file` (WAV, MP3, MP4, or M4A;
extensions case-insensitive) and `xml` (XML transcript). Missing, duplicated,
extra, or text-only fields are rejected. Example:

```powershell
curl.exe -X POST http://127.0.0.1:8000/predict_multi -F "file=@samples/news-video-with-captions 2.mp4" -F "xml=@samples/news-video-with-captions 1.xml" --output test-artifacts/predicted-transcript.xml
```

Create `test-artifacts/` first if necessary. Input files are never overwritten.
A successful response is UTF-8 `application/xml`, with
`Content-Disposition: attachment; filename="predicted-transcript.xml"`.
The OpenAPI documentation includes both binary fields.

The accepted structure is one unnamespaced `AudioDoc` root containing exactly
one direct `SegmentList`, with one or more direct `SpeechSegment` children.
For each speech segment, `stime` is its start in seconds and `dur` is its
duration; the interval is `[stime, stime + dur)`. Times are relative to the
first decoded sample of the first audio track. Segment elements need not be
time-sorted. Decimal timestamp arithmetic avoids binary-float rounding when
converting XML values to sample offsets; boundaries round up to 16 kHz samples.

The first audio track is decoded **once per request** into mono, 16 kHz, PCM16
WAV. Stereo is mixed down; XML `channel="1"` is retained as metadata and does
not select the left channel. Each interval is read by sample offsets, converted
to float32, and passed to the already-loaded CPU model through `predict_samples`
and its inference lock. `/predict` and `/predict_multi` share the request gate;
blocking decoding and inference run in a worker thread.

Every `SpeechSegment` receives a newly predicted English `emotion`, replacing
any existing value. Existing emotion annotations are not treated as ground truth.
All other attributes (including `score`), element order, text/tails, `Word`
elements, and image/sound captions are preserved semantically. In-root comments
and processing instructions are retained. Formatting, XML declarations,
namespace prefixes, quote style, CDATA syntax, and equivalent escaping may change.
For example, the `<unk>` label is serialized safely as `emotion="&lt;unk&gt;"`.
There is no custom byte-offset rewriting.

| Multi-endpoint limit | Value |
| --- | --- |
| Media file | 128 MiB |
| XML file | 2 MiB |
| Total request body, including multipart overhead | 131 MiB; actual bytes counted |
| Speech segments | 1-1000 |
| Each speech segment | 0.25-30 seconds inclusive |
| Decoded audio | At most 30 minutes |
| FFmpeg timeout | 120 seconds |
| Decoder duration/output caps | 1801 seconds / 57,697,536 bytes (one extra second detects overlong audio) |
| Returned XML | At most 16 MiB |
| XML nesting | At most 128 levels |

DTD and entity declarations, including external DTDs/entities, are rejected
using encoding-aware parser callbacks. External entities are never resolved.
All timestamp and sample-range checks finish before any inference begins.
Incomplete/out-of-range clips are rejected without truncation or silence padding.
Container duration is not accepted as proof of available audio: a partial MP4
can declare a longer duration than its physically readable audio packets.

The endpoint returns updated XML **only if every segment succeeds**. Errors
return JSON: 400 for multipart parser errors; 413 for upload/body limits; 415 for
unsupported media extensions; 422 for invalid XML/structure, timestamps,
segment-count/duration/range limits, media decoding errors/timeouts, or decoded/
response-size limits; 500 for internal/model failures. Segment-specific errors
identify the **1-based XML element index**, not the chronological position.
No partial XML is returned. Temporary upload and decoded WAV files are removed
on success and exceptions; forced process termination may leave files.

The original `/predict` retains its 25 MiB file, 26 MiB body and 0.25-30 second
duration limits. The 120-second timeout applies to decoding only; CPU inference
has no whole-request timeout. Up to 1000 segments may therefore take considerable
time and hold the shared request gate.

Run generated-media/fake-model checks without loading model weights:

```powershell
conda activate emotion2vec
python -m unittest -v test_segments test_predict_multi
```

These verify XML updates/preservation, escaping, rejection paths, upload bounds,
single decoding, request serialization, worker-thread execution, and cleanup.
They do not measure classification accuracy. Real-model HTTP verification is
recorded separately under `reports/`; generated responses/media/logs stay in
Git-ignored `test-artifacts/`.

The [full-sample verification report](reports/predict-multi-verification-2026-11-02.md)
records HTTP 200 for all 65 real speech segments in 43.373 seconds excluding
model startup, with one decode, XML preservation and cleanup checks passing.
The earlier truncated-file failure was resolved by re-downloading the MP4;
that failed-run record is retained in the report. These results verify function,
not classification accuracy.
