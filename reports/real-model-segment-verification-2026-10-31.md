# Real-model segment and HTTP functional verification

Verified on 2026-10-31 (Asia/Singapore). Git status was clean before this run.
No application or test code was changed. Historical reports were preserved.

## Environment and startup

- Existing Windows `emotion2vec` Conda environment; Python 3.10.20.
- PyTorch 2.14.0+cpu, FunASR 1.4.15, ModelScope 1.40.0,
  FastAPI 0.161.1, Uvicorn 0.54.0, HTTPX 0.28.1; FFmpeg/FFprobe 6.1.1.
- Used the actual `app.lifespan` startup inside a temporary verification wrapper,
  loading `iic/emotion2vec_plus_seed` once on CPU. The same model instance served
  both direct segment calls and all HTTP predictions in one Uvicorn worker.
- The ignored launcher replaced only FunASR's model-directory resolver with the
  existing local snapshot and blocked non-loopback socket connections. No model
  mocking, dependency installation, upgrades, or weight downloads occurred.
  Ordinary hub-based startup without this cache resolver was not tested.
- Cached `model.pt` SHA256:
  `327e861049c7105a3f8589edfd16543a7cdc0c1926f1b64de975d98e0650cdd3`.

## Real speech and segment results

Input: the cached seed model's supplied `example/test.wav`, not synthetic audio.
It contains 65,666 mono PCM16 samples at 16 kHz (4.104125 seconds).
Input SHA256: `a4839eaaa3d54bd2db6eb48aa3d40def1b5c5004df3fd163a8dcd045097f8a23`.

| Interval, seconds | Observed emotion | Maximum score |
| --- | --- | --- |
| [0, 2) | angry | 0.9999358654022217 |
| [2, 4) | angry | 0.9999967813491821 |

Both `predict_segment` calls passed checks for exactly nine English labels,
matching score lengths, finite scores within [0, 1], a score sum within 1e-5 of
one, and consistent maximum emotion/score fields. Model identity remained
unchanged. Temporary-directory contents matched their pre-call state after each
prediction, and `.tmp` was empty after the segment checks.

## Original API regression checks

Started an owned loopback server on an OS-assigned available port, avoiding any
existing server. Ran the unchanged `verify_api.py` with the real speech path and
`--url` pointing to that server. The verifier exited successfully.

| POST cases | Expected and observed | Count |
| --- | --- | --- |
| WAV, MP3, MP4, M4A, uppercase M4A, three consecutive WAV requests | 200 | 8 |
| Damaged WAV/M4A, no-audio MP4, empty file, too short, too long | 422 | 6 |
| Unsupported extension | 415 | 1 |
| Multiple files | 400 | 1 |
| File-size and body-size limits | 413 | 2 |

All 18 POST cases passed. `/health`, `/docs`, and the OpenAPI multipart schema
also passed. Every successful prediction passed English-label, score-range/
alignment, score-sum, and maximum-field checks. `.tmp` was empty at completion.
The verifier's silence fixtures were used only for duration rejection; successful
inference cases used conversions of the real speech recording.

Only the server process created by the launcher was terminated after verification;
its port was confirmed closed. Windows termination returned process code 1;
this was explicit cleanup after successful checks, not a test failure. Graceful
lifespan shutdown was not exercised.

## Warnings, artifacts, and limitations

No functional checks failed, and no implementation fixes were needed. Startup
reported the previously documented missing `AUDIO.decoder` checkpoint keys;
real inference still completed. This run does not establish that those warnings
are harmless for every model capability.

Generated media, the temporary launcher, full responses, logs, and local paths
remain under Git-ignored `test-artifacts/`; no weights or machine-specific paths
are added to this report. The historical reports are unchanged.

This is real-model functional verification, not classification accuracy evaluation.
There is no independent ground-truth label assessment, calibration study,
performance benchmark, or concurrent-request test. The two intervals come from
one short recording; the supervisor's actual XML/MP4, timestamp origin/units,
audio-track selection, and segment/error policies remain unverified. XML parsing
and `/predict_multi` are still pending and were not implemented.
