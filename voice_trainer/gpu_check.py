"""One-minute check that this PC's GPU can train the host voice, before a multi-hour run:
    <venv>/Scripts/python.exe -m voice_trainer.gpu_check
Runs 10 real training steps of the voice model on dummy data (nothing is saved) and prints PASS or FAIL."""
import os
import sys
import time

import torch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from voice_trainer.data import autocast, pick_device  # noqa: E402


def main():
    print("torch %s | ROCm %s | CUDA %s" % (torch.__version__, getattr(torch.version, "hip", None), torch.version.cuda))
    dev = pick_device()
    print("device: %s %s" % (dev, torch.cuda.get_device_name(0) if dev == "cuda" else ""), flush=True)
    if dev != "cuda":
        print("FAIL: PyTorch sees no GPU here - the trainer would fall back to the (slow) CPU")
        return 1
    from chatterbox.tts import ChatterboxTTS
    flow = ChatterboxTTS.from_pretrained(device=dev).s3gen.flow
    flow.train()
    opt = torch.optim.AdamW([p for p in flow.parameters() if p.requires_grad], lr=1e-6)
    T = 150                                                    # 6 s of speech tokens
    batch = {"speech_token": torch.randint(0, 6561, (2, T)), "speech_token_len": torch.tensor([T, T]),
             "speech_feat": torch.randn(2, 80, 2 * T), "speech_feat_len": torch.tensor([2 * T, 2 * T]),
             "embedding": torch.randn(2, 192)}
    t0 = time.time()
    for i in range(10):
        with autocast(dev):
            loss = flow.compute_loss(batch, dev)["loss"]
        if not torch.isfinite(loss):
            print("FAIL: loss is not a number at step %d" % i)
            return 1
        opt.zero_grad(set_to_none=True)
        loss.backward()
        opt.step()
    torch.cuda.synchronize()
    print("PASS: 10 training steps on the GPU, %.2f steps/s (an RTX 3060 does about 1 step/s here)" % (10 / (time.time() - t0)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
