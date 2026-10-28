from typing import List, Optional, Literal
from pydantic import BaseModel, Field, model_validator

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

SuggestionAction = Literal["add", "mark_not_relevant"]


class TemplateItem(BaseModel):
    id: str = Field(..., description="Unique ID of the template question, e.g. tpl_problem_1")
    topicKey: KnownTopicKey = Field(..., description="One of the 8 predefined topic keys")
    text: str = Field(..., min_length=1, description="The template question text")


class DayOneSuggestionsRequest(BaseModel):
    projectId: str = Field(..., description="Project ID used for logging and tracing only")
    brief: str = Field(default="", description="The project brief text")
    templates: List[TemplateItem] = Field(default_factory=list, description="List of baseline template questions")


class SuggestionItem(BaseModel):
    action: SuggestionAction = Field(..., description="Action to perform: 'add' or 'mark_not_relevant'")
    topicKey: KnownTopicKey = Field(..., description="Must be one of the 8 known topics")
    templateId: Optional[str] = Field(None, description="Required when action is 'mark_not_relevant'")
    text: Optional[str] = Field(None, description="Question text, required when action is 'add'")
    reason: str = Field(..., min_length=1, description="Reason referring specifically to something in the brief")

    @model_validator(mode="after")
    def validate_action_fields(self):
        if self.action == "mark_not_relevant":
            if not self.templateId or not self.templateId.strip():
                raise ValueError("templateId is required when action is 'mark_not_relevant'")
        elif self.action == "add":
            if not self.text or not self.text.strip():
                raise ValueError("text is required when action is 'add'")
        return self


class DayOneSuggestionsResponse(BaseModel):
    briefTooThin: bool = Field(..., description="True if the brief lacks enough substance to tailor anything")
    suggestions: List[SuggestionItem] = Field(
        default_factory=list,
        max_length=8,
        description="List of suggestions, capped at 8 items"
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
