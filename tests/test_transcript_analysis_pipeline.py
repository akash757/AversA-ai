import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from datetime import datetime, timezone
from fastapi.testclient import TestClient

from app.services.transcript_analysis import TranscriptAnalysisService
from app.schemas.transcript_analysis import (
    RawLLMExtractedItem,
    RawLLMFollowUpQuestion,
    ExtractedItemOutput,
    TranscriptAnalysisRequest,
    ProjectQuestionInput,
    ParticipantInput,
)
from main import app


@pytest.fixture
def service():
    return TranscriptAnalysisService()


def test_filter_chunk_items_validation_and_grounding(service):
    chunk_lines = {1, 2, 3, 4, 5}
    valid_qids = {"que_1"}
    valid_pids = {"par_1"}

    raw_items = [
        # Valid answer
        RawLLMExtractedItem(
            type="answer",
            text="Launch is on Nov 15",
            confidence="high",
            evidenceLineNumbers=[1, 2],
            questionId="que_1",
        ),
        # Answer with invalid questionId -> dropped
        RawLLMExtractedItem(
            type="answer",
            text="Invented question answer",
            confidence="high",
            evidenceLineNumbers=[2],
            questionId="que_invented",
        ),
        # Valid action item
        RawLLMExtractedItem(
            type="action_item",
            text="Send API specs",
            confidence="medium",
            evidenceLineNumbers=[3],
            ownerParticipantId="par_1",
            ownerName="Alice",
            duePhrase="tomorrow",
        ),
        # Action item with unmapped participant ID -> ownerParticipantId cleared to None
        RawLLMExtractedItem(
            type="action_item",
            text="Update docs",
            confidence="low",
            evidenceLineNumbers=[3],
            ownerParticipantId="par_unknown",
            ownerName="Bob",
            duePhrase="by Friday",
        ),
        # Valid decision
        RawLLMExtractedItem(
            type="decision",
            text="Use Postgres for storage",
            confidence="high",
            evidenceLineNumbers=[4],
        ),
        # Valid requirement
        RawLLMExtractedItem(
            type="requirement",
            text="System must support SSO",
            confidence="high",
            evidenceLineNumbers=[5],
        ),
        # Item with line numbers not in chunk -> dropped
        RawLLMExtractedItem(
            type="decision",
            text="Fake citation item",
            confidence="high",
            evidenceLineNumbers=[99],
        ),
        # Item with empty text -> dropped
        RawLLMExtractedItem(
            type="decision",
            text="   ",
            confidence="high",
            evidenceLineNumbers=[1],
        ),
        # Item with invalid type -> dropped
        RawLLMExtractedItem(
            type="unknown_type",
            text="Something else",
            confidence="high",
            evidenceLineNumbers=[1],
        ),
    ]

    filtered = service._filter_chunk_items(
        raw_items=raw_items,
        chunk_line_numbers=chunk_lines,
        valid_question_ids=valid_qids,
        valid_participant_ids=valid_pids,
    )

    assert len(filtered) == 5

    # 1. Answer
    assert filtered[0]["type"] == "answer"
    assert filtered[0]["questionId"] == "que_1"
    assert filtered[0]["evidenceLineNumbers"] == [1, 2]

    # 2. Action item with known participant
    assert filtered[1]["type"] == "action_item"
    assert filtered[1]["ownerParticipantId"] == "par_1"
    assert filtered[1]["ownerName"] == "Alice"

    # 3. Action item with unknown participant has ownerParticipantId = None
    assert filtered[2]["type"] == "action_item"
    assert filtered[2]["ownerParticipantId"] is None
    assert filtered[2]["ownerName"] == "Bob"

    # 4. Decision
    assert filtered[3]["type"] == "decision"

    # 5. Requirement
    assert filtered[4]["type"] == "requirement"


def test_merge_items_deduplication_and_date_resolution(service):
    meeting_date = datetime(2026, 11, 2, 10, 0, tzinfo=timezone.utc)  # Monday

    raw_items = [
        # Chunk 1 item
        {
            "type": "decision",
            "text": "Support English only at launch",
            "confidence": "medium",
            "evidenceLineNumbers": [3],
            "questionId": None,
            "ownerParticipantId": None,
            "ownerName": None,
            "duePhrase": None,
        },
        # Chunk 2 item with identical normalized text and higher confidence
        {
            "type": "decision",
            "text": "  support english only at launch   ",
            "confidence": "high",
            "evidenceLineNumbers": [12],
            "questionId": None,
            "ownerParticipantId": None,
            "ownerName": None,
            "duePhrase": None,
        },
        # Action item with duePhrase
        {
            "type": "action_item",
            "text": "Send contract",
            "confidence": "high",
            "evidenceLineNumbers": [5],
            "questionId": None,
            "ownerParticipantId": "par_1",
            "ownerName": "Alice",
            "duePhrase": "tomorrow",
        },
    ]

    merged = service._merge_items(raw_items, meeting_date)

    assert len(merged) == 2

    # Decision merged
    decision_item = next(it for it in merged if it.type == "decision")
    assert decision_item.confidence == "high"  # highest confidence kept
    assert decision_item.evidenceLineNumbers == [3, 12]  # unioned lines

    # Action item due date resolved
    action_item = next(it for it in merged if it.type == "action_item")
    assert action_item.duePhrase == "tomorrow"
    assert action_item.resolvedDueDate == "2026-11-03"


def test_filter_follow_ups(service):
    answered_qids = {"que_1"}
    existing_questions = [
        {"id": "que_open", "text": "What are your 3 to 6 month success metrics?", "topic": "goals"}
    ]
    drop_counts = {}

    raw_fus = [
        # 1. Valid follow-up with answered parent
        RawLLMFollowUpQuestion(
            topic="features",
            text="What payment gateways should be supported in MVP?",
            reason="Client mentioned Stripe and Paypal but didn't confirm priority.",
            parentQuestionId="que_1",
        ),
        # 1b. Valid follow-up exploring new discovery gap with parentQuestionId = None
        RawLLMFollowUpQuestion(
            topic="problem",
            text="How do sales reps currently act on behalf of enterprise clients?",
            reason="New operational gap identified during discussion.",
            parentQuestionId=None,
        ),
        # 2. Unknown parentQuestionId -> dropped (must be answered question)
        RawLLMFollowUpQuestion(
            topic="constraints",
            text="Is 2FA required for admins?",
            reason="Security compliance requirements were not detailed.",
            parentQuestionId="que_invented",
        ),
        # 3. Invalid topic -> dropped
        RawLLMFollowUpQuestion(
            topic="invalid_topic",
            text="What about branding?",
            reason="Unspecified.",
            parentQuestionId="que_1",
        ),
        # 4. Empty text -> dropped
        RawLLMFollowUpQuestion(
            topic="problem",
            text="  ",
            reason="Problem statement empty.",
            parentQuestionId="que_1",
        ),
        # 5. Re-asking an existing question -> dropped
        RawLLMFollowUpQuestion(
            topic="goals",
            text="What are your 3 to 6 month success metrics?",
            reason="Need clarification on goals.",
            parentQuestionId="que_1",
        ),
        # 5b. Near-duplicate paraphrase of existing question -> dropped via Jaccard
        RawLLMFollowUpQuestion(
            topic="goals",
            text="What are your success metrics over 3 to 6 months?",
            reason="Paraphrased question.",
            parentQuestionId="que_1",
        ),
        # 6. Relative date in follow-up -> dropped
        RawLLMFollowUpQuestion(
            topic="next_steps",
            text="Can you confirm if tomorrow afternoon works for the wireframe review?",
            reason="Scheduling clarity.",
            parentQuestionId="que_1",
        ),
        # 7. Action item chase / contingency -> dropped
        RawLLMFollowUpQuestion(
            topic="constraints",
            text="What is your contingency plan if the vendor fails to deliver the export by Friday?",
            reason="Risk mitigation.",
            parentQuestionId="que_1",
        ),
    ]

    clean = service._filter_follow_ups(
        raw_follow_ups=raw_fus,
        answered_question_ids=answered_qids,
        existing_questions=existing_questions,
        drop_counts=drop_counts,
    )

    assert len(clean) == 2
    assert clean[0].topic == "features"
    assert clean[0].parentQuestionId == "que_1"
    assert clean[0].text == "What payment gateways should be supported in MVP?"

    assert clean[1].topic == "problem"
    assert clean[1].parentQuestionId is None
    assert clean[1].text == "How do sales reps currently act on behalf of enterprise clients?"

    # Check drop counter reasons
    assert drop_counts.get("unanswered_parent_followup") == 1
    assert drop_counts.get("invalid_topic") == 1
    assert drop_counts.get("empty_text") == 1
    assert drop_counts.get("duplicate_existing_question") == 2
    assert drop_counts.get("relative_date_or_action_chase") == 2


client = TestClient(app)


def test_route_unauthenticated():
    res = client.post("/internal/transcript-analysis", json={})
    assert res.status_code == 401


def test_route_validation_error():
    from app.config import settings
    headers = {"X-Service-Token": settings.INTERNAL_SERVICE_TOKEN}
    # Payload with empty chunks list
    res = client.post(
        "/internal/transcript-analysis",
        headers=headers,
        json={
            "projectId": "proj_1",
            "transcriptId": "tr_1",
            "chunks": [],
        },
    )
    assert res.status_code == 422


@pytest.mark.anyio
async def test_route_success():
    from app.config import settings
    headers = {"X-Service-Token": settings.INTERNAL_SERVICE_TOKEN}

    payload = {
        "projectId": "proj_1",
        "transcriptId": "tr_1",
        "chunks": ["[1] Alice (client): We need SSO authentication."],
        "questions": [
            {"id": "que_1", "topic": "constraints", "text": "What auth is needed?"}
        ],
        "participants": [
            {"id": "par_1", "name": "Alice", "party": "client"}
        ],
    }

    with patch(
        "app.services.transcript_analysis.TranscriptAnalysisService.analyze_transcript",
        new_callable=AsyncMock,
    ) as mock_analyze:
        from app.schemas.transcript_analysis import (
            TranscriptAnalysisResponse,
            ExtractedItemOutput,
            FollowUpQuestionOutput,
        )

        mock_analyze.return_value = TranscriptAnalysisResponse(
            items=[
                ExtractedItemOutput(
                    type="requirement",
                    text="We need SSO authentication.",
                    confidence="high",
                    evidenceLineNumbers=[1],
                )
            ],
            followUps=[
                FollowUpQuestionOutput(
                    topic="constraints",
                    text="Should SSO support SAML or OIDC?",
                    reason="SSO was requested without protocol specification.",
                    parentQuestionId="que_1",
                )
            ],
        )

        res = client.post(
            "/internal/transcript-analysis",
            headers=headers,
            json=payload,
        )
        assert res.status_code == 200
        data = res.json()
        assert len(data["items"]) == 1
        assert data["items"][0]["type"] == "requirement"
        assert len(data["followUps"]) == 1
