# Environment and model startup

[API entry points](../README.md)

## Environment and startup

Use a Python 3.10 environment with compatible PyTorch, torchaudio, FunASR and ModelScope installations. The supplied `requirements.txt` contains API additions only. `environment/pip-snapshot.txt` records the original Windows environment and is not a portable lockfile or a clean-install guarantee.

```powershell
conda activate emotion2vec
python -m pip install -r requirements.txt
```

Install FFmpeg and FFprobe in this environment or make them available on PATH. The original environment used FFmpeg 6.1.1. Run from this repository root:

```powershell
python -m uvicorn app:app --host 127.0.0.1 --port 8000 --workers 1
```

Wait for `Application startup complete`. Keep one worker and omit `--reload` to avoid extra model loads. Stop with Ctrl+C. The service searches the environment's `Library/bin` first, then PATH.

## Model and processing

The model loads once per process at startup with `hub="ms"`, `device="cpu"`, and `disable_update=True`. First use downloads official weights; cached startup may still contact the hub. Fully offline startup has not been verified. The default model revision is used, not an immutable pinned revision.

Recorded `model.pt` SHA256: `327e861049c7105a3f8589edfd16543a7cdc0c1926f1b64de975d98e0650cdd3`. Loading emitted missing `AUDIO.decoder` key warnings; subsequent classification requests succeeded.

For `/predict`, FFprobe checks the first audio track. FFmpeg converts it to mono 16 kHz PCM16 WAV, then the service passes float32 NumPy samples to the reused model. `/predict_multi` directly decodes the first audio track once with FFmpeg and checks the actual WAV sample count before predicting any segment; it does not run FFprobe for each request. MP4 video is not analyzed. A shared semaphore serializes prediction request processing and a lock protects inference; torch uses at most four CPU threads. Inference uses `granularity="utterance", extract_embedding=False`.
