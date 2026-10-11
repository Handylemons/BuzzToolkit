"""Character handling: what a pack must keep, and what it may tidy.

    python test_charset.py

The toolkit used to keep only code points below 256 and strip the rest to bare ASCII, which
turned WISLA into WISLA, and silently emptied Cyrillic and Greek questions. The game's string
tables store a 16-bit code point per character, so every script we target fits; the only reason
anything is dropped now is that it cannot be stored or drawn.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import buzz_text  # noqa: E402
from buzz_engine import content  # noqa: E402

# (name, input, expected after clean(uppercase=True))
CLEAN_CASES = [
    # tidying that must still happen
    ("html entity", "Tom &amp; Jerry", "TOM & JERRY"),
    ("smart quotes", "He said “hello”", 'HE SAID "HELLO"'),
    ("apostrophe", "it’s mine", "IT'S MINE"),
    ("dashes", "1939–1945 — war", "1939-1945 - WAR"),
    ("ellipsis", "wait…", "WAIT..."),
    ("nbsp and newlines", "a  b\n\tc", "A B C"),
    ("zero width", "a​b", "AB"),
    ("control chars", "a\x00b", "AB"),
    # letters that must survive
    ("ascii", "WHO WON IN 1966?", "WHO WON IN 1966?"),
    ("latin-1 accents", "café naïve", "CAFÉ NAÏVE"),
    ("spanish", "¿cuál montaña?", "¿CUÁL MONTAÑA?"),
    ("german sharp s", "straße", "STRASSE"),
    ("polish", "Wisłą leży", "WISŁĄ LEŻY"),
    ("czech", "město řeka", "MĚSTO ŘEKA"),
    ("croatian", "čuđenje", "ČUĐENJE"),
    ("cyrillic", "Какой город?", "КАКОЙ ГОРОД?"),
    ("greek drops tonos", "πόλη", "ΠΟΛΗ"),
    # what we still give up on
    ("emoji", "hi \U0001f600", "HI"),
]

ROUND_TRIP = [
    "WHO WROTE 'CAFÉ SOCIETY'?", "¿CUÁL ES LA MONTAÑA MÁS ALTA?",
    "OÙ SE TROUVE LE CHÂTEAU ?", "WIE GROSS IST DIE ZUGSPITZE? ÄÖÜ",
    "KTÓRE MIASTO LEŻY NAD WISŁĄ? ŚĆŹŻĘĄŃ", "KTERÉ MĚSTO LEŽÍ NA VLTAVĚ? ŘŠČŽŮ",
    "KOJI GRAD LEŽI NA SAVI? ČĆĐŠŽ", "КАКОЙ ГОРОД СТОИТ НА НЕВЕ?",
    "ΠΟΙΑ ΠΟΛΗ ΕΙΝΑΙ Η ΠΡΩΤΕΥΟΥΣΑ;",
]


def main():
    bad = 0
    print("clean():")
    for name, src, want in CLEAN_CASES:
        got = content.clean(src, uppercase=True)
        ok = got == want
        bad += not ok
        print("  %-20s %-5s %r%s" % (name, "ok" if ok else "FAIL", got,
                                     "" if ok else "   want %r" % want))

    print("\nround trip through the game's string tables:")
    hdr, hst = buzz_text.encode_all(ROUND_TRIP)
    back = [b[1] if isinstance(b, tuple) else b for b in buzz_text.decode_all(hdr, hst)]
    for want, got in zip(ROUND_TRIP, back):
        ok = want == got
        bad += not ok
        print("  %-5s %s" % ("ok" if ok else "FAIL", got))

    print("\n%s (%d failure%s)" % ("PASS" if not bad else "FAIL", bad, "" if bad == 1 else "s"))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
