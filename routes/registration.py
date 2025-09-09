from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import RedirectResponse, HTMLResponse, JSONResponse
from starlette.status import HTTP_303_SEE_OTHER, HTTP_400_BAD_REQUEST
from fastapi.templating import Jinja2Templates
from database import get_connection
from datetime import datetime
import re
from typing import Optional
from utils.auth import get_user_info as get_current_user_info  # ✅ renamed for clarity

templates = Jinja2Templates(directory="templates")
router = APIRouter(prefix="/registration")

@router.get("/list")
def list_registrations(request: Request):
    user_info = get_current_user_info(request)  # ✅ Get username and role
    if isinstance(user_info, RedirectResponse):
        return user_info
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT 
        cic.ID, 
        u.ClientName, 
        im.InsuranceName, 
        cic.Username, 
        cic.Password,
        cic.IsActive, 
        cic.ClientID, 
        cic.InsuranceID, 
        cic.ExpirationDate
    FROM ClientInsuranceConfiguration cic
    JOIN Users u ON cic.ClientID = u.ID
    JOIN InsuranceMaster im ON cic.InsuranceID = im.ID
    """)
    registrations = cursor.fetchall()
    
    cursor.execute("SELECT ID, ClientName FROM Users WHERE IsActive = 1 AND Role = 'Client'")
    clients = cursor.fetchall()
    cursor.execute("SELECT ID, InsuranceName FROM InsuranceMaster WHERE IsActive = 1")
    insurances = cursor.fetchall()
    
    conn.close()
    
    current_date = datetime.now().strftime("%Y-%m-%d")
    
    return templates.TemplateResponse("registration/list.html", {
        "request": request, 
        "registrations": registrations,
        "clients": clients,
        "insurances": insurances,
        "current_date": current_date,
        "username": user_info["username"],       
        "user_role": user_info["user_role"]      
    })

@router.post("/create")
def create_registration(
    request: Request,
    ClientID: int = Form(...),
    InsuranceID: int = Form(...),
    Username: str = Form(...),
    Password: str = Form(...),
    ExpirationDate: str = Form(...),
    IsActive: Optional[str] = Form(None)
):
    user_info = get_current_user_info(request)
    if isinstance(user_info, RedirectResponse):
        return user_info
    
    is_active_value = 1 if IsActive == "on" else 0
    # Validate username format (alphanumeric, hyphen, underscore only)
    if not re.match(r'^[A-Za-z0-9\-_]+$', Username):
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail="Username can only contain letters, numbers, hyphens, and underscores"
        )
    
    # Validate password strength
    if len(Password) < 8:
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail="Password must be at least 8 characters long"
        )
    
    if not re.search(r'[A-Z]', Password):
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail="Password must contain at least one uppercase letter"
        )
    
    if not re.search(r'[0-9]', Password):
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail="Password must contain at least one number"
        )
    
    if not re.search(r'[!@#$%^&*()_+\-=\[\]{};:\'",.<>/?]', Password):
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail="Password must contain at least one special character"
        )
    
    # Validate expiration date
    exp_date = datetime.strptime(ExpirationDate, "%Y-%m-%d")
    if exp_date <= datetime.now():
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail="Expiration date must be in the future"
        )
    
    conn = get_connection()
    cursor = conn.cursor()
    
    # Check if configuration already exists
    cursor.execute(
        "SELECT ID FROM ClientInsuranceConfiguration WHERE ClientID = ? AND InsuranceID = ?",
        (ClientID, InsuranceID)
    )
    existing = cursor.fetchone()
    
    if existing:
        conn.close()
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail="Configuration already exists for this client and insurance combination"
        )
    
    # Insert new configuration
    cursor.execute(
        """INSERT INTO ClientInsuranceConfiguration 
           (ClientID, InsuranceID, Username, Password, ExpirationDate, IsActive, CreatedOn) 
           VALUES (?, ?, ?, ?, ?, ?, GETDATE())""",
        (ClientID, InsuranceID, Username, Password, ExpirationDate, is_active_value)
    )
    
    conn.commit()
    conn.close()
    
    return RedirectResponse("/registration/list", status_code=HTTP_303_SEE_OTHER)

@router.get("/edit/{id}")
def edit_registration_form(request: Request, id: int):
    user_info = get_current_user_info(request)  # ✅ extract username and role
    if isinstance(user_info, RedirectResponse):
        return user_info
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT cic.ID, cic.ClientID, cic.InsuranceID, cic.Username, cic.Password, 
                   cic.IsActive, cic.ExpirationDate, u.ClientName, im.InsuranceName
            FROM ClientInsuranceConfiguration cic
            JOIN Users u ON cic.ClientID = u.ID
            JOIN InsuranceMaster im ON cic.InsuranceID = im.ID
            WHERE cic.ID = ?
        """, (id,))
        registration = cursor.fetchone()
        
        if not registration:
            raise HTTPException(status_code=404, detail="Registration not found")
        
        cursor.execute("SELECT ID, ClientName FROM Users WHERE IsActive = 1 AND Role = 'Client'")
        clients = cursor.fetchall()
        cursor.execute("SELECT ID, InsuranceName FROM InsuranceMaster WHERE IsActive = 1")
        insurances = cursor.fetchall()
        
    return templates.TemplateResponse("registration/edit.html", {
        "request": request, 
        "registration": registration, 
        "clients": clients, 
        "insurances": insurances,
        "username": user_info["username"],      # ✅ Pass to
        "user_role": user_info["user_role"]     # ✅ Pass to template
    })

@router.post("/edit/{id}")
def update_registration(
    request: Request,
    id: int, 
    ClientID: int = Form(...),
    InsuranceID: int = Form(...),
    Username: str = Form(...),
    Password: str = Form(...),
    ExpirationDate: str = Form(...),
    IsActive: Optional[str] = Form(None)
):
    # import pdb; pdb.set_trace()
    user_info = get_current_user_info(request)
    if isinstance(user_info, RedirectResponse):
        return user_info
    is_active_value = 1 if IsActive == "on" else 0
    # Validate username format
    if not re.match(r'^[A-Za-z0-9\-_]+$', Username):
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail="Username can only contain letters, numbers, hyphens, and underscores"
        )
    
    # Validate password strength
    if len(Password) < 8:
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail="Password must be at least 8 characters long"
        )
    
    if not re.search(r'[A-Z]', Password):
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail="Password must contain at least one uppercase letter"
        )
    
    if not re.search(r'[0-9]', Password):
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail="Password must contain at least one number"
        )
    
    if not re.search(r'[!@#$%^&*()_+\-=\[\]{};:\'",.<>/?]', Password):
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail="Password must contain at least one special character"
        )
    
    # Validate expiration date
    exp_date = datetime.strptime(ExpirationDate, "%Y-%m-%d")
    if exp_date <= datetime.now():
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail="Expiration date must be in the future"
        )
    
    with get_connection() as conn:
        cursor = conn.cursor()
        
        # Check if the client-insurance combination already exists for another record
        cursor.execute(
            """SELECT ID FROM ClientInsuranceConfiguration 
               WHERE ClientID = ? AND InsuranceID = ? AND ID != ?""",
            (ClientID, InsuranceID, id)
        )
        existing = cursor.fetchone()
        
        if existing:
            raise HTTPException(
                status_code=HTTP_400_BAD_REQUEST,
                detail="Configuration already exists for this client and insurance combination"
            )
        
        cursor.execute(
            """UPDATE ClientInsuranceConfiguration 
               SET ClientID=?, InsuranceID=?, Username=?, Password=?, 
                   ExpirationDate=?, IsActive=?
               WHERE ID=?""",
            (ClientID, InsuranceID, Username, Password, ExpirationDate, is_active_value, id)
        )
        
        conn.commit()
    
    return RedirectResponse("/registration/list", status_code=HTTP_303_SEE_OTHER)

@router.post("/delete/{id}")
def delete_registration(request: Request, id: int):
    user_info = get_current_user_info(request)
    if isinstance(user_info, RedirectResponse):
        return user_info
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM ClientInsuranceConfiguration WHERE ID=?", (id,))
    conn.commit()
    conn.close()
    return RedirectResponse("/registration/list", status_code=HTTP_303_SEE_OTHER)

# Additional endpoint to check if a configuration already exists
@router.get("/check-config")
def check_configuration(request: Request, client_id: int, insurance_id: int):
    user_info = get_current_user_info(request)
    if isinstance(user_info, RedirectResponse):
        return user_info
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT ID FROM ClientInsuranceConfiguration WHERE ClientID = ? AND InsuranceID = ?",
        (client_id, insurance_id)
    )
    existing = cursor.fetchone()
    conn.close()
    
    return {"exists": existing is not None}

@router.get("/check-config")
async def check_configuration(request: Request, client_id: int, insurance_id: int):
    user_info = get_current_user_info(request)
    if isinstance(user_info, RedirectResponse):
        return user_info
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT ID FROM ClientInsuranceConfiguration WHERE ClientID = ? AND InsuranceID = ?",
        (client_id, insurance_id)
    )
    existing = cursor.fetchone()
    conn.close()
    
    return {"exists": existing is not None}