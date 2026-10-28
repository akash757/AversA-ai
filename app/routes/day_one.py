from fastapi import APIRouter, Depends
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
    return day_one_service.get_suggestions(request)

