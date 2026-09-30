"""Host-voice trainer: one command from the user's own game files to a voice model the pack
builder uses. Nothing from the game ships with the tool - every user runs this on their copy.

    tools/clone_venv/Scripts/python.exe -m voice_trainer.run --disc "<extracted game folder>" \
        --work "<scratch dir, ~3 GB>" [--pack <decrypted DLC .DAT> ...] [--name buzz_host] \
        [--preset standard|best]

Presets (measured on an RTX 3060, English host, 24 held-out questions):
  standard  s3gen 1500 + t3 500 steps, ~1 h in total   speaker similarity 0.964, word errors 13.5%
  best      s3gen 4000 + t3 1000 steps, ~1 h 40 min    speaker similarity 0.959, word errors 14.9%
  (untrained base model: 0.886 / 13.9%.) Fewer than 500 t3 steps adds mispronunciations.

Steps (each resumable; finished steps are skipped):
  1 corpus    decode every host line (disc questions + commentary + DLC) with its text
  2 features  S3 tokens / mels / speaker embeddings (GPU), speaker filter vs the question readings
  3 s3gen     fine-tune the voice (timbre)            -> <work>/models/s3gen_flow.pt
  4 t3        LoRA fine-tune the delivery (cadence)   -> <work>/models/t3_lora/
  5 export    voice_models/<name>/ = weights + reference.wav (10 s of real host speech)
  6 evaluate  base vs trained on held-out questions (speaker similarity, word error rate)
Use it in a pack: "voice": {"engine": "clone:voice_models/<name>/reference.wav",
                            "clone": {"model": "voice_models/<name>"}}
"""
import argparse
import glob
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
PRESETS = {"standard": (1500, 500), "best": (4000, 1000)}     # (s3gen steps, t3 steps)


def step(name, args):
    print("\n=== %s" % name, flush=True)
    subprocess.run([PY, "-m", "voice_trainer." + args[0]] + args[1:], cwd=HERE, check=True)


def export(work, name):
    import numpy as np
    import soundfile as sf
    sys.path.insert(0, HERE)
    from voice_trainer.data import load_items
    out = os.path.join(HERE, "voice_models", name)
    os.makedirs(out, exist_ok=True)
    shutil.copy(os.path.join(work, "models", "s3gen_flow.pt"), out)
    if os.path.isdir(os.path.join(out, "t3_lora")):
        shutil.rmtree(os.path.join(out, "t3_lora"))
    shutil.copytree(os.path.join(work, "models", "t3_lora"), os.path.join(out, "t3_lora"))
    # reference: two typical 4.5-6 s question readings from the training set, 0.25 s apart
    train, _ = load_items(work, need_text=True)
    picks = [it for it in train if it["kind"] == "question" and 4.5 <= it["dur"] <= 6.0][:2]
    parts = []
    for it in picks:
        x, sr = sf.read(os.path.join(work, "audio", it["id"] + ".flac"), dtype="float32")
        parts += [x, np.zeros(int(0.25 * sr), np.float32)]
    sf.write(os.path.join(out, "reference.wav"), np.concatenate(parts[:-1]), sr)
    json.dump({"reference_clips": [(it["id"], it["raw_text"]) for it in picks], "work": work},
              open(os.path.join(out, "info.json"), "w"), indent=1)
    print("exported", out)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--disc", required=True)
    ap.add_argument("--work", required=True)
    ap.add_argument("--pack", action="append", default=[])
    ap.add_argument("--question-pak", default=None)
    ap.add_argument("--name", default="buzz_host")
    ap.add_argument("--preset", choices=sorted(PRESETS), default="standard")
    ap.add_argument("--s3gen-steps", type=int, default=None, help="override the preset")
    ap.add_argument("--t3-steps", type=int, default=None, help="override the preset")
    a = ap.parse_args()
    a.s3gen_steps = a.s3gen_steps or PRESETS[a.preset][0]
    a.t3_steps = a.t3_steps or PRESETS[a.preset][1]
    w = a.work
    if not os.path.exists(os.path.join(w, "manifest.jsonl")):
        args = ["corpus", "--disc", a.disc, "--work", w] + sum([["--pack", p] for p in a.pack], [])
        step("1 corpus", args + (["--question-pak", a.question_pak] if a.question_pak else []))
    if not os.path.exists(os.path.join(w, "speakers.json")):
        step("2 features", ["features", "--work", w])
    if not os.path.exists(os.path.join(w, "models", "s3gen_flow.pt")):
        step("3 s3gen", ["train_s3gen", "--work", w, "--steps", str(a.s3gen_steps)])
    if not glob.glob(os.path.join(w, "models", "t3_lora", "adapter_model.*")):
        step("4 t3", ["train_t3", "--work", w, "--steps", str(a.t3_steps)])
    out = export(w, a.name)
    ref = os.path.join(out, "reference.wav")
    step("6 evaluate (base)", ["evaluate", "--work", w, "--ref", ref, "--label", "base"])
    step("6 evaluate (trained)", ["evaluate", "--work", w, "--ref", ref, "--model", out, "--label", "trained"])
