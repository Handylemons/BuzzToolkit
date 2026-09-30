"""Pack numbers: a pack must not reuse a number that another pack already has.

Installing a pack writes dev_hdd0/game/BCES00098/USRDIR/PACKnnnn/<LANG>PACKnnnn.EDAT, so two packs
with the same number overwrite each other (also retail DLC packs). Every EDAT starts with its content
ID ("EP9000-BCES00098_00-BQC1GBR0099HPOTR"); its last 9 characters (number + the pack's 5-letter
suffix) identify the pack, so a newer build of the SAME pack is fine and anything else is a clash.
"""
import os
import re

DLC_TITLE = "BCES00098"
FIRST_CHOICE = list(range(99, 69, -1)) + list(range(1, 70)) + list(range(100, 1000))


def pack_key(pack):
    """number + content suffix, as it ends the pack's content ID ("0099HPOTR")."""
    return "%04d%s" % (int(pack["pack_number"]), pack.get("content_suffix", "CUSTM")[:5].ljust(5, "X"))


def edat_content_id(path):
    try:
        with open(path, "rb") as f:
            head = f.read(0x40)
    except OSError:
        return None
    if head[:4] != b"NPD\x00":
        return None
    return head[0x10:0x40].rstrip(b"\x00").decode("ascii", "replace")


def installed(rpcs3):
    """Packs installed in RPCS3 -> {number: [content IDs]}."""
    out = {}
    base = os.path.join(rpcs3 or "", "dev_hdd0", "game", DLC_TITLE, "USRDIR")
    if not rpcs3 or not os.path.isdir(base):
        return out
    for d in os.listdir(base):
        m = re.match(r"PACK(\d{4})$", d)
        if not m:
            continue
        cids = []
        for fn in os.listdir(os.path.join(base, d)):
            if fn.upper().endswith(".EDAT"):
                cids.append(edat_content_id(os.path.join(base, d, fn)) or "unknown")
        out[int(m.group(1))] = cids
    return out


def conflicts(pack, rpcs3=None, projects=()):
    """Reasons this pack's number can't be used (empty list = fine).
    projects: [(title, pack dict)] of the user's OTHER projects."""
    num = int(pack["pack_number"])
    if not 1 <= num <= 999:
        return ["pack numbers go from 1 to 999"]
    out = []
    for title, other in projects:
        if int(other["pack_number"]) == num:
            out.append('your pack "%s" already uses number %d' % (title, num))
    key = pack_key(pack)
    for cid in installed(rpcs3).get(num, []):
        if not cid.endswith(key):
            out.append("pack %d is already installed in RPCS3 as a different pack (%s); installing this one "
                       "would replace it" % (num, cid))
            break
    return out


def free_number(rpcs3=None, taken=()):
    used = set(installed(rpcs3)) | set(int(n) for n in taken)
    return next(n for n in FIRST_CHOICE if n not in used)
