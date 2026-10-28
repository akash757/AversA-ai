from fastapi import FastAPI
import uvicorn
from app.routes import health_router, day_one_router

app = FastAPI(
    title="Thunder Agent AI Service",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# Register routes
app.include_router(health_router)
app.include_router(day_one_router)


if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
