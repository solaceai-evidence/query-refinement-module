"""
Authentication API routes.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from datetime import timedelta

from query_refinement_module.db.session import get_db
from query_refinement_module.db.crud import create_user, get_user_by_username, get_user_by_email, verify_user_password
from query_refinement_module.api.schemas import UserCreate, UserResponse, Token
from query_refinement_module.api.auth import (
    get_password_hash,
    verify_password,
    create_access_token,
    get_current_user,
)
from query_refinement_module.api.config import get_settings

router = APIRouter(prefix="/auth", tags=["Authentication"])
settings = get_settings()


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(user_data: UserCreate, db: Session = Depends(get_db)):
    """
    Register a new user.
    
    - **username**: Unique username (3-50 characters, alphanumeric, underscore, hyphen)
    - **email**: Optional email address
    - **name**: Optional display name
    - **password**: Password (minimum 8 characters with uppercase, lowercase, digit, special char)
    """
    # Check if username already exists
    existing_user = get_user_by_username(db, username=user_data.username)
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already registered"
        )
    
    # Check if email already exists (if provided)
    if user_data.email:
        existing_email = get_user_by_email(db, email=user_data.email)
        if existing_email:
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
    
    return user


@router.post("/login", response_model=Token)
def login(
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
    
    return {"access_token": access_token, "token_type": "bearer"}


@router.get("/me", response_model=UserResponse)
def get_current_user_info(current_user = Depends(get_current_user)):
    """
    Get current authenticated user's information.
    
    Requires valid JWT token in Authorization header.
    """
    return current_user
