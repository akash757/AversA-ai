from fastapi import APIRouter
from app.utils.logger import logger

health_router = APIRouter(tags=["Health"])


@health_router.get("/health")
def health():
    logger.debug("Health check ping received")
    return {"status": "ok", "service": "thunder-agent-ai"}
