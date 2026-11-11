# API call flows / 两条接口调用链

[README](../README.md) · [中文 README](../README.zh-CN.md) · [集中报错](api-errors.md) · [逐函数索引](function-index.zh-CN.md)

源码入口保持 [app.py](../app.py)。下列每个自定义调用均可顺着索引查看真实签名、参数、返回值、调用方和下游。箭头表示调用/数据流；库和框架的调度单独标出。

## Shared startup / 共同启动

Uvicorn `app:app` → FastAPI lifespan → [lifespan](function-index.zh-CN.md#app-lifespan) → [executable](function-index.zh-CN.md#app-executable) 查两个媒体工具 → 创建 gate/线程锁 → AutoModel 在 CPU 加载一次 → 等请求。GET [health](function-index.zh-CN.md#app-health) 只报告状态。两个预测接口共用状态；普通导入模块不触发 lifespan。

<a id="post-predict"></a>
## POST /predict

1. [BodyLimitMiddleware.__call__](function-index.zh-CN.md#app-bodylimitmiddleware-call) 包装 ASGI 消息读取；内部 `limited_receive()` 累计真实字节，使用 26 MiB 上限。
2. [predict(request)](function-index.zh-CN.md#app-predict) 取得共享 gate → 表单限一个 `file` → 检查媒体后缀 → 请求目录 `.tmp/ser-*` → 写入媒体（最多 25 MiB）。
3. `run_in_threadpool` → [convert_and_predict(state, source, destination, filename)](function-index.zh-CN.md#app-convert-and-predict) → FFprobe 音轨检查 → FFmpeg 解码到 mono/16 kHz/PCM16 WAV（最多 31 秒，工具超时 20/45 秒）。
4. wave 读取真实帧数和 PCM，检查完整音频在 0.25–30 秒，转换为 NumPy float32。
5. [predict_samples](function-index.zh-CN.md#app-predict-samples) → `state.lock` → 已加载模型 `generate()` → 检查九项标签/分数 → [english_label](function-index.zh-CN.md#app-english-label) → 按实际标签顺序取最高分 → 返回 `Prediction`。
6. 结果回到路由 → 请求目录清理、表单关闭、gate 释放 → FastAPI 将 Prediction 转为 JSON。错误由工作函数转换为明确 HTTP 状态，见[错误表](api-errors.md)。

Detailed beginner walkthrough: [01 单文件学习](01-single-file-api-learning.zh-CN.md)。实际 HTTP 验证入口是 [scripts/verify_predict_http.py](../scripts/verify_predict_http.py)，通过 `python -m scripts.verify_predict_http` 启动客户端。

<a id="post-predict-multi"></a>
## POST /predict_multi

1. 同一个 [BodyLimitMiddleware](function-index.zh-CN.md#app-bodylimitmiddleware-call)，本路径使用 131 MiB 上限。
2. [predict_multi(request)](function-index.zh-CN.md#app-predict-multi) 取得同一个 gate → 表单检查恰好两个文件字段 `file`/`xml` → 独立 `.tmp/ser-multi-*` 目录 → [save_multi_upload](function-index.zh-CN.md#app-save-multi-upload) 分别检查 128/2 MiB → XML bytes。
3. `run_in_threadpool` → [predict_transcript(state, source, transcript, destination)](function-index.zh-CN.md#app-predict-transcript) → [parse_transcript(data)](function-index.zh-CN.md#app-parse-transcript)。Expat 的内部 `forbidden/start/end` 回调拒绝 DTD/实体、限制深度，再建立 ElementTree；检查实际 AudioDoc/SegmentList/SpeechSegment 结构和所有 stime/dur，算出 `end = stime + dur` 及采样索引列表。
4. FFmpeg **只解码一次**完整音频为 mono/16 kHz/PCM16；本路径不调用 FFprobe、不逐段调用 `predict_segment()`。检查格式、1800 秒和输出大小限制。
5. 第一轮 `segments` 循环检查**全部**索引是否在实际帧数内；任何段非法，模型调用次数保持 0。文档顺序不必按时间排列。
6. 第二轮按 XML 原顺序：`wav.setpos(first)` → `readframes(last-first)` → 检查字节数 → float32 → 共用 [predict_samples](function-index.zh-CN.md#app-predict-samples) 和 [english_label](function-index.zh-CN.md#app-english-label) → `element.set("emotion", result.emotion)`。每段调用一次共享模型，保留原 score、Word、图像/声音描述及其他 XML 语义内容。
7. 全段成功后 `ET.tostring(..., encoding="utf-8")` 正确转义属性（包括 `<unk>`），检查 16 MiB 返回上限 → XML bytes 回到路由 → 先清理请求目录，再用内存 Response 返回 `application/xml` 附件。
8. 任一异常只返回 JSON 错误，不返回部分 XML；退出表单、临时目录和 gate。解码子进程有 120 秒超时，但推理、排队和整请求没有独立超时。见[错误表](api-errors.md)。

Detailed walkthrough and a segment example: [02 分段 XML 学习](02-segment-xml-api-learning.zh-CN.md)。成功 65 段验收、完整输入哈希及旧失败处理见[保留报告](../reports/predict-multi-verification-2026-11-02.md)，不是分类准确率评估。

## Direct segment helper / Python 单段调用

[predict_segment(state, source, start, end, filename=None)](function-index.zh-CN.md#app-predict-segment) → [extract_audio_segment](function-index.zh-CN.md#app-extract-audio-segment) 上下文（每次独立 FFmpeg 提取）→ 读 WAV 为 float32 → [predict_samples](function-index.zh-CN.md#app-predict-samples) → Prediction；离开上下文删除段文件。

这不是 HTTP 路由，不自动取得请求 gate，也不解析 XML。直接异步调用时应交给线程池。它复用模型/锁，但每次从媒体开头解码，不能当成多段端点的一次解码策略。其参数 end 已是结束秒数，不能把 XML dur 直接当 end。

## Verification routes / 如何核对上述流程

- [tests/test_audio_segments.py](../tests/test_audio_segments.py) 测媒体和单段；[tests/test_predict_multi.py](../tests/test_predict_multi.py) 测真实 FFmpeg 配合假模型，检查一次解码、65 次假预测、XML 保留和失败清理。
- [scripts/verify_predict_http.py](../scripts/verify_predict_http.py) 是对已启动 `/predict` 的 HTTP 客户端；其 `main.convert()` 在客户端生成测试媒体，与服务器解码次数不是同一计数。
- [README 验证汇总](../README.zh-CN.md#验证)区分生成媒体测试、真实模型功能验收与尚未做的准确率评估，链接原始报告，不重写原始分数或结果。
