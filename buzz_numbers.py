"""Spell out numbers for Czech and Croatian TTS."""

import re

_UNITS = ("nula", "jedan", "dva", "tri", "četiri", "pet", "šest", "sedam", "osam", "devet")
_TEENS = ("deset", "jedanaest", "dvanaest", "trinaest", "četrnaest", "petnaest", "šesnaest", "sedamnaest", "osamnaest", "devetnaest")
_TENS = ("", "", "dvadeset", "trideset", "četrdeset", "pedeset", "šezdeset", "sedamdeset", "osamdeset", "devedeset")
_HUNDREDS = ("", "sto", "dvjesto", "tristo", "četiristo", "petsto", "šesto", "sedamsto", "osamsto", "devetsto")

_DECIMAL_RE = r"(?P<dec_a>\d+)[,.](?P<dec_b>\d{1,2})(?!\d)"
_PERCENT_RE = r"(?P<pct>\d+) ?%"
_PLAIN_RE = r"(?<!\d)(?P<num>\d{1,9})(?!\d)"
_PATTERN = re.compile(f"(?:{_DECIMAL_RE})|(?:{_PERCENT_RE})|(?:{_PLAIN_RE})")


def _hr_below_1000(n: int) -> str:
    if n == 0:
        return "nula"
    parts = []
    h = n // 100
    if h:
        parts.append(_HUNDREDS[h])
    r = n % 100
    if r:
        if r < 10:
            parts.append(_UNITS[r])
        elif r < 20:
            parts.append(_TEENS[r - 10])
        else:
            t = r // 10
            u = r % 10
            parts.append(_TENS[t])
            if u:
                parts.append(_UNITS[u])
    return " ".join(parts)


def _hr(n: int) -> str:
    if n == 0:
        return "nula"

    parts = []

    millions = n // 1_000_000
    if millions:
        parts.append(_hr_below_1000(millions))
        last2 = millions % 100
        if 11 <= last2 <= 14:
            parts.append("milijuna")
        elif millions % 10 == 1:
            parts.append("milijun")
        else:
            parts.append("milijuna")

    remainder = n % 1_000_000
    thousands = remainder // 1000
    if thousands:
        if thousands == 1:
            parts.append("tisuću")
        else:
            words = _hr_below_1000(thousands).split()
            if words[-1] == "jedan":
                words[-1] = "jedna"
            elif words[-1] == "dva":
                words[-1] = "dvije"
            parts.append(" ".join(words))
            last2 = thousands % 100
            if 11 <= last2 <= 14:
                parts.append("tisuća")
            else:
                last = thousands % 10
                if last == 1:
                    parts.append("tisuća")
                elif last in (2, 3, 4):
                    parts.append("tisuće")
                else:
                    parts.append("tisuća")

    remainder %= 1000
    if remainder:
        parts.append(_hr_below_1000(remainder))

    return " ".join(parts)


def spell_numbers(text: str, iso: str) -> str:
    if iso not in ("cs", "hr"):
        return text

    if iso == "cs":
        from num2words import num2words

        def word(n: int) -> str:
            return num2words(n, lang="cs")

        decimal_sep = " celá "
        percent_suffix = " procent"
    else:
        def word(n: int) -> str:
            return _hr(n)

        decimal_sep = " zarez "
        percent_suffix = " posto"

    def repl(m: re.Match) -> str:
        if m.group("dec_a") is not None:
            return word(int(m.group("dec_a"))) + decimal_sep + word(int(m.group("dec_b")))
        if m.group("pct") is not None:
            return word(int(m.group("pct"))) + percent_suffix
        return word(int(m.group("num")))

    return _PATTERN.sub(repl, text)


if __name__ == "__main__":
    print(spell_numbers("1989", "hr"))
    print(spell_numbers("2008", "hr"))
    print(spell_numbers("366 dana", "hr"))
    print(spell_numbers("22000", "hr"))
    print(spell_numbers("21000", "hr"))
    print(spell_numbers("3,5", "hr"))
    print(spell_numbers("50 %", "hr"))
    print(spell_numbers("1000000", "hr"))
    print(spell_numbers("50", "cs"))
    print(spell_numbers("2008", "cs"))
    print(spell_numbers("3,5", "cs"))
    print(spell_numbers("10%", "cs"))
