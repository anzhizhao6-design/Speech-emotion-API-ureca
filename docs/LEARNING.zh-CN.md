# 跟着一条录音读懂本地 SER API

假设你在 Windows 录下一段 `我的录音.m4a`，希望上传后得到情绪标签。我们就沿着这条录音的处理过程读代码。

本教程依据当前 `app.py` 和 `verify_api.py`。下面的源码片段保留完整操作，部分省略外围缩进和注释，不能当作独立程序逐块运行。明确写着“教学例子”的内容只是帮助理解，不是项目增加的功能。

## 一、先知道谁在做事

你启动服务，然后打开网页选文件，点击上传，最后在网页里看到结果。这件事由几部分合作完成：

| 名称 | 在本项目中做什么 |
| --- | --- |
| 浏览器 | 显示 `/docs` 页面，让你选录音；点击 Execute 后发送文件，再显示返回的数据。 |
| Uvicorn | 运行 Python 应用，等待指定地址上有人发来消息，把消息交给应用，再把结果送回去。它需要一直运行。 |
| FastAPI | 按地址找到要执行的 Python 函数，帮助读取上传内容、检查返回数据、提供 `/docs` 页面。 |
| `app.py` | 写出具体处理规则：怎样检查文件、转换音频、调用模型和返回结果。 |
| `verify_api.py` | 不通过鼠标选文件，而是用 Python 主动上传测试文件、检查服务的回答。 |

浏览器发来的“请处理这个文件”叫**请求**；服务返回的结果叫**响应**。它们按 HTTP 这种约定好的方式传递。你暂时不需要学习整个 HTTP 协议，只要知道它包含地址、文件或其他数据，以及表示成功或错误的状态码。

读代码时先区分三个时间点：模块被导入时创建应用和登记函数；服务启动时准备工具和模型；上传录音时才执行文件处理与预测。函数写在文件前面，不代表它一定先被调用。

## 二、启动准备：先准备好，再等录音

### 1. 告诉程序要用哪个模型

```python
MODEL = "iic/emotion2vec_plus_seed"
```

这一步只是保存模型的名称。`MODEL` 里是一段字符串，不是装好了的模型，也不是本机文件路径。后面 FunASR 会按这个名称找到对应的模型。

这里需要分清三个东西：

| 内容 | 具体是什么 |
| --- | --- |
| 模型名称 `iic/emotion2vec_plus_seed` | 用来告诉模型工具“我要哪一个模型”的标识。 |
| 磁盘上的权重文件，例如 `model.pt` | 别人训练后保存的数值参数。关闭服务后文件仍在磁盘上。 |
| `app.state.model` 中的模型 | Python 中已经准备好、可以接受波形并计算的对象，使用内存中的程序结构和参数。 |

这里的模型可以理解为别人训练好的计算程序和参数。**训练**是用数据调整这些参数；**加载**是把已有模型准备好；**推理**是拿准备好的模型计算一条新录音。本项目只加载和推理，不训练。

### 2. 先规定允许多大的录音

```python
MAX_FILE_BYTES = 25 * 1024 * 1024
MAX_BODY_BYTES = MAX_FILE_BYTES + 1024 * 1024
MAX_SECONDS = 30
MIN_SECONDS = 0.25
TEMP_ROOT = Path(__file__).parent / ".tmp"
```

这一步保存后面检查文件时要用的限制。文件最大 25 MiB；一次上传除了文件，还带字段名、文件名等信息，所以整个请求允许 26 MiB。音频必须在 0.25 到 30 秒之间，包含边界。

`TEMP_ROOT` 是项目里 `.tmp` 目录的路径。`__file__` 指当前 `app.py` 文件；`Path(...).parent` 取它所在目录；这里的 `/` 是拼接路径，不是除法。上传的 `我的录音.m4a` 会暂存在这个目录下面，不会改写你原来的录音。

### 3. 创建应用，告诉它启动时执行哪个函数

```python
app = FastAPI(title="Local SER API", lifespan=lifespan)
```

这一步创建应用对象，保存到变量 `app`。`title` 是页面上显示的名称；`lifespan=lifespan` 把函数交给 FastAPI，告诉它启动和关闭时去执行这个函数。

这里没有写 `lifespan()`，因为此时不是马上手动调用，而是先把它交给 FastAPI。等 Uvicorn 真正运行应用，才进入下面的启动准备。

### 4. 找到处理音频的两个程序

```python
    app.state.ffmpeg = executable("ffmpeg")
    app.state.ffprobe = executable("ffprobe")
```

这两行在 `lifespan()` 中执行。FFprobe 用来询问文件“有没有音轨”；FFmpeg 用来把 M4A、MP3、MP4 等转换成模型需要的音频。

`app.state` 是应用上用来保存后续请求会反复使用的内容的地方。此处保存两个程序的路径；不是马上转换录音，因为还没有收到录音。路径保存好，后面才能启动这些程序。

```python
    local = Path(sys.prefix) / "Library" / "bin" / (name + ".exe")
    found = str(local) if local.is_file() else shutil.which(name)
    if not found:
        raise RuntimeError(f"{name} not found in this Python environment")
    return found
```

这是 `executable(name)` 中负责查找的部分。输入 `name` 是前面的 `"ffmpeg"` 或 `"ffprobe"`。`local` 保存优先查找的位置：当前 Python 环境里的 `Library\bin`。找到后，`found` 装路径字符串，再返回给 `app.state`。

`A if 条件 else B` 可以直接读成“条件成立就选 A，否则选 B”。这里环境中的文件不存在，就用 `shutil.which()` 到 PATH 中查找；PATH 是程序查找命令时使用的一组目录。都找不到就抛出错误，无法正常完成启动。

### 5. 准备计算线程和临时目录

```python
    torch.set_num_threads(max(1, min(4, os.cpu_count() or 1)))
    TEMP_ROOT.mkdir(exist_ok=True)
    app.state.lock = threading.Lock()
    app.state.gate = asyncio.Semaphore(1)
```

这一步为后续工作做准备。`mkdir(exist_ok=True)` 创建临时目录，目录已经存在也没关系。`lock` 和 `gate` 用来避免多条录音一起进入某些处理步骤，先记住实际效果即可，后面再讲。

线程是程序里执行工作的一条路径。多个线程可以各做不同任务，也可以协作完成一个任务。这里一次处理一条录音，但 PyTorch 的一些 CPU 计算可以用最多四个线程协作。**四个线程不是四个模型，也不表示同时预测四条录音。**

这个表达式把设置值保持在 1 到 4 之间。`os.cpu_count() or 1` 表示取得 CPU 数量；如果没有取得有效值，就用 1。它也不代表整个服务进程里总共只有四个线程。

### 6. 加载模型，等待后续复用

```python
    app.state.model = AutoModel(model=MODEL, hub="ms", device="cpu",
                                disable_update=True)
    yield
    app.state.model = None
```

这一步把模型准备好，存入 `app.state.model`。`model=MODEL` 指定名称，`hub="ms"` 选择模型来源，`device="cpu"` 指定在 CPU 上计算。首次使用可能需要下载权重，已有缓存也可能联系模型仓库；不能把 `disable_update=True` 理解为已经保证完全离线。

模型准备好后，每次录音都用 `app.state.model`，不用重新加载。**这里还没有开始预测：后面调用 `generate()` 才预测上传录音。**

`yield` 可以先读成“启动准备到这里完成，把控制交回去，让服务继续运行”。它后面的 `app.state.model = None` 在正常关闭阶段才执行，而不是立刻执行。它清空 Python 中的引用，不删除磁盘权重。函数上的 `@asynccontextmanager` 让 FastAPI 能按这种“先准备、关闭时再收尾”的方式调用 `lifespan()`。

## 三、等待请求：还没上传时，预测函数不会运行

### 1. 登记上传地址

```python
@app.post("/predict", response_model=Prediction, openapi_extra={
    "requestBody": {"required": True, "content": {"multipart/form-data": {
        "schema": {"type": "object", "required": ["file"], "properties": {
            "file": {"type": "string", "format": "binary"}}}}}}})
async def predict(request: Request):
```

这一步把 `/predict` 地址和 `predict()` 函数关联起来。代码块只是函数头，不是完整函数。`@...` 是装饰器语法，在这里实际就是登记处理规则。POST 是上传时使用的请求方式；浏览器发来这个请求时，FastAPI 才调用函数。

`request` 不是录音波形，而是装着本次请求信息的对象。`request.app.state` 可以访问启动时保存的模型和工具路径。`async` 暂时理解为这种函数可以在等待操作完成时让出执行机会，具体原理放到后面。

`openapi_extra` 这层字典描述 `/docs` 怎样显示上传框：要有一个叫 `file` 的文件字段。`multipart/form-data` 是把文件和字段信息一起打包上传的格式。你不必现在记住字典层数，真正的文件检查在下一步。

### 2. /health 只回答服务状态

```python
    return {"status": "ready", "model": MODEL, "device": "cpu"}
```

这是 `health()` 的返回语句。浏览器或测试脚本访问 GET `/health` 时，服务回答这些信息。GET 可以先理解为请求读取内容；它不上传录音，也不执行模型预测。打开 `/docs` 也只是获取页面；选文件并点击 Execute，才开始下面的预测流程。

## 四、接收文件：把上传内容保存下来

### 1. 找到名为 file 的上传对象

```python
            async with request.form(max_files=1, max_fields=0) as form:
                entries = list(form.multi_items())
                if len(entries) != 1 or entries[0][0] != "file" or not isinstance(entries[0][1], UploadFile):
                    raise HTTPException(422, "Provide exactly one file in the 'file' field")
                upload = entries[0][1]
```

这一步把收到的上传内容读成 Python 可以操作的字段。`form` 装解析出来的字段集合；`entries` 把它们放到列表里。每项包含字段名和字段值，所以 `entries[0][0]` 是第一个字段的名字，`entries[0][1]` 是对应的内容。

本项目要求只上传一个名叫 `file` 的文件。检查通过后，`upload` 保存上传文件对象，后面能用它读取字节。`isinstance(..., UploadFile)` 是检查“这个值是不是上传文件对象”。`max_files=1` 和 `max_fields=0` 也会让解析过程拒绝多文件和普通附加字段，因此有些错误会先返回 400。

`raise HTTPException(422, ...)` 表示停止正常处理，告诉浏览器输入不符合要求；422 是 HTTP 状态码，不是情绪类别编号。`async with` 在这里负责进入读取范围、结束后关闭相应资源，暂时不必展开实现原理。

### 2. 保留文件名，检查后缀

```python
                filename = (upload.filename or "").replace("\\", "/").split("/")[-1]
                suffix = Path(filename).suffix.lower()
                if suffix not in {".wav", ".mp3", ".mp4", ".m4a"}:
                    raise HTTPException(415, "Supported file extensions: WAV, MP3, MP4, M4A")
```

这一步取得要展示的文件名，并筛选格式。上传 `我的录音.m4a` 时，`filename` 保存这个名称，`suffix` 保存 `.m4a`。`lower()` 转成小写，所以 `.M4A` 也接受。

第一行先把反斜杠改成斜杠，再分割并取最后一段。教学例子：`"folder/record.m4a".split("/")[-1]` 得到 `"record.m4a"`；`[-1]` 表示最后一项。`or ""` 则在没有文件名时用空字符串。

后缀通过不代表文件肯定有效。把文字文件改名为 `.m4a` 仍然会在后面的音频检查中失败。

### 3. 建立本次请求的临时文件

```python
                with tempfile.TemporaryDirectory(prefix="ser-", dir=TEMP_ROOT) as directory:
                    source = Path(directory) / ("input" + suffix)
                    size = 0
```

这一步为这条录音建立独立目录。`directory` 装目录名称，`source` 装要保存的文件路径，可能类似 `.tmp/ser-某个随机名称/input.m4a`；实际名称由程序生成。`size` 从零开始累计文件字节数。

用户的 `filename` 只用于结果展示，不直接作为临时保存路径。`with` 表示在这个范围用完临时目录后清理它。源码中这个范围还包括转换和预测，必须等它们完成才删除；正常返回或抛异常也会清理，强制结束进程则可能留下文件。

### 4. 一块一块读取并写入磁盘

```python
                    with source.open("wb") as target:
                        while chunk := await upload.read(1024 * 1024):
                            size += len(chunk)
                            if size > MAX_FILE_BYTES:
                                raise HTTPException(413, "File exceeds 25 MiB")
                            target.write(chunk)
                    if not size:
                        raise HTTPException(422, "Empty file")
```

这一步把上传对象的内容写进 `source`。`target` 是打开的磁盘文件，`wb` 表示写入字节。`chunk` 每次装最多 1 MiB 字节，`size` 保存累计大小；超过上限返回 413，读完仍为零则说明文件为空。

`:=` 表示“先赋值，再把这个值用于判断”。这里每次读到内容就赋给 `chunk`，有内容就继续；读到空字节就结束。`await` 表示等待读取结果，不是要求你自己创建线程。写完后关闭文件，下一步把路径交给转换函数。

### 5. 调用转换与预测函数

```python
                    return await run_in_threadpool(convert_and_predict, request.app.state,
                                                   source, Path(directory) / "audio.wav", filename)
```

这一步把耗时工作交给 `convert_and_predict()`，等它完成后把结果返回。`run_in_threadpool` 会让工作线程执行它，先记住它不会在这里凭空生成预测结果。

按被调用函数的参数顺序理解输入：

| 参数 | 装什么 | 从哪里来 |
| --- | --- | --- |
| `state` | 模型、工具路径、锁等共享内容 | `request.app.state` |
| `source` | 已保存的 `input.m4a` 等路径 | 刚才写入的上传文件 |
| `destination` | 即将生成的 `audio.wav` 路径 | 当前临时目录与文件名拼接 |
| `filename` | 结果中要显示的录音名称 | 上传时的文件名 |

下面进入 `convert_and_predict()`，不再从浏览器读取文件，而是处理磁盘上的 `source`。

## 五、转换音频：先检查，再变成数值数组

### 1. 询问文件里是否有音频

```python
        probe = subprocess.run(
            [state.ffprobe, "-v", "error", "-protocol_whitelist", "file,pipe", "-select_streams", "a:0",
             "-show_entries", "stream=index", "-of", "json", str(source)],
            capture_output=True, text=True, timeout=20, encoding="utf-8", errors="replace")
        if probe.returncode:
            raise HTTPException(422, "Invalid or damaged media file")
        if not json.loads(probe.stdout).get("streams"):
            raise HTTPException(422, "File contains no audio track")
```

这一步运行 FFprobe 检查文件。`subprocess.run()` 的意思是从 Python 启动另一个程序并等待它完成。列表第一项是程序路径，其余项是给它的参数；`source` 告诉它检查哪个文件，`a:0` 选择第一条音轨。

`probe` 保存运行结果，`returncode` 非零在这里表示失败。`stdout` 是工具输出的文字；`json.loads()` 把这种按固定格式写出的文字变回 Python 字典。JSON 是不同程序常用的数据文本格式，你会在最后响应中再次见到它。

字典里的 `streams` 装音轨信息，没有音轨就返回 422。通过检查，才会继续转换。

### 2. 把 M4A 等统一转成 WAV

```python
        result = subprocess.run(
            [state.ffmpeg, "-nostdin", "-v", "error", "-xerror", "-y",
             "-protocol_whitelist", "file,pipe", "-i", str(source),
             "-map", "0:a:0", "-vn", "-ac", "1", "-ar", "16000",
             "-t", str(MAX_SECONDS + 1), "-c:a", "pcm_s16le", str(destination)],
            capture_output=True, timeout=45)
        if result.returncode:
            raise HTTPException(422, "Audio decoding failed")
```

这一步真正转换录音。输入来自 `source`，输出写到 `destination`。不用记住全部工具参数，先看主要目标：取第一条音轨，不处理视频画面，变成单声道、每秒 16000 个采样的 WAV。

采样就是用一个数记录某个时刻的声音幅度；声音文件最终要变成很多按时间排列的数。`pcm_s16le` 指定每个采样保存为两字节整数的一种格式，方便下一步准确读取。

转换最多得到 31 秒，再判断是否超过 30 秒，而不是把所有长录音剪短后假装完整处理。FFprobe 的 `timeout=20` 和这里的 `timeout=45` 分别限制两个工具的等待时间，不是整个请求或模型预测的超时。

### 3. 读取波形与时长

```python
        with wave.open(str(destination), "rb") as wav:
            duration = wav.getnframes() / wav.getframerate()
            samples = np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2").astype(np.float32) / 32768
```

这一步打开刚转换好的 WAV，把文件内容变成模型能处理的数。`wav` 是打开的音频文件对象；`duration` 装秒数，计算方法是采样总数除以每秒采样数。

`samples` 装一维 NumPy 数组，可以先把它看作一长串按时间排列的数字，而不是路径。读取时 `dtype="<i2"` 指明每两个字节代表一个有正负的整数，`<` 指它的字节排列方式；`astype(np.float32)` 将整数转成浮点数，再除以 32768 缩放幅度。例如 16384 变成 0.5。这个数组下一步会直接传给模型。

```python
        if duration > MAX_SECONDS:
            raise HTTPException(422, f"Audio exceeds {MAX_SECONDS} seconds")
        if duration < MIN_SECONDS:
            raise HTTPException(422, f"Audio must be at least {MIN_SECONDS} seconds")
```

这一步拒绝过长或过短的音频。`f"...{变量}..."` 把变量值填进错误文字。通过后才能预测。服务没有检查“是否真的有人说话”，所以格式有效、时长合规不等于这是一条适合评估情绪的语音。

## 六、模型预测：现在才开始计算情绪

### 1. 把波形交给已经加载的模型

```python
        with state.lock:
            output = state.model.generate(input=samples, fs=16000,
                                          granularity="utterance", extract_embedding=False)
```

这一步开始预测。`state.model` 就是启动时 `app.state.model` 中准备好的对象。它收到 `samples` 中的波形，计算后把结果保存到 `output`。

`fs=16000` 说明每秒有多少采样；`granularity="utterance"` 表示针对整段录音；`extract_embedding=False` 表示不要求另外返回特征向量。特征向量是模型对声音提取的一组数，本接口只需要最终的情绪标签和分数。

`with state.lock` 使当前进程里不会有两个线程同时调用这段共享模型代码。它不妨碍模型内部的多个计算线程协作处理**同一条**录音。

### 2. 从 output 取出标签和分数

```python
        if not isinstance(output, list) or len(output) != 1:
            raise ValueError("Expected one model result")
        labels = list(output[0]["labels"])
        scores = [float(s) for s in output[0]["scores"]]
```

这一步检查返回结构并取出需要的数据。单文件应得到一个结果，所以 `output` 必须是长度为 1 的列表；`output[0]` 才是里面的结果字典。

`labels` 装九个情绪标签，`scores` 装对应分数。同一个位置互相对应：`labels[2]` 的分数是 `scores[2]`，不是由本项目重新猜测标签顺序。

`[float(s) for s in ...]` 可以读成“依次取每个 s，转成浮点数，再收集为一个新列表”。结果准备好后，还要检查它是否合理。

### 3. 避免把异常结果直接返回

```python
        if (len(labels) != 9 or len(scores) != len(labels)
                or not all(isinstance(label, str) for label in labels)
                or not all(math.isfinite(s) and 0 <= s <= 1 for s in scores)):
            raise ValueError("Invalid nine-class model output")
```

这一步检查标签和分数是否各有九项、标签是否都是字符串、分数是否都是有效的 0 到 1 之间的数。`all(...)` 表示里面的每项都满足才为真，`math.isfinite()` 排除无穷大等特殊数值。

这只是数据检查，不是在判断模型猜得对不对。检查通过，才会选最高分标签。

## 七、返回结果：把 Python 数据变成浏览器能显示的内容

### 1. 找最高分的位置

```python
        best = max(range(len(scores)), key=scores.__getitem__)
```

这一步找到最高分所在的下标。`best` 不是分数本身。`range(len(scores))` 给出候选位置，`key=scores.__getitem__` 告诉 `max()`：比较位置时，要看它对应的分数。

教学例子：若 `labels = ["happy", "sad"]`、`scores = [0.2, 0.8]`，候选位置是 0、1；因为 `scores[1]` 大，所以 `best` 是 1。接下来取 `labels[best]` 就得到 `"sad"`。这里只用两类帮助理解，实际模型仍返回九类。

### 2. 组装这一条录音的回答

```python
        return Prediction(filename=filename, model=MODEL, emotion=labels[best],
                          score=scores[best], labels=labels, scores=scores)
```

这一步把文件名、模型名称、最高分标签及分数、全部标签和分数放进同一个返回对象。对于例子录音，`filename` 会显示 `我的录音.m4a`，不是临时文件名 `input.m4a`。

`return` 先把对象交回等待 `convert_and_predict()` 的地方，再由 `predict()` 返回给 FastAPI。此时不是只在终端打印一句结果，而是准备给发起上传的浏览器发送数据。

### 3. Prediction 规定返回的数据长什么样

```python
    filename: str
    model: str
    emotion: str
    score: float
    labels: list[str]
    scores: list[float]
```

这是 `class Prediction(BaseModel)` 里实际的字段声明。冒号后面是类型要求：例如 `score` 是浮点数，`labels` 是字符串列表。

`BaseModel` 来自 Pydantic 这个检查数据的工具。FastAPI 使用 `Prediction` 检查返回结构，再将它转成 JSON 文本发回浏览器。浏览器 `/docs` 显示的那些字段，就来自这里返回的数据。

### 4. 出错时回答错误，不继续编造预测

```python
    except subprocess.TimeoutExpired:
        raise HTTPException(422, "Media processing timed out")
    except HTTPException:
        raise
    except Exception:
        log.exception("Prediction failed")
        raise HTTPException(500, "Prediction failed; see server log")
```

这一步是 `convert_and_predict()` 的错误处理。前面的转换与预测放在 `try` 中，出现错误时跳到对应的 `except`。

工具超时返回 422；前面已经明确写出的 HTTP 错误继续向外传；其他内部错误写入日志并返回 500。单独的 `raise` 表示继续抛出当前异常。无论成功返回还是发生异常，退出临时目录的 `with` 范围都会尝试清理文件。

分数是模型对各类给出的 softmax 数值，也就是模型内部把输出转成一组总和约为 1 的分数。它不是已测得的准确率。某条录音分数高，不足以证明情绪判断正确。

## 八、verify_api.py：用 Python 主动测试服务

### 1. 直接运行脚本时进入 main()

```python
if __name__ == "__main__":
    main()
```

这一步决定什么时候开始测试。直接运行这个文件时调用 `main()`；其他文件导入它时不自动运行整套测试。它没有启动 Uvicorn 的代码，必须先单独启动服务。

### 2. 读取你指定的录音路径

```python
    parser = argparse.ArgumentParser()
    parser.add_argument("speech", type=Path, help="A real speech recording, not synthetic audio")
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    folder = Path("test-artifacts")
    folder.mkdir(exist_ok=True)
    ffmpeg = executable("ffmpeg")
```

这一步从运行命令中取得输入。`argparse` 帮助读取命令后面的参数，`args.speech` 装录音路径，`args.url` 装服务地址；不写 `--url` 就使用本机 8000 端口。

`folder` 装生成测试文件的目录，`ffmpeg` 装转换工具路径。脚本从 `app.py` 导入 `executable` 和 `TEMP_ROOT`，只是复用辅助代码，不会因此执行 `lifespan()` 加载模型。下面先在客户端准备文件，再上传给服务。

### 3. 先生成一份统一的测试 WAV

```python
    def convert(arguments):
        subprocess.run([ffmpeg, "-nostdin", "-v", "error", "-y", *arguments], check=True)
```

这一步定义一个调用 FFmpeg 的小函数，避免每种格式都重复写相同的程序参数。`arguments` 是这次转换需要的参数列表，`*arguments` 将列表中的项目逐个放进外层列表。教学例子：`["a", *["b", "c"]]` 得到 `["a", "b", "c"]`。`check=True` 表示工具失败就报错停止。

```python
    convert(["-i", str(args.speech), "-t", "8", "-ac", "2", "-ar", "44100", str(folder / "speech.wav")])
```

这一步把输入真实录音制成最多八秒、44.1 kHz、双声道的 `speech.wav`。输入路径来自 `args.speech`，输出在 `test-artifacts/`。这里故意不是服务最终要求的单声道 16 kHz，上传后才能检查服务是否完成转换。

### 4. 从这份 WAV 生成其他格式

```python
    convert(["-i", str(folder / "speech.wav"), str(folder / "speech.mp3")])
    convert(["-i", str(folder / "speech.wav"), "-c:a", "aac", str(folder / "speech.m4a")])
```

这一步真正把相同语音转换成 MP3 和 AAC 编码的 M4A。AAC 是一种保存压缩音频的编码方式。不是给 WAV 改后缀，所以能够实际测试这些格式的读取与转换。

```python
    convert(["-f", "lavfi", "-i", "color=c=black:s=160x120:r=10", "-i", str(folder / "speech.wav"),
             "-c:v", "mpeg4", "-c:a", "aac", "-shortest", str(folder / "speech.mp4")])
    convert(["-f", "lavfi", "-i", "color=c=black:s=160x120:r=10", "-t", "1", "-an",
             "-c:v", "mpeg4", str(folder / "no_audio.mp4")])
```

这一步准备两种 MP4：第一种有黑色画面和真实语音，应该成功；第二种只有画面、没有音轨，应该被拒绝。生成的画面只用于构成视频文件，不参与情绪识别。

### 5. 建立客户端，先确认服务能回答

```python
    results = []
    with httpx.Client(base_url=args.url, timeout=180, trust_env=False) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/docs").status_code == 200
        schema = client.get("/openapi.json").json()
        assert "multipart/form-data" in schema["paths"]["/predict"]["post"]["requestBody"]["content"]
```

这一步创建主动发请求的 `client`。浏览器能上传，Python 也能上传；`httpx` 是帮助 Python 发 HTTP 请求的工具。`results` 是稍后收集每个用例结果的列表。

`assert` 可以读成“我要求这个条件成立，否则停止”。先检查状态页和文档页返回 200，再读取 `/openapi.json`。这个地址是描述服务有哪些操作、如何上传文件的说明；`schema` 装解析后的说明字典。这里确认它声明了文件上传格式。

`timeout=180` 是测试客户端的等待配置，不是给服务增加推理超时。测试运行不要加 Python 的 `-O` 参数，否则断言会被禁用。

### 6. check() 发送文件并记录响应

```python
            response = client.post("/predict", files=files)
            data = response.json()
            results.append({"case": name, "status": response.status_code, "response": data})
            print(name, response.status_code, data.get("emotion", data.get("detail")), flush=True)
            assert response.status_code == expected, data
```

这一步是 `check(name, files, expected)` 内部的请求操作。`name` 是测试名称，`files` 装要上传的内容，`expected` 装预期状态码。`response` 是服务的回答对象，`response.json()` 把其中 JSON 文本变成 Python 字典 `data`。

实际结果被加入 `results`，终端也会打印简短信息。`assert 条件, data` 在条件不成立时附带显示 `data`。因此不是收到任何错误就算测试通过，而是要与指定状态码一致。

### 7. 成功时只检查数据一致性

```python
                assert len(data["labels"]) == len(data["scores"]) == 9
                best = max(range(9), key=data["scores"].__getitem__)
                assert data["emotion"] == data["labels"][best]
                assert data["score"] == data["scores"][best]
                assert abs(sum(data["scores"]) - 1) < 1e-5
```

这一步在 `expected == 200` 时执行。它检查是否九类、最高分标签与分数是否对应、分数和是否约为 1。`1e-5` 是 0.00001，允许浮点计算的小误差，例如 0.9999999 也能通过。

这里没有人工正确答案，所以不能判断模型说的“生气”是否真的正确。接下来不同用例只是重复使用这个检查函数。

### 8. 上传正常文件与故意构造的错误输入

```python
        for ext in ["wav", "mp3", "mp4", "m4a"]:
            path = folder / ("speech." + ext)
            check(ext, {"file": (path.name, path.read_bytes())}, 200)
```

这一步上传四种真实语音文件。`path` 是本地文件路径，`read_bytes()` 取出字节。`{"file": (path.name, 字节内容)}` 告诉 httpx：字段名叫 `file`，上传文件名是 `path.name`，内容是这些字节。工具会自动完成打包。

```python
        check("damaged", {"file": ("broken.wav", b"not valid media")}, 422)
        check("uppercase_m4a", {"file": ("speech.M4A", (folder / "speech.m4a").read_bytes())}, 200)
        check("empty", {"file": ("empty.wav", b"")}, 422)
        check("unsupported", {"file": ("speech.txt", b"text")}, 415)
```

这一步展示几种实际用例：损坏 WAV、真实但大写后缀的 M4A、空文件和不支持的文本后缀。`b"..."` 是字节，不是普通字符串；`b""` 是空字节。

源码还测试损坏 M4A、无音轨 MP4、多文件，以及文件或请求体过大。大写后缀应成功，其余按各自错误返回。这里摘选几条说明读法，不代表完整脚本只有这些用例。

### 9. 用静音专门测试时长限制

```python
        for seconds, name in [(0.1, "too_short"), (31, "too_long")]:
            buffer = io.BytesIO()
            with wave.open(buffer, "wb") as wav:
                wav.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
                wav.writeframes(b"\0\0" * int(seconds * 16000))
```

这一步在内存中生成过短和过长的 WAV。`buffer` 可以像文件一样读写，但内容保存在内存中。参数指定单声道、每个采样两字节、每秒 16000 个采样；重复的零采样组成静音。

```python
            check(name, {"file": (name + ".wav", buffer.getvalue())}, 422)
```

这一步取出内存中的完整 WAV 上传。预期它们因为时长而被拒绝，**不把静音预测当成识别效果测试**。

### 10. 连续请求、检查清理并保存结果

```python
        for i in range(3):
            check(f"consecutive_{i+1}", {"file": ("speech.wav", (folder / "speech.wav").read_bytes())}, 200)
        assert not list(TEMP_ROOT.iterdir()), "Temporary files leaked"
```

这一步依次发送三次请求，确认服务还能继续回答。不是同时发三次，也不是测试大量并发。`list(TEMP_ROOT.iterdir())` 装临时目录里的项目，`not` 要求这个列表为空。它检查应用目录，不是整个系统的临时文件。

```python
    (folder / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print("All HTTP checks passed; temporary directory empty.")
```

这一步在所有检查通过后把 `results` 写为 JSON 文件。`ensure_ascii=False` 让中文标签直接可读，`indent=2` 让文本按两格缩进。中途失败就不会写出新的完整结果，但磁盘上可能仍有旧的 `results.json`。

整套脚本做的是**接口功能测试和实际模型调用检查**。情绪识别准确率评估需要独立人工标注录音，再比较预测与正确答案；当前脚本没有这样做。

## 九、以后再学：不影响先理解主流程的内容

### 1. async / await：等待时不一直占着执行机会

```python
                        while chunk := await upload.read(1024 * 1024):
```

这一步要等待上传内容读出。`await` 允许程序等待期间先安排其他合适的工作，拿到结果再继续；相应函数用 `async def` 定义。这种写法称为异步，重点是安排等待，不是自动让 CPU 计算加速。

### 2. semaphore：一次只让一条请求进入处理区

```python
    async with request.app.state.gate:
```

这一步使用启动时 `Semaphore(1)` 创建的控制对象。它的实际效果是同一进程一次只让一个请求进入这段处理区，其他请求等待。这种对象叫信号量。它不代表限制了全部等待请求的数量，也不是完整的流量控制系统。

### 3. lock 与工作线程：保护共享对象，安排耗时工作

```python
                    return await run_in_threadpool(convert_and_predict, request.app.state,
                                                   source, Path(directory) / "audio.wav", filename)
```

这一步让现成的工作线程执行转换和预测，避免耗时的同步函数一直占着负责异步调度的线程。“线程池”就是可用来执行这些工作的线程集合。

模型调用处的 `with state.lock` 则让多个线程不能同时进入同一段共享模型调用，这个对象叫锁。一个控制任务安排，一个保护共享调用；外面仍有 `gate`，所以不能据此说服务在同时预测多条录音。

### 4. middleware：读取请求时多做一次总大小检查

```python
app.add_middleware(BodyLimitMiddleware)
```

这一步给应用登记一层额外的处理代码，叫中间件。这里不是预测情绪，而是在上传内容被读取时累计整个请求的大小。

```python
            nonlocal total
            message = await receive()
            total += len(message.get("body", b""))
            if total > MAX_BODY_BYTES:
                raise BodyTooLarge()
            return message
```

这是 `BodyLimitMiddleware` 内部 `limited_receive()` 的实际内容片段。`receive()` 读取下一块消息，`message` 是装着内容的字典；`body` 是其中的字节。`total` 记录累计大小，`nonlocal` 说明要修改外层函数已有的 `total`。

每次下游读取内容都会经过它，所以即使上传方没有预先说总大小，也按实际字节检查。超过 26 MiB 抛出 `BodyTooLarge`，外层捕获后返回 413。文件本身仍有独立的 25 MiB 检查。更底层怎样传递消息，可以等熟悉核心流程后再学。

## 十、下次如何启动、上传和停止

### 1. 在 PowerShell 启动后台程序

```powershell
Set-Location 'C:\Users\36043\Desktop\uni\ureca\ser-api'
& 'C:\Users\36043\miniconda3\envs\emotion2vec\python.exe' -m uvicorn app:app --host 127.0.0.1 --port 8000 --workers 1
```

第一行进入项目目录。第二行用指定环境的 Python 3.10 运行 Uvicorn；PowerShell 的 `&` 表示执行引号里的程序路径。`app:app` 前一个 `app` 指 `app.py` 模块，后一个指其中的应用对象。

`127.0.0.1` 是本机地址，`8000` 是等待请求的端口，浏览器地址里也要用它。`--workers 1` 表示用一个服务进程；增加进程会各自加载模型，不等于前面说的计算线程。不要加 `--reload`，避免学习时产生额外加载。

等待终端出现 `Application startup complete`，保持窗口运行。直接执行 `python app.py` 不会自动开始监听。端口已占用时，先确认是否已有服务运行，不要反复启动。

### 2. 再打开网页上传录音

```text
http://127.0.0.1:8000/docs
```

在浏览器打开地址，展开 POST `/predict`，点击 **Try it out**，在 `file` 选择录音，再点击 **Execute**。支持 WAV、MP3、MP4、M4A。

**只打开 `/docs` 不会自动启动后台服务。** 页面要靠已经运行的 Uvicorn/FastAPI 提供。服务没启动，这个地址就无法连接；上传后在页面看到的是这次请求的响应。

### 3. 想运行整套测试时，另开一个 PowerShell

```powershell
Set-Location 'C:\Users\36043\Desktop\uni\ureca\ser-api'
& 'C:\Users\36043\miniconda3\envs\emotion2vec\python.exe' verify_api.py 'C:\Users\36043\.cache\modelscope\models\iic--emotion2vec_plus_seed\snapshots\master\example\test.wav'
```

这个可选命令主动测试第一个窗口中的服务，末尾是官方模型附带的真实语音路径，可替换成自己的真实录音。它会覆盖生成的测试文件。测试脚本结束不等于服务结束；本次文档改写没有执行这条命令。

### 4. 在启动服务的窗口停止

```text
在运行 Uvicorn 的 PowerShell 窗口按 Ctrl+C
```

等待关闭提示和命令行提示符返回。关闭浏览器标签页不会停止服务；服务停了，网页也不能继续预测。下次重新执行启动命令即可，不用每次安装依赖。磁盘上的模型权重还在，但新启动的服务仍需要把模型加载到内存。
