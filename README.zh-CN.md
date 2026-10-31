# 本地语音情绪识别 API

[English](README.md)

本项目是 Windows CPU 服务，使用 FastAPI、Uvicorn，通过 FunASR 调用已微调的 `iic/emotion2vec_plus_seed` 模型。每次接收一个 WAV、MP3、MP4 或 M4A 文件，返回模型原生九分类分数。API 不使用 IEMOCAP，也不训练模型。

## 项目文件

| 文件 | 职责 |
| --- | --- |
| `app.py` | 启动时加载模型，检查上传文件，转换媒体，串行 CPU 推理，返回 JSON，并清理临时文件。 |
| `verify_api.py` | 通过真实 HTTP 请求测试已启动的服务。将指定语音转为测试格式，检查响应并保存结果。它不启动服务，也不测量识别准确率。 |
| `requirements.txt` | 固定版本的 API 补充依赖，不是完整环境描述。 |
| `environment/pip-snapshot.txt` | 已记录的 pip 快照，不是可移植的 Conda 锁定文件。 |
| `reports/http-functional-results.json` | 上次 18 个 POST 用例的响应。生成产物被 Git 忽略，新检出的项目中可能不存在。 |

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

FFprobe 检查第一条音轨。FFmpeg 将它转换为单声道 16 kHz PCM16 WAV，服务再将 float32 NumPy 样本交给复用的模型。MP4 画面不参与分析。信号量让请求处理串行进行，线程锁保护推理；torch CPU 线程最多四个。推理参数为 `granularity="utterance", extract_embedding=False`。

## 上传与响应

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

标签不重新排序、不改名。已记录标签：`生气/angry`、`厌恶/disgusted`、`恐惧/fearful`、`开心/happy`、`中立/neutral`、`其他/other`、`难过/sad`、`吃惊/surprised`、`<unk>`。分数是模型 softmax 输出，不是测得的准确率，也不是经过校准的正确性保证。

## 限制与错误

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

可以替换为其他真实语音路径。`--url` 可覆盖 `http://127.0.0.1:8000`。客户端覆盖生成的媒体文件，并在成功运行后写入 `reports/http-functional-results.json`。

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

历史 HTTP 测试结果位于 `reports/http-functional-results.json`，说明见 `reports/functional-verification.md`。测试脚本的新结果仍写入 `test-artifacts/results.json`。旧实验脚本、压缩包、音视频、缓存和日志未纳入此仓库。通用启动命令以英文 README 为准，本文中的 `<username>` 需按本机环境替换。`/predict_multi` 尚未实现。

## 英文标签输出

当前 API 的 `labels` 和 `emotion` 均只返回英文，例如 `吃惊/surprised` 转为 `surprised`。标签顺序和分数不变，特殊标签 `<unk>` 保留。`reports/` 中历史结果保留当时实际返回的中英标签，不能当作此修改后的新测试结果。
