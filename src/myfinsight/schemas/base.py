"""M00-02 스키마 공통 기반: 모든 모델은 오타 필드를 거부한다 (extra="forbid")."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class SchemaModel(BaseModel):
    """모든 도메인 스키마의 기반 모델."""

    model_config = ConfigDict(extra="forbid")
