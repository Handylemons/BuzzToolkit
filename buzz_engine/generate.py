"""One call from a pack project to an installable PKG: the engine's "Generate" button.

    from buzz_engine.generate import generate
    generate("content/packs/pub_quiz/pack.json", language="GBR", audio=True)

Steps: pick the host voice for the language (or build silent) -> build the pack (questions,
pictures, rounds, speech) -> encrypt (EDAT) -> wrap in a PKG for BCES00098. Output goes to
<project>/output/: <Title>_<LANG>_PACKnnnn.pkg (+ the EDAT, for manual copying).
"""
import json
import os
import re
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import build_pack  # noqa: E402
import buzz_pkg  # noqa: E402

from . import voices  # noqa: E402


def generate(project, language=None, audio=True, out_dir=None, progress=print, rpcs3=None,
             allow_replace=False):
    """rpcs3: the RPCS3 folder, to refuse a pack number another installed pack already has
    (allow_replace skips that check)."""
    import buzz_tools
    buzz_tools.ffmpeg()                                   # clear message if ffmpeg is missing
    from . import keys, pack_numbers
    keys.get("klic")                                      # ... and if setup hasn't read the game keys
    with open(project, encoding="utf-8") as f:
        C = json.load(f)
    clash = [] if allow_replace else pack_numbers.conflicts(C, rpcs3)
    if clash:
        raise RuntimeError("%s. Pick another pack number (step 1 in Buzz Pack Studio, free: %d)."
                           % ("; ".join(clash), pack_numbers.free_number(rpcs3)))
    lang = (language or C.get("language") or "GBR").upper()
    out_dir = out_dir or os.path.join(os.path.dirname(os.path.abspath(project)), "output")
    os.makedirs(out_dir, exist_ok=True)
    overrides = {"language": lang, "_out_dir": out_dir}
    voice_note = "no audio"
    if audio:
        # a pack whose content was ported from another title brings its own recordings, so say
        # where the audio really comes from rather than naming a voice model that never runs
        ported = C.get("speech_source")
        # only look for a TTS voice if the pack actually asks for one - a fully ported pack must
        # not quietly pull in a default voice model it never uses
        cfg = voices.voice_config(lang, C["voice"]) if C.get("voice") else None
        notes = []
        if ported:
            notes.append("original recordings from %s" % os.path.basename(ported["archive"]))
        if cfg:
            overrides["voice"] = cfg
            notes.append("host voice %s" % (cfg["clone"].get("model") or cfg["engine"].split(":", 1)[1]))
        else:
            overrides["voice"] = None
            if not ported:
                notes.append("no %s host voice on this machine - built without audio" % lang)
        voice_note = ", ".join(notes)
    else:
        overrides["voice"] = None
    progress("Building %s pack %d (%s, %s)" % (lang, C["pack_number"], C["text"]["menu_name"], voice_note))
    res = build_pack.build(os.path.abspath(project), overrides)
    progress("Pack built: %d files, %d questions in the main bank, %d voiced lines" % (
        res["files"], res["main bank"], res["voiced"]))
    edat = open(res["edat"], "rb").read()
    num = int(C["pack_number"])
    import unicodedata                                    # ČESKÝ KVÍZ -> CeskyKviz, not eskKvz
    plain = unicodedata.normalize("NFKD", C["text"]["menu_name"]).encode("ascii", "ignore").decode()
    title = re.sub(r"[^A-Za-z0-9]+", "", plain.title()) or "Pack"
    pkg_path = os.path.join(out_dir, "%s_%s_PACK%04d.pkg" % (title, lang, num))
    size = buzz_pkg.build_pack_pkg(pkg_path, res["content_id"], {"PACK%04d/%sPACK%04d.EDAT" % (num, lang, num): edat})
    os.remove(res["edat"].replace(".EDAT", ".DAT"))          # plain container: only needed while building
    progress("PKG ready: %s (%.1f MB)" % (pkg_path, size / 1e6))
    return {"pkg": pkg_path, "edat": res["edat"], "language": lang, "pack_number": num,
            "content_id": res["content_id"], "voiced": res["voiced"], "voice": voice_note}


def install_edat(edat_path, number, lang, rpcs3, allow_replace=False, dlc_title=None):
    """Copy the pack straight into RPCS3 (RPCS3's own PKG installer needs RPCS3 closed for the
    command line; File > Install Packages works any time). Refuses to replace a DIFFERENT pack
    with the same number (a newer build of the same pack is fine).

    The destination is created if it is not there, PARAM.SFO included: the DLC container is a
    game-data title, and a bare folder without that file leaves the game unable to resolve its
    DLC path at all. Which container depends on the build - the pack language picks it.
    """
    from . import games, pack_numbers
    _, dlc_title = (None, dlc_title) if dlc_title else games.resolve(lang=lang, rpcs3=rpcs3)
    new_cid = pack_numbers.edat_content_id(edat_path) or ""
    for cid in pack_numbers.installed(rpcs3, dlc_title).get(int(number), []):
        if not allow_replace and cid[-9:] != new_cid[-9:]:
            raise ValueError("pack %d is already installed in RPCS3 as a different pack (%s) - give this "
                             "pack another number and generate again" % (number, cid))
    games.ensure_dlc_container(rpcs3, dlc_title)
    d = os.path.join(rpcs3, "dev_hdd0", "game", dlc_title, "USRDIR", "PACK%04d" % number)
    os.makedirs(d, exist_ok=True)
    dst = os.path.join(d, "%sPACK%04d.EDAT" % (lang, number))
    if os.path.exists(dst):                              # never lose a pack already installed there
        shutil.copy(dst, dst + ".bak")
    shutil.copy(edat_path, dst)
    return dst
