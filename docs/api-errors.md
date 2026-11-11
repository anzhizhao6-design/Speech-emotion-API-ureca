<a id="api-errors--两个预测接口的报错说明"></a>
# API error reference

[README error entry](../README.md#errors) · [Call flows](api-flows.md) · [Function index](function-index.md)

This reference follows the current [app.py](../app.py). Original English messages are retained so they can be matched to responses and logs. Error bodies normally use `{"detail": "..."}` rather than a successful prediction object or XML attachment. A multi-segment request returns XML only after every segment succeeds. Request temporary files are cleaned up on success and exceptions; forced process termination can still leave files. Check the HTTP status before treating a downloaded body as XML.

<a id="shared-errors--共用错误"></a>
## Shared errors

In this table, “both” means `/predict` and `/predict_multi`. Endpoint-specific conditions appear in the following sections. Message placeholders such as `n` and `...` represent a segment index or variable detail, not literal response text.

| Status | Applies to | Trigger | Original message or troubleshooting note | Source |
| --- | --- | --- | --- | --- |
| 400 | Both | Multipart parsing fails, file/text-field counts exceed the parser limits, or the multipart boundary is missing | `Too many files. Maximum number of files is ...`; submit file fields without extra text fields | Starlette form parser, entered by `predict()` or `predict_multi()` |
| 413 | Both | The actual request body, including multipart overhead, exceeds the route limit | `Request body exceeds 26 MiB` or `Request body exceeds 131 MiB`; actual bytes are counted, not just Content-Length | `BodyLimitMiddleware.__call__.limited_receive()` |
| 413 | Both | The media upload exceeds its file limit; the XML route also checks its XML file separately | `/predict`: `File exceeds 25 MiB`; `/predict_multi`: `Media exceeds 128 MiB` or `XML exceeds 2 MiB` | `predict()` / `save_multi_upload()`; `parse_transcript()` also checks XML byte length |
| 415 | Both | The media extension is unsupported, after case normalization | `Supported file extensions: WAV, MP3, MP4, M4A`; renaming a file does not make its content decodable | Both route handlers |
| 422 | Both | A required uploaded file is empty | `/predict`: `Empty file`; `/predict_multi`: `Empty media` or `Empty xml` | `predict()` / `save_multi_upload()` |
| 422 | Both | FFmpeg fails or cannot select the audio track | `/predict`: `Audio decoding failed`; `/predict_multi`: `Audio decoding failed or file contains no audio track` | `convert_and_predict()` / `predict_transcript()` |
| 422 | Both | A media subprocess times out | `/predict`: `Media processing timed out` (20 seconds for FFprobe, 45 for FFmpeg); `/predict_multi`: `Audio decoding timed out (120 seconds)` | The workers catch `subprocess.TimeoutExpired` |
| 500 | Both | The model raises, labels/scores violate the output contract, or an unexpected internal failure occurs | `/predict`: `Prediction failed; see server log`; `/predict_multi`: `Segment n: prediction failed; see server log` or `Transcript prediction failed; see server log`; inspect the server exception | `predict_samples()` failures are wrapped by the relevant worker |
| 404 / 405 | All routes | The URL does not exist / the HTTP method is not supported | Check the path and use POST for prediction. These responses come from framework routing | FastAPI/Starlette routing |

Missing, duplicate, or incorrect fields may trigger a parser-level 400 before the handler can apply its own 422 checks. Not every multipart error has the same status. File, body, duration, and output limits are summarized in the [README](../README.md#processing-contract-and-limits).

<a id="post-predict-only--单文件接口特有错误"></a>
## POST /predict only

| Status | Trigger | Original message | Source |
| --- | --- | --- | --- |
| 422 | The parsed form is not exactly one UploadFile named `file` | `Provide exactly one file in the 'file' field` | `predict()` |
| 422 | FFprobe rejects the container as invalid or damaged | `Invalid or damaged media file` | `convert_and_predict()` |
| 422 | FFprobe finds no first audio track | `File contains no audio track` | `convert_and_predict()` |
| 422 | The actual decoded recording is longer than 30 seconds | `Audio exceeds 30 seconds` | `convert_and_predict()`; decoding up to 31 seconds detects overlong audio rather than silently accepting a truncated clip |
| 422 | The actual decoded recording is shorter than 0.25 seconds | `Audio must be at least 0.25 seconds` | `convert_and_predict()` |

[Follow the request flow](api-flows.md#post-predict) · [Worker details](function-index.md#app-convert-and-predict)

<a id="post-predict_multi-only--xml-接口特有错误"></a>
## POST /predict_multi only

In `Segment n`, **n is the 1-based SpeechSegment position in the original XML document**, not its chronological rank. A document-level structural error may have no usable segment index.

| Status | Trigger | Original message or prefix | Source |
| --- | --- | --- | --- |
| 422 | The parsed form is not exactly two UploadFiles named `file` and `xml`, including duplicate names | `Provide exactly two file fields: 'file' and 'xml'` | `predict_multi()` |
| 422 | XML syntax/encoding is invalid, a DTD or entity declaration/resolution is encountered, or nesting exceeds 128 levels | `Invalid XML: ...`; the detail may include `DTD and entity declarations/resolution are forbidden` or `XML nesting exceeds 128 levels` | `parse_transcript()` and its callbacks |
| 422 | The root is not unnamespaced AudioDoc or there is not exactly one direct SegmentList | `Expected AudioDoc with exactly one SegmentList` | `parse_transcript()` |
| 422 | No direct SpeechSegment is found | `Segment 1: no SpeechSegment found` | `parse_transcript()` |
| 422 | There are more than 1000 direct SpeechSegments | `Segment 1001: at most 1000 speech segments allowed` | `parse_transcript()` |
| 422 | A SpeechSegment occurs elsewhere, such as inside another node | `Segment n: SpeechSegment must be a direct child of AudioDoc/SegmentList` | `parse_transcript()` |
| 422 | stime/dur is missing or not a valid finite number, start is negative or beyond 1800 seconds, or dur is outside 0.25–30 seconds | `Segment n: invalid stime/dur (...)` | `parse_transcript()`; NaN and Infinity are also rejected |
| 422 | The decoded WAV exceeds 57,697,536 bytes | `Decoded audio exceeds output-size limit` | `predict_transcript()` |
| 422 | The decoded WAV is not mono, 16 kHz, with two-byte samples | `Unexpected decoded audio format` | `predict_transcript()` |
| 422 | The actual decoded frame count represents more than 1800 seconds | `Decoded audio exceeds 30 minutes` | `predict_transcript()` |
| 422 | Any first offset is outside the actual audio, or a last offset exceeds the available frames | `Segment n: outside the available audio` | The first range-check loop in `predict_transcript()`, **before any inference** |
| 422 | Reading an interval yields fewer PCM bytes than the required sample count multiplied by two | `Segment n: incomplete decoded audio` | The per-segment loop in `predict_transcript()` |
| 422 | The serialized response exceeds 16 MiB | `Updated XML exceeds 16 MiB` | `predict_transcript()`; inference may already have run, but no partial XML is returned |

[Follow the request flow](api-flows.md#post-predict-multi) · [Parser details](function-index.md#app-parse-transcript) · [Worker details](function-index.md#app-predict-transcript)

<a id="startup-and-direct-python-calls--启动和直接函数调用"></a>
## Startup and direct Python calls

- If FFmpeg or FFprobe cannot be found, `executable()` raises `RuntimeError` with a message ending in `not found in this Python environment`. Dependency or model-loading failures can also prevent lifespan startup. The service is not ready in that situation; this is not a prediction request returning HTTP 500. See the [environment guide](environment.md).
- `predict_segment()` and `extract_audio_segment()` are Python helpers. They do not apply route upload limits or acquire the request gate. Times must be finite Real numbers, excluding bool, with `0 <= start < end`; the selected interval must be 0.25–30 seconds. They can raise HTTPException(422), but a direct Python call does not itself produce an HTTP response. Model errors such as ValueError propagate to the caller.
- The segment helpers also use `Timestamps must be finite numbers with 0 <= start < end`, `Segment must be 0.25-30 seconds`, and `Segment is outside the available audio`. Their FFmpeg timeout is 45 seconds. The temporary segment is cleaned up when the context exits, including on errors.
- Container metadata may claim a longer duration than the audio that can actually be decoded. Keep boundary validation and supply a complete file; do not pad with silence or skip intervals. The [full verification report](../reports/predict-multi-verification-2026-11-02.md) retains the incomplete-download failure and the successful rerun after re-downloading.

<a id="reading-error-evidence--从验证找证据"></a>
## Verification evidence

The README's [verification table](../README.md#verification) brings together both endpoints' tests and retained reports. The rejection tests in [tests/test_predict_multi.py](../tests/test_predict_multi.py) use a fake model to check that invalid inputs do not reach inference. Existing XML emotions and model scores are not independent ground-truth labels.
