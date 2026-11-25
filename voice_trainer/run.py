"""Host-voice trainer: one command from the user's own game files to a voice model the pack
builder uses. Nothing from the game ships with the tool - every user runs this on their copy.

    tools/clone_venv/Scripts/python.exe -m voice_trainer.run --disc "<extracted game folder>" \
        --work "<scratch dir, ~3 GB>" [--pack <decrypted DLC .DAT> ...] [--name buzz_host] \
        [--preset standard|best]

Start with --preview (same command plus --preview). It trains briefly on ~500 clips and writes
<work>/preview/samples/: three held-out questions as the REAL host, the UNTRAINED model and the model
AFTER THE PREVIEW, plus REPORT.txt with this PC's measured speed and the estimated time of a full run.
GPU: a few minutes. CPU: about an hour. Its features are reused; then run without --preview.

Presets (measured on an RTX 3060, English host, 24 held-out questions):
  standard  s3gen 1500 + t3 500 steps, ~1 h in total   speaker similarity 0.964, word errors 13.5%
  best      s3gen 4000 + t3 1000 steps, ~1 h 40 min    speaker similarity 0.959, word errors 14.9%
  (untrained base model: 0.886 / 13.9%.) Fewer than 500 t3 steps adds mispronunciations.
  No working GPU: --device auto falls back to the CPU. It works on any PC but is slow - measured
  on a desktop CPU for 5.8k clips: standard ~15 h, best ~29 h. Use --preset standard there.
  AMD Radeon RX 7000/9000 (EXPERIMENTAL): run tools/setup_amd.ps1, then use tools/clone_venv_amd's python.
  --precision bf16 tries bfloat16 maths on a CPU that has it (e.g. Ryzen 7000/9000); compare with a
  --preview. --no-miopen works around AMD kernel failures (slower).
  Czech/Croatian (spoken through the Polish model) default to t3 1500: 500 -> 1500 steps cut word
  errors 31.8% -> 27.3% (CZE) and 26.0% -> 19.6% (CRO), similarity 0.978/0.979 -> 0.982/0.980.

Steps (stop any time - running the same command again carries on; training saves every 15 min):
  1 corpus    decode every host line (disc questions + commentary + DLC) with its text
  2 features  S3 tokens / mels / speaker embeddings, speaker filter vs the question readings
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
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
PRESETS = {"standard": (1500, 500), "best": (4000, 1000)}     # (s3gen steps, t3 steps)


def step(name, args):
    print("\n=== %s" % name, flush=True)
    t = time.time()
    subprocess.run([PY, "-m", "voice_trainer." + args[0]] + args[1:], cwd=HERE, check=True)
    return time.time() - t


def make_reference(work, out):
    """reference.wav: two typical 4.5-6 s question readings from the training set, 0.25 s apart."""
    import numpy as np
    import soundfile as sf
    from voice_trainer.data import load_items
    train, _ = load_items(work, need_text=True)
    qs = [it for it in train if it["kind"] == "question"]
    picks = ([it for it in qs if 4.5 <= it["dur"] <= 6.0] or [it for it in qs if 3.0 <= it["dur"] <= 8.0] or qs)[:2]
    parts = []
    for it in picks:
        x, sr = sf.read(os.path.join(work, "audio", it["id"] + ".flac"), dtype="float32")
        parts += [x, np.zeros(int(0.25 * sr), np.float32)]
    sf.write(os.path.join(out, "reference.wav"), np.concatenate(parts[:-1]), sr)
    return picks


def export(work, name):
    from voice_trainer.data import work_lang
    out = os.path.join(HERE, "voice_models", name)
    os.makedirs(out, exist_ok=True)
    shutil.copy(os.path.join(work, "models", "s3gen_flow.pt"), out)
    if os.path.isdir(os.path.join(out, "t3_lora")):
        shutil.rmtree(os.path.join(out, "t3_lora"))
    shutil.copytree(os.path.join(work, "models", "t3_lora"), os.path.join(out, "t3_lora"))
    picks = make_reference(work, out)
    lang = work_lang(work)[0]
    json.dump({"lang": "GBR" if lang == "INE" else lang, "work": work,   # voices.py matches packs on lang
               "reference_clips": [(it["id"], it["raw_text"]) for it in picks]},
              open(os.path.join(out, "info.json"), "w"), indent=1)
    print("exported", out)
    return out


def stage_state(output_exists, done, resume):
    if os.path.exists(done):
        return "done"
    if os.path.exists(resume):
        return "resume"
    return "legacy" if output_exists else "todo"


def run_stage(label, state, args, retrain_flag):
    if state == "done":
        print("\n=== %s: finished earlier, skipped" % label)
    elif state == "legacy":
        print("\n=== %s: skipped - its output was made by an older toolkit version, which did not record whether\n"
              "    training finished. If that run was interrupted, add %s to train this stage again." % (label, retrain_flag))
    else:
        step(label + (" (carrying on from the last save)" if state == "resume" else ""), args)


def featured_clips(work):
    try:
        return len(json.load(open(os.path.join(work, "speakers.json")))["sim"])
    except Exception:                                             # noqa: BLE001
        return 0


def preview(a, w):
    from voice_trainer.data import cpu_has_bf16, eta, load_items, pick_device, precision, speed_key
    pdir = os.path.join(w, "preview")
    shutil.rmtree(pdir, ignore_errors=True)
    model_dir = os.path.join(pdir, "model")
    os.makedirs(model_dir)
    limit = max(PREVIEW["clips"], featured_clips(w) + 24)    # always time some new clips on this device
    step("2 features (preview: %d clips)" % limit, ["features", "--work", w, "--limit", str(limit)])
    step("3 s3gen (preview)", ["train_s3gen", "--work", w, "--steps", str(PREVIEW["s3gen"]), "--max-minutes",
                               str(PREVIEW["s3gen_min"]), "--save-final", "--save-every-min", "9999", "--out", model_dir])
    step("4 t3 (preview)", ["train_t3", "--work", w, "--steps", str(PREVIEW["t3"]), "--max-minutes", str(PREVIEW["t3_min"]),
                            "--log-every", "5", "--save-final", "--save-every-min", "9999", "--out", os.path.join(model_dir, "t3_lora")])
    make_reference(w, model_dir)
    ref = os.path.join(model_dir, "reference.wav")
    n = str(PREVIEW["lines"])
    tb = step("6 samples (untrained)", ["evaluate", "--work", w, "--ref", ref, "--n", n, "--label", "preview_base"])
    tt = step("6 samples (after preview)", ["evaluate", "--work", w, "--ref", ref, "--n", n, "--model", model_dir,
                                            "--label", "preview_trained"])
    # samples side by side
    import soundfile as sf
    sdir = os.path.join(pdir, "samples")
    os.makedirs(sdir)
    _, val = load_items(w, need_text=True)
    texts = []
    for i, it in enumerate(val[:PREVIEW["lines"]], 1):
        x, sr = sf.read(os.path.join(w, "audio", it["id"] + ".flac"), dtype="float32")
        sf.write(os.path.join(sdir, "%d_real_host.wav" % i), x, sr)
        for lab, src in (("untrained", "preview_base"), ("after_preview", "preview_trained")):
            shutil.copy(os.path.join(w, "eval", src, it["id"] + ".wav"), os.path.join(sdir, "%d_%s.wav" % (i, lab)))
        texts.append("%d  %s" % (i, it["raw_text"]))
    trained = lambda f: open(f).read().split()[0] if os.path.exists(f) else "?"
    s3n, t3n = trained(os.path.join(model_dir, "s3gen.done")), trained(os.path.join(model_dir, "t3_lora", "t3.done"))
    res = {k: json.load(open(os.path.join(w, "eval", k, "result.json"))) for k in ("preview_base", "preview_trained")}
    # time estimate from what was just measured on this PC
    dev = pick_device()
    sp = json.load(open(os.path.join(w, "speed.json")))
    get = lambda k: sp.get(speed_key(k, dev))
    man = [json.loads(l) for l in open(os.path.join(w, "manifest.jsonl"), encoding="utf-8")]
    left = sum(m["dur"] <= 20.0 for m in man) - featured_clips(w)
    t_feat = left * (get("features_s_per_clip") or 0)
    t_eval = (tb + tt) * 12 / PREVIEW["lines"]
    rows = []
    for name, (s3, t3) in sorted(PRESETS.items(), key=lambda kv: kv[1]):
        t3 = max(1500, t3) if a.lang in ("CZE", "CRO") else t3
        total = t_feat + s3 / get("s3gen_steps_per_s") + t3 / get("t3_steps_per_s") + t_eval
        rows.append("  --preset %-8s about %s  (s3gen %d + t3 %d steps)" % (name, eta(total), s3, t3))
    sim = lambda k: res[k]["speaker_sim"]
    lines = [
        "VOICE TRAINER PREVIEW (%s, %s, %s)" % (a.lang, dev, precision(dev)),
        "",
        "Listen in %s :" % os.path.normpath(sdir),
        "  N_real_host.wav      the real host reading a question the trainer never saw",
        "  N_untrained.wav      Chatterbox copying his voice from a 10 s sample, no training",
        "  N_after_preview.wav  after %s voice + %s delivery steps (a full run trains far longer)" % (s3n, t3n),
        "Lines:", *["  " + t for t in texts],
        "",
        "Speaker similarity (higher = closer to the real host; real host against himself = %.3f):"
        % res["preview_base"]["real_ceiling"],
        "  untrained %.3f   after preview %.3f   (a full run usually moves closer to the real host's score)"
        % (sim("preview_base"), sim("preview_trained")),
        "Misheard words (Whisper): untrained %.0f%%   after preview %.0f%%"
        % (100 * res["preview_base"]["wer"], 100 * res["preview_trained"]["wer"]),
        "These scores come from only %d lines and a very short training, so they are a rough guide: an early"
        % len(texts),
        "sample can even score lower than the untrained one. Listen, and mainly check that it is the host's voice.",
        "",
        "Measured on this PC: features %.2f s/clip, voice %.3f steps/s, delivery %.4f steps/s"
        % (get("features_s_per_clip") or 0, get("s3gen_steps_per_s"), get("t3_steps_per_s")),
        "Rough estimate of a full run on this PC (%d clips still to prepare):" % max(0, left),
        *rows,
        "",
        "Next: run the same command without --preview (stop any time; running it again carries on).",
    ]
    if dev == "cpu" and cpu_has_bf16() and precision(dev) == "fp32":
        lines.append("This processor does bfloat16 natively: run the preview again with --precision bf16 and compare "
                     "the speed and the samples.")
    report = "\n".join(lines)
    open(os.path.join(pdir, "REPORT.txt"), "w", encoding="utf-8").write(report + "\n")
    print("\n" + report)


PREVIEW = {"clips": 480, "s3gen": 200, "s3gen_min": 30, "t3": 40, "t3_min": 15, "lines": 5}


def main():
    for f in (sys.stdout, sys.stderr):              # lines in any language on a Windows console
        f.reconfigure(errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--disc", required=True)
    ap.add_argument("--work", required=True)
    ap.add_argument("--pack", action="append", default=[])
    ap.add_argument("--question-pak", default=None)
    ap.add_argument("--name", default="buzz_host")
    ap.add_argument("--lang", default="INE", help="disc language of the host to learn: INE (English), "
                    "ESP, PRT, FRA, DEU, ITA, NLD, POL, RUS, GRC, CZE, CRO")
    ap.add_argument("--preset", choices=sorted(PRESETS), default="standard")
    ap.add_argument("--preview", action="store_true", help="short trial run: samples + time estimate for this PC")
    ap.add_argument("--device", choices=["auto", "cuda", "cpu", "mps"], default="auto",
                    help="auto = a working NVIDIA/AMD GPU, else Apple GPU, else CPU (works on any PC but is slow)")
    ap.add_argument("--precision", choices=["auto", "fp32", "bf16"], default="auto",
                    help="auto = bf16 on GPUs that support it, fp32 on the CPU; bf16 on a CPU is a beta option")
    ap.add_argument("--no-miopen", action="store_true", help="AMD: avoid MIOpen kernels (if training crashes in them)")
    ap.add_argument("--s3gen-steps", type=int, default=None, help="override the preset")
    ap.add_argument("--t3-steps", type=int, default=None, help="override the preset")
    ap.add_argument("--retrain-s3gen", action="store_true", help="train the voice again from scratch; the previous "
                    "one is kept as s3gen_flow.pt.prev")
    ap.add_argument("--retrain-t3", action="store_true", help="train the delivery again (e.g. with more "
                    "--t3-steps), reusing the corpus and voice; the previous one is kept as t3_lora.prev")
    a = ap.parse_args()
    sys.path.insert(0, HERE)
    if a.device != "auto":
        os.environ["BUZZ_TRAIN_DEVICE"] = a.device   # inherited by every step's subprocess
    os.environ["BUZZ_TRAIN_PRECISION"] = a.precision
    if a.precision == "bf16" and a.device in ("auto", "cpu"):
        from voice_trainer.data import cpu_has_bf16
        if not cpu_has_bf16():
            print("Note: this processor has no native bf16; on the processor the trainer uses fp32 instead.")
    if a.no_miopen:
        os.environ["BUZZ_NO_MIOPEN"] = "1"
    a.s3gen_steps = a.s3gen_steps or PRESETS[a.preset][0]
    a.t3_steps = a.t3_steps or (max(1500, PRESETS[a.preset][1]) if a.lang in ("CZE", "CRO")
                                else PRESETS[a.preset][1])
    w = a.work
    if not os.path.exists(os.path.join(w, "manifest.jsonl")):
        args = ["corpus", "--disc", a.disc, "--work", w, "--lang", a.lang] + sum([["--pack", p] for p in a.pack], [])
        step("1 corpus", args + (["--question-pak", a.question_pak] if a.question_pak else []))
    if a.preview:
        return preview(a, w)
    if not os.path.exists(os.path.join(w, "features.done")):
        step("2 features", ["features", "--work", w])
    m = os.path.join(w, "models")
    flow = os.path.join(m, "s3gen_flow.pt")
    if a.retrain_s3gen:
        if os.path.exists(flow):
            os.replace(flow, flow + ".prev")
        for f in ("s3gen.done", "s3gen_resume.pt"):
            if os.path.exists(os.path.join(m, f)):
                os.remove(os.path.join(m, f))
    run_stage("3 s3gen", stage_state(os.path.exists(flow), os.path.join(m, "s3gen.done"), os.path.join(m, "s3gen_resume.pt")),
              ["train_s3gen", "--work", w, "--steps", str(a.s3gen_steps)], "--retrain-s3gen")
    lora = os.path.join(m, "t3_lora")
    if a.retrain_t3 and os.path.isdir(lora):
        shutil.rmtree(lora + ".prev", ignore_errors=True)
        os.rename(lora, lora + ".prev")
    run_stage("4 t3", stage_state(bool(glob.glob(os.path.join(lora, "adapter_model.*"))), os.path.join(lora, "t3.done"),
                                  os.path.join(lora, "resume.pt")),
              ["train_t3", "--work", w, "--steps", str(a.t3_steps)], "--retrain-t3")
    out = export(w, a.name)
    ref = os.path.join(out, "reference.wav")
    step("6 evaluate (base)", ["evaluate", "--work", w, "--ref", ref, "--label", "base"])
    step("6 evaluate (trained)", ["evaluate", "--work", w, "--ref", ref, "--model", out, "--label", "trained"])


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, subprocess.CalledProcessError) as e:
        print("\nStopped%s. Run the same command again to carry on (training saves every 15 minutes)."
              % ("" if isinstance(e, KeyboardInterrupt) else " (a step failed - see the error above)"))
        sys.exit(1)
