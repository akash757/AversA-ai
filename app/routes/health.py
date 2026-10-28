from fastapi import APIRouter

health_router = APIRouter(tags=["Health"])


@health_router.get("/health")
def health():
    return {"status": "ok"}

