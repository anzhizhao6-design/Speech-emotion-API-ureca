"""Local, single-worker emotion2vec HTTP service.
本地单 worker 的 emotion2vec HTTP 服务。
"""
import asyncio
from contextlib import asynccontextmanager, contextmanager
import json
import logging
import math
import os
from numbers import Real
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import wave

import numpy as np
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.responses import JSONResponse

# Configuration: bound uploads and decoded audio to keep local CPU work manageable.
# 限制文件大小和音频时长；请求体上限还为文件名、分隔符等上传信息留出空间。
MODEL = "iic/emotion2vec_plus_seed"
MAX_FILE_BYTES = 25 * 1024 * 1024
MAX_BODY_BYTES = MAX_FILE_BYTES + 1024 * 1024
MAX_SECONDS = 30
MIN_SECONDS = 0.25
TEMP_ROOT = Path(__file__).parent / ".tmp"
log = logging.getLogger("ser")


def english_label(label: str) -> str:
    """Remove the language prefix while preserving the model's class names."""
    value = label.rsplit("/", 1)[-1].strip()
    allowed = {"angry", "disgusted", "fearful", "happy", "neutral",
               "other", "sad", "surprised", "<unk>"}
    if value not in allowed:
        raise ValueError(f"Unexpected emotion label: {label!r}")
    return value


def executable(name):
    """Find a media tool in this Python environment, then try PATH.
    返回 ffmpeg 或 ffprobe 的程序路径，优先使用当前 Python 环境中的版本。
    """
    local = Path(sys.prefix) / "Library" / "bin" / (name + ".exe")
    found = str(local) if local.is_file() else shutil.which(name)
    if not found:
        raise RuntimeError(f"{name} not found in this Python environment")
    return found


@asynccontextmanager
async def lifespan(app):
    """Load once at startup so requests reuse the same CPU model.
    Uvicorn 启动服务时执行：把工具路径和模型存入 app.state，供各请求共享。
    yield 前是启动准备；yield 后在服务关闭时执行，不会每次请求都重新加载模型。
    """
    app.state.ffmpeg = executable("ffmpeg")
    app.state.ffprobe = executable("ffprobe")
    os.environ["PATH"] = str(Path(app.state.ffmpeg).parent) + os.pathsep + os.environ.get("PATH", "")
    from funasr import AutoModel
    import torch
    torch.set_num_threads(max(1, min(4, os.cpu_count() or 1)))
    TEMP_ROOT.mkdir(exist_ok=True)
    app.state.lock = threading.Lock()
    app.state.gate = asyncio.Semaphore(1)
    app.state.model = AutoModel(model=MODEL, hub="ms", device="cpu",
                                disable_update=True)
    yield
    app.state.model = None


app = FastAPI(title="Local SER API", lifespan=lifespan)


class Prediction(BaseModel):
    """Define the response fields FastAPI validates and serializes.
    声明返回数据的字段与类型；FastAPI 检查这些数据后将它们转换为 JSON 响应。
    """
    filename: str
    model: str
    emotion: str
    score: float
    labels: list[str]
    scores: list[float]


class BodyTooLarge(Exception):
    pass


# Request body guard: include multipart overhead, not just the uploaded file.
# 这层代码包装请求读取过程，在上传内容被解析为文件字段时累计接收大小。
class BodyLimitMiddleware:
    """Bound the body before multipart parsing (including chunked uploads).
    scope 保存请求类型等信息；receive 读取下一块内容，send 发送响应。
    将 receive 换成计数版本，让文件解析器每次读取时都经过大小检查。
    """
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        total = 0

        async def limited_receive():
            # Count actual bytes so chunked uploads cannot bypass the limit.
            # total 属于外层函数；每读一块就累加，即使客户端没有声明总大小也能检查。
            nonlocal total
            message = await receive()
            total += len(message.get("body", b""))
            if total > MAX_BODY_BYTES:
                raise BodyTooLarge()
            return message

        try:
            await self.app(scope, limited_receive, send)
        except BodyTooLarge:
            await JSONResponse({"detail": "Request body exceeds 26 MiB"}, 413)(scope, receive, send)


app.add_middleware(BodyLimitMiddleware)


def predict_samples(state, samples, filename):
    """Run the shared model under its lock and validate aligned English output."""
    # Passing decoded samples avoids torchaudio/torchcodec file-decoder dependencies.
    # 传入已解码样本，避免依赖 torchaudio/torchcodec 的文件解码器。
    # The thread lock prevents simultaneous calls into the shared model.
    # 锁使同一进程内一次只有一个线程进入此模型调用；output 保存模型返回的结果列表。
    with state.lock:
        output = state.model.generate(input=samples, fs=16000,
                                      granularity="utterance", extract_embedding=False)
    # Validate the model contract before exposing scores as JSON.
    # 单文件应只有一个结果；取其中的 labels/scores，并检查九类、数值有效且在 0 到 1 之间。
    if not isinstance(output, list) or len(output) != 1:
        raise ValueError("Expected one model result")
    labels = list(output[0]["labels"])
    scores = [float(s) for s in output[0]["scores"]]
    if (len(labels) != 9 or len(scores) != len(labels)
            or not all(isinstance(label, str) for label in labels)
            or not all(math.isfinite(s) and 0 <= s <= 1 for s in scores)):
        raise ValueError("Invalid nine-class model output")
    # Expose English labels in the same order as the unchanged scores.
    labels = [english_label(label) for label in labels]
    # Use the returned label order rather than assuming a fixed class mapping.
    # 例如 scores=[0.2, 0.8] 时 best=1，最高分对应 labels[1]，无需预设标签顺序。
    best = max(range(len(scores)), key=scores.__getitem__)
    return Prediction(filename=filename, model=MODEL, emotion=labels[best],
                      score=scores[best], labels=labels, scores=scores)


def convert_and_predict(state, source, destination, filename):
    """Normalize media before inference so every format follows the same path.
    state 是 app.state，保存共享模型、工具路径和锁；filename 是展示用文件名。
    source 是已保存的上传文件路径，destination 是待生成的标准 WAV 路径。
    """
    try:
        # Media inspection: reject invalid containers and missing audio before decoding.
        # probe 保存 ffprobe 的执行结果；返回码非零表示失败，stdout 中的 JSON 描述音轨。
        probe = subprocess.run(
            [state.ffprobe, "-v", "error", "-protocol_whitelist", "file,pipe", "-select_streams", "a:0",
             "-show_entries", "stream=index", "-of", "json", str(source)],
            capture_output=True, text=True, timeout=20, encoding="utf-8", errors="replace")
        if probe.returncode:
            raise HTTPException(422, "Invalid or damaged media file")
        if not json.loads(probe.stdout).get("streams"):
            raise HTTPException(422, "File contains no audio track")
        # Decode one extra second to detect overlong audio without decoding the whole file.
        # 读取第一条音轨，转成单声道 16 kHz WAV；最多解码 31 秒以判断是否超过 30 秒。
        result = subprocess.run(
            [state.ffmpeg, "-nostdin", "-v", "error", "-xerror", "-y",
             "-protocol_whitelist", "file,pipe", "-i", str(source),
             "-map", "0:a:0", "-vn", "-ac", "1", "-ar", "16000",
             "-t", str(MAX_SECONDS + 1), "-c:a", "pcm_s16le", str(destination)],
            capture_output=True, timeout=45)
        if result.returncode:
            raise HTTPException(422, "Audio decoding failed")
        # The converted PCM16 WAV gives us a known sample layout and amplitude scale.
        # samples 是一维波形数组：把每两个字节读成有符号整数，再除以 32768 缩放到约 [-1, 1]。
        with wave.open(str(destination), "rb") as wav:
            duration = wav.getnframes() / wav.getframerate()
            samples = np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2").astype(np.float32) / 32768
        if duration > MAX_SECONDS:
            raise HTTPException(422, f"Audio exceeds {MAX_SECONDS} seconds")
        if duration < MIN_SECONDS:
            raise HTTPException(422, f"Audio must be at least {MIN_SECONDS} seconds")
        return predict_samples(state, samples, filename)
    except subprocess.TimeoutExpired:
        raise HTTPException(422, "Media processing timed out")
    except HTTPException:
        raise
    except Exception:
        log.exception("Prediction failed")
        raise HTTPException(500, "Prediction failed; see server log")


@contextmanager
def extract_audio_segment(state, source, start, end):
    """Yield a temporary mono/16 kHz/PCM16 WAV for [start, end) seconds.

    Times are relative to the first decoded audio sample, not video/container
    timestamps. Boundaries round up to the next 16 kHz sample. Each segment
    must be 0.25-30 seconds; the source has no upload-size or duration limit.
    The yielded path is valid only inside the context. All exits remove it.
    """
    try:
        valid = (all(not isinstance(t, bool) and isinstance(t, Real)
                     and math.isfinite(t) for t in (start, end))
                 and start >= 0 and end > start)
    except OverflowError:
        valid = False
    if not valid:
        raise HTTPException(422, "Timestamps must be finite numbers with 0 <= start < end")
    duration = end - start
    if not MIN_SECONDS <= duration <= MAX_SECONDS:
        raise HTTPException(422, f"Segment must be {MIN_SECONDS}-{MAX_SECONDS} seconds")
    first, last = math.ceil(start * 16000), math.ceil(end * 16000)
    TEMP_ROOT.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ser-segment-", dir=TEMP_ROOT) as directory:
        destination = Path(directory) / "segment.wav"
        try:
            # Decode from the beginning for accurate boundaries even in compressed
            # media. Count actual samples instead of trusting container duration.
            result = subprocess.run(
                [state.ffmpeg, "-nostdin", "-v", "error", "-xerror", "-y",
                 "-protocol_whitelist", "file,pipe", "-i", str(source),
                 "-map", "0:a:0", "-vn", "-ac", "1", "-ar", "16000",
                 "-af", f"aresample=16000,atrim=start_sample={first}:end_sample={last},asetpts=PTS-STARTPTS",
                 "-c:a", "pcm_s16le", str(destination)],
                capture_output=True, timeout=45)
            if result.returncode:
                raise HTTPException(422, "Audio decoding failed or file contains no audio track")
            with wave.open(str(destination), "rb") as wav:
                if wav.getnframes() != last - first:
                    raise HTTPException(422, "Segment is outside the available audio")
        except subprocess.TimeoutExpired:
            raise HTTPException(422, "Media processing timed out")
        yield destination


def predict_segment(state, source, start, end, filename=None):
    """Extract and classify one segment using the already-loaded app state.

    Blocking: async callers should use run_in_threadpool. No HTTP call, model
    loading, or XML parsing occurs here. Temporary files also clean up when
    inference fails.
    """
    with extract_audio_segment(state, source, start, end) as segment:
        with wave.open(str(segment), "rb") as wav:
            samples = np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2").astype(np.float32) / 32768
        return predict_samples(state, samples, filename if filename is not None else Path(source).name)


@app.get("/health")
def health():
    """Report readiness after startup without running another inference.
    启动后报告就绪状态，不额外执行推理。
    """
    return {"status": "ready", "model": MODEL, "device": "cpu"}


@app.post("/predict", response_model=Prediction, openapi_extra={
    "requestBody": {"required": True, "content": {"multipart/form-data": {
        "schema": {"type": "object", "required": ["file"], "properties": {
            "file": {"type": "string", "format": "binary"}}}}}}})
async def predict(request: Request):
    """Accept one upload and return its utterance-level emotion scores.
    浏览器或脚本向 /predict 上传文件时执行；request 保存这次 HTTP 请求及其应用引用。
    解析文件字段、保存文件并调用 convert_and_predict，最后返回 Prediction 数据。
    """
    # Allow one request into this processing block; others wait.
    # 同一进程每次只处理一个请求；其他请求在此等待，这不限制所有等待请求的数量。
    async with request.app.state.gate:
        try:
            async with request.form(max_files=1, max_fields=0) as form:
                entries = list(form.multi_items())
                if len(entries) != 1 or entries[0][0] != "file" or not isinstance(entries[0][1], UploadFile):
                    raise HTTPException(422, "Provide exactly one file in the 'file' field")
                upload = entries[0][1]
                filename = (upload.filename or "").replace("\\", "/").split("/")[-1]
                suffix = Path(filename).suffix.lower()
                if suffix not in {".wav", ".mp3", ".mp4", ".m4a"}:
                    raise HTTPException(415, "Supported file extensions: WAV, MP3, MP4, M4A")
                # The context manager removes upload and WAV files, even on handled errors.
                # 离开 with 时删除此请求目录（含上传文件与转换文件）；正常返回或抛异常都会触发，强制终止除外。
                with tempfile.TemporaryDirectory(prefix="ser-", dir=TEMP_ROOT) as directory:
                    source = Path(directory) / ("input" + suffix)
                    size = 0
                    with source.open("wb") as target:
                        while chunk := await upload.read(1024 * 1024):
                            size += len(chunk)
                            if size > MAX_FILE_BYTES:
                                raise HTTPException(413, "File exceeds 25 MiB")
                            target.write(chunk)
                    if not size:
                        raise HTTPException(422, "Empty file")
                    # Keep blocking subprocesses and inference off the async event loop.
                    # 将耗时的转换与推理交给工作线程，避免占住负责异步请求调度的线程；await 等待结果。
                    return await run_in_threadpool(convert_and_predict, request.app.state,
                                                   source, Path(directory) / "audio.wav", filename)
        except HTTPException:
            raise
