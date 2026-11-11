# API errors / 两个预测接口的报错说明

[English API entry](../README.md#errors) · [中文入口](../README.zh-CN.md#报错) · [调用流程](api-flows.md) · [函数索引](function-index.zh-CN.md)

以下按当前 [app.py](../app.py) 列出触发条件；英文消息保留便于查日志。HTTP 错误体通常为 `{"detail": "..."}`，不是成功 JSON 预测或 XML 附件。多段请求只有全部成功才返回 XML；异常后清理请求临时目录。强制终止进程可能留文件。检查状态码后再解释下载内容。

## Shared errors / 共用错误

这里的“两个接口”指 `/predict` 和 `/predict_multi`；各接口特有条件另见后表。

| 状态码 | 适用接口 | 触发条件 | 消息示例/排查 | 产生位置 |
| --- | --- | --- | --- | --- |
| 400 | 两者 | multipart 解析失败、超过允许的文件/文本字段数量、缺少 boundary 等 | `Too many files. Maximum number of files is ...`；确保以文件字段提交，不夹带额外文本字段 | Starlette 表单解析，由 `predict()` / `predict_multi()` 进入 |
| 413 | 两者 | 实际请求体（包括 multipart 开销）超过路由上限 | `Request body exceeds 26 MiB` 或 `...131 MiB`；不能仅看 Content-Length 或单文件大小 | `BodyLimitMiddleware.__call__.limited_receive()` |
| 413 | 两者 | 写入的媒体超限；多段接口还单独限制 XML | 单文件 `File exceeds 25 MiB`；多段 `Media exceeds 128 MiB` / `XML exceeds 2 MiB` | `predict()` / `save_multi_upload()`；`parse_transcript()` 也检查 XML 长度 |
| 415 | 两者 | 媒体后缀不在允许集合中（大小写不敏感） | `Supported file extensions: WAV, MP3, MP4, M4A`；改后缀不等于内容已可解码 | 两个路由 |
| 422 | 两者 | 必需文件为空 | 单文件 `Empty file`；多段 `Empty media` / `Empty xml` | `predict()` / `save_multi_upload()` |
| 422 | 两者 | FFmpeg 返回失败或无法选到音轨 | 单文件 `Audio decoding failed`；多段 `Audio decoding failed or file contains no audio track` | `convert_and_predict()` / `predict_transcript()` |
| 422 | 两者 | 等待媒体工具超时 | 单文件 `Media processing timed out`（FFprobe 20 秒、FFmpeg 45 秒）；多段 `Audio decoding timed out (120 seconds)` | 两个工作函数捕获 `TimeoutExpired` |
| 500 | 两者 | 模型异常、标签/分数结构不符合约定，或其他未预期内部异常 | 单文件 `Prediction failed; see server log`；多段 `Segment n: prediction failed; see server log` 或 `Transcript prediction failed; see server log`；查服务端完整异常 | `predict_samples()` 的异常由对应工作函数包装 |
| 404 / 405 | 两者及其他路径 | URL 不存在 / 方法不支持 | 核对完整路径并使用 POST；这类状态由框架路由产生 | FastAPI/Starlette 路由 |

空/重复/错误字段既可能先触发表单的 400，也可能在解析成功后触发下面路由自己的 422；不要将所有 multipart 错误统一理解成 422。原文件和输出文件的大小上限见 README 的限制表。

## POST /predict only / 单文件接口特有错误

| 状态码 | 触发条件 | 实际消息 | 产生位置 |
| --- | --- | --- | --- |
| 422 | 解析后不是恰好一个名为 `file` 的 UploadFile | `Provide exactly one file in the 'file' field` | `predict()` |
| 422 | FFprobe 认为容器无效/损坏 | `Invalid or damaged media file` | `convert_and_predict()` |
| 422 | FFprobe 没有找到第一条音轨 | `File contains no audio track` | `convert_and_predict()` |
| 422 | 实际解码时长大于 30 秒 | `Audio exceeds 30 seconds` | `convert_and_predict()`；最多解码 31 秒是探测，不是静默截短 |
| 422 | 实际解码时长小于 0.25 秒 | `Audio must be at least 0.25 seconds` | `convert_and_predict()` |

[顺着单文件调用链定位](api-flows.md#post-predict) · [工作函数详情](function-index.zh-CN.md#app-convert-and-predict)

## POST /predict_multi only / XML 接口特有错误

`Segment n` 的 n 是 **XML 文档顺序下从 1 开始的 SpeechSegment 编号**，不是按时间排序的编号。结构级错误还没有可用段时可能没有编号。

| 状态码 | 触发条件 | 实际消息或前缀 | 产生位置 |
| --- | --- | --- | --- |
| 422 | 解析后不是恰好两个 UploadFile，字段名不是 `file`、`xml` 或重复字段 | `Provide exactly two file fields: 'file' and 'xml'` | `predict_multi()` |
| 422 | XML 语法/编码错误，DTD、实体声明或外部实体解析，深度超过 128 层 | `Invalid XML: ...`；内部原因为 `DTD and entity declarations/resolution are forbidden` 或 `XML nesting exceeds 128 levels` | `parse_transcript()` 及其回调 |
| 422 | 根不是无命名空间的 AudioDoc，或直接 SegmentList 不是恰好一个 | `Expected AudioDoc with exactly one SegmentList` | `parse_transcript()` |
| 422 | 没有直接 SpeechSegment | `Segment 1: no SpeechSegment found` | `parse_transcript()` |
| 422 | 超过 1000 个直接 SpeechSegment | `Segment 1001: at most 1000 speech segments allowed` | `parse_transcript()` |
| 422 | 其他位置存在 SpeechSegment，例如嵌在别的节点内 | `Segment n: SpeechSegment must be a direct child of AudioDoc/SegmentList` | `parse_transcript()` |
| 422 | stime/dur 缺失、不是有效有限数，开始为负或超过 1800 秒，dur 不在 0.25–30 秒 | `Segment n: invalid stime/dur (...)` | `parse_transcript()`；NaN/Infinity 也被拒绝 |
| 422 | 解码 WAV 大小超过 57,697,536 字节 | `Decoded audio exceeds output-size limit` | `predict_transcript()` |
| 422 | 解码 WAV 不是单声道/16 kHz/2 字节采样 | `Unexpected decoded audio format` | `predict_transcript()` |
| 422 | 实际解码帧数超过 1800 秒 | `Decoded audio exceeds 30 minutes` | `predict_transcript()` |
| 422 | 任意段 first 不在实际音频内，或 last 超过实际帧数 | `Segment n: outside the available audio` | `predict_transcript()` 的首次范围循环，**任何模型调用前** |
| 422 | 读段时实际 PCM 字节不等于所需采样数 × 2 | `Segment n: incomplete decoded audio` | `predict_transcript()` 的逐段循环 |
| 422 | 序列化结果大于 16 MiB | `Updated XML exceeds 16 MiB` | `predict_transcript()`；此时可能已推理，但不会返回部分 XML |

[顺着 XML 调用链定位](api-flows.md#post-predict-multi) · [解析详情](function-index.zh-CN.md#app-parse-transcript) · [工作函数详情](function-index.zh-CN.md#app-predict-transcript)

## Startup and direct Python calls / 启动和直接函数调用

- 启动找不到 FFmpeg/FFprobe 时，`executable()` 抛出 `RuntimeError("... not found in this Python environment")`；模型缓存/依赖加载失败也会使 lifespan 启动失败。这时尚无就绪服务，不是一次预测的 HTTP 500。见[环境说明](environment.zh-CN.md)。
- `predict_segment()` / `extract_audio_segment()` 是 Python 工具，不经过路由上传限制或 gate。时间需为有限的 Real 数（拒绝 bool），`0 <= start < end`，单段 0.25–30 秒。它们可直接抛出 HTTPException(422)，但没有 HTTP 请求就不会自动变成网络响应。模型输出错误可作为 ValueError 等继续向调用方传播，调用方负责处理。
- 单段工具的额外消息是 `Timestamps must be finite numbers with 0 <= start < end`、`Segment must be 0.25-30 seconds`、`Segment is outside the available audio`。其媒体超时为 45 秒，异常同样清理提取临时文件。
- 不完整媒体的容器头可能仍声明长时长。保留边界拒绝并换成完整输入，不补静音、不跳过片段；[完整验证报告](../reports/predict-multi-verification-2026-11-02.md)保留了这个实际案例及重新下载后的成功记录。

## Reading error evidence / 从验证找证据

README 的[统一验证表](../README.zh-CN.md#验证)汇总两个接口的测试代码和报告；`tests/test_predict_multi.py` 的拒绝用例使用假模型检查失败前是否调用推理。原始模型分数和 XML 标注不能用来替代人工正确答案。
