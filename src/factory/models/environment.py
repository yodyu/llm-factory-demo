"""Explicit runtime-only provider configuration; never logs credentials."""
import os
from pathlib import Path
from contracts import content_hash


def load_environment(path):
    values = dict(os.environ)
    if path:
        allowed = {
            "FACTORY_MODEL_MODE",
            "LLM_BASE_URL",
            "LLM_API_KEY",
            "LLM_MODEL",
            "EMBEDDING_BASE_URL",
            "EMBEDDING_API_KEY",
            "EMBEDDING_MODEL",
            "EMBEDDING_DIMENSIONS",
            "LLM_TRANSPORT",
            "EMBEDDING_TRANSPORT",
        }
        for raw in Path(path).read_text().splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:]
            key, separator, value = line.partition("=")
            if not separator or key.strip() not in allowed:
                raise ValueError("model env file contains an unsupported entry")
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            if key.strip() == "FACTORY_MODEL_MODE" and value != "api":
                raise ValueError("API configuration requires explicit API mode")
            values[key.strip()] = value
    if values.get("FACTORY_MODEL_MODE", "api") != "api":
        raise ValueError("API configuration requires explicit API mode")
    if values.get("LLM_TRANSPORT", "openai") not in {"openai", "ark_chat"} or values.get(
        "EMBEDDING_TRANSPORT", "openai"
    ) not in {"openai", "ark_multimodal"}:
        raise ValueError("unsupported explicit model transport")
    return values

def transport_configuration(values, kind, endpoint):
    """Select an explicit wire protocol; never guess or fall back after errors."""
    from factory.models import ArkChatTransport, ArkMultimodalTransport
    from factory.models.transport import OpenAITransport

    selected = values.get("LLM_TRANSPORT" if kind == "llm" else "EMBEDDING_TRANSPORT", "openai")
    choices = {
        "llm": {"openai": OpenAITransport, "ark_chat": ArkChatTransport},
        "embedding": {"openai": OpenAITransport, "ark_multimodal": ArkMultimodalTransport},
    }
    if kind not in choices or selected not in choices[kind]:
        raise ValueError("unsupported explicit model transport")
    transport = choices[kind][selected](endpoint)
    return transport, getattr(transport, "identity", None)

def profile_identity(endpoint, model, *, dimensions=None, transport_identity=None):
    identity = {"endpoint": endpoint.base_url, "model": model}
    if dimensions is not None:
        identity["dimensions"] = dimensions
    if transport_identity is not None:
        identity["transport"] = transport_identity
    return content_hash(identity)[7:23]
