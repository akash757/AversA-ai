from langchain_google_genai import ChatGoogleGenerativeAI
from app.config import settings


def get_gemini_llm():
    """Create and return the configured Gemini model."""
    if not settings.GOOGLE_API_KEY:
        raise RuntimeError("GOOGLE_API_KEY is not configured in settings")

    return ChatGoogleGenerativeAI(
        model=settings.GEMINI_MODEL,
        google_api_key=settings.GOOGLE_API_KEY,
        temperature=0.2,
        timeout=30.0,
    )
