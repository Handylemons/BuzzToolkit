"""Voice-cloning TTS backend (Chatterbox, MIT licence). Runs inside tools/clone_venv (Python 3.11,
CUDA torch):

    tools/clone_venv/Scripts/python.exe buzz_tts_clone.py jobs.json --ref voice_refs/buzz_host.wav
        [--model voice_models/buzz_host]

jobs.json: [{"text": "...", "out": "clip.wav"}, ...]. Writes 24 kHz mono 16-bit WAVs in the voice
of the reference clip (~10 s of the host, built by make_host_reference.py from the user's own
game files). --model loads weights fine-tuned by voice_trainer (s3gen_flow.pt, t3_lora/) on top
of the base model. Each line uses a fixed seed so runs are repeatable on the same machine.
Setup: tools/clone_requirements.txt; base weights download from Hugging Face (ResembleAI/chatterbox).
"""
import argparse
import json
import os

import numpy as np
import soundfile as sf
import torch
from chatterbox.tts import ChatterboxTTS


ENGLISH = ("en", "", None)


def load(model_dir=None, device=None, lang=None):
    """lang: ISO language code of the pack ("en", "es", "pt", ...). Non-English packs use
    Chatterbox's multilingual model (23 languages)."""
    device = device or ("cuda" if torch.cuda.is_available() else "cpu")
    if lang not in ENGLISH:
        from chatterbox.mtl_tts import ChatterboxMultilingualTTS
        model = ChatterboxMultilingualTTS.from_pretrained(device=torch.device(device))
        model.buzz_lang = lang
        return model
    model = ChatterboxTTS.from_pretrained(device=device)
    model.buzz_lang = None
    if model_dir:
        flow = os.path.join(model_dir, "s3gen_flow.pt")
        if os.path.exists(flow):
            model.s3gen.flow.load_state_dict(torch.load(flow, map_location=device))
        lora = os.path.join(model_dir, "t3_lora")
        if os.path.isdir(lora):
            from peft import PeftModel
            model.t3.tfmr = PeftModel.from_pretrained(model.t3.tfmr, lora).merge_and_unload()
        model.t3.eval()
        model.s3gen.eval()
    return model


def generate(model, text, opts, take=0):
    torch.manual_seed(opts.get("seed", 1234) + take)
    kw = dict(exaggeration=opts.get("exaggeration", 0.5), cfg_weight=opts.get("cfg", 0.5),
              temperature=opts.get("temperature", 0.8))
    if getattr(model, "buzz_lang", None):
        wav = model.generate(text, language_id=model.buzz_lang, **kw)
    else:
        wav = model.generate(text, **kw)
    return wav.squeeze(0).detach().cpu().numpy()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("jobs")
    ap.add_argument("--ref", required=True)
    ap.add_argument("--model", default=None)
    ap.add_argument("--exaggeration", type=float, default=0.5)
    ap.add_argument("--cfg", type=float, default=0.5)
    ap.add_argument("--temperature", type=float, default=0.8)
    ap.add_argument("--seed", type=int, default=1234)
    ap.add_argument("--lang", default="en", help="ISO language code (en, es, pt, de, fr, it, ...)")
    a = ap.parse_args()
    model = load(a.model if a.lang in ENGLISH else None, lang=a.lang)
    model.prepare_conditionals(a.ref, exaggeration=a.exaggeration)
    opts = {"exaggeration": a.exaggeration, "cfg": a.cfg, "temperature": a.temperature, "seed": a.seed}
    for job in json.load(open(a.jobs, encoding="utf-8")):
        x = generate(model, job["text"], opts, job.get("take", 0))
        sf.write(job["out"], np.clip(x * 32767, -32768, 32767).astype("<i2"), model.sr, subtype="PCM_16")
        print(len(x), model.sr, job["out"], flush=True)
