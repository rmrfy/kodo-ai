"""Small shared contract between task orchestration and coding agents."""
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol


@dataclass(frozen=True)
class CodingAgentSandbox:
    """Minimum execution restrictions required by kodai's task runner."""

    workspace_write: bool = True
    network_access: bool = False


@dataclass(frozen=True)
class CodingAgentProgress:
    """Provider-neutral progress that is safe to report in application logs/UI."""

    stage: str
    message: str


@dataclass(frozen=True)
class CodingAgentRequest:
    """Task and workspace data that can be provided to any coding agent."""

    workspace: Path
    repository: str
    task_title: str
    instructions: str
    project_context: str
    previous_work: str
    branch: str
    continue_existing_pr: bool
    timeout_seconds: int
    sandbox: CodingAgentSandbox = CodingAgentSandbox()
    on_progress: Callable[[CodingAgentProgress], None] | None = None


@dataclass(frozen=True)
class CodingAgentResult:
    """Normalized execution outcome; changes_made may be unknown to an agent."""

    success: bool
    final_response: str = ""
    error: str = ""
    changes_made: bool | None = None
    no_changes_needed: bool = False


class CodingAgentProvider(Protocol):
    name: str

    def execute(self, request: CodingAgentRequest) -> CodingAgentResult:
        """Run an agent in the supplied workspace and normalize its outcome."""
