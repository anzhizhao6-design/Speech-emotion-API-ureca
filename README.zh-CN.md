# 本地语音情绪识别 API

[English](README.md)

本项目是 Windows CPU 服务，使用 FastAPI、Uvicorn，通过 FunASR 调用已微调的 `iic/emotion2vec_plus_seed` 模型。`/predict` 接收一个 WAV、MP3、MP4 或 M4A 文件，返回英文标签和模型原生九分类分数；`/predict_multi` 接收媒体与 XML 转录，返回写入各语音段英文 emotion 的 XML。API 不使用 IEMOCAP，也不训练模型。

## 学习文档：按 01、02 顺序阅读

1. [01：单文件 API 基础学习](docs/01-single-file-api-learning.zh-CN.md)：保留最初的 Python、HTTP 上传和 `/predict` 学习记录，并标注当前代码已抽取或变化的部分。
2. [02：分段与 XML API 学习](docs/02-segment-xml-api-learning.zh-CN.md)：按一次真实请求讲解当前 `/predict_multi` 的校验、一次解码、采样定位、共享模型、XML 更新与清理，附函数职责表和读代码顺序。

## 项目文件

| 文件 | 职责 |
| --- | --- |
| `app.py` | 启动时加载共享模型，检查上传文件，转换媒体，串行 CPU 推理，返回 JSON 或更新后的 XML，并清理临时文件。 |
| `verify_api.py` | 通过真实 HTTP 请求测试已启动的服务。将指定语音转为测试格式，检查响应并保存结果。它不启动服务，也不测量识别准确率。 |
| `test_segments.py` | 使用生成媒体及假模型，验证单段提取、格式、边界、标签对齐和清理。 |
| `test_predict_multi.py` | 使用生成媒体及假模型，验证 XML 端点、语义保留、独立限制、共享门控和清理。 |
| `requirements.txt` | 固定版本的 API 补充依赖，不是完整环境描述。 |
| `environment/pip-snapshot.txt` | 已记录的 pip 快照，不是可移植的 Conda 锁定文件。 |
| `reports/http-functional-results.json` | 已纳入 Git 的历史 18 个 POST 用例响应，保留当时的中英标签；新的测试产物写到被忽略的 `test-artifacts/`。 |

## 环境和启动

已记录环境：`C:\Users\<username>\miniconda3\envs\emotion2vec`。

| 组件 | 已记录版本 |
| --- | --- |
| Python | 3.10.20 |
| torch / torchaudio | 2.14.0+cpu / 2.11.0+cpu |
| funasr / modelscope | 1.4.15 / 1.40.0 |
| FastAPI / Uvicorn | 0.161.1 / 0.54.0 |
| python-multipart | 0.0.32 |
| FFmpeg | 6.1.1 |

保留了原有 torch/FunASR 版本；环境配置时 `pip check` 已通过。客户端还需要 `httpx`，已记录环境中已安装。在项目目录执行以下命令可补充该环境：

```powershell
& 'C:\Users\<username>\miniconda3\envs\emotion2vec\python.exe' -m pip install -r requirements.txt
& 'C:\Users\<username>\miniconda3\Scripts\conda.exe' install -p 'C:\Users\<username>\miniconda3\envs\emotion2vec' --override-channels -c defaults ffmpeg=6.1.1 --freeze-installed -y
```

这些命令不能从零重建完整环境。此前 conda-forge FFmpeg 安装因 gdk-pixbuf 的 DLL/GBK 解码错误而回滚。随后补回缺失的 `conda-meta/history` 标识并写入说明，没有重建旧历史。改用 defaults 安装成功，同时更新了 OpenSSL 3.5.7 → 3.5.9 和 CA 证书。

在 PowerShell 中使用明确的 Python 3.10 路径启动：

```powershell
Set-Location 'C:\Users\<username>\Desktop\uni\ureca\ser-api'
& 'C:\Users\<username>\miniconda3\envs\emotion2vec\python.exe' -m uvicorn app:app --host 127.0.0.1 --port 8000 --workers 1
```

等待 `Application startup complete`。保持一个 worker，不加 `--reload`，避免额外加载模型。Ctrl+C 停止。其他开发者需要替换这些本机路径。

服务优先查找所选环境 `Library\bin` 下的 FFmpeg/FFprobe，找不到时查 PATH，并将 FFmpeg 目录加入服务进程的 PATH。使用上述命令无需修改系统 PATH 或激活环境。

## 模型与处理流程

模型在每个进程启动时加载一次，配置为 `hub="ms"`、`device="cpu"`、`disable_update=True`。首次使用下载官方权重；已有缓存时仍可能访问仓库。尚未验证完全离线启动。代码使用默认模型版本，没有固定不可变的模型修订。

已记录缓存：`C:\Users\<username>\.cache\modelscope\models\iic--emotion2vec_plus_seed\snapshots\master`。

已记录 `model.pt` SHA256：`327e861049c7105a3f8589edfd16543a7cdc0c1926f1b64de975d98e0650cdd3`。加载时出现过缺少 `AUDIO.decoder` 键的警告，随后分类请求成功。

`/predict` 先用 FFprobe 检查第一条音轨，再用 FFmpeg 转为单声道 16 kHz PCM16 WAV。`/predict_multi` 不在每次请求中调用 FFprobe，而是直接用 FFmpeg 一次性解码第一条音轨，随后按实际 WAV 采样数检查全部片段。两条流程都将 float32 NumPy 波形交给共享模型。MP4 画面不参与分析。两个预测路由共用信号量串行处理请求，线程锁保护推理；阻塞解码和推理交给线程池，torch CPU 计算线程最多四个。推理参数为 `granularity="utterance", extract_embedding=False`。

## `/predict` 上传与响应

打开 <http://127.0.0.1:8000/docs> → **POST /predict** → **Try it out** → 在 `file` 中选文件 → **Execute**。上传必须恰好包含一个名为 `file` 的 multipart 文件字段，不能附加其他字段。支持 `.wav`、`.mp3`、`.mp4`、`.m4a`，不区分大小写。实际内容必须能成功解码；服务不检查是否包含语音。

<http://127.0.0.1:8000/health> 报告就绪状态、模型和 CPU 设备，不执行推理检查。生成验证产物后，可按以下示例上传：

```powershell
curl.exe -X POST 'http://127.0.0.1:8000/predict' -F 'file=@C:\Users\<username>\Desktop\uni\ureca\ser-api\test-artifacts\speech.wav'
```

| JSON 字段 | 含义 |
| --- | --- |
| `filename` | 去除目录部分后的上传文件名。 |
| `model` | `iic/emotion2vec_plus_seed`。 |
| `emotion`、`score` | 最高分位置的标签和分数。 |
| `labels`、`scores` | 按模型实际输出顺序排列的全部九个标签和对应分数。 |

当前标签保持模型顺序，去掉语言前缀，只返回 `angry`、`disgusted`、`fearful`、`happy`、`neutral`、`other`、`sad`、`surprised`、`<unk>` 九个英文类别。分数不因标签转换而改变。历史报告中的 `生气/angry` 等是旧响应，不能当作当前返回格式。分数是模型 softmax 输出，不是测得的准确率，也不是经过校准的正确性保证。

## `/predict` 限制与错误

| 限制 | 实际实现 |
| --- | --- |
| 文件大小 | 最大 25 MiB |
| 请求体，包含 multipart 开销 | 最大 26 MiB；接收时累计计数 |
| 解码后时长 | 0.25–30 秒，包含边界 |
| FFprobe / FFmpeg 超时 | 20 / 45 秒 |
| 检查时长时的解码上限 | 31 秒；超过 30 秒拒绝 |

上述子进程超时不代表推理或整个请求的超时。

| 状态码 | 含义 |
| --- | --- |
| 400 | multipart 解析错误，包括多文件或不允许的附加字段。 |
| 413 | 文件或请求体超过大小限制。 |
| 415 | 不支持的扩展名。 |
| 422 | 文件字段缺失/不正确、空文件/无效媒体、无音轨、解码失败、媒体处理超时或时长超限。 |
| 500 | 内部预测失败；详细原因写入服务端日志。 |

应用上传与转换文件使用每次请求独立的 `.tmp/ser-*` 目录，正常完成及已处理异常后清理。强制终止可能留下文件。服务用于本机单 worker 使用，没有实现认证或准确率评估接口。

## 接口功能验证与评估范围

此前运行使用官方模型附带的 `example/test.wav` 真实语音。客户端生成最多八秒的 44.1 kHz 双声道 WAV、MP3、带画面/AAC 音轨的 MP4，以及 AAC M4A。M4A 是实际编码媒体，不是改扩展名的文件；未测试用户的 Windows 原始录音。

先启动服务，再在项目目录执行：

```powershell
& 'C:\Users\<username>\miniconda3\envs\emotion2vec\python.exe' verify_api.py 'C:\Users\<username>\.cache\modelscope\models\iic--emotion2vec_plus_seed\snapshots\master\example\test.wav'
```

可以替换为其他真实语音路径。`--url` 可覆盖 `http://127.0.0.1:8000`。客户端覆盖 `test-artifacts/` 下生成的媒体文件，并在全部检查通过后写入 `test-artifacts/results.json`，不会自动覆盖历史 `reports/http-functional-results.json`。这个脚本只测试 `/predict`，不包含 XML 多段请求。

| 已保存 POST 用例（共 18 项） | 状态码 |
| --- | --- |
| WAV、MP3、MP4、M4A；大写 `.M4A`；连续三次 WAV 请求 | 200（8 项） |
| 损坏 WAV/M4A；无音轨 MP4；空文件；过短/过长音频 | 422（6 项） |
| 不支持的扩展名 | 415 |
| 多文件 | 400 |
| 文件过大 / 请求体过大 | 413（2 项） |

成功响应通过了九个标签/分数对应、分数和约为一、最高分标签与分数字段一致的检查。`/health`、`/docs` 和 OpenAPI multipart 描述也已通过检查；运行后 `.tmp` 为空。已记录 WAV 结果为 `生气/angry`，分数为 `0.9999990463256836`。完整响应见 `reports/http-functional-results.json`。静音仅用于时长拒绝测试。

**这些验证接口行为和实际模型推理，不是情绪识别准确率评估。** 尚未使用独立人工标注测试集，未计算准确率或进行校准研究。单个样本的高分不能证明预测正确或具有泛化能力。本次仅根据源码和已保存结果更新文档，没有重新运行服务测试。

## 仓库整理说明

历史 HTTP 测试结果位于 [历史响应](reports/http-functional-results.json)，说明见 [功能验证记录](reports/functional-verification.md)。测试脚本的新结果写入 `test-artifacts/results.json`。旧实验脚本、压缩包、音视频、缓存和日志未纳入此仓库。本文中的 `<username>` 需按本机环境替换；旧路径中的 `ser-api` 也应替换为实际仓库目录。`/predict_multi` 已实现，使用方式如下。

## 英文标签输出

当前 API 的 `labels` 和 `emotion` 均只返回英文，例如 `吃惊/surprised` 转为 `surprised`。标签顺序和分数不变，特殊标签 `<unk>` 保留。`reports/` 中历史结果保留当时实际返回的中英标签，不能当作此修改后的新测试结果。

## `POST /predict_multi`：媒体＋XML 分段预测

请求必须恰好有两个 multipart **文件字段**：

| 字段 | 内容 |
| --- | --- |
| `file` | 一份 WAV、MP3、MP4 或 M4A 媒体，扩展名不区分大小写 |
| `xml` | 一份 XML 转录，按实际内容解析，不能是普通文本字段 |

重复字段、多余字段、缺失字段或普通文本字段会被拒绝。先启动服务，可在 `/docs` 选择两个文件；或在仓库根目录执行以下示例（先准备 `test-artifacts/` 输出目录）：

```powershell
curl.exe -X POST http://127.0.0.1:8000/predict_multi -F "file=@samples/news-video-with-captions 2.mp4" -F "xml=@samples/news-video-with-captions 1.xml" --output test-artifacts/predicted-transcript.xml
```

输入样本不会被覆盖。成功响应为 UTF-8 `application/xml`，附带下载文件名 `predicted-transcript.xml`。

支持的结构是无命名空间的 `AudioDoc` 根元素，恰好一个直接子元素 `SegmentList`，其下有 1–1000 个直接 `SpeechSegment`。`stime` 是开始秒数，`dur` 是持续秒数，结束位置为 `stime + dur`。代码用十进制时间计算、向上取整为 16 kHz 采样索引。时间相对于第一条音轨的首个解码采样；XML 元素不必按时间排序，也不会被重新排序。

服务先检查所有时间字段，再把第一条音轨**解码一次**到单声道、16 kHz、PCM16 WAV。根据实际采样总数验证全部片段后，逐段定位读取，复用 `predict_samples()`、已加载模型和推理锁。立体声会混成单声道，XML `channel="1"` 仅作为元数据保留，不表示选择左声道。

每段都重新预测并新增或覆盖 `emotion`。原有 emotion 不是已验证的真实标签；所有其他属性（包括原 `score`）、元素顺序、文本、Word、图像/声音描述保留语义内容。根内注释、处理指令也保留。格式、引号、XML 声明和等价转义可以改变；`<unk>` 会安全写为 `emotion="&lt;unk&gt;"`。没有自定义字节偏移重写。

解析会拒绝 DTD、实体声明和外部实体解析，不读取外部资源；XML 嵌套超过 128 层拒绝。全部片段成功后才返回 XML，任意片段失败都返回 JSON 错误，不返回部分结果，不静默截短或补静音。错误中的片段编号是原 XML 顺序下的 **1 起始编号**。

| 新端点限制 | 数值 |
| --- | --- |
| 媒体文件 | 128 MiB |
| XML 文件 | 2 MiB |
| 包含 multipart 开销的请求体 | 131 MiB，按实际接收字节计数 |
| 完整解码音频 | 最多 30 分钟 |
| 每段时长 | 0.25–30 秒，包含边界 |
| 语音段数量 | 1–1000 |
| FFmpeg 解码超时 | 120 秒 |
| 解码时长/输出上限 | 1801 秒 / 57,697,536 字节，多一秒用于检测超长 |
| 返回 XML 大小 | 16 MiB |
| XML 嵌套深度 | 128 层 |

媒体头里的时长不能证明文件完整，仍需检查真实解码采样。原 `/predict` 的 25 MiB 文件、26 MiB 请求体和 0.25–30 秒音频限制保持不变。这里的 120 秒只限制解码，不限制全部推理、gate 等待或整个请求。

multipart 解析错误返回 400，上传超限 413，不支持的媒体后缀 415，XML/时间/数量/范围或解码/输出限制错误 422，模型或内部错误 500。临时目录 `.tmp/ser-multi-*` 在成功和异常后清理；强制结束进程可能留下文件。两个预测接口共用请求 gate。

## 分段测试与完整样本验证

无需启动服务或加载真实模型的生成媒体/假模型测试：

```powershell
conda activate emotion2vec
python -m unittest -v test_segments test_predict_multi
```

已保存记录中，10 项单段测试和 16 项 XML 端点测试均通过，原 `/predict` 的 18 个 HTTP 用例也通过。完整真实视频的 `/predict_multi` 请求返回 **HTTP 200**，65 段全部获得有效英文 emotion；耗时 **43.373 秒，不含模型启动**，一次解码、同一模型复用、其他 XML 内容保留及清理检查均通过。

早先 55,062,440 字节的视频下载不完整，实际音频约 452 秒，导致片段越界；重新下载为 71,215,895 字节、完整音频约 570.259 秒后，在**不放宽校验**的情况下通过。历史失败和新成功均见 [XML 端点验证报告](reports/predict-multi-verification-2026-11-02.md)。返回 XML 和日志保存在被忽略的 `test-artifacts/`，不随 Git 分发。

上述结果验证功能，不代表情绪分类准确率；尚无独立人工标注集、准确率/F1、校准或系统性能基准。当前学习文档整理没有重新运行模型或测试。
