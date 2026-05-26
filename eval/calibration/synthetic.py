"""Rule-based synthetic data for threshold calibration (item 3).

No LLM (README forbids LLM components). We perturb real held-out gold records three
ways, each with a known correct HS code so calibration can label was_top1_correct:

  (i)   drop_noun      — delete a content token; correct code unchanged (robustness).
  (ii)  in_chapter_swap — borrow another gold item's description from the SAME 2-digit
                          chapter; correct code = the borrowed item's code (hard negative
                          for the original).
  (iii) cross_chapter_swap — borrow from a DIFFERENT chapter (easy negative).

Synthetic examples are MIXED with the untouched real gold (the doc warns against
calibrating on synthetic only). The input gold should be a held-out split (dev), never
train, to avoid leakage with the LTR.
"""
from __future__ import annotations

import random

_STOP = {"the", "a", "an", "of", "and", "or", "for", "with", "to", "in", "on"}


def _chapter(code: str) -> str:
    return (code or "")[:2]


def _drop_noun(description: str, rng: random.Random) -> str | None:
    toks = description.split()
    content = [i for i, t in enumerate(toks) if t.lower() not in _STOP and len(t) > 2]
    if len(toks) < 3 or not content:
        return None
    drop = rng.choice(content)
    out = [t for i, t in enumerate(toks) if i != drop]
    return " ".join(out) if out else None


def build_synthetic(
    gold: list[dict],
    *,
    per_record: int = 1,
    seed: int = 42,
) -> list[dict]:
    """Return labeled examples: {"description", "hs_code", "kind"}.

    Includes the real gold (kind="real") plus perturbations. `gold` records must have
    "description" and "hs_code".
    """
    rng = random.Random(seed)
    gold = [g for g in gold if g.get("description") and g.get("hs_code")]
    by_chapter: dict[str, list[dict]] = {}
    for g in gold:
        by_chapter.setdefault(_chapter(g["hs_code"]), []).append(g)
    chapters = list(by_chapter)

    out: list[dict] = [{"description": g["description"], "hs_code": g["hs_code"], "kind": "real"} for g in gold]
    if len(gold) < 2 or len(chapters) < 2:
        return out

    for g in gold:
        ch = _chapter(g["hs_code"])
        for _ in range(per_record):
            mode = rng.choice(["drop_noun", "in_chapter_swap", "cross_chapter_swap"])
            if mode == "drop_noun":
                d = _drop_noun(g["description"], rng)
                if d:
                    out.append({"description": d, "hs_code": g["hs_code"], "kind": "drop_noun"})
            elif mode == "in_chapter_swap":
                peers = [p for p in by_chapter[ch] if p["hs_code"] != g["hs_code"]]
                if peers:
                    p = rng.choice(peers)
                    out.append({"description": p["description"], "hs_code": p["hs_code"], "kind": "in_chapter_swap"})
            else:  # cross_chapter_swap
                other = rng.choice([c for c in chapters if c != ch])
                p = rng.choice(by_chapter[other])
                out.append({"description": p["description"], "hs_code": p["hs_code"], "kind": "cross_chapter_swap"})
    return out
