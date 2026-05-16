import re

ABBREV_EXPANSIONS = {
    r"\bw/\b": "with",
    r"\bw/o\b": "without",
    r"\bpcs\b": "pieces",
    r"\bqty\b": "quantity",
    r"\bmfg\b": "manufacturing",
    r"\bmach\b": "machinery",
    r"\bequip\b": "equipment",
    r"\bgds\b": "goods",
    r"\bcomp\b": "components",
    r"\bassy\b": "assembly",
    r"\bpkg\b": "package",
    r"\bcont\b": "containing",
    r"\bunfin\b": "unfinished",
    r"\bfin\b": "finished",
    r"\bss\b": "stainless steel",
    r"\bal\b": "aluminum",
    r"\bcu\b": "copper",
}

STOP_TOKENS = {"the", "a", "an", "of", "for", "to", "and", "or", "with"}

_punct_re = re.compile(r"[^\w\s/%.\-,]")
_ws_re = re.compile(r"\s+")


def normalize(text: str) -> str:
    if not text:
        return ""
    t = text.lower().strip()
    t = _punct_re.sub(" ", t)
    for pat, expansion in ABBREV_EXPANSIONS.items():
        t = re.sub(pat, expansion, t)
    tokens = [tok for tok in t.split() if tok and tok not in STOP_TOKENS]
    return _ws_re.sub(" ", " ".join(tokens)).strip()
