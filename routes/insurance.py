from fastapi import APIRouter, Request, Form
from fastapi.responses import RedirectResponse
from starlette.status import HTTP_303_SEE_OTHER
from database import get_connection
from fastapi.templating import Jinja2Templates
import pyodbc
from urllib.parse import urlencode
from utils.auth import get_user_info as get_current_user_info  # ✅ renamed for clarity

templates = Jinja2Templates(directory="templates")
router = APIRouter(prefix="/insurance")

@router.get("/list")
def list_insurance(request: Request):
    user_info = get_current_user_info(request)  # ✅ extract username and role
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT ID, InsuranceCode, InsauranceName, IsActive, CreatedOn FROM InsauranceMaster")
    insurances = cursor.fetchall()
    conn.close()

    return templates.TemplateResponse("insurance/list.html", {
        "request": request,
        "insurances": insurances,
        "username": user_info["username"],      # ✅ Pass to template
        "user_role": user_info["user_role"]     # ✅ Pass to template
    })
@router.get("/create")
def create_insurance_form(request: Request):
    user_info = get_current_user_info(request)  # ✅ extract username and role
    return templates.TemplateResponse("insurance/create.html", {
        "request": request,
        "username": user_info["username"],      # ✅ Pass to template
        "user_role": user_info["user_role"]     # ✅ Pass to template
        })

@router.post("/create")
def create_insurance(InsuranceCode: str = Form(...), InsauranceName: str = Form(...)):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO InsauranceMaster (InsuranceCode, InsauranceName) VALUES (?, ?)", (InsuranceCode, InsauranceName))
    conn.commit()
    conn.close()
    return RedirectResponse("/insurance/list", status_code=HTTP_303_SEE_OTHER)

@router.get("/edit/{id}")
def edit_insurance_form(request: Request, id: int):
    user_info = get_current_user_info(request)  # ✅ extract username and role
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT ID, InsuranceCode, InsauranceName, IsActive FROM InsauranceMaster WHERE ID = ?", (id,))
    insurance = cursor.fetchone()
    conn.close()
    return templates.TemplateResponse("insurance/edit.html", {
        "request": request, "insurance": insurance,
        "username": user_info["username"],      # ✅ Pass to
        "user_role": user_info["user_role"]     # ✅ Pass to template
        })

@router.post("/edit/{id}")
def update_insurance(id: int, InsuranceCode: str = Form(...), InsauranceName: str = Form(...),  IsActive: str = Form("off")):
    is_active_flag = 1 if IsActive == 'on' else 0
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE InsauranceMaster SET InsuranceCode=?, InsauranceName=?, IsActive=? WHERE ID=?",
        (InsuranceCode, InsauranceName, is_active_flag, id)
    )
    conn.commit()
    conn.close()
    return RedirectResponse("/insurance/list", status_code=HTTP_303_SEE_OTHER)

@router.post("/delete/{id}")
def delete_insurance(id: int):
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        # Check if insurance is used in any client registrations
        cursor.execute("SELECT COUNT(*) FROM ClientInsauranceRegisteration WHERE InsauranceID = ?", (id,))
        registration_count = cursor.fetchone()[0]
        
        if registration_count > 0:
            # Insurance is assigned to clients, cannot delete
            error_msg = f"Cannot delete insurance. It is assigned to {registration_count} client(s)."
            query = urlencode({"error": error_msg})
            return RedirectResponse(f"/insurance/list?{query}", status_code=HTTP_303_SEE_OTHER)
        
        # No registrations, safe to delete
        cursor.execute("DELETE FROM InsauranceMaster WHERE ID=?", (id,))
        conn.commit()
        conn.close()
        return RedirectResponse("/insurance/list", status_code=HTTP_303_SEE_OTHER)

    except pyodbc.IntegrityError as e:
        conn.rollback()
        conn.close()
        # Redirect back to list with error message
        error_msg = "Cannot delete: This insurance is assigned to one or more clients."
        query = urlencode({"error": error_msg})
        return RedirectResponse(f"/insurance/list?{query}", status_code=HTTP_303_SEE_OTHER)
    except Exception as e:
        conn.rollback()
        conn.close()
        error_msg = f"Error deleting insurance: {str(e)}"
        query = urlencode({"error": error_msg})
        return RedirectResponse(f"/insurance/list?{query}", status_code=HTTP_303_SEE_OTHER)