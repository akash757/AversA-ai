import sys
from pathlib import Path
from typing import List

# Ensure app is in path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.schemas.day_one import (
    TemplateItem,
    DayOneSuggestionsRequest,
    DayOneSuggestionsResponse,
)
from app.services.day_one import day_one_service


def parse_templates_file(filepath: Path | str) -> List[TemplateItem]:
    """Parse pipe-separated templates.txt file into TemplateItem objects."""
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"Templates file not found at: {path}")

    templates: List[TemplateItem] = []
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) == 3:
            templates.append(
                TemplateItem(
                    id=parts[0],
                    topicKey=parts[1],  # type: ignore
                    text=parts[2],
                )
            )
    return templates


def process_brief(
    brief: str, templates: List[TemplateItem], project_id: str = "prj_test"
) -> DayOneSuggestionsResponse:
    """Process a brief through DayOneService without needing FastAPI."""
    request = DayOneSuggestionsRequest(
        projectId=project_id,
        brief=brief,
        templates=templates,
    )
    return day_one_service.get_suggestions(request)

