# 环境与模型启动

[返回接口入口](../README.zh-CN.md)

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
Set-Location 'C:\Users\<username>\Desktop\uni\ureca\Speech-emotion-API-ureca'
& 'C:\Users\<username>\miniconda3\envs\emotion2vec\python.exe' -m uvicorn app:app --host 127.0.0.1 --port 8000 --workers 1
```

等待 `Application startup complete`。保持一个 worker，不加 `--reload`，避免额外加载模型。Ctrl+C 停止。其他开发者需要替换这些本机路径。

服务优先查找所选环境 `Library\bin` 下的 FFmpeg/FFprobe，找不到时查 PATH，并将 FFmpeg 目录加入服务进程的 PATH。使用上述命令无需修改系统 PATH 或激活环境。


## 模型与处理流程

模型在每个进程启动时加载一次，配置为 `hub="ms"`、`device="cpu"`、`disable_update=True`。首次使用下载官方权重；已有缓存时仍可能访问仓库。尚未验证完全离线启动。代码使用默认模型版本，没有固定不可变的模型修订。

已记录缓存：`C:\Users\<username>\.cache\modelscope\models\iic--emotion2vec_plus_seed\snapshots\master`。

已记录 `model.pt` SHA256：`327e861049c7105a3f8589edfd16543a7cdc0c1926f1b64de975d98e0650cdd3`。加载时出现过缺少 `AUDIO.decoder` 键的警告，随后分类请求成功。

`/predict` 先用 FFprobe 检查第一条音轨，再用 FFmpeg 转为单声道 16 kHz PCM16 WAV。`/predict_multi` 不在每次请求中调用 FFprobe，而是直接用 FFmpeg 一次性解码第一条音轨，随后按实际 WAV 采样数检查全部片段。两条流程都将 float32 NumPy 波形交给共享模型。MP4 画面不参与分析。两个预测路由共用信号量串行处理请求，线程锁保护推理；阻塞解码和推理交给线程池，torch CPU 计算线程最多四个。推理参数为 `granularity="utterance", extract_embedding=False`。
