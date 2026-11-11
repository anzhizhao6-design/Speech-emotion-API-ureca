# Prediction function index

[README](../README.md) · [Detailed call flows](api-flows.md) · [Errors](api-errors.md) · [Full Chinese function index](function-index.zh-CN.md)

This short guide follows the key [app.py](../app.py) functions used by the two prediction endpoints; test and verification-script functions are covered by the full Chinese index rather than listed here.

<a id="post-predict"></a>
## POST /predict: upload to JSON

<a id="app-predict"></a>
1. **[predict(request: Request)](../app.py#L286)** receives the HTTP upload, acquires the gate, validates and saves the single media file, and passes it to `convert_and_predict()` in a worker thread before returning its `Prediction` through FastAPI as JSON after cleanup.

<a id="app-convert-and-predict"></a>
2. **[convert_and_predict(state, source, destination, filename)](../app.py#L172)** receives the saved media path, probes and decodes it into a short standard WAV, checks its duration, and hands the float32 audio sample values to [predict_samples()](#app-predict-samples).

3. [Shared inference](#shared-inference) returns the labels and scores as a `Prediction` to `convert_and_predict()`, which returns it to the route in step 1.

<a id="post-predict-multi"></a>
## POST /predict_multi: two uploads to XML

<a id="app-predict-multi"></a>
1. **[predict_multi(request: Request)](../app.py#L460)** receives the media and XML uploads, acquires the shared gate, uses `save_multi_upload()` to save both files, and awaits `predict_transcript()` in a worker thread before cleaning up and returning its XML bytes as a download.

<a id="app-save-multi-upload"></a>
2. **[save_multi_upload(upload, path, limit, description)](../app.py#L441)** receives one uploaded file and its size limit, writes its bytes to a temporary path while rejecting empty or oversized content, and returns control to `predict_multi()`.

<a id="app-predict-transcript"></a>
3. **[predict_transcript(state, source, transcript, destination)](../app.py#L390)** receives the media path and XML bytes, calls `parse_transcript()`, decodes the audio once and checks all ranges, sends each interval's float32 sample values to [predict_samples()](#app-predict-samples), writes each returned English label into that node's `emotion`, and returns serialized XML to `predict_multi()`.

<a id="app-parse-transcript"></a>
4. **[parse_transcript(data)](../app.py#L325)** receives XML bytes, safely checks the document structure and every segment's `stime` and `dur`, and returns the original element tree plus node/sample-offset tuples to `predict_transcript()`.

After parsing returns to step 3, the worker uses `end = stime + dur` and the calculated sample offsets to read each interval from the one decoded WAV, then calls [shared inference](#shared-inference) once per interval in XML document order; only after all intervals succeed does it serialize the updated tree and return to step 1.

<a id="shared-inference"></a>
## Shared inference: audio values to labels and scores

<a id="app-predict-samples"></a>
- **[predict_samples(state, samples, filename)](../app.py#L144)** receives a one-dimensional array of 16 kHz float32 audio sample values, uses the **already-loaded model** under its lock to obtain labels and scores, validates them and calls `english_label()`, then returns an aligned `Prediction` to whichever worker called it.

<a id="app-english-label"></a>
- **[english_label(label: str) -> str](../app.py#L48)** receives one model label, removes any language prefix and checks the allowed English class name, then returns that name to `predict_samples()` without rearranging scores.

`predict_samples()` predicts from audio; **`predict_transcript()` writes the returned emotion into XML** and preserves the existing `score` and other XML content.

## Shared startup and upload guard

<a id="app-lifespan"></a>
- **[lifespan(app)](../app.py#L70)** receives the FastAPI application at startup, obtains media-tool paths from `executable()` and loads one model with a shared gate and lock, then makes that state available to both routes until normal shutdown releases the model reference.

<a id="app-executable"></a>
- **[executable(name)](../app.py#L58)** receives a media-tool name, looks in the active Python environment and PATH, and returns the executable path to startup.

<a id="app-bodylimitmiddleware-call"></a>
- **[BodyLimitMiddleware.__call__(self, scope, receive, send)](../app.py#L119)** receives the ASGI request context, selects the route's byte limit and wraps the reader with `limited_receive()`, then forwards messages to the downstream application or sends a 413 response when the limit is exceeded.

<a id="app-bodylimitmiddleware-call-limited-receive"></a>
- **[BodyLimitMiddleware.__call__.limited_receive()](../app.py#L125)** receives no explicit arguments, reads a message from the captured reader and counts its actual body bytes, then returns the message to downstream request parsing or raises `BodyTooLarge`.

The shared guard counts bytes as the route reads the body, rather than reading the whole upload before route dispatch; see [call flows](api-flows.md) for framework operations and [errors](api-errors.md) for failure responses.
