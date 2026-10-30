from typing import List, Optional, Literal, Any
from datetime import datetime
from pydantic import BaseModel, Field, field_validator, model_validator
from app.schemas.day_one import KnownTopicKey

# Enums matching Postgres schema
ExtractedItemType = Literal["answer", "action_item", "decision", "requirement"]
ExtractionConfidence = Literal["low", "medium", "high"]
ParticipantParty = Literal["client", "internal", "third_party"]


# ==============================================================================
# Request Input Models (Strictly Validated)
# ==============================================================================

class ProjectQuestionInput(BaseModel):
    id: str = Field(..., min_length=1, max_length=100, description="Unique question ID")
    topic: KnownTopicKey = Field(..., description="One of the 8 canonical topic keys")
    text: str = Field(..., min_length=1, max_length=1000, description="Question text")
    status: Optional[str] = Field(None, max_length=50, description="Status: answered, asked, pending, suggested")

    @field_validator("id", "text", mode="before")
    @classmethod
    def strip_text(cls, v: str) -> str:
        if isinstance(v, str):
            v = v.strip()
            if not v:
                raise ValueError("Question field must not be empty or whitespace-only")
        return v


class ParticipantInput(BaseModel):
    id: str = Field(..., min_length=1, max_length=100, description="Unique participant ID")
    name: str = Field(..., min_length=1, max_length=120, description="Participant display name")
    party: ParticipantParty = Field(..., description="Participant party: client, internal, or third_party")

    @field_validator("id", "name", mode="before")
    @classmethod
    def strip_text(cls, v: str) -> str:
        if isinstance(v, str):
            v = v.strip()
            if not v:
                raise ValueError("Participant field must not be empty or whitespace-only")
        return v


class TranscriptAnalysisRequest(BaseModel):
    projectId: str = Field(..., min_length=1, max_length=100, description="Project ID for tracing and scoping")
    transcriptId: str = Field(..., min_length=1, max_length=100, description="Transcript ID being analyzed")
    meetingDate: Optional[datetime] = Field(None, description="Anchor meeting timestamp for relative date resolution")
    brief: Optional[str] = Field(None, max_length=10000, description="Project brief for context during follow-up discovery")
    chunks: List[str] = Field(..., min_length=1, max_length=50, description="Formatted transcript dialogue chunks (max 50)")
    questions: List[ProjectQuestionInput] = Field(default_factory=list, max_length=100, description="Project questions (max 100)")
    participants: List[ParticipantInput] = Field(default_factory=list, max_length=50, description="Participants of the call (max 50)")

    @field_validator("projectId", "transcriptId", mode="before")
    @classmethod
    def strip_ids(cls, v: str) -> str:
        if isinstance(v, str):
            v = v.strip()
            if not v:
                raise ValueError("ID must not be empty or whitespace-only")
        return v

    @field_validator("chunks", mode="before")
    @classmethod
    def validate_chunks(cls, v: List[str]) -> List[str]:
        if not isinstance(v, list) or len(v) == 0:
            raise ValueError("chunks must be a non-empty list")
        if len(v) > 50:
            raise ValueError("Maximum 50 chunks allowed per request")

        cleaned = []
        for i, c in enumerate(v):
            if not isinstance(c, str):
                raise ValueError(f"Chunk at index {i} must be a string")
            s = c.strip()
            if not s:
                raise ValueError(f"Chunk at index {i} must not be empty or whitespace-only")
            if len(s) > 30000:
                raise ValueError(f"Chunk at index {i} exceeds maximum limit of 30,000 characters (length: {len(s)})")
            cleaned.append(s)

        if not cleaned:
            raise ValueError("At least one non-empty transcript chunk is required")
        return cleaned

    @field_validator("questions")
    @classmethod
    def validate_unique_questions(cls, v: List[ProjectQuestionInput]) -> List[ProjectQuestionInput]:
        seen_ids = set()
        for q in v:
            if q.id in seen_ids:
                raise ValueError(f"Duplicate question ID found: '{q.id}'")
            seen_ids.add(q.id)
        return v

    @field_validator("participants")
    @classmethod
    def validate_unique_participants(cls, v: List[ParticipantInput]) -> List[ParticipantInput]:
        seen_ids = set()
        for p in v:
            if p.id in seen_ids:
                raise ValueError(f"Duplicate participant ID found: '{p.id}'")
            seen_ids.add(p.id)
        return v


def coerce_evidence_line_numbers(val: Any) -> List[int]:
    """
    Coerces raw evidence citations into a list of positive integers.
    Accepts:
    - Lists/tuples of ints, floats, strings, or mixed types
    - Single scalars (e.g. 5, "5", 12.0)
    - Comma-separated strings (e.g. "12, 13")
    Discards non-positive numbers, fractional floats, booleans, and non-numeric strings.
    Deduplicates while preserving initial encounter order.
    """
    if val is None:
        return []

    # Flatten single scalar or collection into items list
    items: List[Any] = []
    if isinstance(val, (list, tuple, set)):
        items = list(val)
    elif isinstance(val, (int, float, str)):
        if isinstance(val, str) and "," in val:
            items = val.split(",")
        else:
            items = [val]
    else:
        return []

    clean: List[int] = []
    seen = set()

    for item in items:
        if item is None:
            continue
        # In Python, bool is a subclass of int (True == 1), so exclude booleans explicitly
        if isinstance(item, bool):
            continue

        num: Optional[int] = None
        if isinstance(item, int):
            num = item
        elif isinstance(item, float):
            if item.is_integer():
                num = int(item)
        elif isinstance(item, str):
            s = item.strip()
            # Handle possible stringified int or whole float like "12.0"
            if s.isdigit() or (s.startswith("+") and s[1:].isdigit()):
                num = int(s)
            else:
                try:
                    f = float(s)
                    if f.is_integer():
                        num = int(f)
                except Exception:
                    num = None

        if num is not None and num > 0 and num not in seen:
            seen.add(num)
            clean.append(num)

    return clean


# ==============================================================================
# Lenient Raw LLM-Facing Output Models (No Raising Validators)
# ==============================================================================

class RawLLMExtractedItem(BaseModel):
    """
    Lenient model for individual items returned by LLM in chunk extraction.
    Typed as Optional[List[int]] so Gemini schema receives an array of integers.
    Pre-validator coerces scalars, strings, and mixed types without throwing.
    Filtering and strict conversion occur in service code.
    """
    type: Optional[str] = Field(None, description="Item type: answer, action_item, decision, or requirement")
    text: Optional[str] = Field(None, description="Extracted statement")
    confidence: Optional[str] = Field(None, description="Confidence: low, medium, or high")
    evidenceLineNumbers: Optional[List[int]] = Field(default_factory=list, description="Line numbers in chunk citing this item")
    questionId: Optional[str] = Field(None, description="Question ID if answer")
    ownerParticipantId: Optional[str] = Field(None, description="Participant ID if action item")
    ownerName: Optional[str] = Field(None, description="Owner name if action item")
    duePhrase: Optional[str] = Field(None, description="Spoken due phrase if action item")

    @field_validator("evidenceLineNumbers", mode="before")
    @classmethod
    def pre_clean_evidence(cls, v: Any) -> List[int]:
        return coerce_evidence_line_numbers(v)


class RawChunkExtractionLLMResponse(BaseModel):
    """Lenient container for chunk extraction LLM call."""
    items: List[RawLLMExtractedItem] = Field(default_factory=list)


class RawLLMFollowUpQuestion(BaseModel):
    """
    Lenient model for individual follow-ups returned by LLM.
    Topic and text are permissive to allow code-level sanitization without rejecting all items.
    """
    topic: Optional[str] = Field(None, description="Topic key")
    text: Optional[str] = Field(None, description="Follow-up question")
    reason: Optional[str] = Field(None, description="Justification")
    parentQuestionId: Optional[str] = Field(None, description="Parent question ID")


class RawFollowUpLLMResponse(BaseModel):
    """Lenient container for follow-up LLM call (unbounded length, trimmed in code)."""
    followUps: List[RawLLMFollowUpQuestion] = Field(default_factory=list)


# ==============================================================================
# Strict Final API Response Models (Enforces Exact System Integrity)
# ==============================================================================

class ExtractedItemOutput(BaseModel):
    type: ExtractedItemType = Field(..., description="Type: answer, action_item, decision, or requirement")
    text: str = Field(..., min_length=1, max_length=2000, description="Verified statement")
    confidence: ExtractionConfidence = Field(..., description="Verified confidence: low, medium, or high")
    evidenceLineNumbers: List[int] = Field(..., min_length=1, description="Positive unique line numbers cited")
    questionId: Optional[str] = Field(None, max_length=100, description="Answered question ID (type 'answer' only)")
    ownerParticipantId: Optional[str] = Field(None, max_length=100, description="Participant ID (type 'action_item' only)")
    ownerName: Optional[str] = Field(None, max_length=120, description="Spoken or participant name (type 'action_item' only)")
    duePhrase: Optional[str] = Field(None, max_length=200, description="Spoken due phrase (type 'action_item' only)")
    resolvedDueDate: Optional[str] = Field(None, description="ISO YYYY-MM-DD date resolved deterministically in code")

    @field_validator("text", mode="before")
    @classmethod
    def strip_text(cls, v: str) -> str:
        if isinstance(v, str):
            v = v.strip()
            if not v:
                raise ValueError("Item text must not be empty or whitespace-only")
        return v

    @field_validator("ownerName", "duePhrase", mode="before")
    @classmethod
    def strip_optional_text(cls, v: Optional[str]) -> Optional[str]:
        if isinstance(v, str):
            v = v.strip()
            return v if v else None
        return v

    @field_validator("evidenceLineNumbers", mode="before")
    @classmethod
    def clean_evidence_line_numbers(cls, v: Any) -> List[int]:
        clean = coerce_evidence_line_numbers(v)
        if not clean:
            raise ValueError("evidenceLineNumbers must contain at least one positive integer")
        return clean

    @field_validator("resolvedDueDate")
    @classmethod
    def validate_resolved_due_date(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        v = v.strip()
        if not v:
            return None
        try:
            parsed = datetime.strptime(v, "%Y-%m-%d").date()
            return parsed.isoformat()
        except Exception:
            raise ValueError(f"resolvedDueDate must be a valid ISO YYYY-MM-DD date string, received '{v}'")

    @model_validator(mode="after")
    def validate_item_type_constraints(self) -> "ExtractedItemOutput":
        item_type = self.type

        if item_type == "answer":
            if not self.questionId or not self.questionId.strip():
                raise ValueError("An 'answer' item must specify questionId")
            if self.ownerParticipantId or self.ownerName or self.duePhrase or self.resolvedDueDate:
                raise ValueError("An 'answer' item must not have owner or due date fields")

        elif item_type == "action_item":
            if self.questionId is not None:
                raise ValueError("An 'action_item' item must not have questionId")
            if self.resolvedDueDate is not None and not self.duePhrase:
                raise ValueError("A resolvedDueDate requires a duePhrase")

        elif item_type in ("decision", "requirement"):
            if self.questionId is not None:
                raise ValueError(f"A '{item_type}' item must not have questionId")
            if self.ownerParticipantId or self.ownerName or self.duePhrase or self.resolvedDueDate:
                raise ValueError(f"A '{item_type}' item must not have owner or due date fields")

        return self


class FollowUpQuestionOutput(BaseModel):
    topic: KnownTopicKey = Field(..., description="One of the 8 canonical topic keys")
    text: str = Field(..., min_length=1, max_length=1000, description="Clear, professional follow-up question")
    reason: str = Field(..., min_length=1, max_length=1000, description="Specific justification citing details or gaps from the call")
    parentQuestionId: Optional[str] = Field(None, max_length=100, description="Parent question ID if clarifying an existing question")

    @field_validator("text", "reason", mode="before")
    @classmethod
    def strip_text(cls, v: str) -> str:
        if isinstance(v, str):
            v = v.strip()
            if not v:
                raise ValueError("Follow-up field must not be empty or whitespace-only")
        return v


class TranscriptAnalysisResponse(BaseModel):
    items: List[ExtractedItemOutput] = Field(default_factory=list, description="Extracted answers, action items, decisions, and requirements")
    followUps: List[FollowUpQuestionOutput] = Field(default_factory=list, max_length=5, description="Up to 5 ranked follow-up questions")
