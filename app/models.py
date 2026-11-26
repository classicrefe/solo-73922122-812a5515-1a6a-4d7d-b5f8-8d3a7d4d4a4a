"""请求 / 响应的数据模型与录入校验。

音控录入: 原声语种、各译席(输出语种互异、能听懂的语种)、现有接线、要锁定的监听源。
"""
from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

MAX_BOOTHS = 16


class Booth(BaseModel):
    """一个译席: 输出语种全场互异, 另报自己能听懂的语种。"""

    id: str = Field(min_length=1, max_length=64, description="译席编号")
    output_language: str = Field(min_length=1, max_length=64, description="本席输出语种")
    understands: list[str] = Field(default_factory=list, description="本席能听懂的语种")


class Connection(BaseModel):
    """一条接线: 某译席监听某语种信号(原声语种或某席输出语种)。"""

    booth: str = Field(min_length=1, description="译席编号")
    source: str = Field(min_length=1, description="监听信号所承载的语种")


class PlanRequest(BaseModel):
    floor_language: str = Field(min_length=1, max_length=64, description="原声语种")
    booths: list[Booth] = Field(default_factory=list, max_length=MAX_BOOTHS)
    existing: list[Connection] = Field(default_factory=list, description="现有接线")
    locks: list[Connection] = Field(default_factory=list, description="要锁定的监听源")

    @model_validator(mode="after")
    def _check(self) -> "PlanRequest":
        ids = [b.id for b in self.booths]
        if len(ids) != len(set(ids)):
            raise ValueError("译席编号重复")

        outputs = [b.output_language for b in self.booths]
        if len(outputs) != len(set(outputs)):
            raise ValueError("各译席的输出语种必须互异")
        if self.floor_language in outputs:
            raise ValueError("译席输出语种不能与原声语种相同, 否则信号无法区分")

        known = set(ids)
        for conn in (*self.existing, *self.locks):
            if conn.booth not in known:
                raise ValueError(f"接线指向了未录入的译席: {conn.booth}")

        for label, conns in (("现有接线", self.existing), ("锁定", self.locks)):
            seen = [c.booth for c in conns]
            if len(seen) != len(set(seen)):
                raise ValueError(f"{label}中同一译席出现多次(每席只接一路信号)")
        return self
