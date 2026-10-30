import pytest
from datetime import datetime, timezone

from app.config import settings
from app.services.transcript_analysis import transcript_analysis_service
from app.schemas.transcript_analysis import (
    TranscriptAnalysisRequest,
    ProjectQuestionInput,
    ParticipantInput,
)


@pytest.mark.skipif(not settings.GOOGLE_API_KEY, reason="Requires GOOGLE_API_KEY")
@pytest.mark.anyio
async def test_live_gemini_transcript_analysis():
    """
    Live end-to-end test against Gemini with a realistic transcript chunk.
    Verifies that:
    1. Gemini accepts the RawChunkExtractionLLMResponse schema (including Optional[List[int]]).
    2. Evidence lines are grounded to bracketed line numbers [n].
    3. Due dates are deterministically resolved.
    4. Follow-up questions are generated and filtered.
    """
    chunk_1 = """[1] John (internal): Welcome everyone to the kickoff meeting for Acme Commerce.
[2] Sarah (client): Thanks John. To clarify our goals, Phase 1 must be live by Nov 15. That is our hard deadline.
[3] John (internal): Understood. We will target Nov 15 for launch.
[4] Sarah (client): Also, users must be able to log in using their Google or Microsoft enterprise accounts.
[5] John (internal): Got it, OAuth SSO is a core requirement for Phase 1.
[6] Sarah (client): We also decided earlier to only support English for the initial rollout. Spanish can come in Phase 2.
[7] Mark (client): I will email you the database schema and existing customer export by tomorrow.
[8] John (internal): Great Mark, once we get that, we will map out the data migration.
"""

    req = TranscriptAnalysisRequest(
        projectId="proj_test_123",
        transcriptId="tr_test_456",
        meetingDate=datetime(2026, 11, 2, 14, 0, tzinfo=timezone.utc),  # Monday
        brief="Acme Commerce wants to build a new B2B ordering portal for wholesale buyers.",
        chunks=[chunk_1],
        questions=[
            ProjectQuestionInput(
                id="que_launch_date",
                topic="goals",
                text="When must the initial release launch?",
                status="pending",
            ),
            ProjectQuestionInput(
                id="que_payment_methods",
                topic="features",
                text="What payment gateways must be supported?",
                status="pending",
            ),
        ],
        participants=[
            ParticipantInput(id="par_john", name="John", party="internal"),
            ParticipantInput(id="par_sarah", name="Sarah", party="client"),
            ParticipantInput(id="par_mark", name="Mark", party="client"),
        ],
    )

    response = await transcript_analysis_service.analyze_transcript(req)

    assert response is not None
    assert len(response.items) > 0

    # Verify all items have valid evidence citations that exist in chunk lines [1-8]
    valid_lines = set(range(1, 9))
    for item in response.items:
        assert item.type in ("answer", "action_item", "decision", "requirement")
        assert len(item.evidenceLineNumbers) > 0
        for ln in item.evidenceLineNumbers:
            assert ln in valid_lines

        if item.type == "answer":
            assert item.questionId in ("que_launch_date", "que_payment_methods")
            assert item.ownerParticipantId is None
            assert item.duePhrase is None

        if item.type == "action_item":
            assert item.questionId is None
            if item.ownerParticipantId:
                assert item.ownerParticipantId in ("par_john", "par_sarah", "par_mark")
            if item.duePhrase and "tomorrow" in item.duePhrase.lower():
                # Meeting on Monday 2026-11-02 -> tomorrow is 2026-11-03
                assert item.resolvedDueDate == "2026-11-03"

    # Verify follow-up questions
    assert len(response.followUps) <= 5
    for fu in response.followUps:
        assert fu.topic in ("problem", "users", "goals", "features", "existing_systems", "constraints", "people", "next_steps")
        assert len(fu.text.strip()) > 0
        assert len(fu.reason.strip()) > 0

