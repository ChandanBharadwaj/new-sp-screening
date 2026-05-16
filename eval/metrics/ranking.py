from __future__ import annotations


def _prefix_match(gold: str, candidate: str, n: int) -> bool:
    return bool(gold and candidate and len(gold) >= n and len(candidate) >= n and gold[:n] == candidate[:n])


def top_k_subheading(predictions: list[list[str]], gold: list[str], k: int) -> float:
    """Fraction of queries whose gold 6-digit code is in the top-K predictions."""
    if not predictions:
        return 0.0
    hits = 0
    for preds, g in zip(predictions, gold, strict=True):
        if any(p == g for p in preds[:k]):
            hits += 1
    return hits / len(gold)


def top_k_heading(predictions: list[list[str]], gold: list[str], k: int) -> float:
    if not predictions:
        return 0.0
    hits = 0
    for preds, g in zip(predictions, gold, strict=True):
        if any(_prefix_match(g, p, 4) for p in preds[:k]):
            hits += 1
    return hits / len(gold)


def top_k_chapter(predictions: list[list[str]], gold: list[str], k: int) -> float:
    if not predictions:
        return 0.0
    hits = 0
    for preds, g in zip(predictions, gold, strict=True):
        if any(_prefix_match(g, p, 2) for p in preds[:k]):
            hits += 1
    return hits / len(gold)


def mean_reciprocal_rank(predictions: list[list[str]], gold: list[str]) -> float:
    if not predictions:
        return 0.0
    total = 0.0
    for preds, g in zip(predictions, gold, strict=True):
        rr = 0.0
        for i, p in enumerate(preds, start=1):
            if p == g:
                rr = 1.0 / i
                break
        total += rr
    return total / len(gold)
