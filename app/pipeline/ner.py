from app.models.ner_model import NerModel


def extract(model: NerModel, text: str) -> dict[str, list[str]]:
    return model.predict(text)
