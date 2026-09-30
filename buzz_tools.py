"""Where the toolkit finds external programs (nothing here is machine-specific)."""
import json
import os
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
FFMPEG_DIR = os.path.join(HERE, "tools", "ffmpeg", "bin")
# free LGPL build (static), used by `python -m buzz_engine setup --get-ffmpeg`
FFMPEG_URL = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-lgpl.zip"


def find_ffmpeg():
    """ffmpeg: $FFMPEG, then "ffmpeg" in buzz_engine/settings.json, then the copy in
    tools/ffmpeg/bin/, then the system PATH. -> path or None."""
    if os.environ.get("FFMPEG") and os.path.exists(os.environ["FFMPEG"]):
        return os.environ["FFMPEG"]
    cfg = os.path.join(HERE, "buzz_engine", "settings.json")
    if os.path.exists(cfg):
        p = json.load(open(cfg)).get("ffmpeg")
        if p and os.path.exists(p):
            return p
    for name in ("ffmpeg.exe", "ffmpeg"):
        p = os.path.join(FFMPEG_DIR, name)
        if os.path.exists(p):
            return p
    return shutil.which("ffmpeg")


def ffmpeg():
    """ffmpeg for a subprocess call; a clear error if it is missing."""
    p = find_ffmpeg()
    if not p:
        raise RuntimeError("ffmpeg not found. In Buzz Pack Studio use Setup > Download ffmpeg, or run "
                           "`python -m buzz_engine setup --get-ffmpeg`, or put ffmpeg.exe in tools\\ffmpeg\\bin.")
    return p


def download_ffmpeg(progress=print):
    """Fetch the LGPL ffmpeg build and put ffmpeg.exe in tools/ffmpeg/bin. -> path"""
    import io
    import urllib.request
    import zipfile
    progress("Downloading ffmpeg (about 100 MB)...")
    req = urllib.request.Request(FFMPEG_URL, headers={"User-Agent": "BuzzToolkit"})
    with urllib.request.urlopen(req, timeout=600) as r:
        data = r.read()
    z = zipfile.ZipFile(io.BytesIO(data))
    os.makedirs(FFMPEG_DIR, exist_ok=True)
    got = None
    for n in z.namelist():
        base = os.path.basename(n)
        if "/bin/" in n and base.lower().endswith((".exe", ".dll")):
            with open(os.path.join(FFMPEG_DIR, base), "wb") as f:
                f.write(z.read(n))
            if base.lower() == "ffmpeg.exe":
                got = os.path.join(FFMPEG_DIR, base)
        elif base.upper() in ("LICENSE.TXT", "LICENSE"):
            with open(os.path.join(os.path.dirname(FFMPEG_DIR), "LICENSE.txt"), "wb") as f:
                f.write(z.read(n))
    if not got:
        raise RuntimeError("the ffmpeg download did not contain ffmpeg.exe")
    progress("ffmpeg ready: " + got)
    return got
