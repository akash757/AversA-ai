import sys
import os
import pytest
from pydantic import ValidationError

# Add project root to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from main import app
from app.config import settings
from app.schemas.day_one import (
    TemplateItem,
    DayOneSuggestionsRequest,
    SuggestionItem,
    DayOneSuggestionsResponse,
)

client = TestClient(app)


def test_health_endpoint():
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


def test_auth_missing_token():
    payload = {"projectId": "prj_1", "brief": "Valid brief text", "templates": []}
    res = client.post("/internal/day-one/suggestions", json=payload)
    assert res.status_code == 401


def test_auth_invalid_token():
    payload = {"projectId": "prj_1", "brief": "Valid brief text", "templates": []}
    res = client.post(
        "/internal/day-one/suggestions",
        json=payload,
        headers={"X-Service-Token": "invalid-token"},
    )
    assert res.status_code == 401


def test_auth_valid_token():
    payload = {"projectId": "prj_1", "brief": "Valid brief text", "templates": []}
    res = client.post(
        "/internal/day-one/suggestions",
        json=payload,
        headers={"X-Service-Token": settings.INTERNAL_SERVICE_TOKEN},
    )
    assert res.status_code == 200


# --- Schema Rule Tests ---


def test_schema_reject_add_with_template_id():
    """Rule 1: 'add' with a templateId set must be rejected."""
    with pytest.raises(ValidationError) as exc:
        SuggestionItem(
            action="add",
            topicKey="features",
            templateId="tpl_features_1",
            text="What are the key features?",
            reason="Brief mentions features.",
        )
    assert "templateId must be null when action is 'add'" in str(exc.value)


def test_schema_reject_mark_not_relevant_with_text():
    """Rule 2: 'mark_not_relevant' with text set must be rejected."""
    with pytest.raises(ValidationError) as exc:
        SuggestionItem(
            action="mark_not_relevant",
            topicKey="features",
            templateId="tpl_features_1",
            text="Unneeded question text",
            reason="Brief already answered this.",
        )
    assert "text must be null when action is 'mark_not_relevant'" in str(exc.value)


def test_schema_reject_empty_brief():
    """Rule 3: Empty or whitespace-only brief must be rejected."""
    with pytest.raises(ValidationError):
        DayOneSuggestionsRequest(projectId="prj_1", brief="", templates=[])

    with pytest.raises(ValidationError):
        DayOneSuggestionsRequest(projectId="prj_1", brief="   \n\t  ", templates=[])


def test_schema_reject_duplicate_template_ids():
    """Rule 4: Duplicate template IDs in the templates list must be rejected."""
    templates = [
        TemplateItem(id="tpl_1", topicKey="problem", text="Question 1"),
        TemplateItem(id="tpl_1", topicKey="problem", text="Question 2"),
    ]
    with pytest.raises(ValidationError) as exc:
        DayOneSuggestionsRequest(projectId="prj_1", brief="Valid brief", templates=templates)
    assert "Duplicate template ID found" in str(exc.value)


def test_schema_reject_oversized_brief():
    """Rule 5: Brief exceeding 10,000 characters must be rejected."""
    huge_brief = "a" * 10001
    with pytest.raises(ValidationError):
        DayOneSuggestionsRequest(projectId="prj_1", brief=huge_brief, templates=[])


def test_schema_reject_whitespace_only_reason():
    """Rule 6: Whitespace-only reason must be rejected."""
    with pytest.raises(ValidationError):
        SuggestionItem(
            action="add",
            topicKey="users",
            text="Who will use this?",
            reason="   ",
        )


def test_schema_thin_brief_rules():
    """Rule 7 & 8: When briefTooThin is true, max 2 suggestions, and only 'add' is allowed."""
    # Allowed: briefTooThin=True with up to 2 'add' suggestions
    valid_thin = DayOneSuggestionsResponse(
        briefTooThin=True,
        suggestions=[
            SuggestionItem(
                action="add",
                topicKey="problem",
                text="What problem does this solve?",
                reason="Brief does not state the problem.",
            )
        ],
    )
    assert valid_thin.briefTooThin is True

    # Rejected: briefTooThin=True with mark_not_relevant
    with pytest.raises(ValidationError) as exc:
        DayOneSuggestionsResponse(
            briefTooThin=True,
            suggestions=[
                SuggestionItem(
                    action="mark_not_relevant",
                    topicKey="problem",
                    templateId="tpl_problem_1",
                    reason="Not relevant.",
                )
            ],
        )
    assert "only 'add' actions are allowed" in str(exc.value)

    # Rejected: briefTooThin=True with 3 suggestions
    with pytest.raises(ValidationError) as exc:
        DayOneSuggestionsResponse(
            briefTooThin=True,
            suggestions=[
                SuggestionItem(action="add", topicKey="problem", text="Q1", reason="R1"),
                SuggestionItem(action="add", topicKey="users", text="Q2", reason="R2"),
                SuggestionItem(action="add", topicKey="goals", text="Q3", reason="R3"),
            ],
        )
    assert "at most 2 suggestions are allowed" in str(exc.value)


if __name__ == "__main__":
    test_health_endpoint()
    test_auth_missing_token()
    test_auth_invalid_token()
    test_auth_valid_token()
    test_schema_reject_add_with_template_id()
    test_schema_reject_mark_not_relevant_with_text()
    test_schema_reject_empty_brief()
    test_schema_reject_duplicate_template_ids()
    test_schema_reject_oversized_brief()
    test_schema_reject_whitespace_only_reason()
    test_schema_thin_brief_rules()
    print("ALL TESTS PASSED SUCCESSFULLY!")

