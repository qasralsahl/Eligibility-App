from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import RedirectResponse
from starlette.status import HTTP_303_SEE_OTHER
from fastapi.templating import Jinja2Templates
from database import get_connection
from utils.auth import get_user_info as get_current_user_info, require_role # ✅ renamed for clarity


templates = Jinja2Templates(directory="templates")
router = APIRouter(prefix="/client")
@require_role("SuperAdmin")
@router.get("/list")

def client_list(request: Request):
    user_info = get_current_user_info(request)  # ✅ extract username and role

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
    return templates.TemplateResponse("client/create.html", {
        "request": request,
        "username": user_info["username"],    # ✅ passed to base.html
        "user_role": user_info["user_role"]   # ✅ passed to base.html
        })

@router.post("/create")
@require_role("SuperAdmin")
def create_client(ClientName: str = Form(...), IsActive: bool = Form(False)):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO Users (ClientName, IsActive, Role) VALUES (?, ?, 'Client')",
            (ClientName, int(IsActive))
        )
        conn.commit()
    return RedirectResponse("/client/list", status_code=HTTP_303_SEE_OTHER)

@router.get("/edit/{id}")
@require_role("SuperAdmin")
def edit_client_form(request: Request, id: int):
    user_info = get_current_user_info(request)  # ✅ extract username and role
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT ID, ClientName, IsActive FROM Users WHERE ID = ? AND Role = 'Client'", (id,))
        client = cursor.fetchone()
    return templates.TemplateResponse("client/edit.html", {
        "request": request, "client": client,
        "username": user_info["username"],      # ✅ Pass to
        "user_role": user_info["user_role"]     # ✅ Pass to template
        })

@router.post("/edit/{id}")
@require_role("SuperAdmin")
def update_client(id: int, ClientName: str = Form(...), IsActive: bool = Form(False)):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE Users SET ClientName = ?, IsActive = ? WHERE ID = ? AND Role = 'Client'",
            (ClientName, int(IsActive), id)
        )
        conn.commit()
    return RedirectResponse("/client/list", status_code=HTTP_303_SEE_OTHER)

@router.post("/delete/{id}")
@require_role("SuperAdmin")
def delete_client(id: int):
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