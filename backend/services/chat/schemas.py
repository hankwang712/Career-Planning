"""Shared constraints for model output and optional provider JSON schemas."""

import os
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


Text = Annotated[str, StringConstraints(min_length=1, max_length=1000)]


class ModelOutput(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", allow_inf_nan=False)


class Evidence(ModelOutput):
    message_id: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    quote: Annotated[str, StringConstraints(min_length=2, max_length=12000)]


class Candidate(ModelOutput):
    kind: Literal["fact", "preference", "communication"]
    key: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    subject: Annotated[str, StringConstraints(min_length=1, max_length=100)]
    value: Text
    operation: Literal["assert", "correct", "retract"]
    evidence: Annotated[list[Evidence], Field(min_length=1, max_length=5)]
    confidence: Annotated[float, Field(ge=0, le=1)]
    scope: Literal["user", "session"]


class ExtractionOutput(ModelOutput):
    memories: Annotated[list[Candidate], Field(max_length=20)]


class SummaryOutput(ModelOutput):
    summary: Annotated[str, StringConstraints(max_length=2500)]


class DecisionOutput(ModelOutput):
    operation: Literal["ADD", "NOOP", "ENRICH", "REPLACE", "CONFLICT", "RETRACT"]
    target_id: str | None
    value: Text
    reason: Annotated[str, StringConstraints(min_length=1, max_length=500)]
    requires_confirmation: bool


def response_format(output_model):
    """Opt in only for providers/models that support strict JSON schemas.

    JSON object mode remains the compatibility default; both modes are locally
    validated. An unsupported schema is an error, never a silent second call.
    """
    mode = os.environ.get("CHAT_MEMORY_OUTPUT_FORMAT", "json_object")
    if mode == "json_object":
        return {"type": mode}
    if mode != "json_schema":
        raise ValueError("CHAT_MEMORY_OUTPUT_FORMAT must be json_object or json_schema")
    return {"type": mode, "json_schema": {"name": output_model.__name__, "strict": True,
                                          "schema": output_model.model_json_schema()}}
