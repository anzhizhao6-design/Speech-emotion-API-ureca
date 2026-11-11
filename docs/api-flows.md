<a id="api-call-flows--两条接口调用链"></a>
# API call flows

[README](../README.md) · [Error reference](api-errors.md) · [Function index](function-index.md) · [Chinese function index](function-index.zh-CN.md)

The application entry point is [app.py](../app.py). Follow the function links for signatures, parameters, return values, callers, downstream calls, and source locations. Framework dispatch and library operations are named separately from project-defined functions.

<a id="shared-startup--共同启动"></a>
## Shared startup

Uvicorn imports `app:app`, then FastAPI enters [lifespan()](function-index.md#app-lifespan). It uses [executable()](function-index.md#app-executable) to find FFmpeg and FFprobe, creates the shared request gate and thread lock, and loads one CPU model. Both prediction routes reuse that state. Importing the module alone does not enter the lifespan or load weights. GET [health()](../app.py#L275) reports readiness without running inference.

<a id="post-predict"></a>
## POST /predict

1. [BodyLimitMiddleware.__call__()](function-index.md#app-bodylimitmiddleware-call) wraps the ASGI message reader. Its nested `limited_receive()` counts actual body bytes as the downstream app reads them, enforcing the 26 MiB request limit; it does not read the entire upload in advance.
2. [predict(request)](function-index.md#app-predict) acquires the shared gate before parsing the form. It requires exactly one file field named `file`, checks the media extension, creates a `.tmp/ser-*` request directory, and saves the upload with a separate 25 MiB file limit.
3. The route awaits `run_in_threadpool()`, which runs [convert_and_predict(state, source, destination, filename)](function-index.md#app-convert-and-predict). That worker asks FFprobe whether the first audio track exists, then uses FFmpeg to produce mono, 16 kHz, PCM16 WAV. The tool timeouts are 20 and 45 seconds respectively. Decoding is capped at 31 seconds so audio longer than 30 seconds can be detected and rejected.
4. The worker opens the WAV, reads its actual frame count and PCM data, converts the waveform to NumPy float32, and checks that the complete recording is between 0.25 and 30 seconds.
5. [predict_samples()](function-index.md#app-predict-samples) enters `state.lock`, calls the already-loaded model's `generate()`, and validates the nine labels and their aligned scores. [english_label()](function-index.md#app-english-label) removes language prefixes and validates the class names. The maximum-scoring position determines `emotion` and `score`; a `Prediction` object also carries all labels and scores.
6. The result returns through the route. The request directory is removed, the form is closed, and the gate is released. FastAPI serializes the `Prediction` as JSON. Expected worker errors become HTTP errors described in the [error reference](api-errors.md).

In `predict_samples()`, `samples` means the audio sample values in a one-dimensional, 16 kHz NumPy float32 waveform, not a set of uploaded files or training examples.

For a beginner walkthrough, see [01: single-file API learning notes (Chinese)](01-single-file-api-learning.zh-CN.md). The actual HTTP verification client is [scripts/verify_predict_http.py](../scripts/verify_predict_http.py), run from the repository root with `python -m scripts.verify_predict_http`.

<a id="post-predict-multi"></a>
## POST /predict_multi

1. The same [BodyLimitMiddleware](function-index.md#app-bodylimitmiddleware-call) counts incoming body bytes, using the 131 MiB limit for this path.
2. [predict_multi(request)](function-index.md#app-predict-multi) acquires the same request gate and parses exactly two file fields: `file` for media and `xml` for the transcript. It checks the media extension, creates `.tmp/ser-multi-*`, and calls [save_multi_upload()](function-index.md#app-save-multi-upload) for the media and XML, enforcing 128 MiB and 2 MiB limits separately. It then reads the saved XML as bytes in a worker thread.
3. The route awaits `run_in_threadpool()` with [predict_transcript(state, source, transcript, destination)](function-index.md#app-predict-transcript). That worker first calls [parse_transcript(data)](function-index.md#app-parse-transcript). Expat callbacks reject DTD/entity declarations and external entity resolution and enforce the nesting limit before ElementTree builds the tree. The parser checks the `AudioDoc/SegmentList/SpeechSegment` structure and every `stime`/`dur`, calculates `end = stime + dur`, and records each node with its sample offsets.
4. FFmpeg decodes the first audio track **once** into mono, 16 kHz, PCM16 WAV. This route does not run FFprobe or call `predict_segment()` for each interval. The worker checks the output-size limit, WAV format, and actual decoded duration of at most 1800 seconds. The decoder's 1801-second cap provides one extra second for detecting overlong input.
5. A first loop checks **all** segment offsets against the actual WAV frame count before the first model call. Any out-of-range interval rejects the request with zero predictions. The XML nodes remain in document order, even if their timestamps are not chronological.
6. A second loop processes those nodes in their original order: `wav.setpos(first)` positions the reader, and `wav.readframes(last - first)` reads the interval. After checking the byte count, the worker converts that interval's PCM bytes to float32 audio sample values and passes them to the shared [predict_samples(state, samples, source.name)](function-index.md#app-predict-samples). It makes one model call per interval, then sets only `element.set("emotion", result.emotion)`. Existing `score` attributes, Words, image/sound captions, text, and other XML content remain semantically intact.
7. Only after every interval succeeds does `ET.tostring(..., encoding="utf-8", xml_declaration=True)` serialize the tree, escaping attributes such as `<unk>` correctly. The worker checks the 16 MiB response limit and returns XML bytes. The route removes the request directory before returning an in-memory `application/xml` attachment named `predicted-transcript.xml`.
8. On an error, the route returns JSON rather than partially updated XML, and the form, request directory, and gate are released as their contexts exit. FFmpeg has a 120-second timeout; inference, gate waiting, and the whole request have no separate timeout. See the [error reference](api-errors.md).

The model receives audio, not the XML's words or existing emotion annotations. The XML provides the intervals and the structure to update. `channel="1"` is retained as metadata; it does not mean selecting the left stereo channel.

For a full walkthrough and a segment example, see [02: segment/XML API learning notes (Chinese)](02-segment-xml-api-learning.zh-CN.md). The [retained verification report](../reports/predict-multi-verification-2026-11-02.md) records the complete 65-segment HTTP run, input hashes, and the earlier incomplete-download failure. These are functional checks, not classification accuracy measurements.

<a id="direct-segment-helper--python-单段调用"></a>
## Direct Python segment helper

[predict_segment(state, source, start, end, filename=None)](../app.py#L261) enters the [extract_audio_segment()](../app.py#L218) context, which runs FFmpeg to extract one interval. It reads that WAV as float32, calls [predict_samples()](function-index.md#app-predict-samples), returns a `Prediction`, and deletes the temporary segment when the context exits.

This helper is not an HTTP route: it does not acquire the request gate or parse XML. Async callers should put it in a threadpool. It reuses the model and lock, but every extraction decodes from the beginning, so repeated helper calls are not the XML endpoint's one-decode strategy. Its `end` argument is already an end time, not the XML's duration.

<a id="verification-routes--如何核对上述流程"></a>
## How the flows are verified

- [tests/test_audio_segments.py](../tests/test_audio_segments.py) checks media extraction and single-segment inference wiring. [tests/test_predict_multi.py](../tests/test_predict_multi.py) uses real FFmpeg with a fake model to check one decode, 65 fake predictions, XML preservation, validation order, shared gating, and cleanup.
- [scripts/verify_predict_http.py](../scripts/verify_predict_http.py) is a real HTTP client for an already-running `/predict` service. Its nested `main.convert()` generates test media on the client; those conversions are separate from the server's decoding count.
- The README's [verification summary](../README.md#verification) links the original reports and distinguishes generated-media tests, real-model functional acceptance, and classification accuracy evaluation that has not been performed.
