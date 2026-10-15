import unittest
import json
import io
import subprocess
import tempfile
from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock, call, patch

from app.ai import MODES, analyze, pr_prompt
from app.coding_agents import CodingAgentConfigurationError, CodingAgentRequest, CodingAgentSandbox, CodingAgentResult, get_coding_agent_provider
from app.coding_agents.codex import CodexProvider
from app.coding_tasks import _agent_result_with_change_state, _execute_coding_agent, _task_completion_summary
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
            workspace=workspace, repository="acme/project",
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
            output_events = [
                {"type": "turn.started"},
                {"type": "item.started", "item": {"type": "file_change"}},
                {"type": "item.completed", "item": {"type": "agent_message", "text": "Implemented it."}},
            ]

            def run_process(command, **kwargs):
                process = MagicMock(returncode=0, pid=82)
                process.stdin = MagicMock()
                process.stdin.write.side_effect = lambda text: setattr(self, "prompt", text)
                process.stdout = io.StringIO("".join(json.dumps(event) + "\n" for event in output_events))
                process.poll.return_value = 0
                self.command = command
                self.env = kwargs["env"]
                self.process = process
                return process

            progress = []
            request = self.request(workspace)
            request = replace(request, on_progress=progress.append)
            with patch("app.coding_agents.codex.shutil.which", return_value="/usr/bin/codex"), \
                 patch("app.coding_agents.codex.subprocess.Popen", side_effect=run_process):
                result = CodexProvider(cli_path="codex-test", api_key="test-key").execute(request)

            self.assertTrue(result.success)
            self.assertEqual(result.final_response, "Implemented it.")
            self.assertIsNone(result.changes_made)
            self.assertFalse(result.blocked)
            self.assertIn("--sandbox", self.command)
            self.assertIn("workspace-write", self.command)
            self.assertIn("sandbox_workspace_write.network_access=false", self.command)
            self.assertEqual(self.env["CODEX_API_KEY"], "test-key")
            self.assertNotIn("KODO_GIT_TOKEN", self.env)
            self.assertEqual(self.prompt.count("Implement the requested feature."), 1)
            self.assertEqual([event.stage for event in progress], ["thinking", "editing"])
            self.assertIn("Continue on the session PR branch kodo/add-feature-1.", self.prompt)

    def test_codex_normalizes_blocked_outcome_separately_from_response(self):
        self.assertTrue(CodexProvider._says_blocked("Could not complete.\nKODO_TASK_OUTCOME: BLOCKED"))
        self.assertFalse(CodexProvider._says_blocked("Answered the question.\nKODO_TASK_OUTCOME: COMPLETED"))

    def test_codex_failure_extracts_jsonl_error(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = Path(temp) / "workspace"
            workspace.mkdir()

            def run_process(command, **kwargs):
                process = MagicMock(returncode=1)
                process.stdin = MagicMock()
                process.stdout = io.StringIO(json.dumps({"type": "turn.failed", "error": {"message": "agent failed"}}) + "\n")
                process.poll.return_value = 1
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
            process.stdin = io.StringIO()
            process.stdout = io.StringIO()
            process.poll.return_value = None
            process.wait.side_effect = [subprocess.TimeoutExpired("codex", 10), None]
            with patch("app.coding_agents.codex.shutil.which", return_value="/usr/bin/codex"), \
                 patch("app.coding_agents.codex.subprocess.Popen", return_value=process), \
                 patch("app.coding_agents.codex.os.killpg") as killpg:
                result = CodexProvider(cli_path="codex-test", api_key="test-key").execute(self.request(workspace, timeout=0))
            self.assertFalse(result.success)
            self.assertIn("timed out", result.error)
            self.assertEqual(killpg.call_args_list, [call(812, 15), call(812, 9)])

    def test_task_orchestration_normalizes_change_state_from_git_workspace(self):
        result = CodingAgentResult(success=True, final_response="Done.")
        changes = json.dumps({"files": [{"status": "M", "path": "src/app.py", "patch": ""}]})
        normalized = _agent_result_with_change_state(result, changes)
        self.assertTrue(normalized.success)
        self.assertTrue(normalized.changes_made)
        self.assertEqual(normalized.final_response, "Done.")

    def test_task_orchestration_executes_provider_through_shared_contract(self):
        expected = CodingAgentResult(success=True, final_response="Implemented.")
        provider = MagicMock(name="test-provider", execute=MagicMock(return_value=expected))
        request = self.request(Path("/tmp/workspace"))
        self.assertIs(_execute_coding_agent(provider, request), expected)
        provider.execute.assert_called_once_with(request)

    def test_task_orchestration_propagates_normalized_provider_failure(self):
        provider = MagicMock(execute=MagicMock(return_value=CodingAgentResult(False, error="agent unavailable")))
        with self.assertRaisesRegex(RuntimeError, "agent unavailable"):
            _execute_coding_agent(provider, self.request(Path("/tmp/workspace")))

    def test_task_summary_preserves_agent_report_and_limits_length(self):
        summary = _task_completion_summary("Draft PR opened.", "Implemented the fix and ran focused checks.")
        self.assertIn("Draft PR opened.", summary)
        self.assertIn("ran focused checks", summary)
        from app.coding_agents.interface import MAX_CODING_AGENT_RESPONSE_CHARS
        self.assertLessEqual(
            len(_task_completion_summary("Done.", "x" * (MAX_CODING_AGENT_RESPONSE_CHARS + 100))),
            MAX_CODING_AGENT_RESPONSE_CHARS,
        )


if __name__ == "__main__":
    unittest.main()
