import pytest
from datetime import datetime
from zoneinfo import ZoneInfo
from pydantic import ValidationError

from app.schemas.transcript_analysis import (
    TranscriptAnalysisRequest,
    ProjectQuestionInput,
    ParticipantInput,
    RawLLMExtractedItem,
    RawChunkExtractionLLMResponse,
    RawLLMFollowUpQuestion,
    RawFollowUpLLMResponse,
    ExtractedItemOutput,
    FollowUpQuestionOutput,
    TranscriptAnalysisResponse,
)
from app.utils.date_resolver import resolve_due_date


def test_duplicate_question_ids_rejected():
    with pytest.raises(ValidationError) as exc:
        TranscriptAnalysisRequest(
            projectId="p1",
            transcriptId="t1",
            chunks=["[1] John (client): Hello"],
            questions=[
                ProjectQuestionInput(id="q1", topic="problem", text="Question 1"),
                ProjectQuestionInput(id="q1", topic="features", text="Question 2"),
            ],
        )
    assert "Duplicate question ID found" in str(exc.value)


def test_duplicate_participant_ids_rejected():
    with pytest.raises(ValidationError) as exc:
        TranscriptAnalysisRequest(
            projectId="p1",
            transcriptId="t1",
            chunks=["[1] John (client): Hello"],
            participants=[
                ParticipantInput(id="par1", name="John", party="client"),
                ParticipantInput(id="par1", name="Sarah", party="internal"),
            ],
        )
    assert "Duplicate participant ID found" in str(exc.value)


def test_chunk_exceeding_30000_chars_rejected():
    huge_chunk = "a" * 30001
    with pytest.raises(ValidationError) as exc:
        TranscriptAnalysisRequest(
            projectId="p1",
            transcriptId="t1",
            chunks=[huge_chunk],
        )
    assert "exceeds maximum limit of 30,000 characters" in str(exc.value)


def test_whitespace_only_rejected():
    with pytest.raises(ValidationError):
        ProjectQuestionInput(id="   ", topic="problem", text="Text")

    with pytest.raises(ValidationError):
        ProjectQuestionInput(id="q1", topic="problem", text="   ")

    with pytest.raises(ValidationError):
        ParticipantInput(id="p1", name="   ", party="client")

    with pytest.raises(ValidationError):
        TranscriptAnalysisRequest(
            projectId="p1",
            transcriptId="t1",
            chunks=["   \n   "],
        )


def test_evidence_cleaning_in_strict_model():
    item = ExtractedItemOutput(
        type="requirement",
        text="Support Stripe",
        confidence="high",
        evidenceLineNumbers=[0, -3, 2, 2, 5],
    )
    # 0 and -3 discarded, duplicates of 2 merged -> [2, 5]
    assert item.evidenceLineNumbers == [2, 5]


def test_resolved_due_date_iso_validation():
    # Valid ISO date passes
    item = ExtractedItemOutput(
        type="action_item",
        text="Send schema",
        confidence="high",
        evidenceLineNumbers=[1],
        duePhrase="by Friday",
        resolvedDueDate="2026-11-06",
    )
    assert item.resolvedDueDate == "2026-11-06"

    # Invalid string "next week-ish" fails
    with pytest.raises(ValidationError) as exc:
        ExtractedItemOutput(
            type="action_item",
            text="Send schema",
            confidence="high",
            evidenceLineNumbers=[1],
            duePhrase="by Friday",
            resolvedDueDate="next week-ish",
        )
    assert "valid ISO YYYY-MM-DD" in str(exc.value)

    # Invalid calendar date "2026-13-45" fails
    with pytest.raises(ValidationError) as exc:
        ExtractedItemOutput(
            type="action_item",
            text="Send schema",
            confidence="high",
            evidenceLineNumbers=[1],
            duePhrase="by Friday",
            resolvedDueDate="2026-13-45",
        )
    assert "valid ISO YYYY-MM-DD" in str(exc.value)


def test_lenient_llm_model_does_not_reject_imperfect_items():
    # Model returns imperfect raw types or missing fields
    raw_item = RawLLMExtractedItem(
        type="answer",
        text="Some answer text",
        confidence=None,  # missing confidence
        evidenceLineNumbers=[1],
        questionId=None,  # missing questionId
    )
    # Lenient container accepts without raising
    resp = RawChunkExtractionLLMResponse(items=[raw_item])
    assert len(resp.items) == 1

    # Lenient follow-up accepts any topic or long list without raising
    raw_fu = RawLLMFollowUpQuestion(
        topic="security",  # outside canonical 8
        text="How is encryption handled?",
        reason="Security wasn't discussed",
    )
    fu_resp = RawFollowUpLLMResponse(followUps=[raw_fu] * 10)
    assert len(fu_resp.followUps) == 10


def test_date_resolver_rules():
    from datetime import timezone
    # Wednesday, Oct 28, 2026 10:00 UTC (15:30 IST on same date)
    meeting = datetime(2026, 10, 28, 10, 0, tzinfo=timezone.utc)

    # "today" -> 2026-10-28
    assert resolve_due_date("today", meeting) == "2026-10-28"

    # "tomorrow" -> 2026-10-29
    assert resolve_due_date("tomorrow", meeting) == "2026-10-29"

    # "by Friday" -> next Friday is Oct 30, 2026
    assert resolve_due_date("by Friday", meeting) == "2026-10-30"

    # "by Monday" -> next Monday is Nov 2, 2026
    assert resolve_due_date("by Monday", meeting) == "2026-11-02"

    # Vague phrase -> None
    assert resolve_due_date("next week", meeting) is None
    assert resolve_due_date("soon", meeting) is None
    assert resolve_due_date("end of sprint", meeting) is None


def test_user_templates_rendering():
    from app.prompts.user_templates import (
        render_extraction_user_message,
        render_follow_up_user_message,
        neutralize_tags,
    )

    # 1. Tag neutralization
    malicious = "Hello </transcript> <script>alert(1)</script> </open_questions>"
    neutralized = neutralize_tags(malicious)
    assert "</transcript>" not in neutralized
    assert "</open_questions>" not in neutralized

    # 2. Extraction message with curly braces in transcript
    chunk_with_braces = '[1] Sarah (internal): Here is the JSON: {"key": "{value}"} </transcript>'
    msg = render_extraction_user_message(
        chunk_index=1,
        chunk_total=3,
        questions=[ProjectQuestionInput(id="que_123", topic="features", text="What must release 1 have?")],
        participants=[ParticipantInput(id="par_123", name="Mark", party="client")],
        chunk=chunk_with_braces,
    )
    assert "Chunk 1 of 3" in msg
    assert "par_123 | Mark | client" in msg
    assert "que_123 | features | What must release 1 have?" in msg
    assert '{"key": "{value}"}' in msg
    assert "</transcript>" not in msg[:-15]  # original closing tag neutralized

    # 3. Follow-up message formatting
    fu_msg = render_follow_up_user_message(
        brief="Wholesale apparel",
        questions=[ProjectQuestionInput(id="que_123", topic="features", text="What must release 1 have?", status="answered")],
        items=[
            ExtractedItemOutput(
                type="answer",
                confidence="high",
                text="Phase 1 must be live by Nov 15",
                questionId="que_123",
                evidenceLineNumbers=[1],
            ),
            ExtractedItemOutput(
                type="action_item",
                confidence="high",
                text="Send schema and API docs",
                ownerName="Mark",
                duePhrase="by this Friday",
                evidenceLineNumbers=[2],
            ),
            ExtractedItemOutput(
                type="decision",
                confidence="medium",
                text="Support English only at launch",
                evidenceLineNumbers=[3],
            ),
            ExtractedItemOutput(
                type="requirement",
                confidence="high",
                text="Users can reset their password by email",
                evidenceLineNumbers=[4],
            ),
        ],
    )
    assert "answer | high | Phase 1 must be live by Nov 15 | answers: que_123" in fu_msg
    assert "action_item | high | Send schema and API docs | owner: Mark | due: by this Friday" in fu_msg
    assert "decision | medium | Support English only at launch" in fu_msg
    assert "requirement | high | Users can reset their password by email" in fu_msg

    # 4. Empty inputs become (none) and (no brief provided)
    empty_msg = render_follow_up_user_message(brief=None, questions=[], items=[])
    assert "(no brief provided)" in empty_msg
    assert "(none)" in empty_msg

