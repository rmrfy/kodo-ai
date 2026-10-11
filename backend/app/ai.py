"""AI calls with structured outputs, explicit no-credit mock mode, and usage accounting."""
import json
from . import config

MODES = {
    "quick": "Focus only on clear, high-severity correctness and security defects. Return very few findings.",
    "standard": "Review for actionable correctness, security, edge cases, and behavioral risks.",
    "deep": "Trace interactions across changed files, edge cases, error handling, and regressions. Report only concrete findings.",
    "security": "Focus on exploitable security issues, trust boundaries, secrets, authorization, injection, and data exposure.",
}

class AIResult(dict):
    pass

def analyze(task: str, instructions: str, context: str, mode: str = "standard") -> AIResult:
    if config.AI_DISABLED or not config.OPENAI_API_KEY:
        if task == "pr":
            return AIResult(summary="AI is in mock mode. This pull request has been recorded; configure OpenAI to generate a source grounded summary and review.", findings=[])
        if task == "book_chapters":
            chapter_topics = [("architecture", "Architecture"), ("data_flow", "Data flow"), ("integrations", "Integrations"), ("business_logic", "Key business logic")]
            chapters = [{"topic": topic, "title": title, "summary": "Mock Repo Book chapter. Enable AI to generate repository grounded knowledge."} for topic, title in chapter_topics]
            return AIResult(chapters=chapters, input_tokens=0, output_tokens=0, model="mock", cost=0)
        return AIResult(summary=f"Mock Repo Book summary for {context[:500]}", input_tokens=0, output_tokens=0, model="mock", cost=0)
    from openai import OpenAI
    prompt = f"{instructions}\n\nReview mode: {MODES.get(mode, MODES['standard'])}\n\nRepository context:\n{context[:config.MAX_DIFF_CHARS]}"
    client = OpenAI(api_key=config.OPENAI_API_KEY)
    response = client.responses.create(model=config.OPENAI_MODEL, input=prompt, max_output_tokens=1200 if task == "pr" else 500)
    raw = response.output_text
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # Structured response prompt should be JSON; fail the job instead of publishing malformed content.
        raise ValueError("AI returned invalid JSON")
    usage = response.usage
    input_tokens = getattr(usage, "input_tokens", 0) if usage else 0
    output_tokens = getattr(usage, "output_tokens", 0) if usage else 0
    # Model pricing is deliberately configurable because provider pricing changes.
    in_rate = float(__import__('os').getenv("OPENAI_INPUT_USD_PER_MILLION", "0.10"))
    out_rate = float(__import__('os').getenv("OPENAI_OUTPUT_USD_PER_MILLION", "0.50"))
    return AIResult(**data, input_tokens=input_tokens, output_tokens=output_tokens, model=config.OPENAI_MODEL, cost=(input_tokens * in_rate + output_tokens * out_rate) / 1_000_000)

def pr_prompt(title: str, body: str, files: list[dict], book: list[str]) -> str:
    parts = []
    remaining = config.MAX_DIFF_CHARS
    for f in files:
        patch = f.get("patch") or ""
        chunk = f"\nFILE {f['filename']} ({f.get('status','modified')})\n{patch}\n"
        if remaining <= 0:
            break
        parts.append(chunk[:remaining]); remaining -= len(chunk)
    book_context = "\n".join(book)[:12000]
    return f"""Review pull request {title!r}. Description: {body[:3000]}\nRepository book context:\n{book_context}\nDiffs:\n{''.join(parts)}"""

PR_INSTRUCTIONS = """Return ONLY JSON: {\"summary\": string, \"findings\": [{\"path\": string, \"line\": integer, \"severity\": \"critical|high|medium|low\", \"title\": string, \"body\": string}]}.
Summary: explain what changed, why it matters, affected components, behavior and real risks. Findings must be concrete bugs/security issues introduced by these changes, with an actionable fix. Use only changed added lines for line; omit any issue you cannot map accurately. Avoid style opinions and speculation. At most 8 findings."""
