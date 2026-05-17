import os
import secrets
from fastapi import HTTPException, Depends, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

security = HTTPBasic()


def require_admin(credentials: HTTPBasicCredentials = Depends(security)):
    """HTTP Basic auth guard for admin routes."""
    correct_user = os.environ.get("ADMIN_USERNAME", "admin")
    correct_pass = os.environ.get("ADMIN_PASSWORD", "changeme")
    user_ok = secrets.compare_digest(credentials.username.encode(), correct_user.encode())
    pass_ok = secrets.compare_digest(credentials.password.encode(), correct_pass.encode())
    if not (user_ok and pass_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


def validate_magic_token(token: str) -> dict:
    """Validate a player's magic-link token; returns the player row or raises 404."""
    from api.lib.db import get_player_by_token
    player = get_player_by_token(token)
    if not player:
        raise HTTPException(status_code=404, detail="Invalid or expired link.")
    if not player.get("is_active"):
        raise HTTPException(status_code=403, detail="Your account is inactive. Contact the commish.")
    return player
