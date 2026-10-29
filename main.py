import time
from fastapi import FastAPI, Request
import uvicorn
from app.routes import health_router, day_one_router
from app.utils.logger import logger

app = FastAPI(
    title="Thunder Agent AI Service",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start_time = time.time()
    method = request.method
    path = request.url.path

    logger.debug(f"--> {method} {path}")

    try:
        response = await call_next(request)
        duration_ms = (time.time() - start_time) * 1000
        status_code = response.status_code
        log_message = f"<-- {method} {path} {status_code} ({duration_ms:.1f}ms)"

        if status_code >= 500:
            logger.critical(log_message)
        elif status_code >= 400:
            logger.warning(log_message)
        else:
            logger.info(log_message)

        return response
    except Exception as exc:
        duration_ms = (time.time() - start_time) * 1000
        logger.critical(
            f"<-- {method} {path} 500 UNHANDLED EXCEPTION ({duration_ms:.1f}ms): {exc}",
            exc_info=True,
        )
        raise


# Register routes
app.include_router(health_router)
app.include_router(day_one_router)

logger.info("Thunder Agent AI Service ready. Registered routers: health, day_one")

if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
