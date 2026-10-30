import asyncio
from pathlib import Path
from typing import List, Dict, Any, Set, Optional
import re
import time

from app.llm.gemini_llm import get_gemini_llm
from app.config import settings
from app.schemas.day_one import VALID_TOPIC_KEYS
from app.schemas.transcript_analysis import (
    TranscriptAnalysisRequest,
    TranscriptAnalysisResponse,
    ExtractedItemOutput,
    FollowUpQuestionOutput,
    RawLLMExtractedItem,
    RawChunkExtractionLLMResponse,
    RawLLMFollowUpQuestion,
    RawFollowUpLLMResponse,
    coerce_evidence_line_numbers,
)
from app.prompts.user_templates import (
    render_extraction_user_message,
    render_follow_up_user_message,
)
from app.utils.date_resolver import resolve_due_date
from app.utils.logger import logger

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
EXTRACTION_SYSTEM_PROMPT_PATH = PROMPTS_DIR / "transcript_extraction.md"
FOLLOW_UP_SYSTEM_PROMPT_PATH = PROMPTS_DIR / "transcript_follow_up.md"

VALID_TYPES = {"answer", "action_item", "decision", "requirement"}
VALID_CONFIDENCES = {"low", "medium", "high"}
CONFIDENCE_SCORE = {"high": 3, "medium": 2, "low": 1}


class TranscriptAnalysisService:
    def __init__(self):
        self._extraction_system_prompt: Optional[str] = None
        self._follow_up_system_prompt: Optional[str] = None

    def _get_extraction_prompt(self) -> str:
        if self._extraction_system_prompt is None:
            if not EXTRACTION_SYSTEM_PROMPT_PATH.exists():
                logger.critical(f"Prompt file missing: {EXTRACTION_SYSTEM_PROMPT_PATH}")
                raise FileNotFoundError(f"Missing prompt file: {EXTRACTION_SYSTEM_PROMPT_PATH}")
            self._extraction_system_prompt = EXTRACTION_SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
        return self._extraction_system_prompt

    def _get_follow_up_prompt(self) -> str:
        if self._follow_up_system_prompt is None:
            if not FOLLOW_UP_SYSTEM_PROMPT_PATH.exists():
                logger.critical(f"Prompt file missing: {FOLLOW_UP_SYSTEM_PROMPT_PATH}")
                raise FileNotFoundError(f"Missing prompt file: {FOLLOW_UP_SYSTEM_PROMPT_PATH}")
            self._follow_up_system_prompt = FOLLOW_UP_SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
        return self._follow_up_system_prompt

    async def analyze_transcript(
        self, request: TranscriptAnalysisRequest
    ) -> TranscriptAnalysisResponse:
        """
        Analyzes a multi-chunk transcript with 3-worker concurrency,
        strict evidence grounding, deduplication, due date resolution,
        and follow-up discovery. Enforces a 100-second overall pipeline timeout.
        """
        start_time = time.time()
        logger.info(
            f"Starting analysis for transcript {request.transcriptId} in project {request.projectId} "
            f"({len(request.chunks)} chunks, {len(request.questions)} questions, {len(request.participants)} participants)"
        )

        try:
            return await asyncio.wait_for(self._execute_pipeline(request), timeout=100.0)
        except asyncio.TimeoutError:
            duration = time.time() - start_time
            logger.critical(
                f"Transcript analysis for {request.transcriptId} timed out after {duration:.1f}s (> 100s)"
            )
            raise TimeoutError(f"Transcript analysis exceeded 100s timeout limit ({duration:.1f}s elapsed)")

    async def _execute_pipeline(
        self, request: TranscriptAnalysisRequest
    ) -> TranscriptAnalysisResponse:
        total_chunks = len(request.chunks)
        # Open questions for extraction prompt context
        open_questions = [
            q for q in request.questions if (q.status or "").strip().lower() != "answered"
        ]

        # Valid question IDs and participant IDs for cross-checking
        valid_question_ids = {q.id for q in request.questions}
        valid_participant_ids = {p.id for p in request.participants}

        semaphore = asyncio.Semaphore(3)

        async def process_chunk_with_sem(chunk_idx: int, chunk_text: str) -> List[Dict[str, Any]]:
            async with semaphore:
                return await self._extract_chunk_with_retry(
                    chunk_index=chunk_idx + 1,
                    chunk_total=total_chunks,
                    chunk_text=chunk_text,
                    open_questions=open_questions,
                    participants=request.participants,
                    valid_question_ids=valid_question_ids,
                    valid_participant_ids=valid_participant_ids,
                )

        tasks = [
            process_chunk_with_sem(i, chunk)
            for i, chunk in enumerate(request.chunks)
        ]

        # Concurrently execute all chunk extraction tasks
        chunk_results = await asyncio.gather(*tasks)

        # Merge extracted items across all chunks
        all_raw_items: List[Dict[str, Any]] = []
        for items in chunk_results:
            all_raw_items.extend(items)

        merged_items = self._merge_items(
            raw_items=all_raw_items,
            meeting_date=request.meetingDate,
        )

        # Generate follow-up questions across the unified result set
        follow_ups = await self._generate_follow_ups_with_retry(
            brief=request.brief,
            questions=request.questions,
            items=merged_items,
            valid_question_ids=valid_question_ids,
        )

        logger.info(
            f"Transcript analysis completed for {request.transcriptId}: "
            f"{len(merged_items)} items extracted, {len(follow_ups)} follow-ups generated"
        )

        return TranscriptAnalysisResponse(
            items=merged_items,
            followUps=follow_ups,
        )

    async def _extract_chunk_with_retry(
        self,
        chunk_index: int,
        chunk_total: int,
        chunk_text: str,
        open_questions: list,
        participants: list,
        valid_question_ids: Set[str],
        valid_participant_ids: Set[str],
    ) -> List[Dict[str, Any]]:
        # Extract bracketed line numbers present in this chunk
        chunk_line_numbers = {
            int(m.group(1)) for m in re.finditer(r"\[(\d+)\]", chunk_text)
        }

        user_content = render_extraction_user_message(
            chunk_index=chunk_index,
            chunk_total=chunk_total,
            questions=open_questions,
            participants=participants,
            chunk=chunk_text,
        )
        system_prompt = self._get_extraction_prompt()

        llm = get_gemini_llm(temperature=0.1, timeout=40.0)
        structured_llm = llm.with_structured_output(RawChunkExtractionLLMResponse)

        messages = [
            ("system", system_prompt),
            ("human", user_content),
        ]

        last_error = None
        for attempt in (1, 2):
            try:
                logger.debug(f"Calling extraction for chunk {chunk_index}/{chunk_total} (attempt {attempt})")
                result: RawChunkExtractionLLMResponse = await asyncio.to_thread(
                    structured_llm.invoke, messages
                )
                logger.debug(
                    f"Chunk {chunk_index}/{chunk_total} returned {len(result.items)} raw candidate items"
                )
                return self._filter_chunk_items(
                    raw_items=result.items,
                    chunk_line_numbers=chunk_line_numbers,
                    valid_question_ids=valid_question_ids,
                    valid_participant_ids=valid_participant_ids,
                )
            except Exception as exc:
                last_error = exc
                logger.warning(
                    f"Chunk {chunk_index}/{chunk_total} extraction attempt {attempt} failed: {exc}"
                )
                if attempt == 1:
                    await asyncio.sleep(1.0)

        logger.critical(
            f"Chunk {chunk_index}/{chunk_total} extraction failed after 2 attempts. Aborting pipeline: {last_error}"
        )
        raise RuntimeError(f"Chunk {chunk_index} extraction failed: {str(last_error)}")

    def _filter_chunk_items(
        self,
        raw_items: List[RawLLMExtractedItem],
        chunk_line_numbers: Set[int],
        valid_question_ids: Set[str],
        valid_participant_ids: Set[str],
    ) -> List[Dict[str, Any]]:
        valid_items: List[Dict[str, Any]] = []

        for item in raw_items:
            # 1. Type validation
            item_type = (item.type or "").strip().lower()
            if item_type not in VALID_TYPES:
                continue

            # 2. Text validation
            text = (item.text or "").strip()
            if not text:
                continue

            # 3. Confidence normalization
            confidence = (item.confidence or "").strip().lower()
            if confidence not in VALID_CONFIDENCES:
                confidence = "medium"

            # 4. Evidence citations must exist in this chunk
            clean_citations = coerce_evidence_line_numbers(item.evidenceLineNumbers)
            grounded_citations = [ln for ln in clean_citations if ln in chunk_line_numbers]
            if not grounded_citations:
                # Must cite at least one line actually present in this chunk
                continue

            # 5. Type-specific constraint checks
            question_id: Optional[str] = None
            owner_participant_id: Optional[str] = None
            owner_name: Optional[str] = None
            due_phrase: Optional[str] = None

            if item_type == "answer":
                qid = (item.questionId or "").strip()
                if not qid or qid not in valid_question_ids:
                    # Answer must cite an existing question from input
                    continue
                question_id = qid

            elif item_type == "action_item":
                pid = (item.ownerParticipantId or "").strip()
                if pid and pid in valid_participant_ids:
                    owner_participant_id = pid
                if item.ownerName and item.ownerName.strip():
                    owner_name = item.ownerName.strip()
                if item.duePhrase and item.duePhrase.strip():
                    due_phrase = item.duePhrase.strip()

            valid_items.append({
                "type": item_type,
                "text": text,
                "confidence": confidence,
                "evidenceLineNumbers": grounded_citations,
                "questionId": question_id,
                "ownerParticipantId": owner_participant_id,
                "ownerName": owner_name,
                "duePhrase": due_phrase,
            })

        return valid_items

    def _merge_items(
        self,
        raw_items: List[Dict[str, Any]],
        meeting_date: Optional[Any],
    ) -> List[ExtractedItemOutput]:
        """
        Merges items with matching type and normalized text across chunks,
        unioning evidence line numbers, taking the highest confidence,
        and deterministically resolving action item due dates.
        """
        merged_map: Dict[tuple, Dict[str, Any]] = {}

        for it in raw_items:
            norm_text = re.sub(r"\s+", " ", it["text"]).strip().lower()
            key = (it["type"], norm_text)

            if key not in merged_map:
                merged_map[key] = {
                    "type": it["type"],
                    "text": it["text"],
                    "confidence": it["confidence"],
                    "evidenceLineNumbers": set(it["evidenceLineNumbers"]),
                    "questionId": it.get("questionId"),
                    "ownerParticipantId": it.get("ownerParticipantId"),
                    "ownerName": it.get("ownerName"),
                    "duePhrase": it.get("duePhrase"),
                }
            else:
                existing = merged_map[key]
                # Union evidence line numbers
                existing["evidenceLineNumbers"].update(it["evidenceLineNumbers"])

                # Pick highest confidence
                if CONFIDENCE_SCORE.get(it["confidence"], 2) > CONFIDENCE_SCORE.get(existing["confidence"], 2):
                    existing["confidence"] = it["confidence"]

                # For action items, fill in missing owner/due attributes
                if it["type"] == "action_item":
                    if not existing.get("ownerParticipantId") and it.get("ownerParticipantId"):
                        existing["ownerParticipantId"] = it["ownerParticipantId"]
                    if not existing.get("ownerName") and it.get("ownerName"):
                        existing["ownerName"] = it["ownerName"]
                    if not existing.get("duePhrase") and it.get("duePhrase"):
                        existing["duePhrase"] = it["duePhrase"]

        output_items: List[ExtractedItemOutput] = []
        for item_data in merged_map.values():
            due_phrase = item_data.get("duePhrase")
            resolved_due_date = None
            if item_data["type"] == "action_item" and due_phrase:
                resolved_due_date = resolve_due_date(
                    due_phrase=due_phrase,
                    meeting_date=meeting_date,
                    timezone_str=settings.DEFAULT_TIMEZONE,
                )

            evidence_sorted = sorted(list(item_data["evidenceLineNumbers"]))
            output_items.append(
                ExtractedItemOutput(
                    type=item_data["type"],
                    text=item_data["text"],
                    confidence=item_data["confidence"],
                    evidenceLineNumbers=evidence_sorted,
                    questionId=item_data.get("questionId"),
                    ownerParticipantId=item_data.get("ownerParticipantId"),
                    ownerName=item_data.get("ownerName"),
                    duePhrase=due_phrase,
                    resolvedDueDate=resolved_due_date,
                )
            )

        return output_items

    async def _generate_follow_ups_with_retry(
        self,
        brief: Optional[str],
        questions: list,
        items: List[ExtractedItemOutput],
        valid_question_ids: Set[str],
    ) -> List[FollowUpQuestionOutput]:
        user_content = render_follow_up_user_message(
            brief=brief,
            questions=questions,
            items=items,
        )
        system_prompt = self._get_follow_up_prompt()

        llm = get_gemini_llm(temperature=0.2, timeout=40.0)
        structured_llm = llm.with_structured_output(RawFollowUpLLMResponse)

        messages = [
            ("system", system_prompt),
            ("human", user_content),
        ]

        last_error = None
        for attempt in (1, 2):
            try:
                logger.debug(f"Calling follow-up question discovery (attempt {attempt})")
                result: RawFollowUpLLMResponse = await asyncio.to_thread(
                    structured_llm.invoke, messages
                )
                logger.debug(f"LLM returned {len(result.followUps)} raw candidate follow-ups")
                return self._filter_follow_ups(
                    raw_follow_ups=result.followUps,
                    valid_question_ids=valid_question_ids,
                )
            except Exception as exc:
                last_error = exc
                logger.warning(f"Follow-up discovery attempt {attempt} failed: {exc}")
                if attempt == 1:
                    await asyncio.sleep(1.0)

        logger.critical(f"Follow-up discovery failed after 2 attempts: {last_error}")
        raise RuntimeError(f"Follow-up question generation failed: {str(last_error)}")

    def _filter_follow_ups(
        self,
        raw_follow_ups: List[RawLLMFollowUpQuestion],
        valid_question_ids: Set[str],
    ) -> List[FollowUpQuestionOutput]:
        clean_follow_ups: List[FollowUpQuestionOutput] = []

        for fu in raw_follow_ups:
            topic = (fu.topic or "").strip().lower()
            if topic not in VALID_TOPIC_KEYS:
                continue

            text = (fu.text or "").strip()
            if not text:
                continue

            reason = (fu.reason or "").strip()
            if not reason:
                continue

            parent_id = (fu.parentQuestionId or "").strip()
            if parent_id and parent_id not in valid_question_ids:
                # Parent question does not exist in request; clear it rather than dropping
                parent_id = None
            elif not parent_id:
                parent_id = None

            clean_follow_ups.append(
                FollowUpQuestionOutput(
                    topic=topic,  # type: ignore
                    text=text,
                    reason=reason,
                    parentQuestionId=parent_id,
                )
            )

            if len(clean_follow_ups) == 5:
                break

        return clean_follow_ups


transcript_analysis_service = TranscriptAnalysisService()

