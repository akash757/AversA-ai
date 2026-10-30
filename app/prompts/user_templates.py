from pathlib import Path
from typing import List, Optional, Dict
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


def sanitize_line_field(text: Optional[str]) -> str:
    """
    Replaces '|' with '/' to prevent field separator spoofing,
    collapses internal whitespace and newlines to single spaces,
    and neutralizes closing tags.
    """
    if not text:
        return ""
    no_pipes = text.replace("|", "/")
    collapsed = re.sub(r"\s+", " ", no_pipes).strip()
    return neutralize_tags(collapsed)


def single_pass_substitute(template: str, mapping: Dict[str, str]) -> str:
    """
    Substitutes all placeholders in a single pass using regex callback.
    Prevents re-substitution attacks (e.g. participant named '{transcript}').
    """
    pattern = re.compile("|".join(re.escape(k) for k in mapping.keys()))
    return pattern.sub(lambda m: mapping[m.group(0)], template)


def render_extraction_user_message(
    chunk_index: int,
    chunk_total: int,
    questions: List[ProjectQuestionInput],
    participants: List[ParticipantInput],
    chunk: str,
) -> str:
    """
    Renders extraction user message using single-pass substitution.
    Never uses f-strings or sequential replace to prevent re-substitution or curly brace collisions.
    """
    if participants:
        p_lines = [
            f"{sanitize_line_field(p.id)} | {sanitize_line_field(p.name)} | {sanitize_line_field(p.party)}"
            for p in participants
        ]
        p_text = "\n".join(p_lines)
    else:
        p_text = "(none)"

    if questions:
        q_lines = [
            f"{sanitize_line_field(q.id)} | {sanitize_line_field(q.topic)} | {sanitize_line_field(q.text)}"
            for q in questions
        ]
        q_text = "\n".join(q_lines)
    else:
        q_text = "(none)"

    clean_chunk = neutralize_tags(chunk.strip()) if chunk else "(none)"

    mapping = {
        "{chunk_index}": str(chunk_index),
        "{chunk_total}": str(chunk_total),
        "{participants}": p_text,
        "{open_questions}": q_text,
        "{transcript}": clean_chunk,
    }
    return single_pass_substitute(_EXTRACTION_USER_TEMPLATE, mapping)


def render_follow_up_user_message(
    brief: Optional[str],
    questions: List[ProjectQuestionInput],
    items: List[ExtractedItemOutput],
) -> str:
    """
    Renders follow-up user message using single-pass substitution.
    Binds items to at most 100 items, highest confidence first, with collapsed whitespace.
    """
    # 1. Brief
    if brief and brief.strip():
        clean_brief = neutralize_tags(brief.strip())
    else:
        clean_brief = "(no brief provided)"

    # 2. Existing Questions: que_123 | features | answered | What must the first release include?
    if questions:
        q_lines = [
            f"{sanitize_line_field(q.id)} | {sanitize_line_field(q.topic)} | {sanitize_line_field(q.status or 'pending')} | {sanitize_line_field(q.text)}"
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
            # Trim text to max 300 characters with whitespace collapsed
            sanitized_text = sanitize_line_field(it.text)
            trimmed_text = sanitized_text[:300] if len(sanitized_text) > 300 else sanitized_text

            if it.type == "answer":
                line = f"answer | {it.confidence} | {trimmed_text} | answers: {sanitize_line_field(it.questionId) or 'unknown'}"
            elif it.type == "action_item":
                parts = [f"action_item | {it.confidence} | {trimmed_text}"]
                if it.ownerName:
                    parts.append(f"owner: {sanitize_line_field(it.ownerName)}")
                if it.duePhrase:
                    parts.append(f"due: {sanitize_line_field(it.duePhrase)}")
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

    mapping = {
        "{brief}": clean_brief,
        "{existing_questions}": q_text,
        "{extracted_items}": i_text,
    }
    return single_pass_substitute(_FOLLOW_UP_USER_TEMPLATE, mapping)
