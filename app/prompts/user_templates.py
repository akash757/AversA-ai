from pathlib import Path
from typing import List, Optional
import re

from app.schemas.transcript_analysis import (
    ProjectQuestionInput,
    ParticipantInput,
    ExtractedItemOutput,
)

PROMPTS_DIR = Path(__file__).resolve().parent

# Load user templates as plain strings
_EXTRACTION_USER_TEMPLATE_PATH = PROMPTS_DIR / "transcript_extraction_user.md"
_FOLLOW_UP_USER_TEMPLATE_PATH = PROMPTS_DIR / "transcript_follow_up_user.md"

_EXTRACTION_USER_TEMPLATE = _EXTRACTION_USER_TEMPLATE_PATH.read_text(encoding="utf-8")
_FOLLOW_UP_USER_TEMPLATE = _FOLLOW_UP_USER_TEMPLATE_PATH.read_text(encoding="utf-8")

# Dangerous closing tags to neutralize
_CLOSING_TAGS_PATTERN = re.compile(
    r"</\s*(?:transcript|participants|open_questions|project_brief|existing_questions|extracted_items)\s*>",
    re.IGNORECASE,
)


def neutralize_tags(text: Optional[str]) -> str:
    """Removes or neutralizes closing XML-like tags to prevent prompt injection breakouts."""
    if not text:
        return ""
    return _CLOSING_TAGS_PATTERN.sub("< /neutralized_tag>", text)


def render_extraction_user_message(
    chunk_index: int,
    chunk_total: int,
    questions: List[ProjectQuestionInput],
    participants: List[ParticipantInput],
    chunk: str,
) -> str:
    """
    Renders extraction user message using .replace() on the raw template string.
    Never uses f-strings to prevent curly brace collision from transcript code/JSON.
    """
    if participants:
        p_lines = [
            f"{p.id} | {neutralize_tags(p.name)} | {p.party}"
            for p in participants
        ]
        p_text = "\n".join(p_lines)
    else:
        p_text = "(none)"

    if questions:
        q_lines = [
            f"{q.id} | {q.topic} | {neutralize_tags(q.text)}"
            for q in questions
        ]
        q_text = "\n".join(q_lines)
    else:
        q_text = "(none)"

    clean_chunk = neutralize_tags(chunk.strip()) if chunk else "(none)"

    msg = _EXTRACTION_USER_TEMPLATE
    msg = msg.replace("{chunk_index}", str(chunk_index))
    msg = msg.replace("{chunk_total}", str(chunk_total))
    msg = msg.replace("{participants}", p_text)
    msg = msg.replace("{open_questions}", q_text)
    msg = msg.replace("{transcript}", clean_chunk)
    return msg


def render_follow_up_user_message(
    brief: Optional[str],
    questions: List[ProjectQuestionInput],
    items: List[ExtractedItemOutput],
) -> str:
    """
    Renders follow-up user message using .replace() on the raw template string.
    Binds items to at most 100 items, highest confidence first.
    """
    # 1. Brief
    if brief and brief.strip():
        clean_brief = neutralize_tags(brief.strip())
    else:
        clean_brief = "(no brief provided)"

    # 2. Existing Questions: que_123 | features | answered | What must the first release include?
    if questions:
        q_lines = [
            f"{q.id} | {q.topic} | {q.status or 'pending'} | {neutralize_tags(q.text)}"
            for q in questions
        ]
        q_text = "\n".join(q_lines)
    else:
        q_text = "(none)"

    # 3. Extracted Items: sort highest confidence first, bounded to 100 items
    conf_order = {"high": 0, "medium": 1, "low": 2}
    sorted_items = sorted(items, key=lambda it: conf_order.get(it.confidence, 1))[:100]

    if sorted_items:
        i_lines = []
        for it in sorted_items:
            # Trim text to max 300 characters
            raw_text = neutralize_tags(it.text)
            trimmed_text = raw_text[:300] if len(raw_text) > 300 else raw_text

            if it.type == "answer":
                line = f"answer | {it.confidence} | {trimmed_text} | answers: {it.questionId or 'unknown'}"
            elif it.type == "action_item":
                parts = [f"action_item | {it.confidence} | {trimmed_text}"]
                if it.ownerName:
                    parts.append(f"owner: {neutralize_tags(it.ownerName)}")
                if it.duePhrase:
                    parts.append(f"due: {neutralize_tags(it.duePhrase)}")
                line = " | ".join(parts)
            elif it.type == "decision":
                line = f"decision | {it.confidence} | {trimmed_text}"
            elif it.type == "requirement":
                line = f"requirement | {it.confidence} | {trimmed_text}"
            else:
                line = f"{it.type} | {it.confidence} | {trimmed_text}"
            i_lines.append(line)
        i_text = "\n".join(i_lines)
    else:
        i_text = "(none)"

    msg = _FOLLOW_UP_USER_TEMPLATE
    msg = msg.replace("{brief}", clean_brief)
    msg = msg.replace("{existing_questions}", q_text)
    msg = msg.replace("{extracted_items}", i_text)
    return msg
