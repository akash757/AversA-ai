from app.schemas.day_one import (
    DayOneSuggestionsRequest,
    DayOneSuggestionsResponse,
)


class DayOneService:
    """Service to process day-one briefs and generate suggestions."""

    def __init__(self):
        pass

    def get_suggestions(
        self, request: DayOneSuggestionsRequest
    ) -> DayOneSuggestionsResponse:
        brief_stripped = request.brief.strip() if request.brief else ""
        if len(brief_stripped) < 20:
            return DayOneSuggestionsResponse(briefTooThin=True, suggestions=[])

        return DayOneSuggestionsResponse(briefTooThin=False, suggestions=[])


day_one_service = DayOneService()

