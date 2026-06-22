from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field, TypeAdapter


class Provenance(BaseModel):
    content_hash: str = ""
    origin: str
    raw_sha: str | None = None


class _Grouped(BaseModel):
    # filled by grouping.assign_groups (projection, not persisted) — §3.5
    step_id: int | None = None
    run_id: int | None = None
    provenance: Provenance | None = None


class MessageItem(_Grouped):
    type: Literal["message"] = "message"
    role: Literal["system", "user", "assistant", "developer"]
    content: str


class ReasoningItem(_Grouped):
    type: Literal["reasoning"] = "reasoning"
    content: str


class FunctionCallItem(_Grouped):
    type: Literal["function_call"] = "function_call"
    name: str
    arguments: str
    call_id: str


class FunctionCallOutputItem(_Grouped):
    type: Literal["function_call_output"] = "function_call_output"
    call_id: str
    output: str


Item = Annotated[
    Union[MessageItem, ReasoningItem, FunctionCallItem, FunctionCallOutputItem],
    Field(discriminator="type"),
]

_ItemAdapter = TypeAdapter(Item)


def parse_item(payload: dict, provenance: dict | None = None) -> Item:
    data = dict(payload)
    if provenance:
        data["provenance"] = provenance
    return _ItemAdapter.validate_python(data)


class Trajectory(BaseModel):
    content_hash: str
    items: list[Item]
    tools: list[dict] = Field(default_factory=list)
    meta: dict = Field(default_factory=dict)
