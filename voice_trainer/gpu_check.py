"""Quick check that this PC's GPU can train the host voice, before a multi-hour run:
    <venv>/Scripts/python.exe -m voice_trainer.gpu_check [--cpu]
Runs, on dummy data (nothing is saved), each kind of GPU work the trainer does:
  1 features   speech tokenizer + speaker encoders on 4 s of audio (step 2)
  2 voice      5 training steps of the S3Gen flow (step 3)
  3 delivery   5 LoRA training steps of T3 (step 4)
and checks every loss is a real number. On AMD, a failure is retried without MIOpen kernels
(the run.py --no-miopen option). --cpu times fp32 against bf16 on the processor instead."""
import os
import sys
import time

import torch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from voice_trainer.data import autocast, cpu_has_bf16, describe, pick_device  # noqa: E402


def sync(dev):
    if dev == "cuda":
        torch.cuda.synchronize()


def check(model, dev, steps=5):
    """-> dict of timings; raises on any failure or non-finite loss."""
    import numpy as np
    from peft import LoraConfig, get_peft_model
    from voice_trainer.features import extract
    from voice_trainer.train_t3 import step_loss
    r = {}
    t = time.time()
    rng = np.random.default_rng(0)
    wav = (0.1 * np.sin(np.arange(96000) * 0.05) + 0.01 * rng.standard_normal(96000)).astype(np.float32)
    item = extract(model, wav, None)
    sync(dev)
    r["features"] = time.time() - t
    flow = model.s3gen.flow
    flow.train()
    opt = torch.optim.AdamW([p for p in flow.parameters() if p.requires_grad], lr=1e-6)
    T = 150                                                     # 6 s of speech tokens
    batch = {"speech_token": torch.randint(0, 6561, (2, T)), "speech_token_len": torch.tensor([T, T]),
             "speech_feat": torch.randn(2, 80, 2 * T), "speech_feat_len": torch.tensor([2 * T, 2 * T]),
             "embedding": torch.randn(2, 192)}
    t = time.time()
    for i in range(steps):
        with autocast(dev):
            loss = flow.compute_loss(batch, dev)["loss"]
        if not torch.isfinite(loss):
            raise RuntimeError("voice training loss is not a number at step %d" % i)
        opt.zero_grad(set_to_none=True)
        loss.backward()
        opt.step()
    sync(dev)
    r["voice"] = steps / (time.time() - t)
    flow.eval()
    del opt
    t3 = model.t3
    for p in t3.parameters():
        p.requires_grad_(False)
    t3.tfmr = get_peft_model(t3.tfmr, LoraConfig(r=32, lora_alpha=64, target_modules=["q_proj", "k_proj", "v_proj", "o_proj"]))
    t3.train()
    params = [p for p in t3.parameters() if p.requires_grad]
    opt = torch.optim.AdamW(params, lr=1e-6)
    import random
    items = [{"ve": item["ve"], "tokens": torch.randint(0, 6561, (100,)), "text": torch.randint(1, 600, (40,))}
             for _ in range(2)]
    t = time.time()
    for i in range(steps):
        with autocast(dev):
            loss = step_loss(t3, items, items, random.Random(i), dev, drop_text=0)
        if not torch.isfinite(loss):
            raise RuntimeError("delivery training loss is not a number at step %d" % i)
        opt.zero_grad(set_to_none=True)
        loss.backward()
        opt.step()
    sync(dev)
    r["delivery"] = steps / (time.time() - t)
    return r


def load(dev):
    from chatterbox.tts import ChatterboxTTS
    return ChatterboxTTS.from_pretrained(device=dev)


def gpu():
    print("torch %s | ROCm %s | CUDA %s" % (torch.__version__, getattr(torch.version, "hip", None), torch.version.cuda))
    dev = pick_device()
    print(describe(dev), flush=True)
    if dev != "cuda":
        print("FAIL: PyTorch sees no working GPU here - the trainer would use the (slow) CPU")
        return 1
    try:
        r = check(load(dev), dev)
    except Exception as e:                                          # noqa: BLE001
        if not torch.version.hip:
            print("FAIL: %s: %s" % (type(e).__name__, e))
            return 1
        print("failed with MIOpen kernels (%s: %s) - retrying without them" % (type(e).__name__, str(e).splitlines()[0]),
              flush=True)
        torch.backends.cudnn.enabled = False
        torch.cuda.empty_cache()
        try:
            r = check(load(dev), dev)
        except Exception as e2:                                     # noqa: BLE001
            print("FAIL: %s: %s" % (type(e2).__name__, e2))
            return 1
        print("PASS only WITHOUT MIOpen: add --no-miopen to every voice_trainer.run command")
    print("PASS: features %.1f s, voice %.2f steps/s, delivery %.2f steps/s (an RTX 3060 here: 0.7 and 3.3)"
          % (r["features"], r["voice"], r["delivery"]))
    print("Next: voice_trainer.run ... --preview  (a short real run with samples and a time estimate)")
    return 0


def cpu():
    os.environ["BUZZ_TRAIN_DEVICE"] = "cpu"
    print("torch %s | CPU capability %s | native bf16 %s" % (torch.__version__, torch.backends.cpu.get_cpu_capability(),
                                                            cpu_has_bf16()), flush=True)
    if not cpu_has_bf16():
        print("This processor has no native bf16, so the trainer always uses fp32 on it (emulated bf16 was 35-180x "
              "slower in our test). Nothing to compare.")
        return 0
    model = load("cpu")
    out = {}
    for prec in ("fp32", "bf16"):
        os.environ["BUZZ_TRAIN_PRECISION"] = prec
        r = check(model, "cpu", steps=3)
        out[prec] = r
        print("%s: voice %.3f steps/s, delivery %.3f steps/s" % (prec, r["voice"], r["delivery"]), flush=True)
        model = load("cpu")                                         # fresh weights (LoRA was added)
    f, b = out["fp32"], out["bf16"]
    print("bf16 is %.2fx (voice) and %.2fx (delivery) the speed of fp32 on this processor" % (b["voice"] / f["voice"],
          b["delivery"] / f["delivery"]))
    return 0


if __name__ == "__main__":
    sys.exit(cpu() if "--cpu" in sys.argv else gpu())
