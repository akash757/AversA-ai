from typing import List, Optional, Literal, Set
from pydantic import BaseModel, Field, field_validator, model_validator

KnownTopicKey = Literal[
    "problem",
    "users",
    "goals",
    "features",
    "existing_systems",
    "constraints",
    "people",
    "next_steps",
]

VALID_TOPIC_KEYS: Set[str] = {
    "problem",
    "users",
    "goals",
    "features",
    "existing_systems",
    "constraints",
    "people",
    "next_steps",
}

SuggestionAction = Literal["add", "mark_not_relevant"]


class TemplateItem(BaseModel):
    id: str = Field(..., description="Unique ID of the template question, e.g. tpl_problem_1")
    topicKey: KnownTopicKey = Field(..., description="One of the 8 predefined topic keys")
    text: str = Field(..., min_length=1, description="The template question text")

    @field_validator("id", "text", mode="before")
    @classmethod
    def strip_strings(cls, v: str) -> str:
        if isinstance(v, str):
            v = v.strip()
            if not v:
                raise ValueError("Must not be empty or whitespace-only")
        return v


class DayOneSuggestionsRequest(BaseModel):
    projectId: str = Field(..., min_length=1, description="Project ID used for logging and tracing only")
    brief: str = Field(..., min_length=1, max_length=10000, description="The project brief text")
    templates: List[TemplateItem] = Field(default_factory=list, description="List of baseline template questions")

    @field_validator("brief", "projectId", mode="before")
    @classmethod
    def strip_text(cls, v: str) -> str:
        if isinstance(v, str):
            v = v.strip()
            if not v:
                raise ValueError("Must not be empty or whitespace-only")
        return v

    @field_validator("templates")
    @classmethod
    def validate_unique_template_ids(cls, v: List[TemplateItem]) -> List[TemplateItem]:
        seen_ids = set()
        for item in v:
            if item.id in seen_ids:
                raise ValueError(f"Duplicate template ID found: '{item.id}'")
            seen_ids.add(item.id)
        return v


class SuggestionItem(BaseModel):
    action: SuggestionAction = Field(..., description="Action to perform: 'add' or 'mark_not_relevant'")
    topicKey: KnownTopicKey = Field(..., description="Must be one of the 8 known topics")
    templateId: Optional[str] = Field(None, description="Set only when action is 'mark_not_relevant'")
    text: Optional[str] = Field(None, description="Set only when action is 'add'")
    reason: str = Field(..., min_length=1, description="Reason referring specifically to something in the brief")

    @field_validator("reason", mode="before")
    @classmethod
    def strip_reason(cls, v: str) -> str:
        if isinstance(v, str):
            v = v.strip()
            if not v:
                raise ValueError("Reason cannot be empty or whitespace-only")
        return v

    @field_validator("text", mode="before")
    @classmethod
    def strip_text(cls, v: Optional[str]) -> Optional[str]:
        if isinstance(v, str):
            v = v.strip()
            if not v:
                return None
        return v

    @field_validator("templateId", mode="before")
    @classmethod
    def strip_template_id(cls, v: Optional[str]) -> Optional[str]:
        if isinstance(v, str):
            v = v.strip()
            if not v:
                return None
        return v

    @model_validator(mode="after")
    def validate_action_fields(self):
        if self.action == "mark_not_relevant":
            if not self.templateId:
                raise ValueError("templateId is required when action is 'mark_not_relevant'")
            if self.text is not None:
                raise ValueError("text must be null when action is 'mark_not_relevant'")
        elif self.action == "add":
            if not self.text:
                raise ValueError("text is required when action is 'add'")
            if self.templateId is not None:
                raise ValueError("templateId must be null when action is 'add'")
        return self


class DayOneSuggestionsResponse(BaseModel):
    briefTooThin: bool = Field(..., description="True if the brief lacks enough substance to tailor anything")
    suggestions: List[SuggestionItem] = Field(
        default_factory=list,
        max_length=8,
        description="List of suggestions, capped at 8 items",
    )

    @model_validator(mode="after")
    def validate_thin_brief(self):
        if self.briefTooThin:
            if len(self.suggestions) > 2:
                raise ValueError("When briefTooThin is true, at most 2 suggestions are allowed")
            for item in self.suggestions:
                if item.action != "add":
                    raise ValueError("When briefTooThin is true, only 'add' actions are allowed")
        return self


# Lenient schemas for LLM structured output to prevent crashes on minor model format variations
class LLMSuggestionItem(BaseModel):
    action: str = Field(description="add or mark_not_relevant")
    topicKey: str = Field(description="One of the 8 topic keys")
    templateId: Optional[str] = Field(None, description="templateId for mark_not_relevant")
    text: Optional[str] = Field(None, description="Question text for add")
    reason: str = Field(..., description="Reason tied to the brief")


class LLMResponseOutput(BaseModel):
    briefTooThin: bool = Field(description="True if the brief lacks enough substance")
    suggestions: List[LLMSuggestionItem] = Field(default_factory=list)
