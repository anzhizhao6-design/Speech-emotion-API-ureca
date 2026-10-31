# Local Speech Emotion Recognition API

[简体中文](README.zh-CN.md)

A Windows CPU service built with FastAPI and Uvicorn, using the fine-tuned `iic/emotion2vec_plus_seed` model through FunASR. Each request accepts one WAV, MP3, MP4, or M4A file and returns the model's native nine-class scores. The API does not use IEMOCAP or train a model.

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

Labels are neither reordered nor renamed. Recorded output labels: `生气/angry`, `厌恶/disgusted`, `恐惧/fearful`, `开心/happy`, `中立/neutral`, `其他/other`, `难过/sad`, `吃惊/surprised`, `<unk>`. Scores are model softmax outputs, not measured accuracy or calibrated guarantees.

## Limits and errors

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

The XML segment endpoint `/predict_multi` is planned and is not implemented in this snapshot. Real XML/media samples are pending.
