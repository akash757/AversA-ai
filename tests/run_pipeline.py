import asyncio
import json
import time
import sys
from pathlib import Path
from datetime import datetime

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.schemas.transcript_analysis import (
    TranscriptAnalysisRequest,
    ProjectQuestionInput,
    ParticipantInput,
)
from app.services.transcript_analysis import transcript_analysis_service
from app.utils.logger import logger

SAMPLES_DIR = Path(__file__).resolve().parent / "samples"


def load_sample(json_path: Path) -> TranscriptAnalysisRequest:
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    meeting_date = None
    if data.get("meetingDate"):
        meeting_date = datetime.fromisoformat(data["meetingDate"].replace("Z", "+00:00"))

    questions = [
        ProjectQuestionInput(
            id=q["id"],
            topic=q["topic"],
            text=q["text"],
            status=q.get("status", "pending"),
        )
        for q in data["questions"]
    ]

    participants = [
        ParticipantInput(
            id=p["id"],
            name=p["name"],
            party=p.get("party", "client"),
        )
        for p in data["participants"]
    ]

    return TranscriptAnalysisRequest(
        projectId=data["projectId"],
        transcriptId=data["transcriptId"],
        meetingDate=meeting_date,
        brief=data.get("brief"),
        chunks=data["chunks"],
        questions=questions,
        participants=participants,
    )


async def run_single_sample(sample_name: str, sample_file: str, output_file: str):
    print("=" * 80)
    print(f"RUNNING PIPELINE: {sample_name}")
    print("=" * 80)

    sample_path = SAMPLES_DIR / sample_file
    if not sample_path.exists():
        print(f"Error: Sample file not found at {sample_path}")
        return

    request = load_sample(sample_path)
    print(f"Loaded request: {len(request.chunks)} chunks, {len(request.questions)} questions, {len(request.participants)} participants")
    print(f"Meeting Date: {request.meetingDate}")
    print("Executing pipeline on Gemini...\n")

    t0 = time.time()
    response = await transcript_analysis_service.analyze_transcript(request)
    elapsed = time.time() - t0

    # Save full result to JSON
    output_path = SAMPLES_DIR / output_file
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(response.model_dump(), f, indent=2, default=str)
    print(f"Saved full result to {output_path.name}")

    # Output formatted evaluation
    print(f"\nExecution Time: {elapsed:.2f}s ({response.diagnostics.executionTimeMs}ms internal)")
    print(f"\n--- EXTRACTED ITEMS ({len(response.items)} kept / {response.diagnostics.totalItemsExtracted} extracted) ---")
    
    type_counts = {}
    conf_counts = {}
    for item in response.items:
        type_counts[item.type] = type_counts.get(item.type, 0) + 1
        conf_counts[item.confidence] = conf_counts.get(item.confidence, 0) + 1

    print(f"By Type: {type_counts}")
    print(f"By Confidence: {conf_counts}")

    print("\nDetailed Items:")
    for idx, item in enumerate(response.items, 1):
        extra_info = []
        if item.type == "answer":
            extra_info.append(f"QID: {item.questionId}")
        elif item.type == "action_item":
            extra_info.append(f"Owner: {item.ownerName} ({item.ownerParticipantId})")
            extra_info.append(f"Due: '{item.duePhrase}' -> {item.resolvedDueDate}")
        extra_str = f" [{', '.join(extra_info)}]" if extra_info else ""
        print(f"  {idx}. [{item.type.upper()}] ({item.confidence}) Lines {item.evidenceLineNumbers}: {item.text}{extra_str}")

    print(f"\n--- FOLLOW-UP QUESTIONS ({len(response.followUps)} kept / {response.diagnostics.followUpsGenerated} generated) ---")
    for idx, fu in enumerate(response.followUps, 1):
        print(f"  {idx}. [{fu.topic}] (Parent: {fu.parentQuestionId}): {fu.text}")
        print(f"     Reason: {fu.reason}")

    print("\n--- DIAGNOSTICS & DROP COUNTERS ---")
    print(f"Total Items Dropped: {response.diagnostics.totalItemsDropped}")
    print(f"Item Drops By Reason: {json.dumps(response.diagnostics.droppedByReason, indent=2)}")
    print(f"Follow-ups Dropped: {response.diagnostics.followUpsDropped}")
    print(f"Follow-up Drops By Reason: {json.dumps(response.diagnostics.followUpDroppedByReason, indent=2)}")
    print("-" * 80 + "\n")


async def main():
    print("STARTING TRANSCRIPT ANALYSIS PIPELINE EVALUATION\n")
    
    # 1. Run CGM Teams Paste Sample
    await run_single_sample(
        sample_name="CGM Demo (Teams Paste)",
        sample_file="sample_cgm_teams.json",
        output_file="pipeline_result_cgm_teams.json",
    )

    # 2. Run Real SRT Sample
    await run_single_sample(
        sample_name="Fleet Logistics (Real SRT)",
        sample_file="sample_real_srt.json",
        output_file="pipeline_result_real_srt.json",
    )

    print("ALL EVALUATION RUNS COMPLETED SUCCESSFULLY.")


if __name__ == "__main__":
    asyncio.run(main())

