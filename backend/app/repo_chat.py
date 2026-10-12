"""Keyword retrieval over generated Handbook notes for grounded repository chat."""
import math
import re
from collections import Counter

STOP_WORDS = {
    "about", "after", "also", "are", "does", "from", "have", "into", "its", "that", "the", "their",
    "them", "then", "there", "this", "what", "when", "where", "which", "with", "would", "your",
}
MAX_CONTEXT_CHARS = 24000

def retrieve_book_context(question: str, documents: list) -> list:
    """Rank the whole Handbook, returning a bounded set of relevant source notes."""
    terms = [term for term in re.findall(r"[a-zA-Z0-9_]+", question.lower()) if len(term) > 1 and term not in STOP_WORDS]
    term_frequency = Counter(terms)
    scored = []
    for doc in documents:
        title_path = f"{doc.title} {doc.path} {doc.kind}".lower()
        content = doc.content.lower()
        score = 0.0
        for term, query_count in term_frequency.items():
            title_hits = title_path.count(term)
            body_hits = content.count(term)
            if title_hits or body_hits:
                score += query_count * (4 * title_hits + min(body_hits, 5))
        if doc.kind in {"overview", "chapter", "section"}:
            score += 0.35
        scored.append((score, doc))

    # Always keep the overview and chapters available as broad context, then add
    # the strongest module/file matches for the specific question.
    broad = [doc for _, doc in sorted(scored, key=lambda row: (row[1].kind != "section", row[1].kind != "overview", row[1].kind != "chapter", -row[0])) if doc.kind in {"section", "overview", "chapter"}]
    ranked = [doc for score, doc in sorted(scored, key=lambda row: row[0], reverse=True) if score > 0 and doc.kind not in {"overview", "chapter"}]
    if not ranked:
        kind_order = {"section": 0, "module": 1, "file": 2, "overview": 3, "chapter": 4}
        ranked = [doc for _, doc in sorted(scored, key=lambda row: (kind_order.get(row[1].kind, 4), -len(row[1].content))) if doc.kind not in {"overview", "chapter"}]
    selected, seen, used = [], set(), 0
    for doc in [*broad[:5], *ranked[:10]]:
        if doc.id in seen:
            continue
        source_paths = []
        try:
            import json
            source_paths = json.loads(getattr(doc, "source_paths_json", "[]") or "[]")
        except (TypeError, ValueError):
            source_paths = []
        source = f"{doc.title} — {doc.path}" if doc.path else doc.title
        stale = " [STALE NOTE]" if doc.stale else ""
        path_note = f" — {', '.join(source_paths)}" if source_paths else ""
        prefix = f"[Handbook source: {source}{path_note}; kind: {doc.kind}{stale}]\n"
        remaining = MAX_CONTEXT_CHARS - used - len(prefix)
        if remaining <= 0:
            continue
        text = prefix + doc.content.strip()[:remaining]
        selected.append({"doc": doc, "source": source, "text": text})
        seen.add(doc.id)
        used += len(text)
        if len(selected) >= 12:
            break
    return selected

def conversation_prompt(repository: str, question: str, history: list[dict], sources: list[dict]) -> str:
    source_context = "\n\n".join(source["text"] for source in sources)
    prior_turns = "\n".join(f"{turn['role'].upper()}: {turn['content'][:2000]}" for turn in history[-10:])
    return f"""Repository: {repository}

Answer the user's question using only the Handbook excerpts below. These excerpts are generated notes about the repository, not a complete checkout of its source code. If they do not support an answer, say what is missing and suggest which area or file to inspect. Never invent implementation details. Mark stale notes as potentially out of date. For factual statements, cite the exact source title/path in square brackets, using the source label supplied below.

Relevant Handbook excerpts:
{source_context}

Recent conversation:
{prior_turns or '(No earlier messages)'}

User question:
{question}

Give a direct answer first, then explain the reasoning briefly. Use readable paragraphs and short lists when useful."""
