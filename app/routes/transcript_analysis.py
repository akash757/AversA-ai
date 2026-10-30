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
    except TimeoutError as exc:
        logger.warning(f"Analysis timed out for transcript {request.transcriptId}: {str(exc)}")
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=f"Analysis timed out: {str(exc)}",
        )
    except Exception as exc:
        err_msg = str(exc)
        if "timed out" in err_msg.lower() or "timeout" in err_msg.lower():
            logger.warning(f"Analysis timed out for transcript {request.transcriptId}: {err_msg}")
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail=f"Analysis timed out: {err_msg}",
            )
        logger.critical(
            f"Transcript analysis failed for transcript {request.transcriptId}: {err_msg}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Transcript analysis pipeline failed: {err_msg}",
        )

