# HTTP functional verification

## Evidence and scope

This report summarizes the 18 saved POST responses supplied with the existing local project. The source archive records the result file at 2026-10-24 00:11 (archive timestamp, timezone unspecified). The API and model were not rerun during repository preparation.

| Cases | Expected status | Saved responses |
| --- | --- | --- |
| WAV, MP3, MP4, M4A, uppercase M4A, three consecutive WAV requests | 200 | 8 |
| Damaged WAV/M4A, no-audio MP4, empty, too short, too long | 422 | 6 |
| Unsupported extension | 415 | 1 |
| Multiple files | 400 | 1 |
| Oversized file and request body | 413 | 2 |

All 18 saved responses match the status expectations in `verify_api.py`. Successful saved responses contain nine corresponding labels/scores, a consistent maximum emotion/score, and scores summing approximately to one. Original documentation reports health/docs/schema checks and an empty temporary directory; those observations cannot be independently reconstructed from the POST response JSON alone.

The original documented input was the model-provided example speech recording, converted to multiple formats. Media files, logs, model weights and personal paths are excluded from this repository. See `http-functional-results.json` for the saved responses.

## Benchmark status

These are functional checks, not an accuracy or performance benchmark. Classification accuracy, latency, throughput, CPU/memory use and concurrent-request behavior have not been measured in this report. No new training was performed.

## Reproduce locally

Start the service as described in the root README. In a second terminal, using the same environment and repository root:

```powershell
python verify_api.py "path/to/real-speech.wav"
```

The script writes generated media and a new `test-artifacts/results.json`. It does not overwrite the historical report committed here.

## English-label update

The API now removes bilingual prefixes from labels and emotion, preserving score order and values. The historical responses above predate this change. The HTTP verifier now requires the nine English labels. Label conversion was checked locally against all eight saved successful responses, including maximum-label alignment. No new HTTP/model run was performed for this update.
