# 语音情绪 API：从两个预测入口开始

[English](README.md)

本地 Windows CPU FastAPI 服务，通过 FunASR 使用 `iic/emotion2vec_plus_seed`。启动同一个服务后，按处理目标选择接口：

| | `POST /predict` | `POST /predict_multi` |
| --- | --- | --- |
| 输入 | 恰好一个 multipart 文件字段 `file` | 恰好两个 multipart **文件字段**：媒体 `file`、转录 `xml` |
| 媒体 | WAV、MP3、MP4、M4A，后缀不区分大小写 | 相同格式，选第一条音轨并混为单声道 |
| 输出 | JSON：文件名、模型、英文 emotion/score、九项对应的 labels/scores | UTF-8 `application/xml` 附件，文件名 `predicted-transcript.xml` |
| 做什么 | 对完整 0.25–30 秒短录音预测一次 | 媒体解码一次，按 XML 时间逐段预测并写回 emotion |
| 如何运行 | `/docs` → `/predict` → 选择 `file` → Execute | `/docs` → `/predict_multi` → 选择两个文件 → Execute |
| 顺着代码看 | [单文件调用流程](docs/api-flows.md#post-predict) | [XML 调用流程](docs/api-flows.md#post-predict-multi) |
| 出错/验证 | [报错入口](#报错) · [验证汇总](#验证) | [报错入口](#报错) · [验证汇总](#验证) |

## 启动与发送请求

在当前仓库根目录，使用已有环境执行：

```powershell
conda activate emotion2vec
python -m uvicorn app:app --host 127.0.0.1 --port 8000 --workers 1
```

等待 `Application startup complete`，再打开 <http://127.0.0.1:8000/docs>。保持终端运行，按 Ctrl+C 停止。使用单 worker、不加 `--reload`，避免额外模型加载；端口被占用时选择其他空闲端口，并同步修改 URL。`/health` 只报告就绪，不运行推理。仅导入 `app.py` 不加载模型。

```powershell
curl.exe -X POST http://127.0.0.1:8000/predict -F "file=@path/to/speech.wav"
curl.exe -X POST http://127.0.0.1:8000/predict_multi -F "file=@samples/news-video-with-captions 2.mp4" -F "xml=@samples/news-video-with-captions 1.xml" --output test-artifacts/predicted-transcript.xml
```

保存到 `test-artifacts/` 前先准备该目录。`samples/` 是本地样本、被 Git 忽略，新检出仓库不一定有这些文件。失败响应是 JSON，不是 XML；使用命令行下载时需先检查状态码，不能把错误内容当作成功转录。

[环境与模型启动说明](docs/environment.zh-CN.md)集中记录工具、依赖、缓存及启动限制。`requirements.txt` 只是 API 补充依赖，不是完整环境锁；普通应用启动即使有缓存也可能联系模型仓库，历史验证的离线启动器不是应用公开配置。本项目不训练模型。

## 处理约定与限制

`/predict_multi` 接受无命名空间的 `AudioDoc` 根元素、恰好一个直接 `SegmentList`，其下 1–1000 个直接 `SpeechSegment`。`stime` 是开始秒数，`dur` 是持续秒数，`end = stime + dur`；时间相对于第一条音轨的首个解码采样，采用 `[start, end)` 区间。全部时间和实际采样范围在首次推理前检查；XML 不必按时间排序，也不会被重排。

只新增或覆盖 `SpeechSegment.emotion`；其他属性（包括 `score`）、text/tail、Word、图像/声音描述均保留语义内容。根内注释和处理指令也保留，格式、引号和等价转义可以变化。`<unk>` 安全转义为 `&lt;unk&gt;`。原 emotion 不作为真实答案。DTD、实体声明及外部实体解析被拒绝。XML `channel="1"` 是元数据，不能理解为选择左声道。

两个路由共用启动时加载的 CPU 模型、请求 gate 和推理锁，阻塞工作放在线程池。`/predict` 先 FFprobe 检查再 FFmpeg 转换；`/predict_multi` 直接用 FFmpeg **解码一次**，按采样位置读取并调用 **`predict_samples()`**，不循环调用 `predict_segment()`，也不在内部发 HTTP 请求。标准音频为单声道、16 kHz、PCM16 WAV，交给模型的是 NumPy float32 波形。

| 限制 | `/predict` | `/predict_multi` |
| --- | --- | --- |
| 媒体文件 | 25 MiB | 128 MiB |
| XML 文件 | 不接收 | 2 MiB |
| 含 multipart 开销的请求体 | 26 MiB | 131 MiB |
| 完整解码音频 | 0.25–30 秒 | 最多 1800 秒 |
| 单段长度 | 完整短录音为一次输入 | 每段 0.25–30 秒 |
| 段数量 | 不涉及 | 1–1000 |
| FFprobe 超时 | 20 秒 | 路由不调用 FFprobe |
| FFmpeg 超时 | 45 秒 | 120 秒 |
| 解码时长探测上限 | 31 秒，随后拒绝超过 30 秒 | 1801 秒，随后拒绝超过 1800 秒 |
| 解码输出字节上限 | 由时长和格式约束 | 57,697,536 字节 |
| XML 深度/响应大小 | 不涉及 | 128 层 / 16 MiB |

子进程超时不等于推理、排队或整个请求的超时。多段请求全部成功才返回 XML，不返回部分结果、不截短、不补静音。成功或异常都会清理请求临时目录，强制终止进程仍可能留下文件。

英文类别保持与原分数一一对应：`angry`、`disgusted`、`fearful`、`happy`、`neutral`、`other`、`sad`、`surprised`、`<unk>`。`/predict` 按实际返回顺序选最高分位置，不重排标签。分数不是测得的准确率，也不是校准后的正确性保证。

## 可直接调用的 Python 单段函数

[app.py](app.py) 中的 `predict_segment(state, source, start, end, filename=None)` 是同步 Python 函数，不是 HTTP 接口。传入已初始化的应用状态，它通过 `extract_audio_segment()` 提取临时标准 WAV，再返回 `Prediction`；成功或失败都会清理。所选段必须 0.25–30 秒，但源媒体不受 30 秒整段限制；提取超时 45 秒，每次从头解码，因此不是 XML 多段接口的处理方式。异步调用方应使用 `run_in_threadpool`。

[函数及调用方](docs/function-index.zh-CN.md#app-predict-segment) · [共享推理函数](docs/function-index.zh-CN.md#app-predict-samples)

## 报错

**两个接口从这里统一查询：[API 报错说明](docs/api-errors.md)。** 共用错误只列一次，接口特有错误注明适用范围、触发条件、状态码、消息示例和源码位置。片段索引是原 XML 顺序的 **1 起始编号**，不是按时间排序的编号。启动失败与 HTTP 错误分开说明；媒体头时长不能证明实际内容完整。

## 验证

在仓库根目录运行生成媒体/假模型测试，使用现有环境和 FFmpeg，无需启动真实模型服务：

```powershell
python -m unittest discover -s tests -t . -v
# 也可指定模块：
python -m unittest -v tests.test_audio_segments tests.test_predict_multi
```

单独检查已启动的 `/predict` 服务时，提供真实语音：

```powershell
python -m scripts.verify_predict_http "path/to/real-speech.wav" --url http://127.0.0.1:8000
```

该脚本不启动服务、不测试 `/predict_multi`，会转换真实语音并写入 `test-artifacts/results.json`，不覆盖历史报告。只运行 `--help` 不会推理。

| 范围 | 测试代码/保留记录 | 验证什么 |
| --- | --- | --- |
| 单段预处理 | [tests/test_audio_segments.py](tests/test_audio_segments.py)，10 项 | 截取波形和时间、mono/16 kHz/PCM16、拒绝路径、假推理接线与清理 |
| XML 端点 | [tests/test_predict_multi.py](tests/test_predict_multi.py)，16 项 | 65 段生成数据、英文覆盖/转义及 XML 语义保留、输入拒绝、一次解码、gate/线程和清理 |
| `/predict` 真实 HTTP 回归 | [scripts/verify_predict_http.py](scripts/verify_predict_http.py)；[历史报告](reports/functional-verification.md)、[原始响应](reports/http-functional-results.json)、[真实模型复测](reports/real-model-segment-verification-2026-10-31.md) | 18 个 POST 用例及健康页、文档、schema、标签/分数校验；保留原始记录 |
| `/predict_multi` 真实 HTTP 验收 | [完整报告](reports/predict-multi-verification-2026-11-02.md) | HTTP 200、65 段真实推理、**43.373 秒不含启动**、一次解码、XML 保留及清理 |

完整报告仍保留早先下载不完整的失败记录：55,062,440 字节的旧输入被验证过的 71,215,895 字节完整视频替换后通过，没有放宽校验。最终本地输出为 `test-artifacts/supervisor-complete-emotions.xml`。历史原始 JSON 可能包含中英标签，当前响应只用英文。

**功能验证不代表分类准确率评估。** 尚无独立人工标注集、准确率/F1/混淆矩阵、校准或系统性能基准；假模型不能验证真实模型情绪判断。一次请求耗时也不代表吞吐保证。

## 代码与文档导航

```text
app.py                        HTTP 入口、启动、共享媒体/模型/XML 处理
scripts/verify_predict_http.py /predict 的真实 HTTP 验证命令
tests/                       生成媒体及假模型 unittest 测试包
docs/                        调用链、报错表、逐函数索引与学习教程
reports/                     已保存的原始功能验证记录
environment/                 依赖快照
samples/                     本地媒体/XML 输入，Git 忽略
test-artifacts/              生成结果与日志，Git 忽略
.tmp/                        请求临时文件，Git 忽略
```

从仓库根目录使用 `python -m ...` 或 unittest discovery，`scripts/`、`tests/` 都有包入口。验证工具和测试统一导入 `app`；当前应用规模下，保持这个共享状态入口有助于直接追踪调用与测试替换。

- [两个接口调用流程](docs/api-flows.md) → [逐源码文件的全部自定义函数/方法索引](docs/function-index.zh-CN.md)，包括内部辅助函数和测试方法。
- [01：单文件基础](docs/01-single-file-api-learning.zh-CN.md)。
- [02：分段 XML 请求学习](docs/02-segment-xml-api-learning.zh-CN.md)。
- [环境详情](docs/environment.zh-CN.md)、[补充依赖](requirements.txt)、[pip 快照](environment/pip-snapshot.txt)，不是完整环境锁。
