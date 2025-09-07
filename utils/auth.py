from fastapi import Request, HTTPException
from jose import jwt
from jose.exceptions import ExpiredSignatureError, JWTError  # ✅ Import correct exceptions
from database import get_connection
from config import SECRET_KEY, ALGORITHM  # ✅ Safe, no circular imports
from functools import wraps

def get_user_role(username: str):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT Role FROM Users WHERE Username = ? AND IsActive = 1", (username,))
        result = cursor.fetchone()
        return result[0] if result else None

def get_user_info(request: Request):
    token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("sub")
        if not username:
            raise HTTPException(status_code=401, detail="Invalid token")

        user_role = get_user_role(username)
        if not user_role:
            raise HTTPException(status_code=403, detail="User role not found")

        return {"username": username, "user_role": user_role}

    except ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

def require_role(required_role: str):
    def decorator(func):
        @wraps(func)
        async def wrapper(request: Request, *args, **kwargs):
            user_info = get_user_info(request)
            if not user_info["user_role"] or user_info["user_role"] != required_role:
                raise HTTPException(status_code=403, detail="Can't access admin routes!")
            return await func(request, *args, **kwargs)
        return wrapper
    return decorator
