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
            chapters = [{"topic": topic, "title": title, "summary": "Mock Handbook chapter. Enable AI to generate repository grounded knowledge."} for topic, title in chapter_topics]
            return AIResult(chapters=chapters, input_tokens=0, output_tokens=0, model="mock", cost=0)
        if task == "repo_book_guide":
            return AIResult(sections=[], input_tokens=0, output_tokens=0, model="mock", cost=0)
        if task == "repo_book_files_batch":
            paths = [line.removeprefix("FILE: ").strip() for line in context.splitlines() if line.startswith("FILE: ")]
            return AIResult(files=[{"path": path, "summary": f"Mock file summary for {path}. Enable live AI to describe this source file."} for path in paths], input_tokens=0, output_tokens=0, model="mock", cost=0)
        if task == "repo_book_modules_batch":
            paths = [line.removeprefix("AREA: ").strip() for line in context.splitlines() if line.startswith("AREA: ")]
            return AIResult(modules=[{"path": path, "summary": f"Mock module summary for {path}. Enable live AI to describe this repository area."} for path in paths], input_tokens=0, output_tokens=0, model="mock", cost=0)
        return AIResult(summary=f"Mock Handbook summary for {context[:500]}", input_tokens=0, output_tokens=0, model="mock", cost=0)
    from openai import OpenAI
    prompt = f"{instructions}\n\nReview mode: {MODES.get(mode, MODES['standard'])}\n\nRepository context:\n{context[:config.MAX_DIFF_CHARS]}"
    client = OpenAI(api_key=config.OPENAI_API_KEY)
    output_limit = 1200 if task == "pr" else 6000 if task == "repo_book_guide" else 3000 if task == "repo_book_files_batch" else 2400 if task == "repo_book_modules_batch" else 500
    response = client.responses.create(model=config.OPENAI_MODEL, input=prompt, max_output_tokens=output_limit)
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

def answer_repo_question(repository: str, question: str, history: list[dict], sources: list[dict], maintainer_context: str = "") -> AIResult:
    if config.AI_DISABLED or not config.OPENAI_API_KEY:
        return AIResult(answer="Repository chat is in mock mode. Enable AI and configure an OpenAI API key to ask questions about this Handbook.", input_tokens=0, output_tokens=0, model="mock", cost=0)
    from openai import OpenAI
    from .repo_chat import conversation_prompt
    response = OpenAI(api_key=config.OPENAI_API_KEY).responses.create(
        model=config.OPENAI_MODEL,
        input=conversation_prompt(repository, question, history, sources, maintainer_context),
        max_output_tokens=1200,
    )
    usage = response.usage
    input_tokens = getattr(usage, "input_tokens", 0) if usage else 0
    output_tokens = getattr(usage, "output_tokens", 0) if usage else 0
    in_rate = float(__import__('os').getenv("OPENAI_INPUT_USD_PER_MILLION", "0.10"))
    out_rate = float(__import__('os').getenv("OPENAI_OUTPUT_USD_PER_MILLION", "0.50"))
    return AIResult(
        answer=response.output_text or "I couldn't produce an answer from the available Handbook notes.",
        input_tokens=input_tokens, output_tokens=output_tokens, model=config.OPENAI_MODEL,
        cost=(input_tokens * in_rate + output_tokens * out_rate) / 1_000_000,
    )

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
