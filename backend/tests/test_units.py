import unittest
from unittest.mock import patch

from app.ai import MODES, analyze, pr_prompt
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


if __name__ == "__main__":
    unittest.main()
