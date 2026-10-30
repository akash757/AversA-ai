from langchain_google_genai import ChatGoogleGenerativeAI
from app.config import settings
from app.utils.logger import logger


def get_gemini_llm(temperature: float = 0.2, timeout: float = 30.0):
    """Create and return the configured Gemini model."""
    if not settings.GOOGLE_API_KEY:
        logger.critical("Critical configuration error: GOOGLE_API_KEY is not configured in settings!")
        raise RuntimeError("GOOGLE_API_KEY is not configured in settings")

    logger.debug(f"Instantiating ChatGoogleGenerativeAI (model={settings.GEMINI_MODEL}, timeout={timeout}s)")

    return ChatGoogleGenerativeAI(
        model=settings.GEMINI_MODEL,
        google_api_key=settings.GOOGLE_API_KEY,
        temperature=temperature,
        timeout=timeout,
    )
