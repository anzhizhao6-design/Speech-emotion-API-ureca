"""HTTP functional checks, not emotion classification accuracy evaluation.
HTTP 接口功能检查，不是情绪分类准确率评估。

Run with the emotion2vec environment after starting Uvicorn.
先启动 Uvicorn，再使用 emotion2vec 环境运行本脚本。
"""
import argparse
import io
import json
from pathlib import Path
import subprocess
import wave

import httpx

from app import executable, TEMP_ROOT


def main():
    """Prepare media and check the running API without judging emotion correctness.
    args.speech 是输入语音路径，args.url 是服务地址；folder 保存生成的文件和测试结果。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("speech", type=Path, help="A real speech recording, not synthetic audio")
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    folder = Path("test-artifacts")
    folder.mkdir(exist_ok=True)
    ffmpeg = executable("ffmpeg")

    def convert(arguments):
        subprocess.run([ffmpeg, "-nostdin", "-v", "error", "-y", *arguments], check=True)

    # Prepare formats from the same real speech so each exercises the decoding path.
    # 用同一段真实语音生成 WAV/MP3/M4A/MP4，避免把改扩展名当作格式转换；另生成无音轨 MP4 测试拒绝情况。
    convert(["-i", str(args.speech), "-t", "8", "-ac", "2", "-ar", "44100", str(folder / "speech.wav")])
    convert(["-i", str(folder / "speech.wav"), str(folder / "speech.mp3")])
    convert(["-i", str(folder / "speech.wav"), "-c:a", "aac", str(folder / "speech.m4a")])
    convert(["-f", "lavfi", "-i", "color=c=black:s=160x120:r=10", "-i", str(folder / "speech.wav"),
             "-c:v", "mpeg4", "-c:a", "aac", "-shortest", str(folder / "speech.mp4")])
    convert(["-f", "lavfi", "-i", "color=c=black:s=160x120:r=10", "-t", "1", "-an",
             "-c:v", "mpeg4", str(folder / "no_audio.mp4")])
    # Exercise the running service over HTTP, including its upload schema.
    # client 向已启动的服务发请求；results 收集各用例响应。先检查服务、文档和上传格式描述。
    results = []
    with httpx.Client(base_url=args.url, timeout=180, trust_env=False) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/docs").status_code == 200
        schema = client.get("/openapi.json").json()
        assert "multipart/form-data" in schema["paths"]["/predict"]["post"]["requestBody"]["content"]

        def check(name, files, expected):
            """Check response consistency without claiming the emotion is correct.
            files 是待上传的文件字段，expected 是预期 HTTP 状态码（例如 200 成功、422 输入不合规）。
            response 保存 HTTP 响应，data 是从 JSON 解析出的字典；不判断情绪预测是否正确。
            """
            response = client.post("/predict", files=files)
            data = response.json()
            results.append({"case": name, "status": response.status_code, "response": data})
            print(name, response.status_code, data.get("emotion", data.get("detail")), flush=True)
            assert response.status_code == expected, data
            if expected == 200:
                # Check label/score alignment, not a ground-truth emotion label.
                # 例如分数最高位置是 2，就检查 emotion 是否等于 labels[2]，不与人工情绪答案比较。
                assert len(data["labels"]) == len(data["scores"]) == 9
                best = max(range(9), key=data["scores"].__getitem__)
                assert data["emotion"] == data["labels"][best]
                assert data["score"] == data["scores"][best]
                assert abs(sum(data["scores"]) - 1) < 1e-5

        # Accepted formats must preserve the nine-class response contract.
        # 用真实语音请求四种格式，确认都返回包含九个标签和对应分数的结果。
        for ext in ["wav", "mp3", "mp4", "m4a"]:
            path = folder / ("speech." + ext)
            check(ext, {"file": (path.name, path.read_bytes())}, 200)
        # Rejected inputs should produce explicit client errors, not predictions.
        # 故意发送损坏文件、空文件等，检查服务是否给出预期错误；大写后缀则应正常接收。
        check("damaged", {"file": ("broken.wav", b"not valid media")}, 422)
        check("damaged_m4a", {"file": ("broken.m4a", b"not valid media")}, 422)
        check("uppercase_m4a", {"file": ("speech.M4A", (folder / "speech.m4a").read_bytes())}, 200)
        check("no_audio", {"file": ("no_audio.mp4", (folder / "no_audio.mp4").read_bytes())}, 422)
        check("empty", {"file": ("empty.wav", b"")}, 422)
        check("unsupported", {"file": ("speech.txt", b"text")}, 415)
        check("multiple", [("file", ("a.wav", b"a")), ("file", ("b.wav", b"b"))], 400)
        check("file_limit", {"file": ("large.wav", b"x" * (25 * 1024 * 1024 + 1))}, 413)
        check("body_limit", {"file": ("large.wav", b"x" * (27 * 1024 * 1024))}, 413)
        for seconds, name in [(0.1, "too_short"), (31, "too_long")]:
            buffer = io.BytesIO()
            with wave.open(buffer, "wb") as wav:
                wav.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
                wav.writeframes(b"\0\0" * int(seconds * 16000))
            # Silence is used only to test duration rejection, never classification quality.
            # 静音仅用于验证时长限制，不用于评价分类效果。
            check(name, {"file": (name + ".wav", buffer.getvalue())}, 422)
        # Repeated requests check reuse; the directory check catches leftover app files.
        # 顺序发送三次请求，检查服务能否连续响应；再确认应用临时目录为空。这不是并发压力测试。
        for i in range(3):
            check(f"consecutive_{i+1}", {"file": ("speech.wav", (folder / "speech.wav").read_bytes())}, 200)
        assert not list(TEMP_ROOT.iterdir()), "Temporary files leaked"
    # Save actual responses for review only after every check has passed.
    # 所有检查通过后，将 results 转成 JSON 保存；ensure_ascii=False 让中文标签保持可读。
    (folder / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print("All HTTP checks passed; temporary directory empty.")


if __name__ == "__main__":
    main()
