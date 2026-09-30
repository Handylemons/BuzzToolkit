"""Game update 01.02 for Buzz! Quiz World (BCES00645): check, download from Sony, install.

The toolkit is built on update 01.02 (online patches and the login fix target it). The update is
Sony's file, so it is never shipped: `download()` fetches the official package straight from
Sony's PS3 update server to the user's PC, the same way the console does, and checks it against
the known SHA-1 before it is used.

    python -m buzz_engine setup --get-update
"""
import hashlib
import os
import re
import ssl
import subprocess
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TITLE = "BCES00645"
VERSION = "01.02"
VER_XML = "https://a0.ww.np.dl.playstation.net/tpl/np/%s/%s-ver.xml" % (TITLE, TITLE)
# the 01.02 package as listed by Sony's server (checked here, so a changed or damaged file is refused;
# Sony's sha1sum leaves out the last 32 bytes)
PKG_NAME = "EP9000-BCES00645_00-BQW123ESPPATCH02-A0102-V0100-PE.pkg"
PKG_SIZE = 22379568
PKG_SHA1 = "8b704ad01381ed3afb0fd328fb8fabf512a7f74e"
DOWNLOADS = os.path.join(ROOT, "tools", "downloads")


def read_sfo(path):
    """PARAM.SFO -> {key: value} (strings and ints)."""
    import struct
    d = open(path, "rb").read()
    if d[:4] != b"\x00PSF":
        raise ValueError("not a PARAM.SFO")
    kt, dt, n = struct.unpack("<III", d[8:20])
    out = {}
    for i in range(n):
        ko, fmt, ln, _, do = struct.unpack("<HHIII", d[20 + 16 * i:36 + 16 * i])
        key = d[kt + ko:d.index(b"\x00", kt + ko)].decode()
        raw = d[dt + do:dt + do + ln]
        out[key] = struct.unpack("<I", raw)[0] if fmt == 0x0404 else raw.rstrip(b"\x00").decode("utf-8", "replace")
    return out


def installed_version(rpcs3):
    """Installed update version in RPCS3 ("01.02"), or None when no update is installed."""
    if not rpcs3:
        return None
    sfo = os.path.join(rpcs3, "dev_hdd0", "game", TITLE, "PARAM.SFO")
    if not os.path.exists(sfo):
        return None
    try:
        return read_sfo(sfo).get("APP_VER") or None
    except (OSError, ValueError):
        return None


def status(rpcs3):
    v = installed_version(rpcs3)
    pkg = os.path.join(DOWNLOADS, PKG_NAME)
    return {"installed": v, "ok": v == VERSION, "want": VERSION,
            "downloaded": pkg if os.path.exists(pkg) and os.path.getsize(pkg) == PKG_SIZE else None}


def _sony_context():
    # Sony's update servers use their own certificate authority, which Windows doesn't know. The
    # listing is only used to find the URL; the package itself is checked against PKG_SHA1.
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def package_url():
    """Ask Sony's update server for the 01.02 package URL."""
    req = urllib.request.Request(VER_XML, headers={"User-Agent": "BuzzToolkit"})
    with urllib.request.urlopen(req, timeout=30, context=_sony_context()) as r:
        xml = r.read().decode("utf-8", "replace")
    for m in re.finditer(r'<package version="([^"]+)"[^>]*url="([^"]+)"', xml):
        if m.group(1) == VERSION:
            return m.group(2)
    raise RuntimeError("Sony's update server no longer lists update %s for %s" % (VERSION, TITLE))


def download(progress=print):
    """Download the official update package from Sony -> local path (verified)."""
    os.makedirs(DOWNLOADS, exist_ok=True)
    dst = os.path.join(DOWNLOADS, PKG_NAME)
    if os.path.exists(dst) and verified(dst):
        progress("Update %s already downloaded: %s" % (VERSION, dst))
        return dst
    url = package_url()
    progress("Downloading update %s from Sony (%.0f MB)..." % (VERSION, PKG_SIZE / 1e6))
    tmp = dst + ".part"
    req = urllib.request.Request(url, headers={"User-Agent": "BuzzToolkit"})
    with urllib.request.urlopen(req, timeout=120, context=_sony_context()) as r, open(tmp, "wb") as f:
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
    if not verified(tmp):
        os.remove(tmp)
        raise RuntimeError("the downloaded update didn't match Sony's checksum - try again")
    os.replace(tmp, dst)
    progress("Update %s ready: %s" % (VERSION, dst))
    return dst


def verified(path):
    """Right size and Sony's SHA-1, which covers everything but the package's last 32 bytes (the
    package's own digest block, which starts with that same SHA-1)."""
    if os.path.getsize(path) != PKG_SIZE:
        return False
    h, left = hashlib.sha1(), PKG_SIZE - 32
    with open(path, "rb") as f:
        while left:
            chunk = f.read(min(1 << 20, left))
            h.update(chunk)
            left -= len(chunk)
    return h.hexdigest() == PKG_SHA1


def rpcs3_running():
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq rpcs3.exe", "/NH"], capture_output=True, text=True).stdout
    return "rpcs3.exe" in out.lower()


def install(rpcs3, pkg):
    """Open RPCS3's own package installer on the update (RPCS3 must be closed)."""
    exe = os.path.join(rpcs3 or "", "rpcs3.exe")
    if not os.path.exists(exe):
        raise ValueError("rpcs3.exe not found - set the RPCS3 folder first")
    if rpcs3_running():
        raise ValueError("close RPCS3 first, or install it yourself in RPCS3 with File > Install "
                         "Packages/Raps/Edats and pick %s" % pkg)
    subprocess.Popen([exe, "--installpkg", pkg], cwd=rpcs3)
    return exe
