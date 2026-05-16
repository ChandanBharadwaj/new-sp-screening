from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import SessionLocal
from app.models.registry import ModelRegistry, get_models


async def db_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as s:
        yield s


def models(request: Request) -> ModelRegistry:
    reg = getattr(request.app.state, "models", None)
    if reg is None:
        reg = get_models()
        request.app.state.models = reg
    return reg
