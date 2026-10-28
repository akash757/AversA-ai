import secrets
from fastapi import Header, HTTPException, status
from app.config import settings


def verify_service_token(
    x_service_token: str | None = Header(None, alias="X-Service-Token"),
) -> str:
    if not x_service_token or not secrets.compare_digest(
        x_service_token, settings.INTERNAL_SERVICE_TOKEN
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing service token",
        )
    return x_service_token
