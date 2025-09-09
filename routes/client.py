from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import RedirectResponse
from starlette.status import HTTP_303_SEE_OTHER
from fastapi.templating import Jinja2Templates
from database import get_connection
from utils.auth import get_user_info as get_current_user_info, require_role # ✅ renamed for clarity
import bcrypt

templates = Jinja2Templates(directory="templates")
router = APIRouter(prefix="/client")

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

@router.get("/list")
@require_role("SuperAdmin")
def client_list(request: Request):
    user_info = get_current_user_info(request)  # ✅ extract username and role
    if isinstance(user_info, RedirectResponse):
        return user_info
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT ID, ClientName, IsActive, CreatedOn FROM Users WHERE Role = 'Client'")
        clients = cursor.fetchall()

    return templates.TemplateResponse("client/list.html", {
        "request": request,
        "clients": clients,
        "username": user_info["username"],    # ✅ passed to base.html
        "user_role": user_info["user_role"]   # ✅ passed to base.html
    })

@router.get("/create")
@require_role("SuperAdmin")
def create_client_form(request: Request):
    user_info = get_current_user_info(request)  # ✅ extract username and role
    if isinstance(user_info, RedirectResponse):
        return user_info
    return templates.TemplateResponse("client/create.html", {
        "request": request,
        "username": user_info["username"],    # ✅ passed to base.html
        "user_role": user_info["user_role"]   # ✅ passed to base.html
        })

@router.post("/create")
@require_role("SuperAdmin")
def create_client(
    request: Request,
    ClientName: str = Form(...),
    Username: str = Form(...),
    Password: str = Form(...),
    Role: str = Form(...),
    IsActive: bool = Form(False)
):
    user_info = get_current_user_info(request)
    if isinstance(user_info, RedirectResponse):
        return user_info
    # Hash password before storing (use your existing hash function)
    hashed_password = hash_password(Password)
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO Users (ClientName, Username, Password, Role, IsActive) VALUES (?, ?, ?, ?, ?)",
            (ClientName, Username, hashed_password, Role, int(IsActive))
        )
        conn.commit()
    return RedirectResponse("/client/list", status_code=HTTP_303_SEE_OTHER)

@router.get("/edit/{id}")
@require_role("SuperAdmin")
def edit_client_form(request: Request, id: int):
    user_info = get_current_user_info(request)
    if isinstance(user_info, RedirectResponse):
        return user_info
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT ID, ClientName, Username, Password, Role, IsActive, CreatedOn FROM Users WHERE ID = ?", (id,))
        client = cursor.fetchone()
    return templates.TemplateResponse("client/edit.html", {
        "request": request, "client": client,
        "username": user_info["username"],
        "user_role": user_info["user_role"]
    })

@router.post("/edit/{id}")
@require_role("SuperAdmin")
def update_client(
    request: Request,
    id: int,
    ClientName: str = Form(...),
    Username: str = Form(...),
    Password: str = Form(""),
    Role: str = Form(...),
    IsActive: bool = Form(False)
):
    user_info = get_current_user_info(request)
    if isinstance(user_info, RedirectResponse):
        return user_info
    with get_connection() as conn:
        cursor = conn.cursor()
        if Password:
            hashed_password = hash_password(Password)
            cursor.execute(
                "UPDATE Users SET ClientName = ?, Username = ?, Password = ?, Role = ?, IsActive = ? WHERE ID = ?",
                (ClientName, Username, hashed_password, Role, int(IsActive), id)
            )
        else:
            # Keep current password
            cursor.execute(
                "UPDATE Users SET ClientName = ?, Username = ?, Role = ?, IsActive = ? WHERE ID = ?",
                (ClientName, Username, Role, int(IsActive), id)
            )
        conn.commit()
    return RedirectResponse("/client/list", status_code=HTTP_303_SEE_OTHER)

@router.post("/delete/{id}")
@require_role("SuperAdmin")
def delete_client(id: int, request: Request = None):
    user_info = get_current_user_info(request)
    if isinstance(user_info, RedirectResponse):
        return user_info
    # Check if client has any insurance mappings before deletion
    with get_connection() as conn:
        cursor = conn.cursor()
        
        # Check for existing insurance registrations
        cursor.execute("SELECT COUNT(*) FROM ClientInsuranceConfiguration WHERE ClientID = ?", (id,))
        registration_count = cursor.fetchone()[0]
        
        if registration_count > 0:
            # Client has insurance mappings, cannot delete
            return RedirectResponse(f"/client/list?error=Cannot delete client. It has {registration_count} insurance registration(s).", status_code=HTTP_303_SEE_OTHER)
        
        # No registrations, safe to delete
        cursor.execute("DELETE FROM Users WHERE ID = ? AND Role = 'Client'", (id,))
        conn.commit()
    
    return RedirectResponse("/client/list", status_code=HTTP_303_SEE_OTHER)