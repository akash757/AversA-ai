import os
from langchain_google_genai import ChatGoogleGenerativeAI

def get_gemini_llm():
    """Create and return the configured Gemini model."""

    if not os.getenv("GOOGLE_API_KEY"):
        raise RuntimeError("GOOGLE_API_KEY environment variable is not set")

    return ChatGoogleGenerativeAI(
        model=os.getenv("GEMINI_MODEL"),
        verbose=True,
    )


