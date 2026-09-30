"""Host speech for custom packs: text -> TTS -> 48 kHz mono -> ATRAC3 (152-byte frames) -> .rsf

Pipeline (all local, deterministic, no templates):
  1. host_line(): question text as the host should say it (sentence case, optional
     pronunciation fixes, or an explicit "speech" override from the pack JSON).
  2. synthesize(): TTS backend, one of
       clone:<ref>     Chatterbox voice cloning (buzz_tts_clone.py in tools/clone_venv, GPU) in
                       the voice of voice_refs/<ref>.wav - buzz_host.wav is made from the user's
                       own game files by make_host_reference.py. The default when installed.
       kokoro:<voice>  neural Kokoro-82M (buzz_tts_kokoro.py in tools/tts_venv), 24 kHz, e.g.
                       bm_george / bm_lewis / bm_daniel
       onecore:<voice> Windows built-in voices via buzz_tts.ps1 (George/Hazel/Susan), 16 kHz
     Raw output is cached by (text, voice, speed) in voice_cache/ so rebuilds are identical.
  3. ffmpeg resamples to 48 kHz mono with a compressor; silence trimmed; mastered to the
     retail loudness (-13.5 LUFS, look-ahead limited at -1.9 dBFS like retail clips).
  4. buzz_atrac3.encode() -> raw frames; buzz_rsf.speech_header() wraps them.

CLI:  python buzz_voice.py "Which of these must a seeker catch?" out.rsf [--voice onecore:George]
      (also writes out.preview.wav, decoded back through ffmpeg, for listening)
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile

import numpy as np

import buzz_atrac3
import buzz_rsf

HERE = os.path.dirname(os.path.abspath(__file__))
TTS_SCRIPT = os.path.join(HERE, "buzz_tts.ps1")
KOKORO_PY = os.path.join(HERE, "tools", "tts_venv", "Scripts", "python.exe")
CLONE_PY = os.path.join(HERE, "tools", "clone_venv", "Scripts", "python.exe")
REFS = os.path.join(HERE, "voice_refs")
CACHE = os.path.join(HERE, "voice_cache")
RATE = 48000
TARGET_LUFS = -13.5              # retail GBR question clips: -13.7 LUFS (range -14.5..-13.0)
CEILING = 0.80                   # limiter ceiling (-1.9 dBFS, the retail peak level)
LEAD, TAIL = 0.03, 0.15          # seconds of silence kept before/after the line

_SMALL = {"a", "an", "and", "as", "at", "but", "by", "for", "in", "of", "on", "or", "the", "to", "with"}


def host_line(text, pronounce=None):
    """Turn an on-screen question (usually ALL CAPS) into what the host says.
    Lower-casing stops TTS spelling words out as acronyms; `pronounce` maps words to
    respellings, e.g. {"HERMIONE": "Her-my-oh-nee"}."""
    s = text.strip()
    if s.isupper():
        s = s.lower()
        s = s[:1].upper() + s[1:]
    for word, say in (pronounce or {}).items():
        s = re.sub(r"\b%s\b" % re.escape(word), say, s, flags=re.IGNORECASE)
    return s


def _key(text, voice, speed, extra=""):
    return hashlib.sha1(json.dumps([text, voice, speed, extra]).encode()).hexdigest()[:16]


def _ref_path(name):
    """A reference given as a path (absolute or relative to gs_tmp) or a name in voice_refs/."""
    for p in (name, os.path.join(HERE, name)):
        if os.path.isfile(p):
            return p
    return os.path.join(REFS, name + ".wav")


def available_backends():
    out = ["onecore"]
    if os.path.exists(CLONE_PY) and os.path.exists(_ref_path("buzz_host")):
        out.insert(0, "clone")
    if os.path.exists(KOKORO_PY) and os.path.exists(os.path.join(HERE, "tools", "kokoro", "kokoro-v1.0.onnx")):
        out.insert(0, "kokoro")
    return out


DEFAULT_VOICE = ("clone:buzz_host" if "clone" in available_backends() else
                 "kokoro:bm_george" if "kokoro" in available_backends() else "onecore:George")
CLONE_OPTS = {"exaggeration": 0.5, "cfg": 0.5, "temperature": 0.8, "seed": 1234}


def _cache_paths(texts, voice, speed, clone_opts):
    backend, name = voice.split(":", 1)
    extra, opts, ref = "", None, None
    if backend == "clone":
        opts = dict(CLONE_OPTS, **(clone_opts or {}))
        ref = _ref_path(name)
        extra = json.dumps([hashlib.sha1(open(ref, "rb").read()).hexdigest(), sorted(opts.items()),
                            _model_sig(opts.get("model"))])
    tag = os.path.basename(name).replace(".wav", "")
    return [os.path.join(CACHE, "%s_%s_%s.wav" % (backend, tag, _key(t, voice, speed, extra))) for t in texts], opts, ref


def _model_sig(model):
    """Identity of a trained voice model (voice_trainer output) for the cache key."""
    if not model:
        return None
    d = model if os.path.isabs(model) else os.path.join(HERE, model)
    sig = []
    for root, _, files in os.walk(d):
        for f in sorted(files):
            if f in ("info.json", "reference.txt"):           # notes, not weights
                continue
            st = os.stat(os.path.join(root, f))
            sig.append([f, st.st_size, int(st.st_mtime)])
    return sig


def _clone_args(opts):
    args = []
    for k, v in sorted(opts.items()):
        if k == "lang":
            args += ["--lang", v or "en"]
        elif k == "model":
            if v:
                args += ["--model", v if os.path.isabs(v) else os.path.join(HERE, v)]
        else:
            args += ["--" + k, str(v)]
    return args


def _run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError("failed: %s\n%s" % (" ".join(cmd), r.stderr[-2000:]))
    return r.stdout


def _jobs_file(td, jobs):
    path = os.path.join(td, "jobs%d.json" % len(os.listdir(td)))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(jobs, f)
    return path


MAX_TAKES = 4          # cloned lines are checked by speech recognition and re-generated
MAX_WER = 0.15         # (new seed) when words are missing/extra; the best take is kept


def _clone(todo, ref, opts, vocab):
    """Generate cloned lines, verify each with Whisper, retry bad takes; writes each accepted
    take to its cache path plus a .json note (take, transcript, word error rate)."""
    best = {}
    with tempfile.TemporaryDirectory() as td:
        pending = list(todo)
        for take in range(MAX_TAKES):
            if not pending:
                break
            jobs = [{"text": j["text"], "out": os.path.join(td, "%d_%d.wav" % (i, take)), "take": take, "i": i}
                    for i, j in ((todo.index(j), j) for j in pending)]
            _run([CLONE_PY, os.path.join(HERE, "buzz_tts_clone.py"), _jobs_file(td, jobs), "--ref", ref]
                 + _clone_args(opts))
            out = _run([CLONE_PY, os.path.join(HERE, "buzz_tts_verify.py"), "--lang", opts.get("lang") or "en",
                        _jobs_file(td, [{"text": j["text"], "wav": j["out"], "vocab": vocab} for j in jobs])])
            heard = [json.loads(l) for l in out.splitlines() if l.startswith("{")]
            still = []
            for j, h in zip(jobs, heard):
                if j["i"] not in best or h["wer"] < best[j["i"]]["wer"]:
                    best[j["i"]] = dict(h, take=take)
                if h["wer"] > MAX_WER:
                    still.append(todo[j["i"]])
            pending = still
        for i, b in best.items():
            os.replace(b["wav"], todo[i]["out"])
            b["wav"] = os.path.basename(todo[i]["out"])
            with open(todo[i]["out"][:-4] + ".json", "w", encoding="utf-8") as f:
                json.dump(b, f, indent=1)


def synthesize(texts, voice=None, speed=1.0, clone_opts=None, vocab=None):
    """voice: "clone:<ref>" (Chatterbox cloning the voice in voice_refs/<ref>.wav, 24 kHz),
    "kokoro:<name>" (neural, 24 kHz) or "onecore:<name>" (Windows built-in, 16 kHz).
    -> list of float arrays (48 kHz mono, int16 scale), one per text. Raw TTS output is cached
    per (text, voice, speed[, reference + options]): neural TTS is not bit-exact between runs,
    the cache makes rebuilds identical and fast. vocab: spelling hints for the recogniser that
    checks cloned lines (e.g. "Hermione, Quidditch, Hogwarts")."""
    voice = voice or DEFAULT_VOICE
    backend, name = voice.split(":", 1)
    os.makedirs(CACHE, exist_ok=True)
    paths, opts, ref = _cache_paths(texts, voice, speed, clone_opts)
    todo, seen = [], set()
    for t, p in zip(texts, paths):
        if not os.path.exists(p) and p not in seen:
            seen.add(p)
            todo.append({"text": t, "out": p})
    if todo:
        if backend == "clone":
            _clone(todo, ref, opts, vocab)
        else:
            with tempfile.TemporaryDirectory() as td:
                jobs = _jobs_file(td, todo)
                if backend == "kokoro":
                    _run([KOKORO_PY, os.path.join(HERE, "buzz_tts_kokoro.py"), jobs, "--voice", name, "--speed", str(speed)])
                elif backend == "onecore":
                    _run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", TTS_SCRIPT,
                          "-Jobs", jobs, "-Voice", name, "-Rate", str(speed)])
                else:
                    raise ValueError("unknown TTS backend %r" % backend)
    return [_load_48k(p) for p in paths]


def verify_report(texts, voice=None, speed=1.0, clone_opts=None):
    """-> list of the .json notes written for cloned lines (None where absent)."""
    paths, _, _ = _cache_paths(texts, voice or DEFAULT_VOICE, speed, clone_opts)
    out = []
    for p in paths:
        j = p[:-4] + ".json"
        out.append(json.load(open(j, encoding="utf-8")) if os.path.exists(j) else None)
    return out


# Retail host clips are compressed broadcast voice; TTS is more dynamic, so a compressor runs
# during the resample (prepare() then sets the final loudness).
FILTER = "acompressor=threshold=-26dB:ratio=4:attack=4:release=70:knee=4"


def _load_48k(path):
    raw = subprocess.run([__import__("buzz_tools").ffmpeg(), "-v", "error", "-i", path, "-ac", "1",
                          "-af", "aresample=%d,%s" % (RATE, FILTER),
                          "-f", "s16le", "-"], check=True, capture_output=True).stdout
    return np.frombuffer(raw, "<i2").astype(np.float64)


def _ffmpeg_pcm(x, af):
    """Run int16-scale float samples through an ffmpeg filter chain -> (samples, stderr)."""
    pcm = np.clip(np.rint(x), -32768, 32767).astype("<i2").tobytes()
    r = subprocess.run([__import__("buzz_tools").ffmpeg(), "-hide_banner", "-nostats", "-f", "s16le", "-ar", str(RATE), "-ac", "1",
                        "-i", "-", "-af", af, "-f", "s16le", "-"], input=pcm, capture_output=True, check=True)
    return np.frombuffer(r.stdout, "<i2").astype(np.float64), r.stderr.decode("utf-8", "replace")


def loudness(x):
    """Integrated loudness (EBU R128 / BS.1770) in LUFS."""
    _, err = _ffmpeg_pcm(x, "ebur128")
    return float(re.findall(r"I:\s+(-?[\d.]+) LUFS", err)[-1])


def prepare(samples, warmth=0.0):
    """Trim silence (short lead-in/tail kept), optional tone warmth, and master to the retail
    host level: retail question clips measure -13.7 LUFS integrated with peaks at -1.9 dBFS
    (heavily compressed broadcast voice), so gain to TARGET_LUFS then a look-ahead limiter at
    the retail ceiling; one correction pass for the loudness the limiter takes off.
    warmth (dB): low-shelf lift around 200 Hz with half as much cut above 5 kHz."""
    x = np.asarray(samples, np.float64)
    loud = np.nonzero(np.abs(x) > 0.02 * max(np.abs(x).max(), 1))[0]
    if not len(loud):
        return x
    x = x[max(0, loud[0] - int(LEAD * RATE)):min(len(x), loud[-1] + int(TAIL * RATE))]
    x = np.concatenate([x, np.zeros(int(0.05 * RATE))])        # room for the limiter release
    if warmth:
        x, _ = _ffmpeg_pcm(x * 0.5, "bass=g=%.2f:f=200:w=0.7,treble=g=%.2f:f=5000:w=0.7" % (warmth, -warmth / 2))
    for _ in range(2):
        g = TARGET_LUFS - loudness(x)
        if abs(g) < 0.2:
            break
        x, _ = _ffmpeg_pcm(x, "volume=%.2fdB,alimiter=limit=%.3f:attack=3:release=40:level=disabled"
                           % (g, CEILING))
    return x


def to_rsf(samples, warmth=0.0):
    frames = buzz_atrac3.encode(prepare(samples, warmth))
    return buzz_rsf.speech_header(len(frames)) + frames


def host_clips(texts, voice=None, speed=1.0, clone_opts=None, vocab=None, warmth=0.0):
    """Texts exactly as spoken -> list of .rsf bytes."""
    return [to_rsf(s, warmth) for s in synthesize(texts, voice, speed, clone_opts, vocab)]


def preview_wav(rsf, path):
    """Decode an .rsf back through ffmpeg into a normal WAV (what the game will play)."""
    import wave
    pcm = np.array(buzz_rsf.decode(rsf), "<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(buzz_rsf.parse(rsf)[0])
        w.writeframes(pcm.tobytes())


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("text")
    ap.add_argument("out")
    ap.add_argument("--voice", default=None, help="clone:buzz_host (default), kokoro:bm_george or onecore:George")
    ap.add_argument("--speed", type=float, default=1.0)
    a = ap.parse_args()
    clip = host_clips([host_line(a.text)], a.voice, a.speed)[0]
    open(a.out, "wb").write(clip)
    preview_wav(clip, os.path.splitext(a.out)[0] + ".preview.wav")
    print("%s: %d bytes, %.2f s" % (a.out, len(clip), (len(clip) - 32) / 152 * 1024 / RATE))
