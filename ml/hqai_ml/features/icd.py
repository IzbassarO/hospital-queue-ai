"""ICD-10 chapter of a code (WHO ICD-10 block boundaries)."""
import re

# (first code, last code, chapter) — codes compared as letter + 2 digits
_CHAPTERS = [
    ("A00", "B99", "I"), ("C00", "D48", "II"), ("D50", "D89", "III"), ("E00", "E90", "IV"),
    ("F00", "F99", "V"), ("G00", "G99", "VI"), ("H00", "H59", "VII"), ("H60", "H95", "VIII"),
    ("I00", "I99", "IX"), ("J00", "J99", "X"), ("K00", "K93", "XI"), ("L00", "L99", "XII"),
    ("M00", "M99", "XIII"), ("N00", "N99", "XIV"), ("O00", "O99", "XV"), ("P00", "P96", "XVI"),
    ("Q00", "Q99", "XVII"), ("R00", "R99", "XVIII"), ("S00", "T98", "XIX"), ("V01", "Y98", "XX"),
    ("Z00", "Z99", "XXI"), ("U00", "U99", "XXII"),
]
_CODE = re.compile(r"^([A-Z])(\d{2})")


def icd3(code: str | None) -> str | None:
    m = _CODE.match(code or "")
    return f"{m.group(1)}{m.group(2)}" if m else None


def icd_chapter(code: str | None) -> str | None:
    c = icd3(code)
    if c is None:
        return None
    for first, last, chapter in _CHAPTERS:
        if first <= c <= last:
            return chapter
    return None
