"""
Authentication API routes with comprehensive audit logging.
"""
from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from datetime import timedelta

from query_refinement_module.db.session import get_db
from query_refinement_module.db.crud import create_user, get_user_by_username, get_user_by_email, verify_user_password
from query_refinement_module.api.schemas import UserCreate, UserResponse, Token
from query_refinement_module.api.auth import (
    create_access_token,
    get_current_user,
)
from query_refinement_module.api.config import get_settings
from query_refinement_module.audit import audit_service
from query_refinement_module.db.models.audit_log import AuditEventType

router = APIRouter(prefix="/auth", tags=["Authentication"])
settings = get_settings()


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(request: Request, user_data: UserCreate, db: Session = Depends(get_db)):
    """
    Register a new user with audit logging.
    
    - **username**: Unique username (3-50 characters, alphanumeric, underscore, hyphen)
    - **email**: Optional email address
    - **name**: Optional display name
    - **password**: Password (minimum 8 characters with uppercase, lowercase, digit, special char)
    """
    if not settings.allow_registration:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Self-service registration is disabled. Please contact the administrator."
        )
    # Check if username already exists
    existing_user = get_user_by_username(db, username=user_data.username)
    if existing_user:
        # Audit failed registration attempt
        audit_service.log_from_request(
            db=db,
            request=request,
            event_type=AuditEventType.REGISTER,
            severity="warning",
            resource_type="user",
            action=f"Registration failed: username '{user_data.username}' already exists",
            status="failure",
            details={"reason": "username_exists"}
        )
        
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already registered"
        )
    
    # Check if email already exists (if provided)
    if user_data.email:
        existing_email = get_user_by_email(db, email=user_data.email)
        if existing_email:
            # Audit failed registration attempt
            audit_service.log_from_request(
                db=db,
                request=request,
                event_type=AuditEventType.REGISTER,
                severity="warning",
                resource_type="user",
                action=f"Registration failed: email '{user_data.email}' already exists",
                status="failure",
                details={"reason": "email_exists"}
            )
            
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already registered"
            )
    
    # Create new user with hashed password
    user = create_user(
        db,
        username=user_data.username,
        password=user_data.password,
        email=user_data.email,
        name=user_data.name
    )
    
    # Audit successful registration
    audit_service.log_from_request(
        db=db,
        request=request,
        event_type=AuditEventType.REGISTER,
        severity="info",
        resource_type="user",
        resource_id=str(user.id),
        action=f"New user registered: {user.username}",
        status="success",
        details={
            "username": user.username,
            "email": user.email,
            "has_name": user.name is not None
        }
    )
    
    return user


@router.post("/login", response_model=Token)
def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):
    """
    Login with username/email and password to get an access token.
    
    - **username**: User's username or email address
    - **password**: User's password
    
    Returns a JWT access token for authenticated requests.
    The system automatically detects whether the identifier is a username or email.
    """
    # Verify user credentials (supports both username and email)
    user = verify_user_password(db, identifier=form_data.username, password=form_data.password)
    
    if not user:
        # Audit failed login attempt
        audit_service.log_from_request(
            db=db,
            request=request,
            event_type=AuditEventType.LOGIN_FAILURE,
            severity="warning",
            resource_type="user",
            action=f"Failed login attempt for: {form_data.username}",
            status="failure",
            details={
                "identifier": form_data.username,
                "reason": "invalid_credentials"
            }
        )
        db.commit()  # Ensure audit log is committed before raising exception
        
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username/email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Create access token with username in sub claim
    access_token_expires = timedelta(minutes=settings.access_token_expire_minutes)
    access_token = create_access_token(
        data={"sub": user.username}, expires_delta=access_token_expires
    )
    
    # Audit successful login
    audit_service.log_from_request(
        db=db,
        request=request,
        event_type=AuditEventType.LOGIN_SUCCESS,
        severity="info",
        user=user,
        resource_type="user",
        resource_id=str(user.id),
        action=f"User logged in: {user.username}",
        status="success",
        details={
            "login_method": "password",
            "token_expires_minutes": settings.access_token_expire_minutes
        }
    )
    
    return {"access_token": access_token, "token_type": "bearer"}


@router.get("/me", response_model=UserResponse)
def get_current_user_info(current_user = Depends(get_current_user)):
    """
    Get current authenticated user's information.
    
    Requires valid JWT token in Authorization header.
    """
    return current_user


@router.post("/logout", status_code=status.HTTP_200_OK)
def logout(
    request: Request,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Logout endpoint for audit logging.
    
    Note: JWT tokens cannot be invalidated server-side without additional infrastructure
    (e.g., Redis blocklist). This endpoint primarily serves audit logging purposes.
    Clients should discard the token on logout.
    """
    # Audit logout event
    audit_service.log_from_request(
        db=db,
        request=request,
        event_type=AuditEventType.LOGOUT,
        severity="info",
        user=current_user,
        resource_type="user",
        resource_id=str(current_user.id),
        action=f"User logged out: {current_user.username}",
        status="success"
    )
    
    return {"message": "Logout successful. Please discard your access token."}


@router.get("/me/status")
def get_user_status(current_user = Depends(get_current_user)):
    """
    Get current user's workflow status.
    
    Returns:
    - user_id: User's ID
    - username: Username
    - is_superuser: Whether user has unlimited workflows
    - has_completed_workflow: Whether user completed their one allowed workflow
    - can_start_new_workflow: Whether user is allowed to start a new workflow
    """
    return {
        "user_id": current_user.id,
        "username": current_user.username,
        "is_superuser": current_user.is_superuser,
        "has_completed_workflow": current_user.has_completed_workflow,
        "can_start_new_workflow": current_user.is_superuser or not current_user.has_completed_workflow
    }
