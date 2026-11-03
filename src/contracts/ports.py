"""Provider-independent model request/response envelopes."""
from pydantic import Field
from .base import Contract


class ModelRequest(Contract):
    task_id: str
    call_id: str
    profile_id: str
    messages: list[dict[str, str]]
    timeout_seconds: float
    remaining_required: int = Field(default=0, ge=0, le=8)

class ModelResponse(Contract):
    call_id: str
    text: str
    actual_model: str
    input_tokens: int | None
    output_tokens: int | None
    response_ref: str

class EmbeddingResponse(Contract):
    profile_id: str
    vectors: list[list[float]]
    input_tokens: int | None
