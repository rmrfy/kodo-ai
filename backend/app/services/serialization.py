"""Serialization helpers for API responses and stored JSON fields."""
import json
from types import SimpleNamespace

from ..models import RepoBookSection, RepoChatMessage

def _chat_message_json(message: RepoChatMessage) -> dict:
    try:
        sources = json.loads(message.sources_json or "[]")
    except json.JSONDecodeError:
        sources = []
    return {"id": message.id, "role": message.role, "content": message.content, "sources": sources, "created_at": message.created_at.isoformat()}

def _json_list(value: str) -> list:
    try:
        data = json.loads(value or "[]")
        return data if isinstance(data, list) else []
    except (TypeError, json.JSONDecodeError):
        return []

def _section_for_retrieval(section: RepoBookSection):
    blocks = _json_list(section.blocks_json)
    parts = [section.summary]
    for block in blocks:
        if not isinstance(block, dict): continue
        if block.get("type") in {"paragraph", "callout"}:
            parts.append(f"{block.get('label', '')}: {block.get('text', '')}".strip(": "))
        elif block.get("type") in {"bullets", "steps"}:
            parts.extend(str(value) for value in block.get("items", []))
        elif block.get("type") == "table":
            parts.extend(" | ".join(str(value) for value in [*block.get("columns", []), *row]) for row in block.get("rows", []))
    return SimpleNamespace(
        id=f"section-{section.id}", kind="section", title=section.title, path="",
        content="\n".join(parts), stale=section.stale, source_paths_json=section.source_paths_json,
    )
