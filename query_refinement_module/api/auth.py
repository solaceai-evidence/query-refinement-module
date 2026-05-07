"""
Authentication utilities for JWT token handling and password hashing.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional
import secrets
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, Request, status, Security
from fastapi.security import OAuth2PasswordBearer, HTTPBearer, HTTPAuthorizationCredentials, APIKeyHeader
from sqlalchemy.orm import Session

from query_refinement_module.db.session import get_db
from query_refinement_module.db.crud import get_user_by_username, create_user
from query_refinement_module.api.config import get_settings

settings = get_settings()

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# OAuth2 scheme for token authentication
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)
optional_bearer_scheme = HTTPBearer(auto_error=False)
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain password against a hashed password."""
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """Hash a password."""
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create a JWT access token."""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)
    return encoded_jwt


def decode_access_token(token: str) -> Optional[dict]:
    """Decode and verify a JWT access token."""
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        return payload
    except JWTError:
        return None


def _extract_token(request: Request, bearer_token: Optional[str]) -> Optional[str]:
    """Extract JWT from httpOnly cookie or, as fallback, Authorization header.

    Cookie takes precedence because it is the secure default for browser
    clients.  The Authorization header fallback supports the integration
    service and legacy curl / Swagger UI flows.
    """
    cookie_token = request.cookies.get(settings.auth_cookie_name)
    if cookie_token:
        return cookie_token
    return bearer_token


async def get_current_user(
    request: Request,
    bearer_token: Optional[str] = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
):
    """Get the current authenticated user from httpOnly cookie or Bearer token."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    token = _extract_token(request, bearer_token)
    if not token:
        raise credentials_exception

    payload = decode_access_token(token)
    if payload is None:
        raise credentials_exception
    
    username: str = payload.get("sub")
    if username is None:
        raise credentials_exception
    
    user = get_user_by_username(db, username=username)
    if user is None:
        raise credentials_exception
    
    return user


def _get_or_create_integration_service_user(db: Session):
    """Return the configured integration service user, creating it on first use.

    The integration user is a regular (non-superuser) account.  Framework access
    must be granted explicitly via the admin ``user_framework_access`` table.
    """
    username = settings.integration_service_username
    user = get_user_by_username(db, username=username)

    if user is None:
        user = create_user(
            db,
            username=username,
            password=secrets.token_urlsafe(48),
            name="API Integration Service",
        )

    return user


async def get_current_user_or_integration(
    request: Request,
    bearer_credentials: Optional[HTTPAuthorizationCredentials] = Depends(optional_bearer_scheme),
    integration_api_key: Optional[str] = Security(api_key_header),
    db: Session = Depends(get_db),
):
    """Authenticate either an end-user JWT token (cookie or Bearer) or trusted integration API key."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    # Cookie takes precedence for browser clients
    cookie_token = request.cookies.get(settings.auth_cookie_name)
    if cookie_token:
        payload = decode_access_token(cookie_token)
        if payload is None:
            raise credentials_exception
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
        user = get_user_by_username(db, username=username)
        if user is None:
            raise credentials_exception
        return user

    if bearer_credentials and bearer_credentials.scheme.lower() == "bearer":
        payload = decode_access_token(bearer_credentials.credentials)
        if payload is None:
            raise credentials_exception

        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception

        user = get_user_by_username(db, username=username)
        if user is None:
            raise credentials_exception
        return user

    if integration_api_key:
        expected_api_key = settings.integration_api_key
        if expected_api_key and secrets.compare_digest(integration_api_key, expected_api_key):
            return _get_or_create_integration_service_user(db)
        raise credentials_exception

    raise credentials_exception
