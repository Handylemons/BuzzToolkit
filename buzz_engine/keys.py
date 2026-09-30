"""Game values the toolkit needs but does not ship: read once from the user's own game.

    python -m buzz_engine setup --eboot <decrypted EBOOT.elf>
(RPCS3 > Utilities > Decrypt PS3 Binaries turns the game's EBOOT.BIN into an .elf.)

  klic         klicensee the game uses for free-licence DLC - packs are encrypted with it
  svomac_salt  the game's SVO request-signing salt - the online server needs it
Both are found by SHA-1 (only the hashes are in this file) and stored in
buzz_engine/game_keys.json on the user's machine.
"""
import hashlib
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
KEYS_FILE = os.path.join(HERE, "game_keys.json")
HASHES = {
    "klic": ("ecba12402adf3daf400b094539c7ccfa1e769633", 16),
    "svomac_salt": ("b20779981c873a624391d954375276e0d24f5fb0", 32),
}


def load():
    if os.path.exists(KEYS_FILE):
        with open(KEYS_FILE) as f:
            return json.load(f)
    return {}


def get(name):
    env = os.environ.get("BUZZ_" + name.upper())
    if env:
        return env
    v = load().get(name)
    if not v:
        raise RuntimeError("The game keys haven't been read yet. In Buzz Pack Studio's Setup box pick your "
                           "decrypted EBOOT.elf and press Read game keys (or run `python -m buzz_engine setup "
                           "--eboot <EBOOT.elf>`).")
    return v


def find_eboot(path):
    """The decrypted EBOOT from what the user typed: the .elf itself, or a game folder that holds
    it (USRDIR, PS3_GAME/USRDIR). Quotes from Explorer's "Copy as path" are ignored."""
    p = (path or "").strip().strip('"').strip()
    if not p:
        raise ValueError("give the path of your decrypted EBOOT.elf")
    if os.path.isfile(p):
        return p
    if not os.path.isdir(p):
        raise ValueError("can't find %s - check the path" % p)
    bins = []
    for sub in ("", "USRDIR", os.path.join("PS3_GAME", "USRDIR")):
        d = os.path.join(p, sub)
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            if fn.lower().endswith(".elf") and "eboot" in fn.lower():
                return os.path.join(d, fn)
            if fn.lower() == "eboot.bin":
                bins.append(os.path.join(d, fn))
    if bins:
        raise ValueError("found %s but it is still encrypted: in RPCS3 use Utilities > Decrypt PS3 Binaries on "
                         "it, then give the EBOOT.elf it writes next to it" % bins[0])
    raise ValueError("no EBOOT.elf in that folder - give the file itself (RPCS3 > Utilities > Decrypt PS3 "
                     "Binaries writes it next to EBOOT.BIN)")


def setup_from_eboot(path):
    path = find_eboot(path)
    d = open(path, "rb").read()
    if d[:4] != b"\x7fELF":
        raise ValueError("that is not a decrypted EBOOT (.elf) - use RPCS3 > Utilities > Decrypt PS3 Binaries")
    found = {}
    # salt: a 32-character printable string ending in NUL
    for m in re.finditer(rb"[\x21-\x7e]{32}(?=\x00)", d):
        if hashlib.sha1(m.group()).hexdigest() == HASHES["svomac_salt"][0]:
            found["svomac_salt"] = m.group().decode()
            break
    # klicensee: 16 raw bytes, 8-byte aligned in the data segment
    want = HASHES["klic"][0]
    for off in range(0, len(d) - 16, 8):
        if hashlib.sha1(d[off:off + 16]).hexdigest() == want:
            found["klic"] = d[off:off + 16].hex()
            break
    missing = [k for k in HASHES if k not in found]
    if missing:
        raise ValueError("not found in that EBOOT: %s - is it Buzz! Quiz World (BCES00645) v01.02?" % ", ".join(missing))
    keys = load()
    keys.update(found)
    with open(KEYS_FILE, "w") as f:
        json.dump(keys, f, indent=1)
    return sorted(found)
