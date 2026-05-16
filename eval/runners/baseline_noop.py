"""No-op classifier — returns chapter 99 always. Used to anchor the baseline."""
from __future__ import annotations


class Classifier:
    name = "baseline_noop"

    async def classify(self, text: str) -> list[str]:
        return ["990000"]
