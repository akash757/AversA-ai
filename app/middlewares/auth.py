from fastapi import Header, HTTPException, status
from app.config import settings


def verify_service_token(
    x_service_token: str | None = Header(None, alias="X-Service-Token"),
    authorization: str | None = Header(None, alias="Authorization"),
) -> str:
    token = x_service_token
    if not token and authorization:
        if authorization.lower().startswith("bearer "):
            token = authorization[7:].strip()
        else:
            token = authorization.strip()

    if not token or token != settings.INTERNAL_SERVICE_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing service token",
        )
    return token

