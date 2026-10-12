import unittest
import json
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, call, patch

from app.ai import MODES, analyze, pr_prompt
from app.coding_agents import CodingAgentConfigurationError, CodingAgentRequest, CodingAgentSandbox, get_coding_agent_provider
from app.coding_agents.codex import CodexProvider
from app.jobs import _added_line_numbers


class ReviewHelpersTest(unittest.TestCase):
    def test_added_line_parser_ignores_context_and_removed_lines(self):
        patch_text = "@@ -4,3 +4,4 @@\n unchanged\n-removed\n+added one\n+added two\n"
        self.assertEqual(_added_line_numbers(patch_text), {5, 6})

    def test_modes_have_distinct_review_guidance(self):
        self.assertEqual(set(MODES), {"quick", "standard", "deep", "security"})
        self.assertNotEqual(MODES["quick"], MODES["security"])

    def test_mock_mode_never_constructs_openai_client(self):
        with patch("app.ai.config.AI_DISABLED", True), patch("app.ai.OpenAI", create=True) as client:
            result = analyze("pr", "instructions", "some diff", "quick")
            client.assert_not_called()
        self.assertIn("summary", result)
        self.assertEqual(result["findings"], [])

    def test_pr_context_is_bounded_and_includes_book(self):
        prompt = pr_prompt("Improve auth", "Details", [{"filename": "auth.py", "status": "modified", "patch": "-bad\n+good"}], ["module: authentication handles tokens"])
        self.assertIn("Improve auth", prompt)
        self.assertIn("auth.py", prompt)
        self.assertIn("authentication handles tokens", prompt)


class CodingAgentProviderTest(unittest.TestCase):
    def request(self, workspace, timeout=37):
        return CodingAgentRequest(
            workspace=workspace, repository="acme/project", task_title="Add a feature",
            instructions="Implement the requested feature.", project_context="Project context",
            previous_work="Earlier task summary", branch="kodo/add-feature-1",
            continue_existing_pr=True, timeout_seconds=timeout,
            sandbox=CodingAgentSandbox(workspace_write=True, network_access=False),
        )

    def test_provider_selection_uses_configured_default(self):
        with patch("app.coding_agents.factory.config.CODING_AGENT_PROVIDER", "codex"):
            provider = get_coding_agent_provider()
        self.assertIsInstance(provider, CodexProvider)
        self.assertEqual(provider.name, "codex")

    def test_unknown_provider_fails_with_supported_provider_message(self):
        with self.assertRaisesRegex(CodingAgentConfigurationError, "Supported providers: codex"):
            get_coding_agent_provider("claude")

    def test_invalid_configured_provider_fails_selection(self):
        with patch("app.coding_agents.factory.config.CODING_AGENT_PROVIDER", "custom"):
            with self.assertRaisesRegex(CodingAgentConfigurationError, "Unsupported coding agent provider 'custom'"):
                get_coding_agent_provider()

    def test_codex_execution_normalizes_response_and_preserves_security_flags(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = Path(temp) / "workspace"
            workspace.mkdir()
            output_event = {"type": "item.completed", "item": {"type": "agent_message", "text": "Implemented it."}}

            def run_process(command, **kwargs):
                kwargs["stdout"].write(json.dumps(output_event) + "\n")
                process = MagicMock(returncode=0)
                process.communicate.return_value = (None, None)
                self.command = command
                self.env = kwargs["env"]
                # The timeout belongs to communicate, so retain the process for its assertion below.
                self.process = process
                return process

            def communicate(prompt, timeout):
                self.prompt = prompt
                self.timeout = timeout
                return None, None

            def run_process_with_communicate(command, **kwargs):
                process = run_process(command, **kwargs)
                process.communicate.side_effect = communicate
                return process

            with patch("app.coding_agents.codex.shutil.which", return_value="/usr/bin/codex"), \
                 patch("app.coding_agents.codex.subprocess.Popen", side_effect=run_process_with_communicate):
                result = CodexProvider(cli_path="codex-test", api_key="test-key").execute(self.request(workspace))

            self.assertTrue(result.success)
            self.assertEqual(result.final_response, "Implemented it.")
            self.assertIsNone(result.changes_made)
            self.assertFalse(result.no_changes_needed)
            self.assertIn("--sandbox", self.command)
            self.assertIn("workspace-write", self.command)
            self.assertIn("sandbox_workspace_write.network_access=false", self.command)
            self.assertEqual(self.env["CODEX_API_KEY"], "test-key")
            self.assertNotIn("KODO_GIT_TOKEN", self.env)
            self.assertEqual(self.timeout, 37)
            self.assertIn("Continue on the session PR branch kodo/add-feature-1.", self.prompt)

    def test_codex_normalizes_no_change_outcome_without_claiming_workspace_state(self):
        message = "The requested code already exists.\nKODO_TASK_OUTCOME: NO_CHANGES_NEEDED"
        self.assertTrue(CodexProvider._says_no_changes_needed(message))
        self.assertFalse(CodexProvider._says_no_changes_needed("Implemented the feature."))

    def test_codex_failure_extracts_jsonl_error(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = Path(temp) / "workspace"
            workspace.mkdir()

            def run_process(command, **kwargs):
                kwargs["stdout"].write(json.dumps({"type": "turn.failed", "error": {"message": "agent failed"}}) + "\n")
                process = MagicMock(returncode=1)
                process.communicate.return_value = (None, None)
                return process

            with patch("app.coding_agents.codex.shutil.which", return_value="/usr/bin/codex"), \
                 patch("app.coding_agents.codex.subprocess.Popen", side_effect=run_process):
                result = CodexProvider(cli_path="codex-test", api_key="test-key").execute(self.request(workspace))
            self.assertFalse(result.success)
            self.assertIn("exit code 1", result.error)
            self.assertIn("agent failed", result.error)

    def test_codex_timeout_terminates_agent_process_group(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = Path(temp) / "workspace"
            workspace.mkdir()
            process = MagicMock(pid=812, returncode=-15)
            process.communicate.side_effect = subprocess.TimeoutExpired("codex", 37)
            process.wait.side_effect = [subprocess.TimeoutExpired("codex", 10), None]
            with patch("app.coding_agents.codex.shutil.which", return_value="/usr/bin/codex"), \
                 patch("app.coding_agents.codex.subprocess.Popen", return_value=process), \
                 patch("app.coding_agents.codex.os.killpg") as killpg:
                result = CodexProvider(cli_path="codex-test", api_key="test-key").execute(self.request(workspace))
            self.assertFalse(result.success)
            self.assertIn("timed out", result.error)
            self.assertEqual(killpg.call_args_list, [call(812, 15), call(812, 9)])


if __name__ == "__main__":
    unittest.main()
