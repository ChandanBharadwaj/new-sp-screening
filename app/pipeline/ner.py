from typing import Any

from app.models.ner_model import NerModel


def extract(model: NerModel, text: str) -> dict[str, list[dict[str, Any]]]:
    """Structured NER output: {label: [{text, start, end, score}, ...]}."""
    return model.predict(text)


def flatten_to_text(
    structured: dict[str, list[dict[str, Any]]] | dict[str, list[str]],
) -> dict[str, list[str]]:
    """Strip span metadata so downstream consumers that only care about the
    surface form can keep working unchanged. Tolerates legacy
    `dict[label, list[str]]` shape so persisted historical entries don't
    crash on the next read."""
    out: dict[str, list[str]] = {}
    for label, items in (structured or {}).items():
        flat: list[str] = []
        for item in items:
            if isinstance(item, str):
                flat.append(item)
            elif isinstance(item, dict) and "text" in item:
                flat.append(str(item["text"]).lower())
        out[label] = flat
    return out
