"""Shared dataset helpers for the host-voice trainer (features written by features.py)."""
import contextlib
import glob
import json
import os
import random

import torch


def work_lang(work):
    """-> (pack language code, ISO code) the corpus in <work> was built for (lang.json, written by
    corpus.py; work folders from before language support are English)."""
    p = os.path.join(work, "lang.json")
    d = json.load(open(p)) if os.path.exists(p) else {}
    return d.get("lang", "INE"), d.get("iso", "en")


def load_items(work, need_text=False, min_dur=0.8, max_dur=12.0):
    """-> (train, val) lists of feature dicts: speaker-filtered, length-filtered, with a fixed
    held-out validation set (every 60th clip by id)."""
    spk = json.load(open(os.path.join(work, "speakers.json")))
    floor, sims = spk["floor"], spk["sim"]
    items = []
    for f in sorted(glob.glob(os.path.join(work, "features", "shard_*.pt"))):
        for it in torch.load(f):
            if sims.get(it["id"], 0) < floor or not (min_dur <= it["dur"] <= max_dur):
                continue
            if need_text and "text" not in it:
                continue
            items.append(it)
    items.sort(key=lambda it: it["id"])
    val = items[::60]
    vid = {it["id"] for it in val}
    return [it for it in items if it["id"] not in vid], val


def batches(items, max_frames, shuffle=True, seed=0):
    """Length-bucketed batches with at most max_frames speech tokens per batch."""
    rng = random.Random(seed)
    order = sorted(items, key=lambda it: len(it["tokens"]))
    out, cur, longest = [], [], 0
    for it in order:
        n = len(it["tokens"])
        if cur and max(longest, n) * (len(cur) + 1) > max_frames:
            out.append(cur)
            cur, longest = [], 0
        cur.append(it)
        longest = max(longest, n)
    if cur:
        out.append(cur)
    if shuffle:
        rng.shuffle(out)
    return out


def held_out_texts(work, n=12):
    """Question texts of validation clips (for listening tests / evaluation)."""
    _, val = load_items(work, need_text=True)
    return [(it["id"], it["raw_text"]) for it in val[:n]]


_PROBED = {}


def _gpu_works():
    """A broken NVIDIA driver or an unsupported AMD card can still report a GPU; run one real kernel."""
    if "ok" not in _PROBED:
        try:
            x = torch.ones(64, 64, device="cuda")
            (x @ x).sum().item()
            _PROBED["ok"] = True
        except Exception as e:                                    # noqa: BLE001
            print("WARNING: the GPU is visible but failed a test calculation (%s) - using the CPU" % str(e).splitlines()[0],
                  flush=True)
            _PROBED["ok"] = False
    return _PROBED["ok"]


def pick_device():
    """--device / BUZZ_TRAIN_DEVICE wins; else a working NVIDIA/AMD GPU, Apple GPU, else CPU. Always a plain
    string: Chatterbox maps CUDA-saved checkpoints to the CPU only for the strings "cpu"/"mps".
    (AMD's ROCm build of PyTorch presents the Radeon card through the same "cuda" API.)"""
    d = os.environ.get("BUZZ_TRAIN_DEVICE", "").strip().lower()
    if d:
        return d
    if torch.cuda.is_available() and torch.cuda.device_count() > 0 and _gpu_works():
        return "cuda"
    return "mps" if torch.backends.mps.is_available() else "cpu"


def cpu_has_bf16():
    """True on processors with native bfloat16 maths (e.g. AMD Zen 4/5, Intel Sapphire Rapids)."""
    try:
        return bool(torch._C._cpu._is_avx512_bf16_supported())
    except Exception:                                             # noqa: BLE001
        return False


def precision(dev):
    """BUZZ_TRAIN_PRECISION (run.py --precision): auto = bf16 on GPUs that do it natively, fp32 elsewhere
    (CPU bf16 is opt-in until it is measured to help); bf16 / fp32 force it."""
    p = os.environ.get("BUZZ_TRAIN_PRECISION", "auto").strip().lower()
    if p in ("fp32", "bf16"):
        if p == "bf16" and dev == "cpu" and not cpu_has_bf16():
            return "fp32"                  # emulated bf16 measured 35-180x slower on a Ryzen 5800X
        return "fp32" if dev == "mps" else p
    if dev == "cuda":
        try:
            ok = torch.cuda.is_bf16_supported(including_emulation=False)
        except TypeError:
            ok = torch.cuda.is_bf16_supported()
        return "bf16" if ok else "fp32"
    return "fp32"


def autocast(dev):
    """bfloat16 mixed precision where precision() says so (weights and optimiser state stay fp32)."""
    if precision(dev) != "bf16":
        return contextlib.nullcontext()
    return torch.autocast("cuda" if dev == "cuda" else "cpu", dtype=torch.bfloat16)


def free_cache(dev):
    if dev == "cuda":
        torch.cuda.empty_cache()


def describe(dev):
    """One line for the logs: device, card, precision."""
    name = ""
    if dev == "cuda":
        name = " " + torch.cuda.get_device_name(0) + (" (ROCm %s)" % torch.version.hip if torch.version.hip else "")
    return "device: %s%s, precision: %s" % (dev, name, precision(dev))


def speed_key(name, dev):
    return "%s@%s/%s" % (name, dev, precision(dev))


def record_speed(work, name, value, dev):
    """Merge one measured speed into <work>/speed.json, keyed by device and precision (run.py --preview
    turns them into a time estimate for the full run)."""
    p = os.path.join(work, "speed.json")
    try:
        d = json.load(open(p))
    except Exception:                                             # noqa: BLE001
        d = {}
    d[speed_key(name, dev)] = value
    json.dump(d, open(p, "w"), indent=1)


def eta(seconds):
    h = seconds / 3600
    return "%.1f h" % h if h >= 1 else "%d min" % max(1, round(seconds / 60))


def save_atomic(obj, path):
    tmp = path + ".tmp"
    torch.save(obj, tmp)
    os.replace(tmp, path)


# AMD (ROCm): MIOpen searches for the fastest kernels on first use, which can take minutes. FAST mode skips
# the search; BUZZ_NO_MIOPEN=1 (run.py --no-miopen) avoids MIOpen entirely if its kernels fail on a card.
if getattr(torch.version, "hip", None):
    os.environ.setdefault("MIOPEN_FIND_MODE", "FAST")
    if os.environ.get("BUZZ_NO_MIOPEN"):
        torch.backends.cudnn.enabled = False
