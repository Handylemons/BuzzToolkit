"""Xbox 360 Big Button pads (Scene It) as Buzz! buzzers in RPCS3.

    python buzz_bigbutton.py                     run the bridge (leave it running while you play)
    python buzz_bigbutton.py --setup <rpcs3> [--title BCES00645]   map RPCS3 players 1-4 for Buzz! (backed up)
    python buzz_bigbutton.py --test              print presses, send no keys

Needs the Big Button IR receiver (USB 045E:02A0) on the WinUSB driver (install it once with Zadig),
plus `pip install pyusb libusb-package`.

How it works: the receiver sends a 5-byte report "00 05 <pad> <buttons1> <buttons2>" (Xbox 360
button bits) in bursts of four every ~0.2 s while a button is held, and nothing on release. So a
button counts as pressed on its first report and as released 0.3 s after its last one. Each pad
(0-3) drives its own set of keyboard keys; RPCS3's keyboard players 1-4 use those keys, and RPCS3's
Buzz! emulation (1 controller = 4 buzzers) turns players 1-4 into buzzers 1-4:
  big button -> R1 (red buzzer)   X blue -> Triangle (blue)   B red -> Square (orange)
  A green -> Circle (green)       Y yellow -> Cross (yellow)  Start/Back/D-pad -> menus
"""
import ctypes
import os
import re
import shutil
import sys
import time

VID, PID = 0x045E, 0x02A0
RELEASE_AFTER = 0.30          # seconds without a report before a held button counts as released

# report bits: (byte index, mask) -> pad button name
BITS = {(4, 0x08): "big", (4, 0x10): "A", (4, 0x20): "B", (4, 0x40): "X", (4, 0x80): "Y",
        (3, 0x01): "up", (3, 0x02): "down", (3, 0x04): "left", (3, 0x08): "right",
        (3, 0x10): "start", (3, 0x20): "back"}
# pad button -> PS3 button used by RPCS3's Buzz! emulation (config/buzz.yml defaults)
PS3 = {"big": "R1", "X": "Triangle", "B": "Square", "A": "Circle", "Y": "Cross",
       "start": "Start", "back": "Select", "up": "Up", "down": "Down", "left": "Left", "right": "Right"}
# per pad: keys (Qt key names, as RPCS3 stores them) for big, X, B, A, Y, start, back
PAD_KEYS = [
    ["1", "2", "3", "4", "5", "6", "7"],
    ["Q", "W", "E", "R", "T", "Y", "U"],
    ["A", "S", "D", "F", "G", "H", "J"],
    ["Z", "X", "C", "V", "B", "N", "M"],
]
ORDER = ["big", "X", "B", "A", "Y", "start", "back"]
ARROWS = {"up": "Up", "down": "Down", "left": "Left", "right": "Right"}      # shared by all pads

# Windows set-1 scan codes; arrows are extended keys
SCAN = {"1": 0x02, "2": 0x03, "3": 0x04, "4": 0x05, "5": 0x06, "6": 0x07, "7": 0x08,
        "Q": 0x10, "W": 0x11, "E": 0x12, "R": 0x13, "T": 0x14, "Y": 0x15, "U": 0x16,
        "A": 0x1E, "S": 0x1F, "D": 0x20, "F": 0x21, "G": 0x22, "H": 0x23, "J": 0x24,
        "Z": 0x2C, "X": 0x2D, "C": 0x2E, "V": 0x2F, "B": 0x30, "N": 0x31, "M": 0x32,
        "Up": 0x48, "Down": 0x50, "Left": 0x4B, "Right": 0x4D}
EXTENDED = {"Up", "Down", "Left", "Right"}


def key_for(pad, button):
    if button in ARROWS:
        return ARROWS[button]
    return PAD_KEYS[pad][ORDER.index(button)] if 0 <= pad < 4 and button in ORDER else None


# ------------------------------------------------------------------------------ key output
class _KI(ctypes.Structure):
    _fields_ = [("wVk", ctypes.c_ushort), ("wScan", ctypes.c_ushort), ("dwFlags", ctypes.c_ulong),
                ("time", ctypes.c_ulong), ("dwExtraInfo", ctypes.c_size_t)]


class _INPUT(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [("ki", _KI), ("pad", ctypes.c_byte * 32)]
    _anonymous_ = ("u",)
    _fields_ = [("type", ctypes.c_ulong), ("u", _U)]


def send_key(name, down):
    flags = 0x0008 | (0 if down else 0x0002) | (0x0001 if name in EXTENDED else 0)   # SCANCODE, KEYUP, EXTENDED
    inp = _INPUT(type=1)
    inp.ki = _KI(0, SCAN[name], flags, 0, 0)
    ctypes.windll.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))


# ------------------------------------------------------------------------------ receiver
def open_receiver():
    import usb.core
    import usb.util
    import libusb_package
    d = usb.core.find(idVendor=VID, idProduct=PID, backend=libusb_package.get_libusb1_backend())
    if d is None:
        raise SystemExit("Big Button receiver (USB 045E:02A0) not found - is it plugged in, with the "
                         "WinUSB driver installed (Zadig)?")
    try:
        d.set_configuration()
        usb.util.claim_interface(d, 0)
    except usb.core.USBError as e:
        raise SystemExit("Can't open the receiver (%s). Close any other program using it; if it keeps "
                         "happening, reinstall the WinUSB driver with Zadig." % e)
    return d


def _release_all(held, test):
    for k in held:
        key = key_for(*k)
        if key and not test:
            send_key(key, False)


def run(test=False, stop_file=None):
    """stop_file: the Studio asks the bridge to stop by creating this file, so held keys are
    released properly instead of staying down when the process is killed."""
    import usb.core
    d = open_receiver()
    held = {}                                # (pad, button) -> time of last report
    print("Big Button bridge running%s. Press Ctrl+C to stop." % (" (test mode, no keys)" if test else ""),
          flush=True)
    try:
        while True:
            if stop_file and os.path.exists(stop_file):
                _release_all(held, test)
                os.remove(stop_file)
                print("stopped", flush=True)
                return
            try:
                r = bytes(d.read(0x81, 32, timeout=20))
            except usb.core.USBTimeoutError:
                r = b""
            now = time.time()
            if len(r) >= 5 and r[1] == 0x05:
                pad = r[2]
                for (i, mask), button in BITS.items():
                    if r[i] & mask:
                        k = (pad, button)
                        if k not in held:
                            key = key_for(pad, button)
                            print("pad %d %-5s down -> %s" % (pad + 1, button, key or "(unmapped)"), flush=True)
                            if key and not test:
                                send_key(key, True)
                        held[k] = now
            for k, t in list(held.items()):
                if now - t > RELEASE_AFTER:
                    del held[k]
                    key = key_for(*k)
                    if key and not test:
                        send_key(key, False)
    except KeyboardInterrupt:
        _release_all(held, test)
        print("stopped")


# ------------------------------------------------------------------------------ RPCS3 setup
KEY_FIELDS = ["Left Stick Left", "Left Stick Down", "Left Stick Right", "Left Stick Up", "Right Stick Left",
              "Right Stick Down", "Right Stick Right", "Right Stick Up", "Start", "Select", "PS Button",
              "Square", "Cross", "Circle", "Triangle", "Left", "Down", "Right", "Up",
              "R1", "R2", "R3", "L1", "L2", "L3"]


def player_block(template, player, pad):
    """A keyboard player block for Big Button pad `pad`, from any keyboard player block."""
    keys = {PS3[b]: key_for(pad, b) for b in ORDER + list(ARROWS)}
    out = re.sub(r"^Player \d+ Input:", "Player %d Input:" % player, template, flags=re.M)
    out = re.sub(r"^  Handler: .*$", "  Handler: Keyboard", out, flags=re.M)
    out = re.sub(r"^  Device: .*$", "  Device: Keyboard", out, flags=re.M)
    for f in KEY_FIELDS:
        v = keys.get(f, "")
        out = re.sub(r"^    %s: .*$" % re.escape(f), "    %s: %s" % (f, v if v else '""'), out, flags=re.M)
    return out


def _files(rpcs3, title):
    """The files setup() changes: the title's input profile, then its custom config, then config.yml."""
    c = os.path.join(rpcs3, "config")
    return [os.path.join(c, "input_configs", title, "Default.yml"),
            os.path.join(c, "custom_configs", "config_%s.yml" % title), os.path.join(c, "config.yml")]


def is_set_up(rpcs3, title="BCES00645"):
    return os.path.exists(_files(rpcs3, title)[0] + ".before_bigbutton")


def restore(rpcs3, title="BCES00645"):
    """Undo setup(): put back every file it backed up. -> names of the files restored."""
    done = []
    for f in _files(rpcs3, title):
        if os.path.exists(f + ".before_bigbutton"):
            shutil.copy(f + ".before_bigbutton", f)
            os.remove(f + ".before_bigbutton")
            done.append(os.path.basename(f))
    if done:
        print("%s: previous RPCS3 controller settings restored (%s)" % (title, ", ".join(done)))
    return done


def setup(rpcs3, title="BCES00645"):
    cfg = _files(rpcs3, title)[0]
    if not os.path.exists(cfg):
        raise SystemExit("no Buzz! input profile at %s - open Buzz! once in RPCS3 first" % cfg)
    txt = open(cfg, encoding="utf-8").read()
    blocks = re.split(r"(?m)^(?=Player \d+ Input:)", txt)
    head, blocks = blocks[0], blocks[1:]
    template = next((b for b in blocks if re.search(r"(?m)^  Handler: Keyboard$", b)), None)
    if template is None:
        raise SystemExit("no keyboard player in the Buzz! profile to copy from - set one player to "
                         "Keyboard in RPCS3's pad settings once, then run this again")
    backup = cfg + ".before_bigbutton"
    if not os.path.exists(backup):
        shutil.copy(cfg, backup)
    for i in range(4):
        blocks[i] = player_block(template, i + 1, i)
    open(cfg, "w", encoding="utf-8").write(head + "".join(blocks))
    print("%s: RPCS3 Buzz! players 1-4 now use the Big Button pads (backup: %s)" % (title, os.path.basename(backup)))
    for c in _files(rpcs3, title)[1:]:
        if os.path.exists(c):
            t = open(c, encoding="utf-8").read()
            if re.search(r"(?m)^  Buzz emulated controller: .*$", t):
                if not os.path.exists(c + ".before_bigbutton"):
                    shutil.copy(c, c + ".before_bigbutton")
                t = re.sub(r"(?m)^  Buzz emulated controller: .*$", "  Buzz emulated controller: 1 controller", t)
                open(c, "w", encoding="utf-8").write(t)
                print("%s: Buzz! emulation set to 1 controller (4 buzzers) in %s" % (title, os.path.basename(c)))
                break


if __name__ == "__main__":
    def arg(name, default=None):
        return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default
    if "--setup" in sys.argv:
        setup(arg("--setup"), arg("--title", "BCES00645"))
    else:
        run(test="--test" in sys.argv, stop_file=arg("--stop-file"))
