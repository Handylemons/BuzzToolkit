"""Big Button buzzers: runs the bridge (buzz_bigbutton.py) from the Studio and maps RPCS3's players
to it. Switching off stops the bridge and puts the player's previous RPCS3 controller settings back.
"""
import contextlib
import importlib.util
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import buzz_bigbutton  # noqa: E402

from . import games  # noqa: E402

BRIDGE = os.path.join(ROOT, "buzz_bigbutton.py")
LOG = os.path.join(ROOT, "bigbutton.log")
STOP = os.path.join(ROOT, "bigbutton.stop")         # the bridge exits (releasing held keys) when this appears
_PROC = None


def running():
    return _PROC is not None and _PROC.poll() is None


def titles(rpcs3):
    """Buzz! builds RPCS3 has an input profile for (it makes one the first time a game runs)."""
    return [t for t in games.GAMES if os.path.isdir(os.path.join(rpcs3, "config", "input_configs", t))]


def receiver():
    """-> "ok", "running" (our bridge has it), "missing", "no_driver" or "no_library"."""
    if not (importlib.util.find_spec("usb") and importlib.util.find_spec("libusb_package")):
        return "no_library"
    if running():
        return "running"
    import libusb_package
    import usb.core
    import usb.util
    d = usb.core.find(idVendor=buzz_bigbutton.VID, idProduct=buzz_bigbutton.PID,
                      backend=libusb_package.get_libusb1_backend())
    if d is None:
        return "missing"
    try:                                  # libusb lists the receiver without WinUSB but can't open it
        d.set_configuration()
    except (usb.core.USBError, NotImplementedError):
        return "no_driver"
    finally:
        usb.util.dispose_resources(d)
    return "ok"


def _log_tail():
    if not os.path.exists(LOG):
        return []
    with open(LOG, "rb") as f:
        f.seek(max(0, os.path.getsize(LOG) - 4000))
        return f.read().decode("utf-8", "replace").splitlines()[-12:]


def status(rpcs3):
    ts = titles(rpcs3) if rpcs3 else []
    return {"running": running(), "receiver": receiver(), "titles": ts,
            "mapped": [t for t in ts if buzz_bigbutton.is_set_up(rpcs3, t)], "log": _log_tail()}


def _logged(fn, *args):
    """Run a buzz_bigbutton setup step with its messages going to the bridge log."""
    with open(LOG, "a", encoding="utf-8") as f, contextlib.redirect_stdout(f):
        try:
            return fn(*args)
        except SystemExit as e:          # the script reports problems as SystemExit(message)
            raise ValueError(str(e))


def _stop_leftover():
    """Stop a bridge started by an earlier Studio session (closing the Studio doesn't stop it)."""
    open(STOP, "w").close()
    for _ in range(30):                   # it deletes the file once it has released its keys
        if not os.path.exists(STOP):
            return True
        time.sleep(0.1)
    os.remove(STOP)
    return False


def start(rpcs3):
    global _PROC
    if running():
        return status(rpcs3)
    if not rpcs3:
        raise ValueError("set the RPCS3 folder first")
    ts = titles(rpcs3)
    if not ts:
        raise ValueError("open Buzz! once in RPCS3 first, so it has an input profile to map the pads into")
    problem = {"no_library": "the USB library is missing: run Install.bat again",
               "missing": "plug in the Big Button receiver",
               "no_driver": "install the WinUSB driver for the receiver with Zadig (see the README)"}
    r = receiver()
    if r == "no_driver":                  # or a bridge left over from an earlier session still has it
        _stop_leftover()
        r = receiver()
    if r in problem:
        raise ValueError(problem[r])
    for t in ts:
        if not buzz_bigbutton.is_set_up(rpcs3, t):
            _logged(buzz_bigbutton.setup, rpcs3, t)
    if os.path.exists(STOP):
        os.remove(STOP)
    log = open(LOG, "ab")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    _PROC = subprocess.Popen([sys.executable, "-u", BRIDGE, "--stop-file", STOP], cwd=ROOT,
                             stdout=log, stderr=log, creationflags=flags)
    return status(rpcs3)


def stop(rpcs3, restore=True):
    global _PROC
    if running():
        open(STOP, "w").close()
        try:
            _PROC.wait(3)
        except subprocess.TimeoutExpired:
            _PROC.terminate()
            _PROC.wait(5)
    else:
        _stop_leftover()
    _PROC = None
    if os.path.exists(STOP):
        os.remove(STOP)
    if restore and rpcs3:
        for t in titles(rpcs3):
            _logged(buzz_bigbutton.restore, rpcs3, t)
    return status(rpcs3)
