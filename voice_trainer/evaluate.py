"""Step 5 of the host-voice trainer: measure how close generated speech is to the real host.

    tools/clone_venv/Scripts/python.exe -m voice_trainer.evaluate --work <dir> --ref <ref.wav>
        [--model <dir>] [--label trained] [--n 12]

Generates held-out question texts (validation clips the trainer never saw) and scores them with
an INDEPENDENT speaker-verification model (microsoft/wavlm-base-plus-sv, not part of Chatterbox):
cosine similarity of each generated line to the real host's clips. Also reports the same score
for real host clips against each other (the ceiling) and Whisper word error rate.
Writes <work>/eval/<label>/*.wav for listening and prints a summary line.
"""
import argparse
import json
import os
import sys

import librosa
import numpy as np
import soundfile as sf
import torch

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import buzz_tts_clone  # noqa: E402
from voice_trainer.data import load_items  # noqa: E402


class SpeakerScorer:
    def __init__(self, dev="cuda"):
        from transformers import AutoFeatureExtractor, WavLMForXVector
        self.fe = AutoFeatureExtractor.from_pretrained("microsoft/wavlm-base-plus-sv")
        self.m = WavLMForXVector.from_pretrained("microsoft/wavlm-base-plus-sv").to(dev).eval()
        self.dev = dev

    @torch.no_grad()
    def embed(self, wav16):
        x = self.fe([wav16], sampling_rate=16000, return_tensors="pt", padding=True).to(self.dev)
        e = self.m(**x).embeddings[0]
        return e / e.norm()


def main(a):
    _, val = load_items(a.work, need_text=True)
    val = val[:a.n]
    audio = lambda i: librosa.load(os.path.join(a.work, "audio", i + ".flac"), sr=16000)[0]
    sc = SpeakerScorer()
    real = [sc.embed(audio(it["id"])) for it in val]
    centroid = torch.stack(real).mean(0)
    centroid = centroid / centroid.norm()
    ceiling = np.mean([(r @ centroid).item() for r in real])

    model = buzz_tts_clone.load(a.model)
    model.prepare_conditionals(a.ref, exaggeration=a.exaggeration)
    opts = {"exaggeration": a.exaggeration, "cfg": a.cfg, "temperature": 0.8, "seed": 1234}
    out = os.path.join(a.work, "eval", a.label)
    os.makedirs(out, exist_ok=True)
    import whisper
    asr = whisper.load_model("small.en")
    from buzz_tts_verify import wer  # noqa: E402  (same scoring as the pipeline check)
    sims, wers = [], []
    for it in val:
        x = buzz_tts_clone.generate(model, it["raw_text"], opts)
        sf.write(os.path.join(out, it["id"] + ".wav"), x, model.sr)
        x16 = librosa.resample(x, orig_sr=model.sr, target_sr=16000)
        sims.append((sc.embed(x16) @ centroid).item())
        heard = asr.transcribe(x16.astype(np.float32), language="en", fp16=False, temperature=0.0)["text"]
        wers.append(wer(it["raw_text"], heard))
    res = {"label": a.label, "speaker_sim": round(float(np.mean(sims)), 4), "real_ceiling": round(float(ceiling), 4),
           "wer": round(float(np.mean(wers)), 4), "n": len(val)}
    json.dump(res, open(os.path.join(out, "result.json"), "w"), indent=1)
    print(json.dumps(res), flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True)
    ap.add_argument("--ref", required=True)
    ap.add_argument("--model", default=None)
    ap.add_argument("--label", default="base")
    ap.add_argument("--n", type=int, default=12)
    ap.add_argument("--exaggeration", type=float, default=0.5)
    ap.add_argument("--cfg", type=float, default=0.5)
    main(ap.parse_args())
