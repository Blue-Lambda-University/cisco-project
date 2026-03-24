"""
Formats chat history for routing and subagent prompts.

Keeps the last RECENT_TURNS (default 15) messages in full. If the history
API later provides a summary (via SUMMARY_PREFIX), it is preserved and
prepended to the recent turns so routing and subagents see full context.
"""

import logging
from typing import List, Optional, Any

from .properties import RECENT_TURNS

logger = logging.getLogger(__name__)

SUMMARY_PREFIX = "Previous conversation summary:"


def format_history_for_prompt(
    history: List[Any],
    max_messages: int = RECENT_TURNS,
    max_content_chars: int = 200,
) -> tuple[str, list[dict[str, str]]]:
    """
    Format conversation history for routing prompts or subagent context.

    When the first message has SUMMARY_PREFIX, it is kept in full and the rest
    are limited to the last max_messages. Content is truncated per message.

    Args:
        history: List of messages (LangChain-style or dict with role/content).
        max_messages: Max number of non-summary turns to include.
        max_content_chars: Max characters per message content (summary not truncated).

    Returns:
        (formatted_text, structured_list) where structured_list is
        [{"role": "user"|"assistant", "content": "..."}, ...].
    """
    if not history:
        return "", []

    messages_to_turns = list(history)
    summary: Optional[str] = None
    first = messages_to_turns[0]
    content = getattr(first, "content", None) or (
        first.get("content", "") if isinstance(first, dict) else ""
    )
    if content and str(content).strip().startswith(SUMMARY_PREFIX):
        summary = str(content).strip()
        messages_to_turns = messages_to_turns[1:]

    recent = (
        messages_to_turns[-max_messages:]
        if len(messages_to_turns) > max_messages
        else messages_to_turns
    )

    lines: List[str] = []
    structured: List[dict[str, str]] = []

    if summary:
        lines.append(summary)
        structured.append({"role": "user", "content": summary})

    for msg in recent:
        if hasattr(msg, "content"):
            raw = getattr(msg, "content", None)
            content = raw if isinstance(raw, str) else str(raw) if raw is not None else ""
            role = "user" if getattr(msg, "type", None) == "human" or msg.__class__.__name__ == "HumanMessage" else "assistant"
        elif isinstance(msg, dict) and "role" in msg and "content" in msg:
            role = msg["role"]
            content = str(msg["content"])
        else:
            continue

        if len(content) > max_content_chars:
            content = content[:max_content_chars] + "..."
        label = "User" if role == "user" else "Assistant"
        lines.append(f"{label}: {content}")
        structured.append({"role": role, "content": content})

    return "\n".join(lines), structured
