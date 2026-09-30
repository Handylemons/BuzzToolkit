"""Neural TTS backend (Kokoro-82M via kokoro-onnx). Runs inside tools/tts_venv:

    tools/tts_venv/Scripts/python.exe buzz_tts_kokoro.py jobs.json --voice bm_george --speed 1.0

jobs.json: [{"text": "...", "out": "clip.wav"}, ...]. Writes 24 kHz mono 16-bit WAVs.
British voices: bm_george, bm_lewis, bm_daniel, bm_fable (male), bf_emma, bf_isabella,
bf_alice, bf_lily (female); lang "en-gb". Model files live in tools/kokoro/.
Setup: see tools/tts_requirements.txt (pip install -r) and the kokoro-onnx model-files-v1.0 release.
"""
import argparse
import json
import os

import numpy as np
import soundfile as sf
from kokoro_onnx import Kokoro

HERE = os.path.dirname(os.path.abspath(__file__))
MODEL_DIR = os.path.join(HERE, "tools", "kokoro")

ap = argparse.ArgumentParser()
ap.add_argument("jobs")
ap.add_argument("--voice", default="bm_george")
ap.add_argument("--speed", type=float, default=1.0)
ap.add_argument("--lang", default="en-gb")
a = ap.parse_args()

tts = Kokoro(os.path.join(MODEL_DIR, "kokoro-v1.0.onnx"), os.path.join(MODEL_DIR, "voices-v1.0.bin"))
for job in json.load(open(a.jobs, encoding="utf-8")):
    samples, rate = tts.create(job["text"], voice=a.voice, speed=a.speed, lang=a.lang)
    pcm = np.clip(np.asarray(samples) * 32767, -32768, 32767).astype("<i2")
    sf.write(job["out"], pcm, rate, subtype="PCM_16")
    print(len(pcm), rate, job["out"])
