from langchain_google_genai import ChatGoogleGenerativeAI
from app.config import settings

for model in ["gemini-3.8-flash", "gemini-2.5-flash", "gemini-2.0-flash"]:
    try:
        m = ChatGoogleGenerativeAI(model=model, google_api_key=settings.GOOGLE_API_KEY)
        res = m.invoke("Hi")
        print(f"SUCCESS with {model}: {res.content[:50]}")
        break
    except Exception as e:
        print(f"FAILED {model}: {e}")
