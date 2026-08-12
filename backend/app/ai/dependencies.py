from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.ai.gateway import ModelGateway
from app.db import get_session

SessionDependency = Annotated[Session, Depends(get_session)]


def get_model_gateway(session: SessionDependency) -> ModelGateway:
    return ModelGateway(session)
