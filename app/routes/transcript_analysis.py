import asyncio
import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from app.middlewares.auth import verify_service_token
from app.schemas.transcript_analysis import (
    TranscriptAnalysisRequest,
    TranscriptAnalysisResponse,
)
from app.services.transcript_analysis import transcript_analysis_service
from app.utils.logger import logger

transcript_analysis_router = APIRouter(
    prefix="/internal",
    tags=["Transcript Analysis"],
    dependencies=[Depends(verify_service_token)],
)


@transcript_analysis_router.post(
    "/transcript-analysis",
    response_model=TranscriptAnalysisResponse,
)
async def analyze_transcript(request: TranscriptAnalysisRequest):
    logger.info(
        f"Received transcript analysis request for transcript {request.transcriptId} "
        f"in project {request.projectId} ({len(request.chunks)} chunks, "
        f"{len(request.questions)} questions, {len(request.participants)} participants)"
    )

    try:
        response = await transcript_analysis_service.analyze_transcript(request)
        logger.info(
            f"Successfully analyzed transcript {request.transcriptId}: "
            f"extracted {len(response.items)} items, generated {len(response.followUps)} follow-ups"
        )
        return response
    except (asyncio.TimeoutError, TimeoutError, httpx.TimeoutException):
        logger.warning(
            "Analysis timed out for transcript %s",
            request.transcriptId,
        )
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="TRANSCRIPT_ANALYSIS_TIMEOUT: Analysis pipeline timed out.",
        )
    except Exception as exc:
        exc_class = type(exc).__name__
        logger.critical(
            "Transcript analysis failed for transcript %s with %s",
            request.transcriptId,
            exc_class,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="TRANSCRIPT_ANALYSIS_FAILED: An internal error occurred during transcript analysis.",
        )

