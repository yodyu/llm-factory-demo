"""Compatible API clients. Importing this package performs no network I/O."""

from .checks import (
    CapabilityCheck,
    check_embedding,
    check_generation,
    validate_structured,
)
from .clients import LLMClient
from .config import EmbeddingProfile, LLMProfile, ModelEndpoint
from .transport import ModelCallError, OpenAITransport
from .ark import (
    ARK_CHAT_IDENTITY,
    ARK_MULTIMODAL_IDENTITY,
    ARK_STS_INSTRUCTIONS,
    ArkChatTransport,
    ArkMultimodalTransport,
)

__all__ = [
    "CapabilityCheck",
    "EmbeddingProfile",
    "LLMClient",
    "LLMProfile",
    "ModelCallError",
    "ModelEndpoint",
    "OpenAITransport",
    "check_embedding",
    "check_generation",
    "validate_structured",
    "ARK_CHAT_IDENTITY",
    "ARK_MULTIMODAL_IDENTITY",
    "ARK_STS_INSTRUCTIONS",
    "ArkChatTransport",
    "ArkMultimodalTransport",
]
