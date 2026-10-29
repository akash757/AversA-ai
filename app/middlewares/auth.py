import secrets
from fastapi import Header, HTTPException, status
from app.config import settings
from app.utils.logger import logger


def verify_service_token(
    x_service_token: str | None = Header(None, alias="X-Service-Token"),
) -> str:
    logger.debug("Validating incoming X-Service-Token")

    if not settings.INTERNAL_SERVICE_TOKEN:
        logger.critical("Security misconfiguration: INTERNAL_SERVICE_TOKEN is not set in environment!")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Server security configuration error",
        )

    if not x_service_token:
        logger.warning("Authentication failed: Missing X-Service-Token in request headers")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing service token",
        )

    if not secrets.compare_digest(x_service_token, settings.INTERNAL_SERVICE_TOKEN):
        logger.warning("Authentication failed: Invalid X-Service-Token provided")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing service token",
        )

    logger.debug("X-Service-Token authenticated successfully")
    return x_service_token
