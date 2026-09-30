"""Online side of the toolkit: self-hosted Buzz server + publishing quizzes to it + setting up a
PC (host or friend) for online play. Everything game-specific is taken from the user's own copy.

Host: run the server (fake_buzz_server.py) - ports 10060 (SVO/HTTP), 10071 (Medius login),
10075 (Medius DME). Friends set their RPCS3 "IP swap list" to buzzps3.online.scee.com=<host IP>.
Every player's game also needs (applied by setup_pc):
  * the login fix in Patched/GLOBALSCRIPTS.SDAT (initnetworkconnection.clu, svoLogin: the
    Network.Login(false) CALL -> LOADBOOL true, so the game never waits for Sony's login server)
  * RPCS3 patch "Online: force IsLoggedIn true" (Network.IsLoggedIn -> true), game v01.02
  * RPCS3 network settings: Internet Connected, PSN = RPCN (free RPCS3 account), IP swap list
The server needs the game's SVO signing salt: read once from the host's decrypted EBOOT
(RPCS3 > Utilities > Decrypt PS3 Binaries) by setup_server - only its SHA-1 is stored here.
"""
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))
CATALOG_DIR = os.path.join(ROOT, "content", "packs")
SERVER = os.path.join(ROOT, "fake_buzz_server.py")
SERVER_LOG = os.path.join(ROOT, "buzz_server_live.log")
PORTS = (10060, 10071, 10075)
HOSTNAME = "buzzps3.online.scee.com"

# initnetworkconnection.clu (update 01.02): svoLogin proto, instruction 3
LOGIN_FIX = {"file": "Global/SCRIPTS/initnetworkconnection.clu", "offset": 0x581F,
             "orig": bytes.fromhex("0100805C"), "new": bytes.fromhex("00800042")}

CATEGORY_ONLINE = {"Knowledge": "General Knowledge", "TVCinema": "Film & TV", "Lifestyle": "Lifestyle", "Music": "Music"}


# ------------------------------------------------------------------------------ publishing
def publish(project_json, quiz_size=10):
    """A pack project's standard questions -> online quizzes in the server's catalogue
    (content/packs/studio_<id>.json). The server reloads it automatically."""
    with open(project_json, encoding="utf-8") as f:
        pack = json.load(f)
    pid = os.path.basename(os.path.dirname(os.path.abspath(project_json)))
    title = pack["text"]["menu_name"].title()
    qs = [{"question": {"text": q[0]}, "correctAnswer": q[1], "incorrectAnswers": q[2:5], "difficulty": "medium"}
          for q in pack["standard"]]
    if not qs:
        raise ValueError("no standard questions to publish (online quizzes are text-only)")
    quizzes = []
    for i in range(0, len(qs), quiz_size):
        part = qs[i:i + quiz_size]
        if len(part) < 3 and quizzes:
            quizzes[-1]["questions"] += part
            continue
        quizzes.append({"name": "%s %d" % (title, len(quizzes) + 1) if len(qs) > quiz_size else title,
                        "description": pack["text"]["description"].capitalize(), "questions": part})
    data = {"pack": title, "category": CATEGORY_ONLINE.get(pack.get("category"), "General Knowledge"),
            "author": pack.get("author") or "Buzz Pack Studio", "description": pack["text"]["description"].capitalize(),
            "tags": [title.lower()], "enabled": True, "source_project": pid, "quizzes": quizzes}
    os.makedirs(CATALOG_DIR, exist_ok=True)
    out = os.path.join(CATALOG_DIR, "studio_%s.json" % pid)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
    return {"file": out, "quizzes": len(quizzes), "questions": len(qs)}


def published():
    out = []
    for fn in sorted(os.listdir(CATALOG_DIR)) if os.path.isdir(CATALOG_DIR) else []:
        if fn.endswith(".json"):
            try:
                d = json.load(open(os.path.join(CATALOG_DIR, fn), encoding="utf-8"))
                out.append({"file": fn, "pack": d.get("pack"), "quizzes": len(d.get("quizzes", [])),
                            "enabled": d.get("enabled", True), "project": d.get("source_project")})
            except (OSError, ValueError):
                pass
    return out


def set_enabled(fn, enabled):
    p = os.path.join(CATALOG_DIR, os.path.basename(fn))
    d = json.load(open(p, encoding="utf-8"))
    d["enabled"] = bool(enabled)
    json.dump(d, open(p, "w", encoding="utf-8"), indent=1, ensure_ascii=False)


# ------------------------------------------------------------------------------ server
_PROC = None


def port_open(port, host="127.0.0.1"):
    s = socket.socket()
    s.settimeout(0.3)
    try:
        return s.connect_ex((host, port)) == 0
    finally:
        s.close()


def lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def port_in_use(port):
    """True if something is listening on the port - checked by trying to bind it, so the server
    never sees a connection (a connect-based check fills its log and opens Medius sessions)."""
    s = socket.socket()
    try:
        s.bind(("0.0.0.0", port))
        return False
    except OSError:
        return True
    finally:
        s.close()


def server_status():
    up = {p: port_in_use(p) for p in PORTS}
    tail = []
    if os.path.exists(SERVER_LOG):
        with open(SERVER_LOG, "rb") as f:
            f.seek(max(0, os.path.getsize(SERVER_LOG) - 4000))
            tail = f.read().decode("utf-8", "replace").splitlines()[-12:]
    return {"running": all(up.values()), "ports": up, "managed": _PROC is not None and _PROC.poll() is None,
            "lan_ip": lan_ip(), "hostname": HOSTNAME, "configured": bool(server_salt()), "log": tail}


def server_salt():
    from . import keys
    return os.environ.get("BUZZ_SVOMAC_SALT") or keys.load().get("svomac_salt")


def setup_server(eboot_elf):
    """Read the game values the server (and the pack builder) need from a decrypted EBOOT."""
    from . import keys
    return keys.setup_from_eboot(eboot_elf)


def start_server():
    global _PROC
    if server_status()["running"]:
        return server_status()
    if not server_salt():
        raise ValueError("server not set up yet: point setup at your decrypted EBOOT first")
    env = dict(os.environ, BUZZ_SVOMAC_SALT=server_salt())
    log = open(SERVER_LOG, "ab")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    _PROC = subprocess.Popen([sys.executable, SERVER], cwd=ROOT, env=env, stdout=log, stderr=log, creationflags=flags)
    return server_status()


def stop_server():
    global _PROC
    if _PROC is not None and _PROC.poll() is None:
        _PROC.terminate()
        _PROC.wait(10)
    _PROC = None
    return server_status()


# ------------------------------------------------------------------------------ player PC setup
def apply_login_fix(entries):
    """buzz_pak entries of GLOBALSCRIPTS -> same list with the login fix (no-op if already applied)."""
    from buzz_pak import Entry
    out = []
    for e in entries:
        if e.name == LOGIN_FIX["file"]:
            d = bytearray(e.data)
            o, n = LOGIN_FIX["offset"], len(LOGIN_FIX["orig"])
            cur = bytes(d[o:o + n])
            if cur == LOGIN_FIX["orig"]:
                d[o:o + n] = LOGIN_FIX["new"]
            elif cur != LOGIN_FIX["new"]:
                raise ValueError("unexpected initnetworkconnection script - is the game update v01.02 installed?")
            e = Entry(e.name, bytes(d), e.date_time, e.internal_attr, e.external_attr, e.volume)
        out.append(e)
    return out


LOGIN_PATCH = "Online: logged in when connected to the server"
OLD_LOGIN_PATCH = "Online: force IsLoggedIn true"      # 0.1.0 dev builds: crashed the menu with the server down
FPS_PATCH = "60 FPS (frame interval 1)"
# Our server can't complete the account login, so the game's own IsLoggedIn (network state ==
# LoggedIn) stays false. It now answers "has the server sent its URI list" instead (the URI store
# at [TOC+0x3080]+0x18, count at +4: 30-53 entries when connected, 0 when not). With the server
# down it stays false, so the game plays offline; forcing it true made the menu's advert code look
# up advertisingListURI_2009, get NULL and crash.
RPCS3_PATCHES = {
    LOGIN_PATCH: '''
  "Online: logged in when connected to the server":
    Games:
      "Buzz! Quiz World":
        BCES00645: [ 01.02 ]
    Author: "Buzz Toolkit"
    Notes: "Network.IsLoggedIn (0x1dd3a0) -> true only when the server has sent its URI list, so the game still boots and plays offline when the server is down."
    Patch Version: "1.1"
    Patch:
      - [ be32, 0x001dd3a0, 0x81223080 ]
      - [ be32, 0x001dd3a4, 0x81290018 ]
      - [ be32, 0x001dd3a8, 0x2f890000 ]
      - [ be32, 0x001dd3ac, 0x38600000 ]
      - [ be32, 0x001dd3b0, 0x4d9e0020 ]
      - [ be32, 0x001dd3b4, 0x80090004 ]
      - [ be32, 0x001dd3b8, 0x2f800000 ]
      - [ be32, 0x001dd3bc, 0x4d9e0020 ]
      - [ be32, 0x001dd3c0, 0x38600001 ]
      - [ be32, 0x001dd3c4, 0x4e800020 ]
''',
    FPS_PATCH: '''
  "60 FPS (frame interval 1)":
    Games:
      "Buzz! Quiz World":
        BCES00645: [ 01.02 ]
    Author: "Buzz Toolkit"
    Notes: "Frame interval 2 -> 1 (display init li r0,2 @0x26cbac; SetVsyncTo30 li r3,2 @0x22eab4)."
    Patch Version: "1.0"
    Patch:
      - [ be32, 0x0026cbac, 0x38000001 ]
      - [ be32, 0x0022eab4, 0x38600001 ]
''',
}


def _drop_patch(txt, name):
    """Remove one patch definition ('  "name":' up to the next top-level patch) from patch yml text."""
    m = re.search(r'\n  "%s":\n.*?(?=\n  "|\Z)' % re.escape(name), txt, re.S)
    return txt[:m.start()] + txt[m.end():] if m else txt


PPU_HASH = "PPU-35a27ffa1242df7b535018a03b360b3e351a1584"      # RPCS3's id for the v01.02 EBOOT


def _add_under_hash(txt, block):
    """Put a patch block (2-space indented) inside the game's PPU-hash section of an RPCS3 patch
    file (imported_patch.yml or patch_config.yml), creating the section if it isn't there."""
    header = PPU_HASH + ":"
    body = block.strip("\n").split("\n")
    lines = txt.rstrip("\n").split("\n") if txt.strip() else []
    if header not in lines:
        return "\n".join(lines + ([""] if lines else []) + [header] + body) + "\n"
    start = lines.index(header)
    end = start + 1
    while end < len(lines) and (not lines[end] or lines[end].startswith(" ")):
        end += 1
    while end - 1 > start and lines[end - 1] == "":
        end -= 1
    return "\n".join(lines[:end] + [""] + body + ([""] if end < len(lines) else []) + lines[end:]) + "\n"


def _enable_patch(patch_config, name):
    txt = open(patch_config, encoding="utf-8").read() if os.path.exists(patch_config) else ""
    if '"%s":' % name in txt:
        return
    block = '  "%s":\n    Buzz! Quiz World:\n      BCES00645:\n        01.02:\n          Enabled: true\n' % name
    open(patch_config, "w", encoding="utf-8").write(_add_under_hash(txt, block))


def _set_net(cfg_path, server_ip):
    """Set Internet Connected / PSN RPCN / IP swap list in an RPCS3 config's Net: section."""
    lines = open(cfg_path, encoding="utf-8").read().split("\n")
    want = {"Internet enabled": "Connected", "PSN status": "RPCN", "IP swap list": "%s=%s" % (HOSTNAME, server_ip)}
    try:
        start = lines.index("Net:")
    except ValueError:
        lines += ["Net:"] + ["  %s: %s" % kv for kv in want.items()]
        open(cfg_path, "w", encoding="utf-8").write("\n".join(lines))
        return
    end = start + 1
    while end < len(lines) and lines[end].startswith("  "):
        end += 1
    seen = set()
    for i in range(start + 1, end):
        k = lines[i].strip().split(":", 1)[0]
        if k in want:
            lines[i] = "  %s: %s" % (k, want[k])
            seen.add(k)
    lines[end:end] = ["  %s: %s" % (k, v) for k, v in want.items() if k not in seen]
    open(cfg_path, "w", encoding="utf-8").write("\n".join(lines))


def install_rpcs3_patches(rpcs3, fps60=True):
    """Our RPCS3 patches (online login, optional 60 FPS): defined in patches/imported_patch.yml and
    enabled in config/patch_config.yml, under the game's PPU-hash section."""
    pdir = os.path.join(rpcs3, "patches")
    os.makedirs(pdir, exist_ok=True)
    imported = os.path.join(pdir, "imported_patch.yml")
    txt = open(imported, encoding="utf-8").read() if os.path.exists(imported) else "Version: 1.2\n"
    new = _drop_patch(txt, OLD_LOGIN_PATCH)
    for name, block in RPCS3_PATCHES.items():
        if '"%s":' % name not in new:
            new = _add_under_hash(new, block)
    if new != txt:
        if os.path.exists(imported) and not os.path.exists(imported + ".before_buzz_toolkit"):
            shutil.copy(imported, imported + ".before_buzz_toolkit")
        open(imported, "w", encoding="utf-8").write(new)
    pc = os.path.join(rpcs3, "config", "patch_config.yml")
    if os.path.exists(pc):                                   # upgrade: keep it enabled under the new name
        cur = open(pc, encoding="utf-8").read()
        if OLD_LOGIN_PATCH in cur:
            open(pc, "w", encoding="utf-8").write(cur.replace('"%s"' % OLD_LOGIN_PATCH, '"%s"' % LOGIN_PATCH))
    _enable_patch(pc, LOGIN_PATCH)
    if fps60:
        _enable_patch(pc, FPS_PATCH)


def setup_pc(rpcs3, server_ip="127.0.0.1", fps60=True):
    """Prepare this PC's RPCS3 for online play against server_ip (127.0.0.1 = this PC hosts).
    Changes are backed up next to each file (*.before_buzz_toolkit)."""
    done = []
    game = os.path.join(rpcs3, "dev_hdd0", "game", "BCES00645", "USRDIR", "Patched", "GLOBALSCRIPTS.SDAT")
    if not os.path.exists(game):
        raise ValueError("game update not found (dev_hdd0/game/BCES00645/USRDIR/Patched) - install update 01.02 first")
    from buzz_pak import read_pak, write_pak
    backup = game + ".before_buzz_toolkit"
    if not os.path.exists(backup):
        shutil.copy(game, backup)
    entries = apply_login_fix(read_pak(game))
    write_pak(game, entries, tail_pad=16)
    done.append("login fix in GLOBALSCRIPTS")
    install_rpcs3_patches(rpcs3, fps60)
    done.append("RPCS3 patches (online login%s)" % (", 60 FPS" if fps60 else ""))
    custom = os.path.join(rpcs3, "config", "custom_configs", "config_BCES00645.yml")
    cfg = custom if os.path.exists(custom) else os.path.join(rpcs3, "config", "config.yml")
    if not os.path.exists(cfg + ".before_buzz_toolkit"):
        shutil.copy(cfg, cfg + ".before_buzz_toolkit")
    _set_net(cfg, server_ip)
    done.append("RPCS3 network: Internet on, PSN = RPCN, %s -> %s (%s)" % (HOSTNAME, server_ip, os.path.basename(cfg)))
    return done
