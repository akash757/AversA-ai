from fastapi import APIRouter, Depends, HTTPException, status
from app.middlewares.auth import verify_service_token
from app.schemas.day_one import (
    DayOneSuggestionsRequest,
    DayOneSuggestionsResponse,
)
from app.services.day_one import day_one_service

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
    try:
        return day_one_service.get_suggestions(request)
    except TimeoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=f"Model call timed out: {str(exc)}",
        )
    except Exception as exc:
        err_msg = str(exc)
        if "timed out" in err_msg.lower() or "timeout" in err_msg.lower():
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail=f"Model call timed out: {err_msg}",
            )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"The model failed: {err_msg}",
        )
