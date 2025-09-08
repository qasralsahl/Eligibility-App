from fastapi import Request, HTTPException
from jose import jwt
from jose.exceptions import ExpiredSignatureError, JWTError  # ✅ Import correct exceptions
from database import get_connection
from config import SECRET_KEY, ALGORITHM  # ✅ Safe, no circular imports
from functools import wraps
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.status import HTTP_303_SEE_OTHER
import inspect


templates = Jinja2Templates(directory="templates")

def get_user_role(username: str):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT Role FROM Users WHERE Username = ? AND IsActive = 1", (username,))
        result = cursor.fetchone()
        return result[0] if result else None

def get_user_info(request: Request):
    token = request.cookies.get("access_token")
    if not token:
        # Redirect to login if not authenticated
        return RedirectResponse("/login", status_code=HTTP_303_SEE_OTHER)
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("sub")
        if not username:
            return RedirectResponse("/login", status_code=HTTP_303_SEE_OTHER)
        user_role = get_user_role(username)
        if not user_role:
            return RedirectResponse("/login", status_code=HTTP_303_SEE_OTHER)
        return {"username": username, "user_role": user_role}
    except ExpiredSignatureError:
        return RedirectResponse("/login", status_code=HTTP_303_SEE_OTHER)
    except JWTError:
        return RedirectResponse("/login", status_code=HTTP_303_SEE_OTHER)

def require_role(required_role: str):
    def decorator(func):
        if inspect.iscoroutinefunction(func):
            @wraps(func)
            async def async_wrapper(request: Request, *args, **kwargs):
                user_info = get_user_info(request)
                if not user_info.get("user_role") or user_info["user_role"] != required_role:
                    return templates.TemplateResponse("acessdenied.html", {"request": request}, status_code=403)
                return await func(request, *args, **kwargs)
            return async_wrapper
        else:
            @wraps(func)
            def sync_wrapper(request: Request, *args, **kwargs):
                user_info = get_user_info(request)
                if not user_info.get("user_role") or user_info["user_role"] != required_role:
                    return templates.TemplateResponse("acessdenied.html", {"request": request}, status_code=403)
                return func(request, *args, **kwargs)
            return sync_wrapper
    return decorator
