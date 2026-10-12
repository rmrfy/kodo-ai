"""Select the configured coding-agent implementation."""
from .. import config
from .codex import CodexProvider


class CodingAgentConfigurationError(ValueError):
    pass


def get_coding_agent_provider(name: str | None = None):
    provider_name = (name if name is not None else config.CODING_AGENT_PROVIDER).strip().lower()
    if provider_name == "codex":
        return CodexProvider()
    if not provider_name:
        raise CodingAgentConfigurationError("KODO_CODING_AGENT_PROVIDER cannot be empty")
    raise CodingAgentConfigurationError(
        f"Unsupported coding agent provider '{provider_name}'. Supported providers: codex"
    )
