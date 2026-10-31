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
    TranscriptAnalysisDiagnostics,
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
ALLOWED_OPEN_STATUSES = {"pending", "asked"}

RELATIVE_DATE_PATTERN = re.compile(
    r"\b(tomorrow|tomorrow afternoon|tomorrow morning|tomorrow evening|yesterday|next week|next month|this week|next friday|next monday|next tuesday|next wednesday|next thursday|in \d+ days?)\b",
    re.IGNORECASE,
)
ACTION_CHASE_PATTERN = re.compile(
    r"(contingency.*(if|plan)|what if.*(miss|delay|fail|cannot send|does not send|fails)|if.*(miss|delay|late))",
    re.IGNORECASE,
)

STOP_WORDS = {
    "a", "an", "the", "is", "are", "was", "were", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "and", "or", "what", "which", "how", "do", "does",
    "did", "can", "could", "should", "would", "your", "our", "their", "this", "that",
    "over", "about", "into", "then", "there", "any", "some", "be", "been", "being",
    "have", "has", "had",
}


def _normalize_token(t: str) -> str:
    if len(t) > 3 and t.endswith("s") and not t.endswith("ss"):
        return t[:-1]
    return t


def _extract_content_tokens(text: str) -> Set[str]:
    tokens = set(re.findall(r"\b[a-z0-9]+\b", text.lower()))
    content_tokens = {_normalize_token(t) for t in tokens if t not in STOP_WORDS and len(t) > 1}
    return content_tokens if content_tokens else {_normalize_token(t) for t in tokens}


def _jaccard_similarity(set1: Set[str], set2: Set[str]) -> float:
    if not set1 or not set2:
        return 0.0
    intersection = len(set1.intersection(set2))
    union = len(set1.union(set2))
    return intersection / union if union > 0 else 0.0


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
        start_exec = time.time()
        total_chunks = len(request.chunks)

        # Allow-list for open questions: only pending and asked
        open_questions = [
            q for q in request.questions
            if (q.status or "").strip().lower() in ALLOWED_OPEN_STATUSES
        ]
        allowed_answer_question_ids = {q.id for q in open_questions}
        valid_participant_ids = {p.id for p in request.participants}

        semaphore = asyncio.Semaphore(3)

        async def process_chunk_with_sem(chunk_idx: int, chunk_text: str) -> Dict[str, Any]:
            async with semaphore:
                return await self._extract_chunk_with_retry(
                    chunk_index=chunk_idx + 1,
                    chunk_total=total_chunks,
                    chunk_text=chunk_text,
                    open_questions=open_questions,
                    participants=request.participants,
                    allowed_answer_question_ids=allowed_answer_question_ids,
                    valid_participant_ids=valid_participant_ids,
                )

        task_objs = [
            asyncio.create_task(process_chunk_with_sem(i, chunk))
            for i, chunk in enumerate(request.chunks)
        ]

        try:
            # Concurrently execute all chunk extraction tasks
            chunk_results = await asyncio.gather(*task_objs)
        except Exception:
            for t in task_objs:
                if not t.done():
                    t.cancel()
            await asyncio.gather(*task_objs, return_exceptions=True)
            raise

        # Aggregate raw items and drop counts across chunks
        all_raw_items: List[Dict[str, Any]] = []
        item_drop_counts: Dict[str, int] = {}
        total_items_extracted = 0

        for res in chunk_results:
            total_items_extracted += res["rawCount"]
            all_raw_items.extend(res["items"])
            for reason, count in res["dropCounts"].items():
                item_drop_counts[reason] = item_drop_counts.get(reason, 0) + count

        merged_items = self._merge_items(
            raw_items=all_raw_items,
            meeting_date=request.meetingDate,
            drop_counts=item_drop_counts,
        )

        # Derive answered question IDs strictly from items extracted in this call
        answered_question_ids = {
            it.questionId for it in merged_items
            if it.type == "answer" and it.questionId
        }

        # Generate follow-up questions across the unified result set
        follow_ups_res = await self._generate_follow_ups_with_retry(
            brief=request.brief,
            questions=request.questions,
            items=merged_items,
            answered_question_ids=answered_question_ids,
        )

        follow_ups = follow_ups_res["followUps"]
        total_fu_generated = follow_ups_res["rawCount"]
        fu_drop_counts = follow_ups_res["dropCounts"]

        total_items_dropped = total_items_extracted - len(merged_items)
        total_fu_dropped = total_fu_generated - len(follow_ups)
        exec_duration_ms = int((time.time() - start_exec) * 1000)

        diagnostics = TranscriptAnalysisDiagnostics(
            chunkCount=total_chunks,
            totalItemsExtracted=total_items_extracted,
            totalItemsKept=len(merged_items),
            totalItemsDropped=total_items_dropped,
            droppedByReason=item_drop_counts,
            followUpsGenerated=total_fu_generated,
            followUpsKept=len(follow_ups),
            followUpsDropped=total_fu_dropped,
            followUpDroppedByReason=fu_drop_counts,
            executionTimeMs=exec_duration_ms,
        )

        logger.info(
            f"Transcript analysis completed for {request.transcriptId}: "
            f"{len(merged_items)} items extracted, {len(follow_ups)} follow-ups generated, "
            f"{total_items_dropped} items dropped, {total_fu_dropped} follow-ups dropped ({exec_duration_ms}ms)"
        )

        return TranscriptAnalysisResponse(
            items=merged_items,
            followUps=follow_ups,
            diagnostics=diagnostics,
        )

    async def _extract_chunk_with_retry(
        self,
        chunk_index: int,
        chunk_total: int,
        chunk_text: str,
        open_questions: list,
        participants: list,
        allowed_answer_question_ids: Set[str],
        valid_participant_ids: Set[str],
    ) -> Dict[str, Any]:
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

        last_error_cls = None
        for attempt in (1, 2):
            try:
                logger.debug(f"Calling extraction for chunk {chunk_index}/{chunk_total} (attempt {attempt})")
                result: RawChunkExtractionLLMResponse = await asyncio.to_thread(
                    structured_llm.invoke, messages
                )
                logger.debug(
                    f"Chunk {chunk_index}/{chunk_total} returned {len(result.items)} raw candidate items"
                )
                drop_counts: Dict[str, int] = {}
                valid_items = self._filter_chunk_items(
                    raw_items=result.items,
                    chunk_line_numbers=chunk_line_numbers,
                    allowed_answer_question_ids=allowed_answer_question_ids,
                    valid_participant_ids=valid_participant_ids,
                    drop_counts=drop_counts,
                )
                return {
                    "items": valid_items,
                    "rawCount": len(result.items),
                    "dropCounts": drop_counts,
                }
            except Exception as exc:
                last_error_cls = type(exc).__name__
                logger.warning(
                    f"Chunk {chunk_index}/{chunk_total} extraction attempt {attempt} failed with {last_error_cls}"
                )
                if attempt == 1:
                    await asyncio.sleep(1.0)

        logger.critical(
            f"Chunk {chunk_index}/{chunk_total} extraction failed after 2 attempts with {last_error_cls}"
        )
        raise RuntimeError(f"Chunk {chunk_index} extraction failed ({last_error_cls})")

    def _filter_chunk_items(
        self,
        raw_items: List[RawLLMExtractedItem],
        chunk_line_numbers: Set[int],
        allowed_answer_question_ids: Optional[Set[str]] = None,
        valid_participant_ids: Optional[Set[str]] = None,
        drop_counts: Optional[Dict[str, int]] = None,
        valid_question_ids: Optional[Set[str]] = None,
    ) -> List[Dict[str, Any]]:
        valid_items: List[Dict[str, Any]] = []
        if drop_counts is None:
            drop_counts = {}
        allowed_qids = (
            allowed_answer_question_ids
            if allowed_answer_question_ids is not None
            else (valid_question_ids or set())
        )
        valid_pids = valid_participant_ids or set()
        seen_chunk_keys: Set[tuple] = set()

        for item in raw_items:
            # 1. Type validation
            item_type = (item.type or "").strip().lower()
            if item_type not in VALID_TYPES:
                drop_counts["invalid_type"] = drop_counts.get("invalid_type", 0) + 1
                continue

            # 2. Text validation
            text = (item.text or "").strip()
            if not text:
                drop_counts["empty_text"] = drop_counts.get("empty_text", 0) + 1
                continue

            # In-chunk deduplication
            chunk_key = (item_type, re.sub(r"\s+", " ", text).strip().lower())
            if chunk_key in seen_chunk_keys:
                drop_counts["duplicate_in_chunk"] = drop_counts.get("duplicate_in_chunk", 0) + 1
                continue
            seen_chunk_keys.add(chunk_key)

            # 3. Confidence normalization
            confidence = (item.confidence or "").strip().lower()
            if confidence not in VALID_CONFIDENCES:
                confidence = "medium"

            # 4. Evidence citations must exist in this chunk
            clean_citations = coerce_evidence_line_numbers(item.evidenceLineNumbers)
            grounded_citations = [ln for ln in clean_citations if ln in chunk_line_numbers]
            if not grounded_citations:
                drop_counts["ungrounded_evidence"] = drop_counts.get("ungrounded_evidence", 0) + 1
                continue

            # 5. Type-specific constraint checks
            question_id: Optional[str] = None
            owner_participant_id: Optional[str] = None
            owner_name: Optional[str] = None
            due_phrase: Optional[str] = None

            if item_type == "answer":
                qid = (item.questionId or "").strip()
                if not qid or qid not in allowed_qids:
                    # Answer must cite an allowed open question
                    drop_counts["invalid_answer_question"] = drop_counts.get("invalid_answer_question", 0) + 1
                    continue
                question_id = qid

            elif item_type == "action_item":
                pid = (item.ownerParticipantId or "").strip()
                if pid and pid in valid_pids:
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
        drop_counts: Optional[Dict[str, int]] = None,
    ) -> List[ExtractedItemOutput]:
        """
        Merges items with matching type and normalized text across chunks,
        unioning evidence line numbers, taking the highest confidence,
        and deterministically resolving action item due dates.
        """
        if drop_counts is None:
            drop_counts = {}
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
                drop_counts["duplicate_across_chunks"] = drop_counts.get("duplicate_across_chunks", 0) + 1
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
        answered_question_ids: Set[str],
    ) -> Dict[str, Any]:
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

        last_error_cls = None
        for attempt in (1, 2):
            try:
                logger.debug(f"Calling follow-up question discovery (attempt {attempt})")
                result: RawFollowUpLLMResponse = await asyncio.to_thread(
                    structured_llm.invoke, messages
                )
                logger.debug(f"LLM returned {len(result.followUps)} raw candidate follow-ups")
                drop_counts: Dict[str, int] = {}
                clean_follow_ups = self._filter_follow_ups(
                    raw_follow_ups=result.followUps,
                    answered_question_ids=answered_question_ids,
                    existing_questions=questions,
                    drop_counts=drop_counts,
                )
                return {
                    "followUps": clean_follow_ups,
                    "rawCount": len(result.followUps),
                    "dropCounts": drop_counts,
                }
            except Exception as exc:
                last_error_cls = type(exc).__name__
                logger.warning(f"Follow-up discovery attempt {attempt} failed with {last_error_cls}")
                if attempt == 1:
                    await asyncio.sleep(1.0)

        logger.critical(f"Follow-up discovery failed after 2 attempts with {last_error_cls}")
        raise RuntimeError(f"Follow-up question generation failed ({last_error_cls})")

    def _filter_follow_ups(
        self,
        raw_follow_ups: List[RawLLMFollowUpQuestion],
        answered_question_ids: Optional[Set[str]] = None,
        existing_questions: Optional[list] = None,
        drop_counts: Optional[Dict[str, int]] = None,
        valid_question_ids: Optional[Set[str]] = None,
    ) -> List[FollowUpQuestionOutput]:
        clean_follow_ups: List[FollowUpQuestionOutput] = []
        if drop_counts is None:
            drop_counts = {}

        answered_ids = (
            answered_question_ids
            if answered_question_ids is not None
            else (valid_question_ids or set())
        )

        existing_question_texts = set()
        existing_question_token_sets: List[Set[str]] = []
        if existing_questions:
            for q in existing_questions:
                q_text = getattr(q, "text", None) or (q.get("text") if isinstance(q, dict) else "")
                if q_text:
                    clean_q = re.sub(r"\s+", " ", q_text).strip().lower()
                    existing_question_texts.add(clean_q)
                    existing_question_token_sets.append(_extract_content_tokens(clean_q))

        accepted_fu_token_sets: List[Set[str]] = []

        for fu in raw_follow_ups:
            topic = (fu.topic or "").strip().lower()
            if topic not in VALID_TOPIC_KEYS:
                drop_counts["invalid_topic"] = drop_counts.get("invalid_topic", 0) + 1
                continue

            text = (fu.text or "").strip()
            if not text:
                drop_counts["empty_text"] = drop_counts.get("empty_text", 0) + 1
                continue

            reason = (fu.reason or "").strip()
            if not reason:
                drop_counts["empty_reason"] = drop_counts.get("empty_reason", 0) + 1
                continue

            # Rule: Follow-ups must never duplicate existing open questions or near-duplicate accepted follow-ups
            norm_fu_text = re.sub(r"\s+", " ", text).strip().lower()
            if norm_fu_text in existing_question_texts:
                drop_counts["duplicate_existing_question"] = (
                    drop_counts.get("duplicate_existing_question", 0) + 1
                )
                continue

            fu_tokens = _extract_content_tokens(norm_fu_text)
            is_near_dup = False
            for ex_tokens in existing_question_token_sets:
                if _jaccard_similarity(fu_tokens, ex_tokens) >= 0.55:
                    is_near_dup = True
                    break
            if is_near_dup:
                drop_counts["duplicate_existing_question"] = (
                    drop_counts.get("duplicate_existing_question", 0) + 1
                )
                continue

            for acc_tokens in accepted_fu_token_sets:
                if _jaccard_similarity(fu_tokens, acc_tokens) >= 0.55:
                    is_near_dup = True
                    break
            if is_near_dup:
                drop_counts["duplicate_existing_question"] = (
                    drop_counts.get("duplicate_existing_question", 0) + 1
                )
                continue

            # Rule: Follow-ups must never chase action items or use relative dates
            if RELATIVE_DATE_PATTERN.search(text) or ACTION_CHASE_PATTERN.search(text):
                drop_counts["relative_date_or_action_chase"] = (
                    drop_counts.get("relative_date_or_action_chase", 0) + 1
                )
                continue

            # Rule: If parentQuestionId is provided, it MUST be a question answered in this call.
            # If parentQuestionId is null/omitted, it explores a new discovery gap (allowed).
            raw_parent_id = (fu.parentQuestionId or "").strip()
            if raw_parent_id:
                if raw_parent_id not in answered_ids:
                    drop_counts["unanswered_parent_followup"] = (
                        drop_counts.get("unanswered_parent_followup", 0) + 1
                    )
                    continue
                parent_id: Optional[str] = raw_parent_id
            else:
                parent_id = None

            clean_follow_ups.append(
                FollowUpQuestionOutput(
                    topic=topic,  # type: ignore
                    text=text,
                    reason=reason,
                    parentQuestionId=parent_id,
                )
            )
            accepted_fu_token_sets.append(fu_tokens)

            if len(clean_follow_ups) == 5:
                # Any remaining candidate follow-ups are dropped by the 5-item cap
                remaining = len(raw_follow_ups) - (len(clean_follow_ups) + sum(drop_counts.values()))
                if remaining > 0:
                    drop_counts["max_cap_reached"] = remaining
                break

        return clean_follow_ups


transcript_analysis_service = TranscriptAnalysisService()
