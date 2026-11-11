# 逐函数与方法索引（按当前源码文件）

[中文 README](../README.zh-CN.md) · [English README](../README.md) · [接口调用链](api-flows.md) · [集中报错](api-errors.md)

范围为版本化 Python 源码：app.py、scripts/、tests/。包括类方法、嵌套函数、Expat 回调和假模型，不列第三方继承方法、lambda 表达式或被 Git 忽略的本地验证启动器。两个 __init__.py 只含包说明，无自定义函数。Prediction 和 BodyTooLarge 无项目自定义方法；前者继承 Pydantic，后者是异常标记。签名保留源码中的参数名、默认值与已有注解；没有注解的返回值以行为说明，不伪造静态类型。

参数表中的 self/cls/inner 是绑定实例或类，不要求外部调用者显式传入。async def 的返回说明指 await 后的结果；带 contextmanager 的函数说明指装饰后的上下文管理器。捕获外层变量的 helper 会在职责中标出。下游包含注册后由框架触发的回调，不表示都在函数体中立即调用。测试方法通常返回 None，以断言/异常表示通过或失败，不返回分类评估结果。

入口：[/predict](#app-predict) → [convert_and_predict](#app-convert-and-predict) → [predict_samples](#app-predict-samples) → [english_label](#app-english-label)。

入口：[/predict_multi](#app-predict-multi) → [save_multi_upload](#app-save-multi-upload) → [predict_transcript](#app-predict-transcript) → [parse_transcript](#app-parse-transcript) / [predict_samples](#app-predict-samples) → XML bytes。

直接 Python 工具：[predict_segment](#app-predict-segment) → [extract_audio_segment](#app-extract-audio-segment) → [predict_samples](#app-predict-samples)。


## app.py

[源码](../app.py)；本文件共 19 个项目自定义函数/方法。


<a id="app-english-label"></a>
### english_label

```python
def english_label(label: str) -> str
```

- **源码：** [app.py:48](../app.py#L48)。
- **参数：** `label`：模型返回的单个标签字符串，可能带语言前缀。
- **返回值：** str；非法类别抛 ValueError。
- **职责：** 取最后一个斜杠后的英文名并检查允许类别，不改分数顺序。
- **调用方：** predict_samples；直接工具/测试。
- **主要下游：** 无其他项目自定义函数；库/框架调用见职责及源码。


<a id="app-executable"></a>
### executable

```python
def executable(name)
```

- **源码：** [app.py:58](../app.py#L58)。
- **参数：** `name`：工具名 ffmpeg 或 ffprobe。
- **返回值：** str 程序路径；未找到抛 RuntimeError。
- **职责：** 优先环境 Library/bin，再查 PATH。
- **调用方：** lifespan；HTTP 验证 CLI；两组测试 setup。
- **主要下游：** 无其他项目自定义函数；库/框架调用见职责及源码。


<a id="app-lifespan"></a>
### lifespan

```python
async def lifespan(app)
```

- **源码：** [app.py:70](../app.py#L70)。
- **参数：** `app`：FastAPI 应用（lifespan）。
- **返回值：** 异步上下文管理器；yield 期间提供共享状态，正常关闭后释放模型引用。
- **职责：** 启动查工具、建 gate/lock、限制 torch 线程、加载单个 CPU 模型。
- **调用方：** FastAPI/Uvicorn 生命周期。
- **主要下游：** [executable()](#app-executable)。


<a id="app-bodylimitmiddleware-init"></a>
### BodyLimitMiddleware.__init__

```python
def __init__(self, app)
```

- **源码：** [app.py:116](../app.py#L116)。
- **参数：** `self`：当前 BodyLimitMiddleware 实例，保存下游 ASGI 应用；`app`：下游 ASGI 应用（中间件构造）。
- **返回值：** None；保存下游 ASGI app。
- **职责：** 建立请求大小中间件实例。
- **调用方：** FastAPI 中间件栈构建。
- **主要下游：** 无其他项目自定义函数；库/框架调用见职责及源码。


<a id="app-bodylimitmiddleware-call"></a>
### BodyLimitMiddleware.__call__

```python
async def __call__(self, scope, receive, send)
```

- **源码：** [app.py:119](../app.py#L119)。
- **参数：** `self`：当前 BodyLimitMiddleware 实例，保存下游 ASGI 应用；`scope`：ASGI 请求信息字典，含 type/path/headers；`receive`：可 await 的 ASGI 消息读取函数；可能被中间件包装；`send`：可 await 的 ASGI 响应发送函数。
- **返回值：** None / 下游 ASGI 调用结果；通过 send 输出响应。
- **职责：** 选择路径上限，包装 receive 并将 BodyTooLarge 转 413。
- **调用方：** ASGI 服务器/中间件栈；body guard 测试。
- **主要下游：** [BodyLimitMiddleware.__call__.limited_receive()](#app-bodylimitmiddleware-call-limited-receive)。


<a id="app-bodylimitmiddleware-call-limited-receive"></a>
### BodyLimitMiddleware.__call__.limited_receive

```python
async def limited_receive()
```

- **源码：** [app.py:125](../app.py#L125)。
- **参数：** 无显式参数；所需状态见职责中的闭包/实例说明。
- **返回值：** dict：下一条 ASGI 消息；超限抛 BodyTooLarge。
- **职责：** 闭包累计真实 body 字节；即使声明长度不实仍检查。
- **调用方：** 下游应用/表单解析器通过包装后的 receive 调用。
- **主要下游：** 无其他项目自定义函数；库/框架调用见职责及源码。


<a id="app-predict-samples"></a>
### predict_samples

```python
def predict_samples(state, samples, filename)
```

- **源码：** [app.py:144](../app.py#L144)。
- **参数：** `state`：已初始化应用共享状态，含工具路径、model、lock 等；`samples`：16 kHz 一维 NumPy float32 波形数组；`filename`：Prediction 的展示文件名；predict_segment 的 None 默认使用 source.name。
- **返回值：** Prediction；模型结构或标签/分数非法时抛异常。
- **职责：** 锁内调用已有模型，校验九项，保持标签分数对应并选择最高项。
- **调用方：** convert_and_predict、predict_segment、predict_transcript；测试。
- **主要下游：** [english_label()](#app-english-label)。


<a id="app-convert-and-predict"></a>
### convert_and_predict

```python
def convert_and_predict(state, source, destination, filename)
```

- **源码：** [app.py:172](../app.py#L172)。
- **参数：** `state`：已初始化应用共享状态，含工具路径、model、lock 等；`source`：磁盘媒体文件 Path/路径，通常为本次上传的临时副本；`destination`：输出标准 PCM16 WAV 的 Path；`filename`：Prediction 的展示文件名；predict_segment 的 None 默认使用 source.name。
- **返回值：** Prediction；输入错误抛 HTTPException(422)，内部错误 500。
- **职责：** FFprobe 检查、FFmpeg 转短音频、读 float32、检查 0.25–30 秒。
- **调用方：** predict 在线程池中；单段回归测试。
- **主要下游：** [predict_samples()](#app-predict-samples)。


<a id="app-extract-audio-segment"></a>
### extract_audio_segment

```python
def extract_audio_segment(state, source, start, end)
```

- **源码：** [app.py:218](../app.py#L218)。
- **参数：** `state`：已初始化应用共享状态，含工具路径、model、lock 等；`source`：磁盘媒体文件 Path/路径，通常为本次上传的临时副本；`start`：Python 单段工具的开始秒数，有限 Real，非 bool；`end`：Python 单段工具的结束秒数，不是 XML 的 dur。
- **返回值：** 上下文管理器，yield 临时 WAV 的 Path；退出时删除。
- **职责：** 检查 Python 时间参数，FFmpeg 提取一个区间并核对真实帧数。
- **调用方：** predict_segment；单段测试中的 with。
- **主要下游：** 无其他项目自定义函数；库/框架调用见职责及源码。


<a id="app-predict-segment"></a>
### predict_segment

```python
def predict_segment(state, source, start, end, filename=None)
```

- **源码：** [app.py:261](../app.py#L261)。
- **参数：** `state`：已初始化应用共享状态，含工具路径、model、lock 等；`source`：磁盘媒体文件 Path/路径，通常为本次上传的临时副本；`start`：Python 单段工具的开始秒数，有限 Real，非 bool；`end`：Python 单段工具的结束秒数，不是 XML 的 dur；`filename`：Prediction 的展示文件名；predict_segment 的 None 默认使用 source.name。
- **返回值：** Prediction；提取/模型异常向调用方传播。
- **职责：** 直接 Python 单段推理，不加载模型、不发 HTTP，不取得路由 gate。
- **调用方：** 直接 Python 调用、单段测试；不由 predict_multi 调用。
- **主要下游：** [extract_audio_segment()](#app-extract-audio-segment)；[predict_samples()](#app-predict-samples)。


<a id="app-health"></a>
### health

```python
def health()
```

- **源码：** [app.py:275](../app.py#L275)。
- **参数：** 无显式参数；所需状态见职责中的闭包/实例说明。
- **返回值：** dict：status/model/device。
- **职责：** 报告就绪信息，不运行模型。
- **调用方：** FastAPI GET /health；HTTP 验证脚本。
- **主要下游：** 无其他项目自定义函数；库/框架调用见职责及源码。


<a id="app-predict"></a>
### predict

```python
async def predict(request: Request)
```

- **源码：** [app.py:286](../app.py#L286)。
- **参数：** `request`：FastAPI/Starlette Request，带本次表单和 request.app.state。
- **返回值：** Prediction，FastAPI 按 response_model 序列化为 JSON。
- **职责：** 单文件 POST 入口：gate、表单/后缀/大小检查、临时上传、线程池工作。
- **调用方：** FastAPI POST /predict；HTTP 客户端与测试。
- **主要下游：** [convert_and_predict()](#app-convert-and-predict)。


<a id="app-parse-transcript"></a>
### parse_transcript

```python
def parse_transcript(data)
```

- **源码：** [app.py:325](../app.py#L325)。
- **参数：** `data`：上传 XML 的 bytes。
- **返回值：** (root, segments)：Element 根与 (element, first, last) 元组列表；失败为 413/422。
- **职责：** 安全解析、检查结构/数量/全部时间，保留文档顺序并计算采样索引。
- **调用方：** predict_transcript；直接解析边界测试。
- **主要下游：** [parse_transcript.forbidden()](#app-parse-transcript-forbidden)；[parse_transcript.start()](#app-parse-transcript-start)；[parse_transcript.end()](#app-parse-transcript-end)。


<a id="app-parse-transcript-forbidden"></a>
### parse_transcript.forbidden

```python
def forbidden(*args)
```

- **源码：** [app.py:337](../app.py#L337)。
- **参数：** `args`：对应 DTD/实体事件参数；不读取内容而直接抛异常。
- **返回值：** 不正常返回；抛 ValueError。
- **职责：** 拒绝 DTD、实体声明及外部实体解析事件。
- **调用方：** Expat 对应三个事件回调（由 parse_transcript 注册）。
- **主要下游：** 无其他项目自定义函数；库/框架调用见职责及源码。


<a id="app-parse-transcript-start"></a>
### parse_transcript.start

```python
def start(*args)
```

- **源码：** [app.py:340](../app.py#L340)。
- **参数：** `args`：Expat 开始事件的元素名/属性等参数；回调只使用闭包深度。
- **返回值：** None；更新闭包 depth；超 128 层抛 ValueError。
- **职责：** 每个 XML 开始元素事件增加深度。
- **调用方：** Expat StartElementHandler。
- **主要下游：** 无其他项目自定义函数；库/框架调用见职责及源码。


<a id="app-parse-transcript-end"></a>
### parse_transcript.end

```python
def end(*args)
```

- **源码：** [app.py:346](../app.py#L346)。
- **参数：** `args`：Expat 结束事件的元素名参数；回调只使用闭包深度。
- **返回值：** None；减少闭包 depth。
- **职责：** 每个 XML 结束元素事件减少深度。
- **调用方：** Expat EndElementHandler。
- **主要下游：** 无其他项目自定义函数；库/框架调用见职责及源码。


<a id="app-predict-transcript"></a>
### predict_transcript

```python
def predict_transcript(state, source, transcript, destination)
```

- **源码：** [app.py:390](../app.py#L390)。
- **参数：** `state`：已初始化应用共享状态，含工具路径、model、lock 等；`source`：磁盘媒体文件 Path/路径，通常为本次上传的临时副本；`transcript`：predict_transcript 接受的 XML bytes，不是上传对象；`destination`：输出标准 PCM16 WAV 的 Path。
- **返回值：** bytes：完整更新后的 UTF-8 XML；失败抛 HTTPException。
- **职责：** 先解析全部段，再一次解码、验全部范围、逐段预测/改 emotion、序列化；不改其他属性。
- **调用方：** predict_multi 在线程池中；端点测试。
- **主要下游：** [parse_transcript()](#app-parse-transcript)；[predict_samples()](#app-predict-samples)。


<a id="app-save-multi-upload"></a>
### save_multi_upload

```python
async def save_multi_upload(upload, path, limit, description)
```

- **源码：** [app.py:441](../app.py#L441)。
- **参数：** `upload`：UploadFile 上传文件对象；`path`：上传内容写入的临时 Path；`limit`：此上传文件允许的最大字节数；`description`：Media/XML，用于空文件/大小超限消息。
- **返回值：** None；副作用为已写入 path，空文件/超限为 422/413。
- **职责：** 分块读 UploadFile、限制单文件大小并在线程池写磁盘。
- **调用方：** predict_multi，分别用于媒体和 XML。
- **主要下游：** 无其他项目自定义函数；库/框架调用见职责及源码。


<a id="app-predict-multi"></a>
### predict_multi

```python
async def predict_multi(request: Request)
```

- **源码：** [app.py:460](../app.py#L460)。
- **参数：** `request`：FastAPI/Starlette Request，带本次表单和 request.app.state。
- **返回值：** Response：UTF-8 application/xml 附件；错误 JSON 由框架输出。
- **职责：** 双文件 POST 入口：共享 gate、临时文件和表单上下文；只在全部成功后返回。
- **调用方：** FastAPI POST /predict_multi；TestClient/HTTP 客户端。
- **主要下游：** [save_multi_upload()](#app-save-multi-upload)；[predict_transcript()](#app-predict-transcript)。


## scripts/verify_predict_http.py

[源码](../scripts/verify_predict_http.py)；本文件共 3 个项目自定义函数/方法。


<a id="scripts-main"></a>
### main

```python
def main()
```

- **源码：** [scripts/verify_predict_http.py:19](../scripts/verify_predict_http.py#L19)。
- **参数：** 无显式参数；所需状态见职责中的闭包/实例说明。
- **返回值：** None；打印断言结果，成功后写 test-artifacts/results.json。
- **职责：** 解析 speech/--url，生成媒体后对运行中的 /predict 做 18 个 POST 检查。
- **调用方：** python -m scripts.verify_predict_http 的 __main__ 分支。
- **主要下游：** [executable()](#app-executable)；[main.convert()](#scripts-main-convert)；[main.check()](#scripts-main-check)。


<a id="scripts-main-convert"></a>
### main.convert

```python
def convert(arguments)
```

- **源码：** [scripts/verify_predict_http.py:31](../scripts/verify_predict_http.py#L31)。
- **参数：** `arguments`：传给 FFmpeg 的参数列表，展开到公共命令后。
- **返回值：** None；FFmpeg 失败由 check=True 抛 CalledProcessError。
- **职责：** 生成测试格式和无音轨视频，使用闭包 ffmpeg。
- **调用方：** main；在发 HTTP 前准备文件。
- **主要下游：** 无其他项目自定义函数；库/框架调用见职责及源码。


<a id="scripts-main-check"></a>
### main.check

```python
def check(name, files, expected)
```

- **源码：** [scripts/verify_predict_http.py:52](../scripts/verify_predict_http.py#L52)。
- **参数：** `name`：本次 HTTP 测试用例的显示名称；`files`：HTTPX multipart files 数据，含上传名和字节内容；`expected`：HTTP 用例预期状态码，如 200/422。
- **返回值：** None；更新闭包 results；断言不符则失败。
- **职责：** 上传一个用例，校验状态码和成功 JSON 的九英文标签/分数/最大值。
- **调用方：** main 的格式、错误、连续请求用例循环。
- **主要下游：** 无其他项目自定义函数；库/框架调用见职责及源码。


## tests/test_audio_segments.py

[源码](../tests/test_audio_segments.py)；本文件共 16 个项目自定义函数/方法。


<a id="tests-audio-segmenttests-setupclass"></a>
### SegmentTests.setUpClass

```python
def setUpClass(cls)
```

- **源码：** [tests/test_audio_segments.py:18](../tests/test_audio_segments.py#L18)。
- **参数：** `cls`：SegmentTests 测试类，设置共享 ffmpeg 路径。
- **返回值：** None；设置类属性 ffmpeg。
- **职责：** 整组测试前查现有 FFmpeg。
- **调用方：** unittest 类级初始化。
- **主要下游：** [executable()](#app-executable)。


<a id="tests-audio-segmenttests-setup"></a>
### SegmentTests.setUp

```python
def setUp(self)
```

- **源码：** [tests/test_audio_segments.py:21](../tests/test_audio_segments.py#L21)。
- **参数：** `self`：当前测试类实例，保存 fixture、客户端/状态和断言方法。
- **返回值：** None；生成 self.source、自有 state 与隔离 TEMP_ROOT。
- **职责：** 每例建立生成 stereo/48 kHz WAV、补丁和自动清理。
- **调用方：** unittest 每个 test_* 方法前。
- **主要下游：** [SegmentTests.write_wav()](#tests-audio-segmenttests-write-wav)；[executable()](#app-executable)。


<a id="tests-audio-segmenttests-write-wav"></a>
### SegmentTests.write_wav

```python
def write_wav(path, samples, rate)
```

- **源码：** [tests/test_audio_segments.py:37](../tests/test_audio_segments.py#L37)。
- **参数：** `path`：生成测试 WAV 的输出 Path；`samples`：二维浮点数组，第二维是声道数；`rate`：生成 WAV 的每秒采样数。
- **返回值：** None；写入 path。
- **职责：** 将二维浮点采样保存为指定声道数/rate 的 PCM16 WAV；staticmethod。
- **调用方：** setUp；长源和时长限制测试。
- **主要下游：** 无其他项目自定义函数；库/框架调用见职责及源码。


<a id="tests-audio-segmenttests-assert-clean"></a>
### SegmentTests.assert_clean

```python
def assert_clean(self)
```

- **源码：** [tests/test_audio_segments.py:42](../tests/test_audio_segments.py#L42)。
- **参数：** `self`：当前测试类实例，保存 fixture、客户端/状态和断言方法。
- **返回值：** None；若临时目录非空则断言失败。
- **职责：** 核对应用临时目录无残留。
- **调用方：** 本类提取/推理/失败用例。
- **主要下游：** 无其他项目自定义函数；库/框架调用见职责及源码。


<a id="tests-audio-segmenttests-test-accuracy-and-format"></a>
### SegmentTests.test_accuracy_and_format

```python
def test_accuracy_and_format(self)
```

- **源码：** [tests/test_audio_segments.py:45](../tests/test_audio_segments.py#L45)。
- **参数：** `self`：当前测试类实例，保存 fixture、客户端/状态和断言方法。
- **返回值：** None；断言不满足时测试失败。
- **职责：** 用频率/振幅变化核对片段时点、mono/16 kHz/PCM16 与样本数；accuracy 指提取准确。
- **调用方：** unittest runner；由 setUp 先准备 fixture。
- **主要下游：** [extract_audio_segment()](#app-extract-audio-segment)；[SegmentTests.assert_clean()](#tests-audio-segmenttests-assert-clean)。


<a id="tests-audio-segmenttests-test-fractional-sample-boundaries-and-exact-end"></a>
### SegmentTests.test_fractional_sample_boundaries_and_exact_end

```python
def test_fractional_sample_boundaries_and_exact_end(self)
```

- **源码：** [tests/test_audio_segments.py:58](../tests/test_audio_segments.py#L58)。
- **参数：** `self`：当前测试类实例，保存 fixture、客户端/状态和断言方法。
- **返回值：** None；断言不满足时测试失败。
- **职责：** 检查非整采样边界的向上取整和恰好音频末尾。
- **调用方：** unittest runner；由 setUp 先准备 fixture。
- **主要下游：** [extract_audio_segment()](#app-extract-audio-segment)；[SegmentTests.assert_clean()](#tests-audio-segmenttests-assert-clean)。


<a id="tests-audio-segmenttests-test-invalid-timestamps"></a>
### SegmentTests.test_invalid_timestamps

```python
def test_invalid_timestamps(self)
```

- **源码：** [tests/test_audio_segments.py:65](../tests/test_audio_segments.py#L65)。
- **参数：** `self`：当前测试类实例，保存 fixture、客户端/状态和断言方法。
- **返回值：** None；断言不满足时测试失败。
- **职责：** 拒绝负数/倒序/相等/NaN/无穷/类型错误/极大数和不支持长度。
- **调用方：** unittest runner；由 setUp 先准备 fixture。
- **主要下游：** [extract_audio_segment()](#app-extract-audio-segment)。


<a id="tests-audio-segmenttests-test-out-of-range"></a>
### SegmentTests.test_out_of_range

```python
def test_out_of_range(self)
```

- **源码：** [tests/test_audio_segments.py:73](../tests/test_audio_segments.py#L73)。
- **参数：** `self`：当前测试类实例，保存 fixture、客户端/状态和断言方法。
- **返回值：** None；断言不满足时测试失败。
- **职责：** 拒绝部分越界和完全越界片段并清理。
- **调用方：** unittest runner；由 setUp 先准备 fixture。
- **主要下游：** [extract_audio_segment()](#app-extract-audio-segment)；[SegmentTests.assert_clean()](#tests-audio-segmenttests-assert-clean)。


<a id="tests-audio-segmenttests-test-long-source-and-video"></a>
### SegmentTests.test_long_source_and_video

```python
def test_long_source_and_video(self)
```

- **源码：** [tests/test_audio_segments.py:80](../tests/test_audio_segments.py#L80)。
- **参数：** `self`：当前测试类实例，保存 fixture、客户端/状态和断言方法。
- **返回值：** None；断言不满足时测试失败。
- **职责：** 验证长于 30 秒源媒体仍可取合法段，并检查视频音轨。
- **调用方：** unittest runner；由 setUp 先准备 fixture。
- **主要下游：** [extract_audio_segment()](#app-extract-audio-segment)；[SegmentTests.assert_clean()](#tests-audio-segmenttests-assert-clean)。


<a id="tests-audio-segmenttests-test-missing-audio-track"></a>
### SegmentTests.test_missing_audio_track

```python
def test_missing_audio_track(self)
```

- **源码：** [tests/test_audio_segments.py:95](../tests/test_audio_segments.py#L95)。
- **参数：** `self`：当前测试类实例，保存 fixture、客户端/状态和断言方法。
- **返回值：** None；断言不满足时测试失败。
- **职责：** 拒绝没有音轨的生成视频并清理。
- **调用方：** unittest runner；由 setUp 先准备 fixture。
- **主要下游：** [extract_audio_segment()](#app-extract-audio-segment)；[SegmentTests.assert_clean()](#tests-audio-segmenttests-assert-clean)。


<a id="tests-audio-segmenttests-fake-model"></a>
### SegmentTests.fake_model

```python
def fake_model(self, output=None, failure=None)
```

- **源码：** [tests/test_audio_segments.py:107](../tests/test_audio_segments.py#L107)。
- **参数：** `self`：当前测试类实例，保存 fixture、客户端/状态和断言方法；`output`：假模型预先安排的单结果列表，默认 None；不代表真实推理；`failure`：假模型要抛出的异常，默认 None 不抛。
- **返回值：** None；设置 self.state.model。
- **职责：** 用带锁、参数、形状断言的假模型代替权重模型。
- **调用方：** 英文对齐与失败清理测试。
- **主要下游：** [SegmentTests.fake_model.FakeModel.generate()](#tests-audio-segmenttests-fake-model-fakemodel-generate)。


<a id="tests-audio-segmenttests-fake-model-fakemodel-generate"></a>
### SegmentTests.fake_model.FakeModel.generate

```python
def generate(inner, **kwargs)
```

- **源码：** [tests/test_audio_segments.py:110](../tests/test_audio_segments.py#L110)。
- **参数：** `inner`：局部 FakeModel 实例，方法实际读取外层测试闭包；`kwargs`：模型 generate 关键字参数，检查 input/fs/granularity/extract_embedding。
- **返回值：** 单结果列表，来自闭包 output；指定 failure 时抛异常。
- **职责：** 断言锁、16 kHz、float32、12000 采样及推理选项。
- **调用方：** app.predict_samples 经 state.model.generate 调用。
- **主要下游：** 无其他项目自定义函数；库/框架调用见职责及源码。


<a id="tests-audio-segmenttests-test-fake-model-english-alignment-and-shared-upload-path"></a>
### SegmentTests.test_fake_model_english_alignment_and_shared_upload_path

```python
def test_fake_model_english_alignment_and_shared_upload_path(self)
```

- **源码：** [tests/test_audio_segments.py:122](../tests/test_audio_segments.py#L122)。
- **参数：** `self`：当前测试类实例，保存 fixture、客户端/状态和断言方法。
- **返回值：** None；断言不满足时测试失败。
- **职责：** 假模型核对英文标签/分数及共享短上传路径。
- **调用方：** unittest runner；由 setUp 先准备 fixture。
- **主要下游：** [SegmentTests.fake_model()](#tests-audio-segmenttests-fake-model)；[predict_segment()](#app-predict-segment)；[convert_and_predict()](#app-convert-and-predict)；[SegmentTests.assert_clean()](#tests-audio-segmenttests-assert-clean)。


<a id="tests-audio-segmenttests-test-cleanup-on-inference-or-output-failure"></a>
### SegmentTests.test_cleanup_on_inference_or_output_failure

```python
def test_cleanup_on_inference_or_output_failure(self)
```

- **源码：** [tests/test_audio_segments.py:138](../tests/test_audio_segments.py#L138)。
- **参数：** `self`：当前测试类实例，保存 fixture、客户端/状态和断言方法。
- **返回值：** None；断言不满足时测试失败。
- **职责：** 推理异常及非法模型结果均触发清理。
- **调用方：** unittest runner；由 setUp 先准备 fixture。
- **主要下游：** [SegmentTests.fake_model()](#tests-audio-segmenttests-fake-model)；[predict_segment()](#app-predict-segment)；[SegmentTests.assert_clean()](#tests-audio-segmenttests-assert-clean)。


<a id="tests-audio-segmenttests-test-cleanup-on-decode-failure-timeout-and-caller-failure"></a>
### SegmentTests.test_cleanup_on_decode_failure_timeout_and_caller_failure

```python
def test_cleanup_on_decode_failure_timeout_and_caller_failure(self)
```

- **源码：** [tests/test_audio_segments.py:145](../tests/test_audio_segments.py#L145)。
- **参数：** `self`：当前测试类实例，保存 fixture、客户端/状态和断言方法。
- **返回值：** None；断言不满足时测试失败。
- **职责：** 损坏输入、模拟超时和 with 调用方异常均清理。
- **调用方：** unittest runner；由 setUp 先准备 fixture。
- **主要下游：** [extract_audio_segment()](#app-extract-audio-segment)；[predict_segment()](#app-predict-segment)；[SegmentTests.assert_clean()](#tests-audio-segmenttests-assert-clean)。


<a id="tests-audio-segmenttests-test-existing-upload-duration-limits"></a>
### SegmentTests.test_existing_upload_duration_limits

```python
def test_existing_upload_duration_limits(self)
```

- **源码：** [tests/test_audio_segments.py:161](../tests/test_audio_segments.py#L161)。
- **参数：** `self`：当前测试类实例，保存 fixture、客户端/状态和断言方法。
- **返回值：** None；断言不满足时测试失败。
- **职责：** 原短音频转换仍拒绝 .1 秒/31 秒。
- **调用方：** unittest runner；由 setUp 先准备 fixture。
- **主要下游：** [convert_and_predict()](#app-convert-and-predict)。


## tests/test_predict_multi.py

[源码](../tests/test_predict_multi.py)；本文件共 31 个项目自定义函数/方法。


<a id="tests-multi-xml-document"></a>
### xml_document

```python
def xml_document(segments=None)
```

- **源码：** [tests/test_predict_multi.py:23](../tests/test_predict_multi.py#L23)。
- **参数：** `segments`：可选的 SpeechSegment XML 字符串；None 用默认双段。
- **返回值：** bytes：生成的 UTF-8 AudioDoc 测试 XML。
- **职责：** 包装图像/声音描述、注释/PI 和 SegmentList，默认含乱序/旧 emotion 两段。
- **调用方：** MultiTests.request；多个 XML 拒绝/保留用例。
- **主要下游：** 无其他项目自定义函数；库/框架调用见职责及源码。


<a id="tests-multi-tree-signature"></a>
### tree_signature

```python
def tree_signature(data)
```

- **源码：** [tests/test_predict_multi.py:29](../tests/test_predict_multi.py#L29)。
- **参数：** `data`：XML bytes；tree_signature 中是待比较的 XML 内容。
- **返回值：** 嵌套 tuple：排除 SpeechSegment.emotion 的树签名。
- **职责：** 解析并递归收集 tag/其他属性/text/tail/子元素顺序。
- **调用方：** 保留、Unicode、65 段测试。
- **主要下游：** [tree_signature.walk()](#tests-multi-tree-signature-walk)。


<a id="tests-multi-tree-signature-walk"></a>
### tree_signature.walk

```python
def walk(e)
```

- **源码：** [tests/test_predict_multi.py:31](../tests/test_predict_multi.py#L31)。
- **参数：** `e`：ElementTree 当前元素节点。
- **返回值：** tuple：当前元素及递归子树签名。
- **职责：** 只去掉 SpeechSegment 的 emotion，不忽略其他属性和文本。
- **调用方：** tree_signature；自身递归。
- **主要下游：** [tree_signature.walk()](#tests-multi-tree-signature-walk)。


<a id="tests-multi-multitests-setup"></a>
### MultiTests.setUp

```python
def setUp(self)
```

- **源码：** [tests/test_predict_multi.py:40](../tests/test_predict_multi.py#L40)。
- **参数：** `self`：当前测试类实例，保存 fixture、客户端/状态和断言方法。
- **返回值：** None；设置隔离目录/全局 app.state、TestClient 和生成 WAV。
- **职责：** 注册还原/清理，准备假模型及 stereo/48 kHz 波形，不启动 lifespan。
- **调用方：** unittest 每例前。
- **主要下游：** [executable()](#app-executable)；[MultiTests.setUp.FakeModel.generate()](#tests-multi-multitests-setup-fakemodel-generate)。


<a id="tests-multi-multitests-setup-fakemodel-generate"></a>
### MultiTests.setUp.FakeModel.generate

```python
def generate(inner, **kwargs)
```

- **源码：** [tests/test_predict_multi.py:53](../tests/test_predict_multi.py#L53)。
- **参数：** `inner`：局部 FakeModel 实例，方法实际读取外层测试闭包；`kwargs`：模型 generate 关键字参数，检查 input/fs/granularity/extract_embedding。
- **返回值：** 九类单结果列表；首次选 `<unk>`，随后选 happy。
- **职责：** 断言 lock/gate/线程/float32/8000 采样，记录数组到闭包 owner.calls。
- **调用方：** app.predict_samples 经被替换的模型调用。
- **主要下游：** 无其他项目自定义函数；库/框架调用见职责及源码。


<a id="tests-multi-multitests-request"></a>
### MultiTests.request

```python
def request(self, xml=None, audio=None)
```

- **源码：** [tests/test_predict_multi.py:75](../tests/test_predict_multi.py#L75)。
- **参数：** `self`：当前测试类实例，保存 fixture、客户端/状态和断言方法；`xml`：可选测试 XML bytes，None 使用默认生成文档；`audio`：可选测试媒体 bytes，None 使用生成 WAV。
- **返回值：** httpx.Response（TestClient 运行 ASGI 后的响应）。
- **职责：** 将给定或默认生成媒体/XML 以两个文件字段发到 /predict_multi。
- **调用方：** 多数 MultiTests.test_* 用例。
- **主要下游：** [xml_document()](#tests-multi-xml-document)。


<a id="tests-multi-multitests-assert-clean"></a>
### MultiTests.assert_clean

```python
def assert_clean(self)
```

- **源码：** [tests/test_predict_multi.py:78](../tests/test_predict_multi.py#L78)。
- **参数：** `self`：当前测试类实例，保存 fixture、客户端/状态和断言方法。
- **返回值：** None；残留时断言失败。
- **职责：** 检查隔离应用临时目录为空。
- **调用方：** 本类多数测试。
- **主要下游：** 无其他项目自定义函数；库/框架调用见职责及源码。


<a id="tests-multi-multitests-test-updates-preservation-order-escaping-offsets-and-one-decode"></a>
### MultiTests.test_updates_preservation_order_escaping_offsets_and_one_decode

```python
def test_updates_preservation_order_escaping_offsets_and_one_decode(self)
```

- **源码：** [tests/test_predict_multi.py:81](../tests/test_predict_multi.py#L81)。
- **参数：** `self`：当前测试类实例，保存 fixture、客户端/状态和断言方法。
- **返回值：** None；断言不满足时测试失败。
- **职责：** 双段乱序、旧 emotion 覆盖、`<unk>` 转义、实际采样振幅、附件头和一次解码。
- **调用方：** unittest runner；由 setUp 先准备 fixture。
- **主要下游：** [MultiTests.request()](#tests-multi-multitests-request)；[tree_signature()](#tests-multi-tree-signature)；[MultiTests.assert_clean()](#tests-multi-multitests-assert-clean)。


<a id="tests-multi-multitests-test-65-generated-segments-preserve-all-other-content"></a>
### MultiTests.test_65_generated_segments_preserve_all_other_content

```python
def test_65_generated_segments_preserve_all_other_content(self)
```

- **源码：** [tests/test_predict_multi.py:99](../tests/test_predict_multi.py#L99)。
- **参数：** `self`：当前测试类实例，保存 fixture、客户端/状态和断言方法。
- **返回值：** None；断言不满足时测试失败。
- **职责：** 65 段假模型均更新、仅一次解码、其他 XML 签名不变。
- **调用方：** unittest runner；由 setUp 先准备 fixture。
- **主要下游：** [xml_document()](#tests-multi-xml-document)；[MultiTests.request()](#tests-multi-multitests-request)；[tree_signature()](#tests-multi-tree-signature)；[MultiTests.assert_clean()](#tests-multi-multitests-assert-clean)。


<a id="tests-multi-multitests-test-maximum-segment-count-and-decimal-boundaries"></a>
### MultiTests.test_maximum_segment_count_and_decimal_boundaries

```python
def test_maximum_segment_count_and_decimal_boundaries(self)
```

- **源码：** [tests/test_predict_multi.py:114](../tests/test_predict_multi.py#L114)。
- **参数：** `self`：当前测试类实例，保存 fixture、客户端/状态和断言方法。
- **返回值：** None；断言不满足时测试失败。
- **职责：** 1000 段接受边界及十进制采样索引。
- **调用方：** unittest runner；由 setUp 先准备 fixture。
- **主要下游：** [xml_document()](#tests-multi-xml-document)；[parse_transcript()](#app-parse-transcript)。


<a id="tests-multi-multitests-test-invalid-segments-fail-before-any-inference"></a>
### MultiTests.test_invalid_segments_fail_before_any_inference

```python
def test_invalid_segments_fail_before_any_inference(self)
```

- **源码：** [tests/test_predict_multi.py:121](../tests/test_predict_multi.py#L121)。
- **参数：** `self`：当前测试类实例，保存 fixture、客户端/状态和断言方法。
- **返回值：** None；断言不满足时测试失败。
- **职责：** 第二段缺失/无效时间在解码及任何推理前拒绝。
- **调用方：** unittest runner；由 setUp 先准备 fixture。
- **主要下游：** [MultiTests.request()](#tests-multi-multitests-request)；[xml_document()](#tests-multi-xml-document)；[MultiTests.assert_clean()](#tests-multi-multitests-assert-clean)。


<a id="tests-multi-multitests-test-late-out-of-range-fails-before-any-inference"></a>
### MultiTests.test_late_out_of_range_fails_before_any_inference

```python
def test_late_out_of_range_fails_before_any_inference(self)
```

- **源码：** [tests/test_predict_multi.py:131](../tests/test_predict_multi.py#L131)。
- **参数：** `self`：当前测试类实例，保存 fixture、客户端/状态和断言方法。
- **返回值：** None；断言不满足时测试失败。
- **职责：** 后续段实际采样越界时不调用模型，返回段索引。
- **调用方：** unittest runner；由 setUp 先准备 fixture。
- **主要下游：** [MultiTests.request()](#tests-multi-multitests-request)；[MultiTests.assert_clean()](#tests-multi-multitests-assert-clean)。


<a id="tests-multi-multitests-test-xml-declarations-rejected-in-multiple-encodings"></a>
### MultiTests.test_xml_declarations_rejected_in_multiple_encodings

```python
def test_xml_declarations_rejected_in_multiple_encodings(self)
```

- **源码：** [tests/test_predict_multi.py:139](../tests/test_predict_multi.py#L139)。
- **参数：** `self`：当前测试类实例，保存 fixture、客户端/状态和断言方法。
- **返回值：** None；断言不满足时测试失败。
- **职责：** UTF-8/UTF-16 中 DTD/实体/外部声明均拒绝且不解码。
- **调用方：** unittest runner；由 setUp 先准备 fixture。
- **主要下游：** [MultiTests.request()](#tests-multi-multitests-request)；[MultiTests.assert_clean()](#tests-multi-multitests-assert-clean)。


<a id="tests-multi-multitests-test-malformed-wrong-structure-empty-too-many-and-deep-xml"></a>
### MultiTests.test_malformed_wrong_structure_empty_too_many_and_deep_xml

```python
def test_malformed_wrong_structure_empty_too_many_and_deep_xml(self)
```

- **源码：** [tests/test_predict_multi.py:149](../tests/test_predict_multi.py#L149)。
- **参数：** `self`：当前测试类实例，保存 fixture、客户端/状态和断言方法。
- **返回值：** None；断言不满足时测试失败。
- **职责：** 空/畸形/错根/错层级/无段/1001 段/过深 XML 在解码前拒绝。
- **调用方：** unittest runner；由 setUp 先准备 fixture。
- **主要下游：** [MultiTests.request()](#tests-multi-multitests-request)；[MultiTests.assert_clean()](#tests-multi-multitests-assert-clean)。


<a id="tests-multi-multitests-test-exactly-two-file-fields"></a>
### MultiTests.test_exactly_two_file_fields

```python
def test_exactly_two_file_fields(self)
```

- **源码：** [tests/test_predict_multi.py:158](../tests/test_predict_multi.py#L158)。
- **参数：** `self`：当前测试类实例，保存 fixture、客户端/状态和断言方法。
- **返回值：** None；断言不满足时测试失败。
- **职责：** 少/多/重复/错名/文本字段拒绝。
- **调用方：** unittest runner；由 setUp 先准备 fixture。
- **主要下游：** [MultiTests.assert_clean()](#tests-multi-multitests-assert-clean)。


<a id="tests-multi-multitests-test-upload-limits-and-extensions"></a>
### MultiTests.test_upload_limits_and_extensions

```python
def test_upload_limits_and_extensions(self)
```

- **源码：** [tests/test_predict_multi.py:166](../tests/test_predict_multi.py#L166)。
- **参数：** `self`：当前测试类实例，保存 fixture、客户端/状态和断言方法。
- **返回值：** None；断言不满足时测试失败。
- **职责：** 缩小常量检查媒体/XML 独立大小限制、后缀和空文件。
- **调用方：** unittest runner；由 setUp 先准备 fixture。
- **主要下游：** [MultiTests.request()](#tests-multi-multitests-request)；[MultiTests.assert_clean()](#tests-multi-multitests-assert-clean)。


<a id="tests-multi-multitests-test-body-limits-are-route-specific-and-count-actual-bytes"></a>
### MultiTests.test_body_limits_are_route_specific_and_count_actual_bytes

```python
def test_body_limits_are_route_specific_and_count_actual_bytes(self)
```

- **源码：** [tests/test_predict_multi.py:177](../tests/test_predict_multi.py#L177)。
- **参数：** `self`：当前测试类实例，保存 fixture、客户端/状态和断言方法。
- **返回值：** None；断言不满足时测试失败。
- **职责：** 路径独立请求体上限，较小旧上限不影响新路径。
- **调用方：** unittest runner；由 setUp 先准备 fixture。
- **主要下游：** [MultiTests.request()](#tests-multi-multitests-request)；[MultiTests.assert_clean()](#tests-multi-multitests-assert-clean)。


<a id="tests-multi-multitests-test-model-failure-returns-no-partial-xml-and-cleans-up"></a>
### MultiTests.test_model_failure_returns_no_partial_xml_and_cleans_up

```python
def test_model_failure_returns_no_partial_xml_and_cleans_up(self)
```

- **源码：** [tests/test_predict_multi.py:186](../tests/test_predict_multi.py#L186)。
- **参数：** `self`：当前测试类实例，保存 fixture、客户端/状态和断言方法。
- **返回值：** None；断言不满足时测试失败。
- **职责：** 第二段模型失败时只给错误，无部分 XML，仍清理。
- **调用方：** unittest runner；由 setUp 先准备 fixture。
- **主要下游：** [MultiTests.request()](#tests-multi-multitests-request)；[MultiTests.test_model_failure_returns_no_partial_xml_and_cleans_up.fail_second()](#tests-multi-multitests-test-model-failure-returns-no-partial-xml-and-cleans-up-fail-second)；[MultiTests.assert_clean()](#tests-multi-multitests-assert-clean)。


<a id="tests-multi-multitests-test-model-failure-returns-no-partial-xml-and-cleans-up-fail-second"></a>
### MultiTests.test_model_failure_returns_no_partial_xml_and_cleans_up.fail_second

```python
def fail_second(**kwargs)
```

- **源码：** [tests/test_predict_multi.py:188](../tests/test_predict_multi.py#L188)。
- **参数：** `kwargs`：模型 generate 关键字参数，检查 input/fs/granularity/extract_embedding。
- **返回值：** 第一次返回假模型结果；第二次抛 RuntimeError。
- **职责：** 闭包捕获 original 和 self，用于制造后续片段失败。
- **调用方：** patch 替换的 model.generate，由 predict_samples 触发。
- **主要下游：** 无其他项目自定义函数；库/框架调用见职责及源码。


<a id="tests-multi-multitests-test-decode-failure-timeout-audio-and-output-limits"></a>
### MultiTests.test_decode_failure_timeout_audio_and_output_limits

```python
def test_decode_failure_timeout_audio_and_output_limits(self)
```

- **源码：** [tests/test_predict_multi.py:199](../tests/test_predict_multi.py#L199)。
- **参数：** `self`：当前测试类实例，保存 fixture、客户端/状态和断言方法。
- **返回值：** None；断言不满足时测试失败。
- **职责：** 损坏媒体、模拟超时及缩小的完整时长/输出上限均拒绝。
- **调用方：** unittest runner；由 setUp 先准备 fixture。
- **主要下游：** [MultiTests.request()](#tests-multi-multitests-request)；[MultiTests.assert_clean()](#tests-multi-multitests-assert-clean)。


<a id="tests-multi-multitests-test-shared-gate-and-worker-do-not-block-event-loop"></a>
### MultiTests.test_shared_gate_and_worker_do_not_block_event_loop

```python
def test_shared_gate_and_worker_do_not_block_event_loop(self)
```

- **源码：** [tests/test_predict_multi.py:216](../tests/test_predict_multi.py#L216)。
- **参数：** `self`：当前测试类实例，保存 fixture、客户端/状态和断言方法。
- **返回值：** None；断言不满足时测试失败。
- **职责：** 两个 HTTP 入口共用 gate，阻塞 worker 不阻塞事件循环。
- **调用方：** unittest runner；由 setUp 先准备 fixture。
- **主要下游：** [MultiTests.test_shared_gate_and_worker_do_not_block_event_loop.check()](#tests-multi-multitests-test-shared-gate-and-worker-do-not-block-event-loop-check)；[MultiTests.assert_clean()](#tests-multi-multitests-assert-clean)。


<a id="tests-multi-multitests-test-shared-gate-and-worker-do-not-block-event-loop-check"></a>
### MultiTests.test_shared_gate_and_worker_do_not_block_event_loop.check

```python
async def check()
```

- **源码：** [tests/test_predict_multi.py:217](../tests/test_predict_multi.py#L217)。
- **参数：** 无显式参数；所需状态见职责中的闭包/实例说明。
- **返回值：** None；异步验证并断言两个响应。
- **职责：** 启动阻塞 multi，再调 single，确认事件循环可运行而 single 等 gate。
- **调用方：** 父测试通过 asyncio.run 调用。
- **主要下游：** [MultiTests.test_shared_gate_and_worker_do_not_block_event_loop.check.multi_worker()](#tests-multi-multitests-test-shared-gate-and-worker-do-not-block-event-loop-check-multi-worker)；[MultiTests.test_shared_gate_and_worker_do_not_block_event_loop.check.single_worker()](#tests-multi-multitests-test-shared-gate-and-worker-do-not-block-event-loop-check-single-worker)。


<a id="tests-multi-multitests-test-shared-gate-and-worker-do-not-block-event-loop-check-multi-worker"></a>
### MultiTests.test_shared_gate_and_worker_do_not_block_event_loop.check.multi_worker

```python
def multi_worker(*args)
```

- **源码：** [tests/test_predict_multi.py:222](../tests/test_predict_multi.py#L222)。
- **参数：** `args`：解析回调为 Expat 传入的事件参数；worker 替身为原工作函数位置参数，均不展开使用。
- **返回值：** bytes：`<AudioDoc/>`。
- **职责：** 替换多段工作函数；检查 gate，记录调用，等待 release 事件。
- **调用方：** predict_multi 的 run_in_threadpool，经 patch 替换。
- **主要下游：** 无其他项目自定义函数；库/框架调用见职责及源码。


<a id="tests-multi-multitests-test-shared-gate-and-worker-do-not-block-event-loop-check-single-worker"></a>
### MultiTests.test_shared_gate_and_worker_do_not_block_event_loop.check.single_worker

```python
def single_worker(*args)
```

- **源码：** [tests/test_predict_multi.py:229](../tests/test_predict_multi.py#L229)。
- **参数：** `args`：解析回调为 Expat 传入的事件参数；worker 替身为原工作函数位置参数，均不展开使用。
- **返回值：** Prediction：固定 happy 的九类结果。
- **职责：** 替换短音频工作函数，记录调用并断言 gate 已取得。
- **调用方：** predict 的 run_in_threadpool，经 patch 替换。
- **主要下游：** 无其他项目自定义函数；库/框架调用见职责及源码。


<a id="tests-multi-multitests-test-chunked-body-guard-ignores-untrusted-content-length"></a>
### MultiTests.test_chunked_body_guard_ignores_untrusted_content_length

```python
def test_chunked_body_guard_ignores_untrusted_content_length(self)
```

- **源码：** [tests/test_predict_multi.py:254](../tests/test_predict_multi.py#L254)。
- **参数：** `self`：当前测试类实例，保存 fixture、客户端/状态和断言方法。
- **返回值：** None；断言不满足时测试失败。
- **职责：** 两条路径按真实分块计数而非相信声明长度。
- **调用方：** unittest runner；由 setUp 先准备 fixture。
- **主要下游：** [MultiTests.test_chunked_body_guard_ignores_untrusted_content_length.check()](#tests-multi-multitests-test-chunked-body-guard-ignores-untrusted-content-length-check)。


<a id="tests-multi-multitests-test-chunked-body-guard-ignores-untrusted-content-length-check"></a>
### MultiTests.test_chunked_body_guard_ignores_untrusted_content_length.check

```python
async def check(path, limit)
```

- **源码：** [tests/test_predict_multi.py:255](../tests/test_predict_multi.py#L255)。
- **参数：** `path`：被测 HTTP 路径 /predict 或 /predict_multi；`limit`：要临时缩小的请求体常量名字符串。
- **返回值：** None；异步断言最终状态 413。
- **职责：** 用两块真实字节和虚假 Content-Length 检查两个路由的限流中间件。
- **调用方：** 父测试用 asyncio.run，分别传两个路径/常量名。
- **主要下游：** [BodyLimitMiddleware.__call__()](#app-bodylimitmiddleware-call)；[MultiTests.test_chunked_body_guard_ignores_untrusted_content_length.check.receive()](#tests-multi-multitests-test-chunked-body-guard-ignores-untrusted-content-length-check-receive)；[MultiTests.test_chunked_body_guard_ignores_untrusted_content_length.check.send()](#tests-multi-multitests-test-chunked-body-guard-ignores-untrusted-content-length-check-send)；[MultiTests.test_chunked_body_guard_ignores_untrusted_content_length.check.consumer()](#tests-multi-multitests-test-chunked-body-guard-ignores-untrusted-content-length-check-consumer)。


<a id="tests-multi-multitests-test-chunked-body-guard-ignores-untrusted-content-length-check-receive"></a>
### MultiTests.test_chunked_body_guard_ignores_untrusted_content_length.check.receive

```python
async def receive()
```

- **源码：** [tests/test_predict_multi.py:259](../tests/test_predict_multi.py#L259)。
- **参数：** 无显式参数；所需状态见职责中的闭包/实例说明。
- **返回值：** dict：下一块预置 ASGI http.request 消息。
- **职责：** 异步产生测试字节块，捕获 messages 迭代器。
- **调用方：** 中间件 limited_receive 中 await receive()。
- **主要下游：** 无其他项目自定义函数；库/框架调用见职责及源码。


<a id="tests-multi-multitests-test-chunked-body-guard-ignores-untrusted-content-length-check-send"></a>
### MultiTests.test_chunked_body_guard_ignores_untrusted_content_length.check.send

```python
async def send(message)
```

- **源码：** [tests/test_predict_multi.py:261](../tests/test_predict_multi.py#L261)。
- **参数：** `message`：要收集的 ASGI 响应消息字典。
- **返回值：** None；追加到闭包 sent 列表。
- **职责：** 收集 ASGI 响应消息供断言。
- **调用方：** 中间件生成的 JSONResponse。
- **主要下游：** 无其他项目自定义函数；库/框架调用见职责及源码。


<a id="tests-multi-multitests-test-chunked-body-guard-ignores-untrusted-content-length-check-consumer"></a>
### MultiTests.test_chunked_body_guard_ignores_untrusted_content_length.check.consumer

```python
async def consumer(scope, receive, send)
```

- **源码：** [tests/test_predict_multi.py:263](../tests/test_predict_multi.py#L263)。
- **参数：** `scope`：ASGI 请求信息字典，含 type/path/headers；`receive`：可 await 的 ASGI 消息读取函数；可能被中间件包装；`send`：可 await 的 ASGI 响应发送函数。
- **返回值：** None。
- **职责：** 模拟下游 ASGI 应用，不断从包装后的 receive 读取直到末块。
- **调用方：** BodyLimitMiddleware.__call__ 调用 self.app。
- **主要下游：** 无其他项目自定义函数；库/框架调用见职责及源码。


<a id="tests-multi-multitests-test-no-audio-video-is-rejected-and-cleaned"></a>
### MultiTests.test_no_audio_video_is_rejected_and_cleaned

```python
def test_no_audio_video_is_rejected_and_cleaned(self)
```

- **源码：** [tests/test_predict_multi.py:272](../tests/test_predict_multi.py#L272)。
- **参数：** `self`：当前测试类实例，保存 fixture、客户端/状态和断言方法。
- **返回值：** None；断言不满足时测试失败。
- **职责：** 新端点拒绝无音轨的生成 MP4且无推理/残留。
- **调用方：** unittest runner；由 setUp 先准备 fixture。
- **主要下游：** [MultiTests.assert_clean()](#tests-multi-multitests-assert-clean)。


<a id="tests-multi-multitests-test-non-utf8-xml-preserves-unicode-semantics"></a>
### MultiTests.test_non_utf8_xml_preserves_unicode_semantics

```python
def test_non_utf8_xml_preserves_unicode_semantics(self)
```

- **源码：** [tests/test_predict_multi.py:282](../tests/test_predict_multi.py#L282)。
- **参数：** `self`：当前测试类实例，保存 fixture、客户端/状态和断言方法。
- **返回值：** None；断言不满足时测试失败。
- **职责：** UTF-16 中文输入输出为 UTF-8，XML 语义不变。
- **调用方：** unittest runner；由 setUp 先准备 fixture。
- **主要下游：** [MultiTests.request()](#tests-multi-multitests-request)；[tree_signature()](#tests-multi-tree-signature)；[MultiTests.assert_clean()](#tests-multi-multitests-assert-clean)。


总计 **69** 个函数/方法。签名、源码行和嵌套层级按当前 AST 核对；库函数不计入此数量。
