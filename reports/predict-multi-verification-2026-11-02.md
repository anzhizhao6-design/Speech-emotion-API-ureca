# POST /predict_multi implementation and functional verification

Date: 2026-11-02 (Asia/Singapore). Git status was clean before implementation.
Historical reports and input samples were preserved during verification.

Latest result: the complete replacement MP4 passed real HTTP verification for
all 65 segments: HTTP 200 in **43.373 seconds**, excluding model startup,
with one decode, XML preservation and cleanup checks passing. Re-downloading
the complete MP4 resolved the earlier truncated-file failure; that failed run
is retained below as historical context. See the final section for details.

## Implementation

Added exactly-two-file multipart handling (`file`, `xml`) for the actual
unnamespaced AudioDoc/SegmentList/SpeechSegment structure. Each interval is
[stime, stime + dur), in seconds. The worker validates every interval before
inference, decodes the first audio track once to mono/16 kHz/PCM16 WAV, reads
sample offsets, and reuses `predict_samples`, the loaded model and inference
lock. Both endpoints share the request gate; blocking work uses the threadpool.

Only SpeechSegment emotion attributes are added/replaced. Other attributes,
including score, child order, text/tails, Words and captions are preserved
semantically. ElementTree handles escaping, including `<unk>`; encoding-aware
Expat callbacks reject DTD/entity declarations and external entity resolution.
No byte-offset rewriting is used. XML is returned as a UTF-8 application/xml
attachment only after every segment succeeds. Failure returns JSON, with a
1-based XML segment index where applicable. Temporary files clean up on either
outcome.

New limits: media 128 MiB, XML 2 MiB, actual request bytes 131 MiB, decoded audio
1800 seconds, 1000 segments, 0.25-30 seconds per segment. FFmpeg has a 120-second
timeout, a 1801-second decode cap and a 57,697,536-byte output cap. Updated XML
is capped at 16 MiB and input nesting at 128 levels. Existing /predict limits
remain unchanged. There is no whole-inference/request timeout.

## Environment and model provenance

Existing Windows emotion2vec Conda environment: Python 3.10.20, PyTorch
2.14.0+cpu, FunASR 1.4.15, ModelScope 1.40.0, FastAPI 0.161.1, Uvicorn 0.54.0,
HTTPX 0.28.1; FFmpeg/FFprobe 6.1.1. No dependencies were installed/upgraded and
no weights downloaded.

Real HTTP checks used the actual application lifespan and one owned Uvicorn
worker. A Git-ignored launcher resolved the model ID to its existing local
snapshot and blocked outbound connections. The model was loaded once for the
supervisor-file rejection, successful real-speech check, and original HTTP
regression. Only this owned server was stopped; graceful shutdown exited 0,
released the model and left .tmp empty. Ordinary hub resolution was not tested.

Cached iic/emotion2vec_plus_seed model.pt SHA256:
`327e861049c7105a3f8589edfd16543a7cdc0c1926f1b64de975d98e0650cdd3`.
Startup emitted the previously documented missing AUDIO.decoder checkpoint-key
warnings; actual inference succeeded. TestClient emitted an existing HTTPX
deprecation warning; no dependency changes were made.

## Generated-media / fake-model checks

All 26 tests passed: the existing 10 segment tests and 16 new endpoint tests.
The final 24-test suite passed in 3.067 seconds; two additional focused checks
for 65-segment preservation and the 1000-segment boundary passed in 0.197 seconds.
Commands used the existing environment's Python and unittest.

Coverage includes emotion replacement, unordered intervals and sample selection,
all-other-content semantic comparisons, escaped unknown labels, Unicode/UTF-16,
DTD/external entity rejection, invalid XML/structure/timestamps, duration and
range errors before inference, multipart fields/extensions, route-specific and
chunked body guards, cleanup, decode/model failures, one decode per request,
shared request gate and event-loop responsiveness. Upload/time/output limit
branches use reduced constants in focused tests rather than allocating maximum
payloads. The real 52.51 MiB upload separately exercised the larger body path.

The generated 65-segment request made exactly one decode and 65 fake-model calls;
all 65 emotions were valid and recursive comparison showed every other XML
attribute, text/tail, element and order unchanged. This was not real-model
validation of the supervisor transcript.

## Historical first run: incomplete supervisor MP4

Input XML: news-video-with-captions 1.xml, 104,320 bytes, 65 SpeechSegments.
Its intervals range from 0.03 to 570.24 seconds, with durations 1.72-19.72
seconds. All pass syntax and per-segment duration checks. Five existing emotion
attributes are annotations only, not verified ground truth.

Input MP4: news-video-with-captions 2.mp4, 55,062,440 bytes. Its header declares
570.258866 seconds of AAC stereo/44.1 kHz audio. Investigation after the first
real HTTP attempt showed that this metadata does not reflect readable content:

| Evidence | Observation |
| --- | --- |
| Decoded mono/16 kHz audio | 7,233,109 samples = 452.0693125 seconds |
| AAC frames declared / packets readable | 24,559 / 19,469 |
| Video frames declared / packets readable | 14,256 / 11,312 |
| Packet scan warnings | Packet corrupt, invalid NAL unit, partial file |
| Audio packet timestamp gaps | None; readable audio ends at about 452.069 seconds |

The first supervisor-file request returned 422 at Segment 48. Investigation
confirmed incomplete media rather than an implementation defect, so no padding,
skipping or weakened validation was introduced. Repeating the request returned:
`{"detail":"Segment 48: outside the available audio"}`.
Measured repeat HTTP wall time: **0.989864 seconds**, excluding model startup;
worker time: **0.716989 seconds**. Instrumentation confirmed **one decode, zero
model calls**. Seventeen XML intervals exceed readable audio: indices 48 and
50-65. No partial/updated supervisor XML was returned or fabricated.

At that time, all-65 real-model success and input/output preservation on the
supervisor transcript could not be verified. This historical blocker was
resolved by re-downloading the complete MP4 and passing the acceptance check
recorded in the final section.
The initial metadata-only inspection could not establish this completeness.

Input hashes were unchanged after requests:

- MP4 SHA256: `19ef412a0428f163682604b574b19aaf0d8153332564bc346efb57337859ef79`
- XML SHA256: `2a9561c20d9b717236f64cb37813dfc62cab9fdad650a1b5ea8999634e82090d`

## Successful real-model HTTP check and original API regression

To verify the successful new endpoint independently, used the cached seed
model's real example/test.wav (4.104125 seconds), with a separate two-segment
transcript covering [0, 2) and [2, 4). Both returned English `angry` attributes.
HTTP status 200, UTF-8 XML attachment; **0.700064 seconds** wall time, excluding
startup, with **0.606614 seconds** in the worker. Instrumentation recorded one
decode, two actual model calls and the same model instance. Recursive XML
comparison confirmed all content/attributes except emotion were unchanged,
including scores 0.98/0.97. Output is saved, Git-ignored, at
`test-artifacts/cached-real-speech-emotions.xml`.

The unchanged verify_api.py then passed all **18 POST cases** against that same
server: 8 successes (WAV/MP3/MP4/M4A, uppercase M4A, repeated requests), 6 expected
422 rejections, one 415, one 400 and two 413 cases. Health, docs, multipart schema,
English-label/score/max-field checks and temporary-directory cleanup also passed.
The new endpoint's OpenAPI multipart schema was checked as well.

These are functional checks, not emotion classification accuracy, calibration
or performance benchmarks. No existing XML emotions were treated as ground
truth. The timing observations describe only these local requests. Generated
media, diagnostics, XML responses, launchers, full evidence and logs remain
Git-ignored under test-artifacts/; samples remain ignored. No machine-specific
paths or model weights were added to Git.


## Complete replacement MP4: all 65 real-model segments passed

Follow-up verification on 2026-11-02 used the original XML and the complete
replacement MP4. The requested filename ending in `2(1).mp4` was not present;
the replacement was found under `samples/news-video-with-captions 2.mp4`.
Its identity was confirmed by both the expected size and SHA256 before inference:

- Exact size: **71,215,895 bytes**.
- SHA256: `1ef3546dc6cab8094cf829472d38a333eb081a448e4a18a818c4cd60cbb03465`.
- Independent audio decode: **570.258875 seconds**, 9,124,142 mono/16 kHz
  samples; FFmpeg exited 0 without warnings/errors. No duration/output cap was
  used for this completeness check; the 120-second watchdog was not reached.
- Original XML SHA256 remained
  `2a9561c20d9b717236f64cb37813dfc62cab9fdad650a1b5ea8999634e82090d`.

The current, unchanged application was started through its actual lifespan on
an owned single-worker loopback server, using the same cached seed-model
checkpoint and software versions listed above. The temporary launcher again
resolved the model to the local cache and blocked outbound connections. No
validation was relaxed and no dependencies or weights were downloaded.

The real multipart POST /predict_multi returned **HTTP 200**, a UTF-8
application/xml attachment. HTTP request wall time was **43.372984 seconds**,
including upload/processing/response but excluding model startup. Measured
worker processing time was **43.021091 seconds**. Instrumentation confirmed
**one audio decode, 65 real-model predictions, and the same model instance**.

All **65 SpeechSegment** elements have allowed English emotion attributes:

| Predicted emotion | Count |
| --- | --- |
| neutral | 57 |
| &lt;unk&gt; | 6 |
| sad | 1 |
| happy | 1 |

Recursive comparison of the original and returned XML, excluding only each
SpeechSegment's emotion attribute, confirmed identical element order, text,
tails, Words, image/sound captions, and all other attributes including score.
Existing emotion attributes were replaced and missing attributes added.
Unknown labels were correctly serialized as `emotion="&lt;unk&gt;"`.
Input media/XML hashes remained unchanged after processing.

Returned XML is saved at the Git-ignored path:
`test-artifacts/supervisor-complete-emotions.xml` (105,460 bytes).
Output SHA256:
`c17f2cdc9b0c3305469507a97961d98b5b8a3ad8a456bab417c835fa90d2352d`.
Separate ignored evidence/log files use the `complete-` prefix, preserving
previous failed-run evidence. The earlier failure section remains unchanged
apart from its historical heading.

The request temporary directory was removed, .tmp was empty after response,
and graceful shutdown released the model and exited 0. Only the owned server
was stopped; its port was confirmed closed. No application/test code was
changed for this follow-up, and tests were not rerun beyond this requested
real HTTP acceptance check.

The previous all-65 verification blocker is resolved for this complete file.
This remains functional verification, not classification accuracy evaluation:
existing XML emotion annotations were not used as ground truth, and label
counts or model scores do not establish correctness.
