# 02：跟着一次媒体＋XML 请求读懂分段情绪 API

先读 [01：单文件 API 基础](01-single-file-api-learning.zh-CN.md)，再打开 [app.py](../app.py) 对照本文。本文依据当前源码，也核对了 [verify_api.py](../verify_api.py)、[test_segments.py](../test_segments.py)、[test_predict_multi.py](../test_predict_multi.py) 和已保存的[验证报告](../reports/predict-multi-verification-2026-11-02.md)。本次整理没有运行模型。

下面沿着“一次用户上传完整媒体和 XML，最后下载新 XML”的顺序阅读。代码片段均是相关函数的短摘录；外围分支、缩进或参数可能省略，不能把它们逐块粘贴当作完整程序运行。标为“示意”的数据不是模型实测结果。各节都按“代码 → 解释 → 输入/输出 → 下一步”展开。

## 1. 先分清三个名字：接口和普通函数不同

**代码摘录（`app.py`）：**

```python
return predict_samples(state, samples, filename)
```

**通俗解释：** 这行位于 `convert_and_predict()` 的末尾。原先单文件 API 的模型调用已提取到共享函数 `predict_samples()`，现在新增的单段工具和 XML 接口也复用它。模型名称、启动加载、推理锁、英文标签转换和输出校验都继续共用；没有给每段加载模型，也没有从服务器内部再发 HTTP 请求给 `/predict`。

| 名字 | 调用方式 | 处理内容 | 返回值 |
| --- | --- | --- | --- |
| `POST /predict` → `predict()` | 用户发 HTTP 请求 | 一份媒体的完整音频，必须是 0.25–30 秒 | JSON：最高分标签及全部九类标签/分数 |
| `predict_segment()` | Python 代码直接调用；不是 URL | 本地媒体的一个 `[start, end)` 区间 | Python `Prediction` 对象 |
| `POST /predict_multi` → `predict_multi()` | 用户发 HTTP 请求 | 一份媒体＋一份 XML 的全部语音片段 | 添加/覆盖各段 emotion 的 XML |

`predict_segment()` 内部用 `extract_audio_segment()`；每次调用都会启动 FFmpeg 提取一段。`/predict_multi` **不循环调用这个工具**，而由 `predict_transcript()` 一次解码，再按位置读很多段。

**输入/输出：** 用户先选处理目标；两种 HTTP 入口和一个 Python 工具最终都把波形交给 `predict_samples()`。

**下一步：** 请求到来前，服务要先准备好共享模型。

## 2. 服务先启动：模型只准备一次

**代码摘录（`app.py`，`lifespan()`）：**

```python
app.state.lock = threading.Lock()
app.state.gate = asyncio.Semaphore(1)
app.state.model = AutoModel(model=MODEL, hub="ms", device="cpu",
                            disable_update=True)
yield
app.state.model = None
```

**通俗解释：** Uvicorn 启动 FastAPI 时执行 `lifespan()`，将模型对象放在 `app.state`，之后所有请求传递这个共享状态。函数内 `from funasr import AutoModel` 是启动时才执行的导入；仅导入 `app.py` 不等于已加载模型。`@asynccontextmanager` 配合 `yield` 划分启动准备和正常关闭收尾。关闭时设为 `None` 是释放引用，不是删除磁盘权重。

`executable()` 优先在当前 Python 环境的 `Library/bin` 找 FFmpeg/FFprobe，再查 PATH。PyTorch 设最多四个计算线程；它们可协作计算同一段音频，不代表四个模型或四条请求并行。保持 `--workers 1`；多个进程会各自加载模型。普通启动的 `disable_update=True` 不保证完全离线；历史真实验证通过临时验证启动器固定本地缓存并阻止外连，应用本身没有新增这种启动选项。

**输入/输出：** 模型标识与环境 → `app.state.model`、工具路径、`lock`、`gate`。这里还没有请求，也没有推理。

**下一步：** 用户准备媒体和 XML，发送一个 HTTP 请求。

## 3. 一次请求带两个文件：multipart 字段名必须对

**代码摘录（`app.py`，`predict_multi()`）：**

```python
async with request.form(max_files=2, max_fields=0) as form:
    entries = list(form.multi_items())
```

**通俗解释：** multipart/form-data 是在同一个 HTTP 请求里装多个部分的格式。必须恰好两个**文件字段**：`file` 是媒体，`xml` 是转录文件；不能是 `media`、`transcript` 等其他字段名，也不能把 XML 作为普通文本字段发送。XML 文件的后缀不是这里的判断依据，实际内容要通过解析；媒体后缀支持 `.wav`、`.mp3`、`.mp4`、`.m4a`，不区分大小写。

`multi_items()` 会保留重复字段，所以代码能拒绝重复的 `file`，不会因为字典覆盖而漏掉。源码还检查字段数量、字段名集合和 `UploadFile` 类型。`async with` 表示进入表单资源范围，退出时关闭上传资源；`async`/`await` 用于等待，不会自动加速 CPU 推理。

可先在仓库根目录打开 `/docs`，选择 POST `/predict_multi` 的两个文件框；或者在已有 `test-artifacts/` 目录时使用：

```powershell
curl.exe -X POST http://127.0.0.1:8000/predict_multi -F "file=@samples/news-video-with-captions 2.mp4" -F "xml=@samples/news-video-with-captions 1.xml" --output test-artifacts/predicted-transcript.xml
```

`-F` 的 `@` 表示读本地文件；它不是 XML 语法。样本没有纳入 Git，新检出仓库不一定存在这些文件。服务需先启动，打开网页不会替你启动 Uvicorn。

**输入/输出：** 本地两个文件 → 一个 HTTP POST → 两个 `UploadFile` 对象，还不是波形和 XML 树。

**下一步：** 在读取和解析上传内容时执行请求大小检查，并进入共享处理区。

## 4. 中间件与 gate：限制大小和限制同时处理是两件事

**代码摘录（`app.py`）：**

```python
limit = MULTI_BODY_BYTES if scope["path"] == "/predict_multi" else MAX_BODY_BYTES
```

```python
async with request.app.state.gate:
```

**通俗解释：** 第一行在 `BodyLimitMiddleware.__call__()` 中，`A if 条件 else B` 根据请求路径选上限。它包装底层 `receive()`，每当下游读取请求字节就累加 `total`，不是相信客户端声明的 Content-Length。中间件包在路由外，但字节计数随实际读取发生，不能理解为它已提前把整个上传文件读完。新端点请求体上限 131 MiB；`/predict` 仍是 26 MiB。

第二行在路由函数中，`Semaphore(1)` 使 `/predict` 和 `/predict_multi` 共享一个处理名额；另一条预测请求等待。它不限制全部等待连接数，也没有为等待时间设置超时。GET `/health` 不经过这个 gate，且只报告状态，不执行推理。

**输入/输出：** HTTP 字节块、请求路径 → 合规字节继续解析；超限返回 413。取得 gate 名额后，预测请求才能继续本段处理。

**下一步：** 把上传内容保存到此次请求的独立临时目录。

## 5. 保存文件，然后把耗时工作交给线程池

**代码摘录（`app.py`，`predict_multi()`）：**

```python
source = Path(directory) / ("input" + suffix)
xml_path = Path(directory) / "input.xml"
await save_multi_upload(media, source, MULTI_MEDIA_BYTES, "Media")
await save_multi_upload(transcript, xml_path, MULTI_XML_BYTES, "XML")
data = await run_in_threadpool(xml_path.read_bytes)
output = await run_in_threadpool(predict_transcript, request.app.state,
                                source, data, Path(directory) / "audio.wav")
```

**通俗解释：** `directory` 来自 `TemporaryDirectory(prefix="ser-multi-", dir=TEMP_ROOT)`。`Path / "文件名"` 是拼接路径；`source` 是上传媒体副本，不是用户的原文件，程序不改写 `samples/`。

`save_multi_upload()` 每次读最多 1 MiB，累计 `size`，超限就 `raise HTTPException(...)`。`while chunk := await upload.read(...)` 中 `:=` 表示先赋值再判断；读到空字节结束。`target.write` 也交给线程池执行。文件大小上限与整个请求体上限分别检查，因为 multipart 还含字段名、文件名和边界信息。

`run_in_threadpool(函数, 参数...)` 把同步函数交给工作线程，`await` 等结果回来。否则 `subprocess.run()` 和 CPU 模型推理会占住异步事件循环，妨碍其他请求调度。它不绕过 gate，也不让 65 段自动并行推理。

同名变量要按函数区分：

| 变量 | 所在函数 | 此处含义 |
| --- | --- | --- |
| `transcript` | `predict_multi()` | 上传的 XML 文件对象 `UploadFile` |
| `data` | `predict_multi()` | 从临时 XML 读出的 bytes |
| `transcript` | `predict_transcript()` | 接收到的 XML bytes，已经不是上传对象 |
| `source` | 两个函数 | 同一个上传媒体临时路径 |
| `destination` | `predict_transcript()` | 完整标准音频 `audio.wav` 的路径 |
| `state` | 工作函数 | `request.app.state` 的引用，不是新模型 |

**输入/输出：** 上传对象 → 临时媒体/XML 文件 → 工作线程得到媒体路径、XML 字节、WAV 输出路径和共享状态。

**下一步：** 工作线程先调用 `parse_transcript()`，不立刻预测。

## 6. 安全解析 XML：先禁止危险声明，再建元素树

**代码摘录（`app.py`，`parse_transcript()`）：**

```python
parser.StartDoctypeDeclHandler = forbidden
parser.EntityDeclHandler = forbidden
parser.ExternalEntityRefHandler = forbidden
```

```python
root = ET.fromstring(data, parser=ET.XMLParser(
    target=ET.TreeBuilder(insert_comments=True, insert_pis=True)))
```

**通俗解释：** XML 是有层次的文本，但客户端可以提交不可信内容。Expat 先读取 XML；遇到 DTD、实体声明或外部实体解析请求，就调用 `forbidden()` 抛错，外部内容不被读取。这里将函数名交给解析器，没写 `forbidden()`，因为要在对应事件发生时才调用。编码感知的解析器也能处理 UTF-16，不用“搜索某段 UTF-8 字节”来代替安全检查。XML 标准内建的 `&amp;`、`&lt;` 等转义仍可以使用。

预检查通过后，ElementTree 再构造树，保留根元素内部的注释和处理指令。解析深度超过 128 层拒绝。`try`/`except` 将格式、编码、安全检查错误转为 HTTP 422。`parse_transcript()` 中的 `data` 是 XML bytes；与路由中的 `data` 内容相同，但属于不同函数的局部变量。

**输入/输出：** 最多 2 MiB 的 XML bytes → 可操作的根元素 `root`；失败就结束请求，无模型调用。

**下一步：** 检查根元素和片段位置是否符合实际样本结构。

## 7. XML 树里的四个层次，以及不能重排的顺序

**代码摘录（`app.py`，`parse_transcript()`）：**

```python
elements = root.findall("./SegmentList/SpeechSegment")
```

**通俗解释：** 代码要求无命名空间的 `AudioDoc` 根元素，且恰好一个直接子元素 `SegmentList`；`SpeechSegment` 必须是它的直接子元素，不能藏在其他节点下。大小写有意义，不是早期讨论中的 `Speechsegment`。至少一段，最多 1000 段。

| XML 元素 | 在这个样本中的含义 | 程序如何处理 |
| --- | --- | --- |
| `AudioDoc` | 整份媒体标注的根节点，含名称等元数据 | 保留，检查根名 |
| `SegmentList` | 语音片段集合 | 按现有子元素顺序读取 |
| `SpeechSegment` | 一段语音的时间、说话人等属性及内容 | 读取 `stime`、`dur`，最后只改 `emotion` |
| `Word` | 转录中的词及其已有时间/分数属性 | 原样保留语义内容，不逐词做情绪预测 |

`ImageCaptionList/ImageSegment` 和 `SoundCaptionList/SoundSegment` 是图像/声音描述，也留在原树上。情绪模型只接收媒体音频，不接收这些文字；本项目没有用 XML 文字做情绪分类或重新转录。

`findall()` 按文档顺序给出元素。真实样本有 65 段，存在时间回跳，因此**最后一个元素不一定结束得最晚**。代码没有 `sort()`；每段有自己的采样位置，后面可以独立定位。不重排能保留原始标注结构；报错里的 Segment 48 指 XML 中第 48 个语音段，不是按时间排列后的第 48 段。

**输入/输出：** `root` → `elements`，即指向原 XML 树节点的列表；不是复制后另造一份片段文本。

**下一步：** 把各节点的时间属性变成采样索引。

## 8. stime＋dur：先校验所有时间，不边读边猜

**代码摘录（`app.py`，`parse_transcript()`）：**

```python
start = Decimal(element.attrib["stime"])
duration = Decimal(element.attrib["dur"])
end = start + duration
first, last = math.ceil(start * 16000), math.ceil(end * 16000)
segments.append((element, first, last))
```

**通俗解释：** `stime` 是开始秒数；`dur` 是持续秒数，不是结束时间。XML 属性读出来是字符串，`Decimal` 用十进制数计算，减少二进制浮点边界误差。`math.ceil()` 向上取整，得到 16 kHz 下的采样索引，区间按 `[first, last)` 处理。

这个摘录省略了中间校验：属性不能缺失，时间必须有限，`start` 在 0–1800 秒内，`duration` 在 0.25–30 秒内。NaN、无穷大、负开始时间、无法转换的文字都会拒绝。源码用 `enumerate(elements, 1)` 从 1 开始编号，异常里能告诉用户是哪一段。

`(element, first, last)` 是一个三项元组；`segments` 是这些元组组成的列表。`element` 仍引用原树节点，所以稍后修改它就修改了待返回的树。

“先校验所有片段”分两轮：这里检查所有时间格式/长度；解码后再检查所有采样边界。任何一段无效，都不先为前面的合法段调用模型。这样避免花时间算到最后才发现请求无法成功。内部推理仍可能失败，但不会把部分更新的 XML 发给用户。

**输入/输出：** `elements` 的时间字符串 → `root, segments`；`segments` 携带 XML 节点及采样起止位置。

**下一步：** 取得真实音频，再判断这些位置是否存在。

## 9. FFprobe 与 FFmpeg：一个询问信息，一个真正解码

**代码摘录（`app.py`，`predict_transcript()` 的 FFmpeg 参数）：**

```python
"-map", "0:a:0", "-vn", "-ac", "1", "-ar", "16000",
"-t", str(MULTI_SECONDS + 1), "-fs", str(MULTI_WAV_BYTES),
"-c:a", "pcm_s16le", str(destination)
```

**通俗解释：** `subprocess.run()` 启动外部 FFmpeg 并等待完成，输出保存到 `destination`。`0:a:0` 选择第一个输入里的第一条音轨，`-vn` 不处理视频画面，`-ac 1` 混成单声道，`-ar 16000` 统一采样率，`pcm_s16le` 指定有符号 16 位小端 PCM。

XML 的 `channel="1"` 只是保留的元数据，**不能据此推断“只用左声道”**。现在的行为是将第一条音轨的声道混为一个声道。

FFprobe 可询问音轨、时长、声道、采样率等信息；`/predict` 的 `convert_and_predict()` 会先调用它检查音轨。**当前 `/predict_multi` 的 `predict_transcript()` 没有先调用 FFprobe**，直接用 FFmpeg 的选轨、返回码和生成的 WAV 检查可用音频。以前调查 MP4 完整性时另外运行过 FFprobe，这是诊断工作，不是新路由每次必走的步骤。

一次正常多段请求只运行这次完整媒体解码；不能为 65 段反复从 MP4 开头解码。最多解码 1801 秒，多出来的一秒用于检测超过 1800 秒的输入，不能把长文件静默剪成合格文件。`-fs` 另限制输出字节数，`timeout=120` 限制本次外部进程等待时间。

**输入/输出：** 压缩或其他格式媒体路径 → 临时标准 WAV。FFprobe 元数据不能替代实际可解码采样。

**下一步：** 读取 WAV 的实际长度，完成所有片段的边界检查。

## 10. 先看完整 WAV，再按位置读取每段

**代码摘录（`app.py`，`predict_transcript()`，两处循环摘录）：**

```python
for index, (_, first, last) in enumerate(segments, 1):
    if first >= frames or last > frames:
        raise HTTPException(422, f"Segment {index}: outside the available audio")
```

```python
wav.setpos(first)
pcm = wav.readframes(last - first)
```

**通俗解释：** `frames = wav.getnframes()` 是实际标准 WAV 的采样帧数。单声道中一帧就是一个采样。源码也检查声道数、采样率、采样字节数，并拒绝超过 30 分钟的解码结果。

第一轮循环只检查，里面的 `_` 表示这次不使用元组中的 XML 节点。全部通过之后，第二轮循环才逐段读取和预测。`setpos(first)` 相当于把读取位置移到指定采样；因此下一段开始时间更小也没关系，不依赖上一段读到哪。`readframes(last - first)` 应读到恰好对应数量的采样，否则拒绝，不补零、不静默截短。

**输入/输出：** 完整 WAV＋`segments` → 所有边界合法后，依次得到各段 `pcm` 字节；此时尚未变成浮点数组。

**下一步：** 把 PCM16 字节转换成模型接受的数值。

## 11. 16 kHz、单声道、PCM16、float32 分别在哪里

**代码摘录（`app.py`，`predict_transcript()`）：**

```python
samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768
```

**通俗解释：** 这些词是不同层次，不能混作同一件事：

| 名字 | 表示什么 | 在流程中的位置 |
| --- | --- | --- |
| 16 kHz | 每秒 16,000 个采样位置 | FFmpeg 重采样；把秒转换成索引时也乘 16,000 |
| 单声道 | 每个时刻只保留一个混合后的幅度 | FFmpeg 的 `-ac 1`，不是挑左声道 |
| PCM16 | 每个幅度用 16 位有符号整数保存 | WAV 数据区每个单声道采样占 2 字节 |
| NumPy float32 | 32 位浮点数组元素 | 交给模型之前的内存表示，每个元素占 4 字节 |

`np.frombuffer()` 按已有字节解释整数，`<i2` 表示小端、两字节有符号整数；`astype(np.float32)` 转成浮点数，再除以 32768，把幅度从约 -32768–32767 缩放到约 -1–1。这不是训练，也不是自动调节音量。传给模型的是一维数组，不是文件名，避免再依赖其他音频文件解码器。

**输入/输出：** 本段 `pcm` 字节 → 本段 `samples` 浮点波形。其他函数里也叫 `samples`：`convert_and_predict()` 指完整短录音；`predict_segment()` 指它刚提取的一个片段；变量名相同不表示同一数组。

**下一步：** 将这段数组交给共享模型。

## 12. gate、thread lock、线程池如何配合

**代码摘录（`app.py`，`predict_samples()`）：**

```python
with state.lock:
    output = state.model.generate(input=samples, fs=16000,
                                  granularity="utterance", extract_embedding=False)
```

**通俗解释：** `state.model` 就是启动时的模型。`generate()` 在这里才进行实际推理，整段输入音频给出一个情绪结果，不返回每个词的情绪。`fs` 说明输入采样率；`extract_embedding=False` 表示不额外提取特征向量。

| 控制 | 放在哪里 | 解决什么问题 |
| --- | --- | --- |
| `gate`（异步信号量） | 两个预测路由外层 | 同一进程一次处理一个预测请求 |
| `state.lock`（线程锁） | 共享模型调用周围 | 不让多个线程同时进入同一模型调用，也保护直接调用工具的情况 |
| `run_in_threadpool` | 路由调用同步工作时 | 不让阻塞解码、推理占住异步事件循环 |

线程锁在 `with` 退出时释放，即使模型抛异常也一样。`predict_segment()` 作为普通函数自己不取得路由 gate；调用方若在异步程序中使用它，应放进线程池。不要把它误认作已自动安排好请求生命周期的 HTTP 入口。

**输入/输出：** 单段 `samples`＋已加载模型 → 模型原始结果列表 `output`。

**下一步：** 校验输出，并根据分数位置得到英文标签。

## 13. 原始模型输出怎样变成英文 emotion

**代码摘录（`app.py`，`predict_samples()`）：**

```python
labels = [english_label(label) for label in labels]
best = max(range(len(scores)), key=scores.__getitem__)
```

**通俗解释：** 源码先要求 `output` 是长度为 1 的列表，读取 `output[0]["labels"]` 和 `scores`；检查九项对应、标签是字符串、分数有限且在 0–1 内。之后才执行上面的英文转换和最大值选择。九项英文类别为 `angry`、`disgusted`、`fearful`、`happy`、`neutral`、`other`、`sad`、`surprised`、`<unk>`。

`[函数(x) for x in 列表]` 是列表推导式。`english_label()` 用 `rsplit("/", 1)[-1].strip()` 取最后一个斜杠后的内容，检查允许的英文名；它不会把任意大写旧标注翻译成新类别。`best` 是最高分的**索引**，不是分数；同一位置的 `labels[best]` 和 `scores[best]` 一起组成结果，不先把标签排序。分数不因英文转换而改变。

函数返回 `Prediction` 对象，其中有 `emotion`、`score`、`labels`、`scores` 等字段。这里没有用人工答案判断它是否正确；分数和约为一是 HTTP 验证脚本的额外检查，不是 `predict_samples()` 里的和检查。

**输入/输出：** 模型原始 `output` → 校验后的 `Prediction`。注意：`predict_transcript()` 中的 `output` 最后是 XML bytes，与这里的原始模型结果不是同一含义；`result` 在工作函数里是 `Prediction`，在 `convert_and_predict()` 中却曾用于 FFmpeg 进程结果。

**下一步：** 从 `Prediction` 只取英文 emotion，更新相应 XML 节点。

## 14. 只改 emotion：旧标签覆盖，旧 score 保留

**代码摘录（`app.py`，`predict_transcript()`）：**

```python
result = predict_samples(state, samples, source.name)
element.set("emotion", result.emotion)
```

**通俗解释：** `element` 引用原树中的本段节点。`.set()` 在属性不存在时新增，存在时替换。即使已有 `emotion="LOVE"`，也重新对音频推理并覆盖；原有 emotion 不是经过验证的真实标签，程序没有拿它做训练或计算准确率。

`result.score` 是当前模型最高分类分数；XML 原有 `score` 的来源和定义不能直接认定为情绪分数。因此代码只 `.set("emotion", ...)`，不覆盖原有 `score`，也不向 XML 添加 labels/scores 等额外字段。`Word` 的 `score` 同样保留。传入的 `source.name` 是临时媒体名，用于内部 `Prediction.filename`，不会替换 XML 文档名。

每一段仍按原 XML 顺序处理，节点和子元素不重排。文本的 `element.text` 与子节点后面的 `tail` 都跟着原树保留，不重新拼接转录文字。

**输入/输出：** 本段 `Prediction`＋原 XML 节点 → 同一节点多了新 emotion，其他属性及子树不变。

**下一步：** 所有段成功才序列化为新 XML。

## 15. 返回 XML 和清理临时文件：不返回半成品

**代码摘录（`app.py`，工作函数和路由的返回部分）：**

```python
output = ET.tostring(root, encoding="utf-8", xml_declaration=True)
```

```python
return Response(output, media_type="application/xml; charset=utf-8", headers={
    "Content-Disposition": 'attachment; filename="predicted-transcript.xml"'})
```

**通俗解释：** ElementTree 负责 XML 属性转义；如果预测是 `<unk>`，文件写成 `emotion="&lt;unk&gt;"`，再次解析后的属性值仍是 `<unk>`。这次采用语义保留，不自制字节偏移替换：等价转义、缩进、引号、自闭合写法或 XML 声明可以变化。根内注释、处理指令会保留；不能把它理解为输入文件逐字节不变。

工作函数检查返回 XML 最大 16 MiB，然后把 bytes 交回路由。路由在 `TemporaryDirectory` 的 `with` 块退出后才构造内存 `Response`；响应不再依赖已删除的 WAV。`Content-Disposition` 提示客户端下载文件，内容类型是 XML，不是 `/predict` 的 JSON。

若第 n 段模型失败，工作函数返回带 `Segment n` 的 HTTP 500，记录服务端异常，不返回前面部分更新的 XML。结构/时间/范围错误通常是 422；大小超限 413；媒体后缀不支持 415；multipart 解析错误 400。`except HTTPException: raise` 保留已明确的错误状态；`raise ... from error` 保留底层异常原因用于排查。

无论成功还是处理异常，请求临时目录都会退出并清理；上传对象由表单上下文关闭。操作系统强制终止进程仍可能留下文件。磁盘原样本和用户客户端收到的输出不是这些待清理临时文件。

**输入/输出：** 全部更新完成的树 → UTF-8 XML bytes → HTTP 200 附件；失败则 JSON 错误，无部分 XML。

**下一步：** 对照限制，理解为什么有些请求会在不同阶段被拒绝。

## 16. 新旧接口的限制不能混用

**代码摘录（`app.py` 顶部常量）：**

```python
MULTI_SECONDS = 30 * 60
MULTI_SEGMENTS = 1000
MULTI_DECODE_TIMEOUT = 120
MULTI_WAV_BYTES = (MULTI_SECONDS + 1) * 16000 * 2 + 65536
```

**通俗解释：** `*` 是乘法，`30 * 60` 是 1800 秒；1 MiB 是 `1024 * 1024` 字节。不同上限分别约束网络、磁盘、单次模型输入和处理时间。

| 检查 | `/predict` | `/predict_multi` |
| --- | --- | --- |
| 媒体大小 | 25 MiB | 128 MiB |
| XML 大小 | 不接收 XML | 2 MiB |
| 请求体总大小 | 26 MiB | 131 MiB |
| 完整音频时长 | 0.25–30 秒 | 最多 1800 秒，且必须容纳所有合法段 |
| 单段时长 | 完整短音频即一次输入 | 每段 0.25–30 秒，包含边界 |
| SpeechSegment 数量 | 不涉及 | 1–1000 |
| FFprobe 超时 | 20 秒 | 当前流程不调用 FFprobe |
| FFmpeg 超时 | 45 秒 | 120 秒 |
| 解码时长探测上限 | 31 秒，之后拒绝超过 30 秒 | 1801 秒，之后拒绝超过 1800 秒 |
| 解码输出大小上限 | 未单独设置 `-fs`，由时长/格式约束 | 57,697,536 字节 |
| XML 深度/响应大小 | 不涉及 | 128 层 / 16 MiB |

`predict_segment()` 没有 HTTP 上传限制，也不把源文件限制在 30 秒；它只允许所选段为 0.25–30 秒，FFmpeg 超时 45 秒。它与新端点的完整媒体解码限制是不同的调用规则。

**120 秒不是整个请求超时**，也不包括 gate 排队或全部模型推理。当前没有单独的推理/整请求超时；客户端需自行设置合适等待时间。文件扩展名合格也不证明内容完整。

**输入/输出：** 请求大小、实际音频长度、片段清单 → 分阶段接受或明确拒绝，不改变原接口上限来迁就大视频。

**下一步：** 用测试区分“代码按约定工作”和“模型判断正确”。

## 17. 三种验证：假模型、真实功能、准确率评估

**代码摘录（`test_predict_multi.py`）：**

```python
with patch.object(app.subprocess, 'run', wraps=subprocess.run) as run:
    response = self.request()
self.assertEqual(run.call_count, 1)
```

**通俗解释：** `patch.object()` 在测试范围临时替换对象，退出后恢复。`wraps` 仍调用真正 FFmpeg，同时记录次数；`FakeModel.generate()` 则返回预先安排的标签分数，不是模型猜出的情绪。`assertEqual()` 失败会让测试失败。`setUp()` 为每个用例准备目录和假状态，`addCleanup()` 注册清理。

| 文件/证据 | 验证什么 | 不证明什么 |
| --- | --- | --- |
| [test_segments.py](../test_segments.py)，10 项 | 生成音频的截取时点/波形、mono/16 kHz/PCM16、非法时间和越界、英文对齐及清理 | 函数名里的 `accuracy` 指提取准确，不是情绪分类准确率 |
| [test_predict_multi.py](../test_predict_multi.py)，16 项 | HTTP 字段、XML 保留/覆盖/转义、安全拒绝、先校验、只解码一次、65 段假推理、1000 段边界、共享 gate、线程调度和失败清理 | TestClient 不通过实际 TCP 服务；假模型不会验证真实权重 |
| [verify_api.py](../verify_api.py) | 先启动服务，再用真实语音转换各格式，通过实际 HTTP 检查 `/predict` 的 18 个 POST 用例、健康页/文档/结构及清理 | 它没有实现 `/predict_multi` 客户端，也不自动启动服务，不算准确率 |
| [真实验证报告](../reports/predict-multi-verification-2026-11-02.md) | 缓存真实模型＋完整真实 MP4＋原 XML，经实际 HTTP 完成 65 段 | 一段视频不能代表跨语言、跨场景泛化或标注一致性 |

生成的正弦波/静音可检查媒体处理和限制，不能当作真实情绪验证数据。部分大小/超时分支测试临时缩小常量，不代表每次都上传 128 MiB。`verify_api.py` 运行成功后写的是 `test-artifacts/results.json`，不是覆盖历史 `reports/http-functional-results.json`。

可阅读而不立即执行的测试命令：`python -m unittest -v test_segments test_predict_multi`。它们不调用真实模型；`verify_api.py` 则需要正在运行的真实服务。不要把学习文档中的命令理解为本次已重新执行。

**输入/输出：** 可控测试输入或真实语音请求 → 断言结果/功能报告；只有另建独立人工标注集并比较预测，才谈准确率等指标。

**下一步：** 看已经保存的完整样本验证及早先失败的原因。

## 18. 65 段成功与旧失败：边界检查没有放宽

**代码摘录（`app.py`，实际边界判断）：**

```python
if first >= frames or last > frames:
    raise HTTPException(422, f"Segment {index}: outside the available audio")
```

**通俗解释：** 早期 MP4 是不完整下载，55,062,440 字节。文件头声明约 570 秒，但真正解码只得到约 452.069 秒；FFprobe 还报告 `partial file` 和包损坏。XML 需要到 570.24 秒，于是在任何推理前拒绝第 48 段，这是应有行为，不能靠补静音、跳过片段或放松校验来“通过”。

重新下载后，本地媒体仍使用原文件名，大小为 71,215,895 字节，SHA256 为 `1ef3546dc6cab8094cf829472d38a333eb081a448e4a18a818c4cd60cbb03465`，完整解码约 570.258875 秒。保存的[报告](../reports/predict-multi-verification-2026-11-02.md)记录：

- HTTP 200，全部 65 个 `SpeechSegment` 得到有效英文 emotion；一次解码、65 次真实模型调用，复用同一模型。
- 请求耗时 **43.373 秒，不含模型启动**，包含上传、处理和响应；工作函数约 43.021 秒。这是本机一次运行观测，不是性能保证。
- 递归比较元素、属性、text/tail 和顺序，只排除目标 emotion，其他内容一致；临时文件清理、正常关服检查通过。
- 当次标签分布为 neutral 57、`<unk>` 6、sad 1、happy 1，只是观测结果，不是正确率。

原 API 的 18 个 POST 回归用例也已通过。真实输出保存在被忽略的 `test-artifacts/supervisor-complete-emotions.xml`；这个文件可能不在其他人的检出目录中。旧失败仍留在报告里，标明已由重新下载解决。

**输入/输出：** 完整下载＋原 XML → 65 段成功 XML；不完整下载＋同一 XML → 有片段索引的错误，无部分输出。

**下一步：** 用一个具体片段把刚才的数据类型和调用串起来。

## 19. 完整示例：从一段时间到 emotion（预测为示意）

**XML 代码示意：**

```xml
<SpeechSegment channel="1" stime="0.03" dur="6.87" score="0.98" emotion="SADNESS">
  <Word stime="0.03" dur="0.36" score="0.7">well</Word>
</SpeechSegment>
```

**通俗解释：** 时间和属性取真实样本第一段的形式，`Word` 只摘一个用于说明。以下假设模型最终选中 `happy`，**这是教学示意，不是该真实片段的已保存预测**。

1. 客户端把媒体放进 `file`、这段所属的完整 XML 放进 `xml`，不是每一段单发一个请求。
2. `parse_transcript()` 读到 `Decimal("0.03")` 和 `Decimal("6.87")`，得到 `end = 6.90` 秒。
3. `first = 480`，`last = 110400`，需要 `109920` 个采样，持续 6.87 秒。全部其他片段也须先校验完。
4. 完整媒体解码一次；确认 WAV 至少有 110400 帧。`setpos(480)` 后读 109920 帧，PCM16 单声道应有 219840 字节。
5. 字节转为长度 109920 的 float32 数组；`predict_samples()` 在锁内调用已有模型，检查九个标签/分数并选择最高分位置。
6. 假设英文 `result.emotion` 为 `happy`，只调用 `element.set("emotion", result.emotion)`；原 `score="0.98"`、Word 属性和文本不改。
7. 等所有片段成功，再序列化并返回完整 XML，而不是只返回这个节点。

示意更新结果：

```xml
<SpeechSegment channel="1" stime="0.03" dur="6.87" score="0.98" emotion="happy">
  <Word stime="0.03" dur="0.36" score="0.7">well</Word>
</SpeechSegment>
```

**输入/输出：** 时间字符串和本段真实音频 → 采样索引 → float32 波形 → `Prediction` → 更新 emotion 的原 XML 节点；没有把旧 `SADNESS` 作为正确答案。

**下一步：** 用下面三张索引表回到实际代码，不必记住所有细节。

## 20. 附表：当前核心函数与职责

**代码摘录（`app.py`，工作函数入口）：**

```python
root, segments = parse_transcript(transcript)
```

**通俗解释：** 逗号是解包：把返回元组中的树和区间列表分别交给两个变量。沿这些函数的“谁调用谁”阅读，比从文件第一行硬背到最后更容易。

| 核心函数/类（均在 [app.py](../app.py)） | 职责 | 主要输入 → 输出 |
| --- | --- | --- |
| `executable()` | 查找环境工具 | 工具名 → 程序路径 |
| `lifespan()` | 启动共享资源、正常关闭释放引用 | 应用 → 初始化后的 `app.state` |
| `BodyLimitMiddleware.__call__()` | 按路径计数请求体 | HTTP 消息 → 继续读取或 413 |
| `predict()` | 单文件 HTTP 入口、上传与 gate | Request → Prediction/JSON |
| `convert_and_predict()` | FFprobe 检查、短音频转换与校验 | 媒体路径 → Prediction |
| `extract_audio_segment()` | 提取一段，管理其临时文件 | 媒体/start/end → 上下文内可用的 WAV 路径 |
| `predict_segment()` | 单段 Python 工具 | 媒体/start/end → Prediction |
| `predict_samples()` | 锁内推理、输出校验、英文标签及最高分 | float32 波形 → Prediction |
| `english_label()` | 提取并验证英文类别 | 模型标签 → 允许的英文标签 |
| `predict_multi()` | XML 多段 HTTP 入口与临时目录管理 | Request → XML Response |
| `save_multi_upload()` | 逐块保存并检查单文件大小 | UploadFile → 已保存文件 |
| `parse_transcript()` | XML 安全/结构/全部时间检查 | XML bytes → 树、节点/采样元组列表 |
| `predict_transcript()` | 一次解码、全部范围检查、逐段预测和 XML 序列化 | 媒体路径/XML bytes → 更新 XML bytes |
| `health()` | 报告就绪、模型和设备 | GET 请求 → 状态字典，不推理 |

**输入/输出：** 函数名索引 → 可在编辑器查找的真实实现；HTTP 入口与普通工具不要混淆。

**下一步：** 看这些实现和证据分别放在哪些文件夹。

## 21. 附表：文件和文件夹有什么用

**代码摘录（`app.py`）：**

```python
TEMP_ROOT = Path(__file__).parent / ".tmp"
```

**通俗解释：** `__file__` 是模块文件路径，`.parent` 是它的目录。相对路径说明仓库内的位置，不要求其他人拥有你的绝对 Windows 路径。

| 文件/目录 | 作用 |
| --- | --- |
| [app.py](../app.py) | 服务及可复用媒体/推理/XML 函数 |
| [verify_api.py](../verify_api.py) | 对已启动 `/predict` 服务做真实 HTTP 功能检查 |
| [test_segments.py](../test_segments.py)、[test_predict_multi.py](../test_predict_multi.py) | 无需加载真实模型的媒体/假模型测试 |
| [README.md](../README.md)、[README.zh-CN.md](../README.zh-CN.md) | 两种语言的使用、字段、限制和文档入口 |
| `docs/` | 01 单文件基础、02 当前分段 XML 流程，都是学习材料 |
| `reports/` | 已保存的功能验证证据和报告，区分历史与当前运行 |
| `environment/`、[requirements.txt](../requirements.txt) | 现有环境快照与 API 补充依赖，不是从零可复现的完整环境锁 |
| `samples/` | 本地导师样本，Git 忽略；程序不覆盖输入 |
| `test-artifacts/` | 测试生成媒体、返回 XML、结果和诊断日志，Git 忽略 |
| `.tmp/` | 应用每次请求的临时文件，处理结束清理，Git 忽略 |
| `__pycache__/` | Python 导入产生的缓存，不是模型权重，Git 忽略 |
| [.gitignore](../.gitignore) | 规定哪些本地产物不进入 Git |

模型权重在环境的模型缓存中，不应加入仓库。`reports/` 的历史 JSON 是版本化证据，不等于测试脚本每次自动覆盖的 `test-artifacts/results.json`。

**输入/输出：** 看到一个文件名 → 能判断它是实现、教学、证据还是临时产物。

**下一步：** 按下面顺序在编辑器中真正走一遍调用链。

## 22. 建议读代码顺序，以及可以向 Zin 汇报什么

**代码摘录（`app.py`，XML 更新的核心两步）：**

```python
result = predict_samples(state, samples, source.name)
element.set("emotion", result.emotion)
```

**通俗解释：** 先看“哪段音频传进来，哪个属性改掉”，再往外追 HTTP 和资源管理，比一次理解所有库更容易。

建议阅读顺序：

1. 先看 [01](01-single-file-api-learning.zh-CN.md) 的第 1–5 节，理解 Request、上传对象、文件路径和数组不同。
2. 在 [app.py](../app.py) 读 `predict_multi()`，圈出两个文件字段、gate、临时目录和线程池调用。
3. 读 `parse_transcript()`，用纸写出一段的 `stime + dur`、`first`、`last`，再看异常分支。
4. 读 `predict_transcript()`：第一轮只验范围，第二轮读采样/推理/改属性，最后序列化。
5. 读 `predict_samples()` 和 `english_label()`，追踪索引、标签、分数对齐；再回看 `lifespan()` 理解共享模型从哪来。
6. 对比 `predict()`、`convert_and_predict()` 与 `predict_segment()`，确认它们不是 XML 路由的内部 HTTP 调用。
7. 读两份测试中的成功用例、故意失败用例和 `tree_signature()`，最后读 `verify_api.py` 及[真实报告](../reports/predict-multi-verification-2026-11-02.md)。

目前可以向 Zin 汇报：

- 保留原单文件 JSON API，完成媒体＋XML 多段接口；按实际 AudioDoc 结构读取秒级时间，对全部段新增/覆盖英文 emotion。
- 全部时间与范围先校验，一次解码，复用 CPU 模型与锁，保留其他 XML 语义内容；有独立大小/时长/数量限制和失败清理。
- 已记录 26 项生成媒体/假模型测试及原 API 18 项 HTTP 用例通过；完整真实视频 65 段 HTTP 验证通过，耗时 43.373 秒不含模型启动，XML 保留和清理检查通过。
- 早期失败是视频下载不完整，重新下载后在不放松校验的情况下通过。

尚未完成的评估要同时说明：没有独立人工标注测试集、准确率/F1/混淆矩阵、置信度校准或跨语言/噪声/不同说话人的系统评估；没有用旧 XML emotion 当正确答案，也没有训练或微调模型。一次时间观测不是延迟/吞吐量基准；测试中的 gate 调度检查不是生产并发压力测试，普通 hub 启动的完全离线保证也没有建立。当前实现针对已支持的无命名空间结构，不宣称兼容任意 XML schema。

**输入/输出：** 已完成的代码和验证证据 → 可以准确汇报的功能成果与明确的评估边界。

**下一步：** 先不运行昂贵推理，任选一个测试里的两段 XML，在纸上追踪四种对象：上传文件、XML 节点、采样数组、Prediction；再用实际代码核对你的理解。
