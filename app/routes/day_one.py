from fastapi import APIRouter, Depends, HTTPException, status
from app.middlewares.auth import verify_service_token
from app.schemas.day_one import (
    DayOneSuggestionsRequest,
    DayOneSuggestionsResponse,
)
from app.services.day_one import day_one_service
from app.utils.logger import logger

day_one_router = APIRouter(
    prefix="/internal/day-one",
    tags=["Day One Suggestions"],
    dependencies=[Depends(verify_service_token)],
)


@day_one_router.post(
    "/suggestions",
    response_model=DayOneSuggestionsResponse,
)
def get_day_one_suggestions(request: DayOneSuggestionsRequest):
    logger.info("Received request for Day One suggestions")
    logger.debug(
        f"Payload summary: brief_chars={len(request.brief.strip())}, "
        f"templates_count={len(request.templates)}"
    )

    try:
        response = day_one_service.get_suggestions(request)
        logger.info(
            f"Successfully produced {len(response.suggestions)} suggestions "
            f"(briefTooThin={response.briefTooThin})"
        )
        return response
    except TimeoutError as exc:
        logger.warning(f"Model call timed out: {str(exc)}")
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=f"Model call timed out: {str(exc)}",
        )
    except Exception as exc:
        err_msg = str(exc)
        if "timed out" in err_msg.lower() or "timeout" in err_msg.lower():
            logger.warning(f"Model call timed out: {err_msg}")
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail=f"Model call timed out: {err_msg}",
            )
        logger.critical(f"Unexpected failure generating suggestions: {err_msg}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"The model failed: {err_msg}",
        )
