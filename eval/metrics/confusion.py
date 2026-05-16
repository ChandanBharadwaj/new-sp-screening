from collections import Counter


def chapter_confusion(predictions: list[list[str]], gold: list[str]) -> dict[str, dict[str, int]]:
    """Returns nested dict gold_chapter -> predicted_chapter -> count (using top-1)."""
    matrix: dict[str, Counter[str]] = {}
    for preds, g in zip(predictions, gold, strict=True):
        if not g or len(g) < 2:
            continue
        gc = g[:2]
        pc = preds[0][:2] if preds and preds[0] else "??"
        matrix.setdefault(gc, Counter())[pc] += 1
    return {gc: dict(c) for gc, c in matrix.items()}


def hardest_pairs(matrix: dict[str, dict[str, int]], top_n: int = 10) -> list[dict]:
    """List the most-confused (gold, predicted) chapter pairs."""
    flat = []
    for gc, row in matrix.items():
        for pc, n in row.items():
            if pc != gc:
                flat.append({"gold_chapter": gc, "pred_chapter": pc, "count": n})
    flat.sort(key=lambda x: x["count"], reverse=True)
    return flat[:top_n]
