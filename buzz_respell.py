"""Respell Czech and Croatian text into Polish orthography for Chatterbox TTS.

Chatterbox Multilingual's Polish voice is used for languages it lacks (cs, hr);
the respelling makes a Polish reader pronounce the text close to the original.
"""

import re
import unicodedata

RESPELL = {"cs": "pl", "hr": "pl"}

_VOWELS = "aeiouyáéíóúůýě"
_V_CLASS = f"[{_VOWELS}]"

_PH_CZ_C = "\x01"
_PH_CZ_S = "\x02"
_PH_CZ_Z = "\x03"
_PH_CZ_U = "\x04"

_PH_HR_C = "\x05"
_PH_HR_S = "\x06"
_PH_HR_Z = "\x07"
_PH_HR_N = "\x08"


def _common(word: str) -> str:
    return (
        word.replace("č", "cz")
        .replace("š", "sz")
        .replace("ž", "ż")
        .replace("v", "w")
        .replace("á", "a")
        .replace("é", "e")
        .replace("í", "i")
        .replace("ó", "o")
        .replace("ú", "u")
        .replace("ý", "y")
    )


def _czech(word: str) -> str:
    # Protect original hard sibilant+i before rules create new "ci"/"zi".
    word = (
        word.replace("ci", _PH_CZ_C)
        .replace("cí", _PH_CZ_C)
        .replace("si", _PH_CZ_S)
        .replace("sí", _PH_CZ_S)
        .replace("zi", _PH_CZ_Z)
        .replace("zí", _PH_CZ_Z)
    )

    for src, dst in (
        ("dě", "dzie"),
        ("tě", "cie"),
        ("ně", "nie"),
        ("mě", "mnie"),
        ("bě", "bie"),
        ("pě", "pie"),
        ("vě", "wie"),
        ("fě", "fie"),
    ):
        word = word.replace(src, dst)
    word = word.replace("ě", "je")

    word = word.replace("ti", "ci").replace("tí", "ci")
    word = word.replace("di", "dzi").replace("dí", "dzi")

    word = (
        word.replace(_PH_CZ_C, "cy")
        .replace(_PH_CZ_S, "sy")
        .replace(_PH_CZ_Z, "zy")
    )

    word = word.replace("ř", "rz")

    word = re.sub(rf"ť(?={_V_CLASS})", "ci", word)
    word = word.replace("ť", "ć")

    word = re.sub(rf"ď(?={_V_CLASS})", "dzi", word)
    word = word.replace("ď", "dź")

    word = re.sub(rf"ň(?={_V_CLASS})", "ni", word)
    word = word.replace("ň", "ń")

    word = word.replace("ů", _PH_CZ_U)
    word = _common(word)
    word = word.replace(_PH_CZ_U, "ó")
    return word


def _croatian(word: str) -> str:
    word = word.replace("dž", "dż")

    # Protect original hard i before rules create new "ci"/"ni".
    word = (
        word.replace("ci", _PH_HR_C)
        .replace("si", _PH_HR_S)
        .replace("zi", _PH_HR_Z)
        .replace("ni", _PH_HR_N)
    )

    word = re.sub(rf"đ(?={_V_CLASS})", "dzi", word)
    word = word.replace("đ", "dź")

    word = re.sub(rf"ć(?={_V_CLASS})", "ci", word)

    word = re.sub(rf"lj(?={_V_CLASS})", "li", word)
    word = word.replace("lj", "l")

    word = re.sub(rf"nj(?={_V_CLASS})", "ni", word)
    word = word.replace("nj", "ń")

    word = (
        word.replace(_PH_HR_C, "cy")
        .replace(_PH_HR_S, "sy")
        .replace(_PH_HR_Z, "zy")
        .replace(_PH_HR_N, "ny")
    )

    word = re.sub(rf"(?<=[^{_VOWELS}])r(?=[^{_VOWELS}])", "yr", word)
    word = re.sub(rf"^r(?=[^{_VOWELS}])", "yr", word)

    return _common(word)


def _respell_word(word: str, iso: str) -> str:
    if len(word) > 1 and word.isupper():
        shape = "upper"
    elif word[0].isupper():
        shape = "capital"
    else:
        shape = "lower"

    lower = word.lower()
    if iso == "cs":
        lower = _czech(lower)
    else:
        lower = _croatian(lower)

    if shape == "upper":
        return lower.upper()
    if shape == "capital":
        return lower[:1].upper() + lower[1:]
    return lower


def respell(text: str, iso: str) -> str:
    text = unicodedata.normalize("NFC", text)
    if iso not in RESPELL:
        return text

    def repl(match):
        return _respell_word(match.group(0), iso)

    return re.sub(r"[^\W\d_]+", repl, text)


def prepare(text: str, iso: str) -> tuple[str, str]:
    if iso in RESPELL:           # digits would otherwise be read as Polish numbers
        import buzz_numbers
        text = buzz_numbers.spell_numbers(text, iso)
    return respell(text, iso), RESPELL.get(iso, iso)


if __name__ == "__main__":
    _tests = [
        ("cs", "Který řecký bůh vládl moři a zemětřesením?"),
        ("cs", "Kolik je čtyřicet tři plus dvacet osm?"),
        ("cs", "Ticho, děti! Cizí síla."),
        ("cs", "Ťapka, Ďábel, kůň"),
        ("hr", "Što je đumbir i gdje najčešće raste?"),
        ("hr", "Koliko županija ima Republika Hrvatska?"),
        ("hr", "Ljubav, kralj, njemački, sin"),
    ]
    for _iso, _text in _tests:
        print(f'{_iso} "{_text}" -> "{respell(_text, _iso)}"')
