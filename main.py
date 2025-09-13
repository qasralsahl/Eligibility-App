import asyncio

if hasattr(asyncio, "WindowsSelectorEventLoopPolicy"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from fastapi import FastAPI, HTTPException, Request, Form, Depends, UploadFile, File
from fastapi.responses import RedirectResponse, HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, validator
from starlette.status import HTTP_303_SEE_OTHER
from datetime import datetime, timedelta
from pydantic import ValidationError
import pandas as pd
import asyncio
import io
import os
import bcrypt
from jose import jwt
from functools import wraps
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

# Local imports
from database import get_connection

# from eligibility_checker import EligibilityChecker
from routes import insurance
from routes import client
from routes import registration

from config import SECRET_KEY, ALGORITHM
from utils.auth import get_user_info as get_current_user_info

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)
from automation.nextcare_checker import NextCareEligibilityChecker


# -------------------- Logging Configuration --------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("app.log", encoding="utf-8"),
    ],
)

# -------------------- App Setup --------------------
app = FastAPI()
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")
# app.mount("/screenshots", StaticFiles(directory=os.path.join(BASE_DIR, "/screenshots")), name="screenshots")
executor = ThreadPoolExecutor(max_workers=5)

# Include modular routes
app.include_router(insurance.router)
app.include_router(client.router)
app.include_router(registration.router)


# -------------------- Authentication Functions --------------------
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(
        plain_password.encode("utf-8"), hashed_password.encode("utf-8")
    )


def create_access_token(data: dict, expires_delta: timedelta = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=60)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def require_role(required_role: str):
    def decorator(func):
        @wraps(func)
        async def wrapper(request: Request, *args, **kwargs):
            user_info = get_current_user_info(request)
            if not user_info["user_role"] or user_info["user_role"] != required_role:
                raise HTTPException(status_code=403, detail="Insufficient permissions")
            return await func(request, *args, **kwargs)

        return wrapper

    return decorator


def get_clients(user_role: str, username: str):
    """Get clients based on user role from registration data"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT DISTINCT 
                u.ID, 
                u.ClientName
            FROM ClientInsuranceConfiguration cic
            JOIN Users u ON cic.ClientID = u.ID
            WHERE cic.IsActive = 1 AND u.IsActive = 1 AND u.Role = 'Client'
            ORDER BY u.ClientName
        """
        )
        clients = cursor.fetchall()
        logging.info(
            f"get_clients - Role: {user_role}, Username: {username}, Found: {len(clients)} clients"
        )
        return clients


def get_upload_history(user_role: str, username: str):
    """Get upload history based on user role"""
    with get_connection() as conn:
        cursor = conn.cursor()
        if user_role == "SuperAdmin":
            cursor.execute(
                """
                SELECT uh.ID, u.ClientName, uh.FileName, uh.UploadDate 
                FROM UploadHistory uh
                JOIN Users u ON uh.ClientID = u.ID
                ORDER BY uh.UploadDate DESC
            """
            )
        else:
            cursor.execute(
                """
                SELECT uh.ID, u.ClientName, uh.FileName, uh.UploadDate 
                FROM UploadHistory uh
                JOIN Users u ON uh.ClientID = u.ID
                WHERE u.Username = ?
                ORDER BY uh.UploadDate DESC
            """,
                (username,),
            )
        return cursor.fetchall()


def get_patient_data(user_role: str, username: str):
    """Get patient data based on user role with required columns"""
    with get_connection() as conn:
        cursor = conn.cursor()
        if user_role == "SuperAdmin":
            cursor.execute(
                """
                SELECT TOP 10 
                    er.EligibilityId as PatientID, 
                    er.AppointmentDateTime as AppointmentDate, 
                    im.InsuranceCode as InsuranceCode,
                    u.ClientName as ClientName,
                    CASE 
                        WHEN ers.ID IS NULL THEN 'Pending' 
                        WHEN ers.Is_Eligible = 'Eligible' THEN 'Eligible' 
                        ELSE 'Not Eligible' 
                    END as Status,
                    er.CreatedOn 
                FROM EligibilityRequest er
                LEFT JOIN EligibilityResponse ers ON er.EligibilityId = ers.EligibilityRequestID
                JOIN Users u ON er.ClientID = u.ID
                JOIN InsuranceMaster im ON er.InsuranceID = im.ID
                ORDER BY er.CreatedOn DESC
            """
            )
        else:
            cursor.execute(
                """
                SELECT TOP 10 
                    er.EligibilityId as PatientID, 
                    er.AppointmentDateTime as AppointmentDate, 
                    im.InsuranceCode as InsuranceCode,
                    u.ClientName as ClientName,
                    CASE 
                        WHEN ers.ID IS NULL THEN 'Pending' 
                        WHEN ers.Is_Eligible = 'Eligible' THEN 'Eligible'
                        ELSE 'Not Eligible' 
                    END as Status,
                    er.CreatedOn 
                FROM EligibilityRequest er
                LEFT JOIN EligibilityResponse ers ON er.EligibilityId = ers.EligibilityRequestID
                JOIN Users u ON er.ClientID = u.ID
                JOIN InsuranceMaster im ON er.InsuranceID = im.ID
                WHERE u.Username = ?
                ORDER BY er.CreatedOn DESC
            """,
                (username,),
            )
        return cursor.fetchall()


# -------------------- Authentication Routes --------------------
@app.get("/")
def root_redirect():
    """Redirect root path to login"""
    return RedirectResponse("/dashboard")


@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


@app.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT ID, Username, Password, Role FROM Users WHERE Username = ? AND IsActive = 1",
            (username,),
        )
        user = cursor.fetchone()

    if not user or not verify_password(password, user[2]):
        return templates.TemplateResponse(
            "login.html", {"request": request, "error": "Invalid username or password"}
        )

    access_token = create_access_token(data={"sub": user[1], "role": user[3]})
    response = RedirectResponse("/dashboard", status_code=HTTP_303_SEE_OTHER)
    response.set_cookie(key="access_token", value=access_token, httponly=True)
    return response


# -------------------------
# Signup (GET + POST)
# -------------------------
@app.get("/signup", response_class=HTMLResponse)
def signup_form(request: Request):
    return templates.TemplateResponse("signup.html", {"request": request})


@app.post("/signup")
def signup(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...),
    client_name: str = Form(None),
):
    # Check password match
    if password != confirm_password:
        return templates.TemplateResponse(
            "signup.html", {"request": request, "error": "Passwords do not match"}
        )

    hashed_pw = hash_password(password)

    try:
        with get_connection() as conn:
            cursor = conn.cursor()

            # Check existing user
            cursor.execute("SELECT ID FROM Users WHERE Username = ?", (username,))
            if cursor.fetchone():
                return templates.TemplateResponse(
                    "signup.html",
                    {"request": request, "error": "Username already exists"},
                )

            # Default new users to "Client"
            cursor.execute(
                """
                INSERT INTO Users (ClientName, Username, Password, Role, IsActive, CreatedOn)
                VALUES (?, ?, ?, ?, 1, GETDATE())
            """,
                (client_name, username, hashed_pw, "Client"),
            )
            conn.commit()

            # Get newly created user
            cursor.execute(
                "SELECT ID, Username, Role FROM Users WHERE Username = ?", (username,)
            )
            new_user = cursor.fetchone()

    except Exception as e:
        return templates.TemplateResponse(
            "signup.html",
            {"request": request, "error": f"Error creating account: {str(e)}"},
        )

    # Auto-login after signup
    access_token = create_access_token(data={"sub": new_user[1], "role": new_user[2]})
    response = RedirectResponse("/dashboard", status_code=HTTP_303_SEE_OTHER)
    response.set_cookie(key="access_token", value=access_token, httponly=True)
    return response


@app.get("/logout")
def logout():
    response = RedirectResponse("/login", status_code=HTTP_303_SEE_OTHER)
    response.delete_cookie("access_token")
    return response


# -------------------- Dashboard Route --------------------
@app.get("/dashboard")
def dashboard(request: Request):
    user_info = get_current_user_info(request)
    if isinstance(user_info, RedirectResponse):
        return user_info
    username = user_info["username"]
    user_role = user_info["user_role"]

    with get_connection() as conn:
        cursor = conn.cursor()

        # Get dashboard stats
        cursor.execute("SELECT COUNT(*) FROM InsuranceMaster WHERE IsActive = 1")
        total_insurance = cursor.fetchone()[0]

        if user_role == "SuperAdmin":
            cursor.execute(
                "SELECT COUNT(*) FROM Users WHERE IsActive = 1 AND Role = 'Client'"
            )
            active_clients = cursor.fetchone()[0]

            cursor.execute(
                """
                SELECT COUNT(*) FROM EligibilityRequest 
                WHERE CAST(CreatedOn AS DATE) = CAST(GETDATE() AS DATE)
            """
            )
            eligibility_today = cursor.fetchone()[0]

            cursor.execute(
                """
                SELECT COUNT(*) FROM EligibilityRequest 
                WHERE EligibilityId NOT IN (SELECT EligibilityRequestID FROM EligibilityResponse)
            """
            )
            pending_actions = cursor.fetchone()[0]

            # Get recent activity for SuperAdmin
            cursor.execute(
                """
                SELECT TOP 5 er.EligibilityId, u.ClientName, im.InsuranceName, er.CreatedOn,
                    CASE WHEN ers.ID IS NULL THEN 'Pending' ELSE 'Completed' END as Status
                FROM EligibilityRequest er
                LEFT JOIN EligibilityResponse ers ON er.EligibilityId = ers.EligibilityRequestID
                JOIN Users u ON er.ClientID = u.ID
                JOIN InsuranceMaster im ON er.InsuranceID = im.ID
                ORDER BY er.CreatedOn DESC
            """
            )
        else:
            # For Client users, we need to find their client ID from Users
            cursor.execute(
                "SELECT ID FROM Users WHERE ClientName = ? AND Role = 'Client'",
                (username,),
            )
            client_result = cursor.fetchone()
            client_id = client_result[0] if client_result else None

            if not client_id:
                active_clients = 0
                eligibility_today = 0
                pending_actions = 0
                recent_activity = []
            else:
                cursor.execute(
                    "SELECT COUNT(*) FROM Users WHERE ID = ? AND IsActive = 1 AND Role = 'Client'",
                    (client_id,),
                )
                active_clients = cursor.fetchone()[0]

                cursor.execute(
                    """
                    SELECT COUNT(*) FROM EligibilityRequest 
                    WHERE ClientID = ? AND CAST(CreatedOn AS DATE) = CAST(GETDATE() AS DATE)
                """,
                    (client_id,),
                )
                eligibility_today = cursor.fetchone()[0]

                cursor.execute(
                    """
                    SELECT COUNT(*) FROM EligibilityRequest 
                    WHERE ClientID = ? AND EligibilityId NOT IN (SELECT EligibilityRequestID FROM EligibilityResponse)
                """,
                    (client_id,),
                )
                pending_actions = cursor.fetchone()[0]

                # Get recent activity for Client
                cursor.execute(
                    """
                    SELECT TOP 5 er.EligibilityId, u.ClientName, im.InsuranceName, er.CreatedOn, 
                           CASE WHEN ers.ID IS NULL THEN 'Pending' ELSE 'Completed' END as Status
                    FROM EligibilityRequest er
                    LEFT JOIN EligibilityResponse ers ON er.EligibilityId = ers.EligibilityRequestID
                    JOIN Users u ON er.ClientID = u.ID
                    JOIN InsuranceMaster im ON er.InsuranceID = im.ID
                    WHERE er.ClientID = ?
                    ORDER BY er.CreatedOn DESC
                """,
                    (client_id,),
                )

        recent_activity = cursor.fetchall()

        # Get system status
        cursor.execute(
            """
            SELECT TOP 1 CreatedOn FROM EligibilityResponse ORDER BY CreatedOn DESC
        """
        )
        last_run = cursor.fetchone()
        last_run_time = last_run[0] if last_run else None

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "username": username,
            "user_role": user_role,
            "total_insurance": total_insurance,
            "active_clients": active_clients,
            "eligibility_today": eligibility_today,
            "pending_actions": pending_actions,
            "recent_activity": recent_activity,
            "last_run_time": last_run_time,
        },
    )


# -------------------- Data Source Route --------------------
@app.get("/datasource")
def datasource_page(request: Request):
    user_info = get_current_user_info(request)
    if isinstance(user_info, RedirectResponse):
        return user_info
    username = user_info["username"]
    user_role = user_info["user_role"]

    clients = get_clients(user_role, username)
    upload_history = get_upload_history(user_role, username)
    patient_data = get_patient_data(user_role, username)

    return templates.TemplateResponse(
        "datasource.html",
        {
            "request": request,
            "username": username,
            "user_role": user_role,
            "clients": clients,
            "upload_history": upload_history,
            "patient_data": patient_data,
        },
    )


# ------------------- Walk-in Eligibility Check Route -------------------------


@app.get("/walk-in", response_class=HTMLResponse)
def walkin_page(request: Request, message: str = None):
    user_info = get_current_user_info(request)
    if isinstance(user_info, RedirectResponse):
        return user_info

    username = user_info["username"]
    user_role = user_info["user_role"]

    with get_connection() as conn:
        cursor = conn.cursor()
        if user_role == "SuperAdmin":
            # Show all insurance companies
            cursor.execute(
                "SELECT ID, InsuranceCode, InsuranceName FROM InsuranceMaster WHERE IsActive = 1 ORDER BY InsuranceName"
            )
            insurances = cursor.fetchall()
        else:
            # Show only insurance companies configured for this client
            cursor.execute("SELECT ID FROM Users WHERE Username = ?", (username,))
            client_row = cursor.fetchone()
            client_id = client_row[0] if client_row else None

            cursor.execute(
                """
                SELECT im.ID, im.InsuranceCode, im.InsuranceName
                FROM InsuranceMaster im
                JOIN ClientInsuranceConfiguration cic ON im.ID = cic.InsuranceID
                WHERE cic.ClientID = ? AND cic.IsActive = 1 AND im.IsActive = 1
                ORDER BY im.InsuranceName
            """,
                (client_id,),
            )
            insurances = cursor.fetchall()

        # Get last eligibility check for this user (if any)
        cursor.execute(
            """
            SELECT TOP 1 er.EligibilityId, im.InsuranceName, er.CreatedOn, 
                CASE WHEN ers.ID IS NULL THEN 'Pending'
                     WHEN ers.Is_Eligible = 'Eligible' THEN 'Eligible'
                     ELSE 'Not Eligible' END as Status
            FROM EligibilityRequest er
            LEFT JOIN EligibilityResponse ers ON er.EligibilityId = ers.EligibilityRequestID
            JOIN InsuranceMaster im ON er.InsuranceID = im.ID
            JOIN Users u ON er.ClientID = u.ID
            WHERE u.Username = ?
            ORDER BY er.CreatedOn DESC
        """,
            (username,),
        )
        last_check = cursor.fetchone()

    insurance_list = [
        {"id": row[0], "code": row[1], "name": row[2]} for row in insurances
    ]

    return templates.TemplateResponse(
        "walkin.html",
        {
            "request": request,
            "username": username,
            "user_role": user_role,
            "insurances": insurance_list,
            "last_check": last_check,
            "message": message,
        },
    )


@app.post("/walk-in")
async def walkin_submit(
    request: Request,
    emirates_id: str = Form(...),
    mobile_no: str = Form(...),
    clinician_id: str = Form(...),
    insurance_company: int = Form(...),  # InsuranceMaster.ID
    appointment_date: str = Form(...),  # from <input type="date">
):
    # ✅ Get logged in user info
    user_info = get_current_user_info(request)
    if isinstance(user_info, RedirectResponse):
        return user_info

    username = user_info["username"]
    user_role = user_info["user_role"]

    # ✅ Get client_id from Users table
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT ID FROM Users WHERE Username = ?", (username,))
        client_row = cursor.fetchone()
        client_id = client_row[0] if client_row else None

    if not client_id:
        return JSONResponse(
            {"status": "error", "message": "Client not found"}, status_code=400
        )

    # ✅ Format appointment datetime for Pydantic model (dd/MM/yyyy HH:mm)
    formatted_appt = datetime.strptime(appointment_date, "%Y-%m-%d").strftime(
        "%d/%m/%Y %H:%M"
    )

    # ✅ Normalize inputs before validation
    emirates_id_clean = emirates_id.replace("-", "").strip()
    mobile_clean = mobile_no.lstrip("0").strip()

    form_data = {
        "ClinicDoctorId": clinician_id,
        "ClinicDoctorLicense": clinician_id,
        "EmiratesId": emirates_id_clean,
        "MobileCountryCode": "+971",
        "MobileNumber": mobile_clean,
        "ClinicLicense": "DEFAULT_LICENSE",
        "InsuranceCode": str(insurance_company),
        "ClientName": username,
        "AppointmentDateTime": formatted_appt,
    }

    # ✅ Validate with Pydantic
    try:
        validated = AppointmentRequest(**form_data)
    except ValidationError as e:
        return JSONResponse(
            content={"status": "error", "errors": e.errors()}, status_code=400
        )
    except Exception as e:
        return JSONResponse(
            content={"status": "error", "message": str(e)}, status_code=500
        )

    # ✅ Insert into EligibilityRequest
    eligibility_id = save_to_eligibility_request_table(
        validated.dict(), client_id, insurance_company
    )

    # ✅ Get insurance credentials
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT Username, Password 
            FROM ClientInsuranceConfiguration 
            WHERE ClientID = ? AND InsuranceID = ? AND IsActive = 1
        """,
            (client_id, insurance_company),
        )
        row = cursor.fetchone()

    if not row or not row[0] or not row[1]:
        return JSONResponse(
            {
                "status": "error",
                "message": "No active credentials found for this insurance",
            },
            status_code=400,
        )

    insurance_username, insurance_password = row

    # ✅ Trigger Selenium automation
    response = await trigger_selenium_script(
        insurance_username, insurance_password, validated.dict()
    )
    import pdb

    pdb.set_trace()
    # ✅ Save response
    # to store emirates id also in response table

    response["Emirates_ID"] = emirates_id_clean

    if response.get("status") == "error":
        print("❌ Skipping save, error:", response["message"])
        return RedirectResponse(
            url=f"/walk-in?message=Error:+{response['message']}", status_code=303
        )
    else:
        import pdb

        pdb.set_trace()
        save_to_eligibility_response_table(response, eligibility_id)
        return RedirectResponse(
            url=f"/walk-in?message=Successfully+processed+eligibility+request",
            status_code=303,
        )

    # return JSONResponse({
    #     "status": "success",
    #     "message": "Eligibility check completed",
    #     "eligibility_id": eligibility_id,
    #     "response": response
    # })


# -------------------- File Upload Route --------------------
@app.post("/upload")
async def upload_file(
    request: Request, client_id: int = Form(...), file: UploadFile = File(...)
):
    """Upload Excel file -> validate -> store records in UploadHistory"""
    user_info = get_current_user_info(request)
    if isinstance(user_info, RedirectResponse):
        return user_info

    username = user_info["username"]
    user_role = user_info["user_role"]

    # ---- Validate file type ----
    if not file.filename.endswith((".xlsx", ".xls")):
        return templates.TemplateResponse(
            "datasource.html",
            {
                "request": request,
                "username": username,
                "user_role": user_role,
                "error": "Only Excel files (.xlsx, .xls) are allowed",
                "clients": get_clients(user_role, username),
                "upload_history": get_upload_history(user_role, username),
            },
        )

    # ---- Read file content & check size ----
    try:
        file_content = await file.read()
        file_size = len(file_content)
    except Exception as e:
        return templates.TemplateResponse(
            "datasource.html",
            {
                "request": request,
                "username": username,
                "user_role": user_role,
                "error": f"Error reading file: {str(e)}",
                "clients": get_clients(user_role, username),
                "upload_history": get_upload_history(user_role, username),
            },
        )

    if file_size > 10 * 1024 * 1024:  # 10MB
        return templates.TemplateResponse(
            "datasource.html",
            {
                "request": request,
                "username": username,
                "user_role": user_role,
                "error": "File size exceeds 10MB limit",
                "clients": get_clients(user_role, username),
                "upload_history": get_upload_history(user_role, username),
            },
        )

    # ---- Load Excel ----
    try:
        df = pd.read_excel(io.BytesIO(file_content), engine="openpyxl")
    except Exception:
        try:
            df = pd.read_excel(io.BytesIO(file_content), engine="xlrd")
        except Exception as e:
            return templates.TemplateResponse(
                "datasource.html",
                {
                    "request": request,
                    "username": username,
                    "user_role": user_role,
                    "error": f"Failed to read Excel file: {str(e)}",
                    "clients": get_clients(user_role, username),
                    "upload_history": get_upload_history(user_role, username),
                },
            )

    # ---- Validate required columns ----
    required_cols = [
        "ClinicDoctorLicense",
        "MemberId",
        "EmiratesId",
        "MobileNumber",
        "ClinicLicense",
        "InsuranceCode",
        "AppointmentDateTime",
    ]
    missing_cols = [col for col in required_cols if col not in df.columns]
    if missing_cols:
        return templates.TemplateResponse(
            "datasource.html",
            {
                "request": request,
                "username": username,
                "user_role": user_role,
                "error": f"Missing required columns: {', '.join(missing_cols)}",
                "clients": get_clients(user_role, username),
                "upload_history": get_upload_history(user_role, username),
            },
        )

    # ---- Insert records into UploadHistory ----
    inserted_count = 0
    errors = []
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            for idx, row in df.iterrows():
                try:
                    cursor.execute(
                        """
                        INSERT INTO UploadHistory (
                            ClientID, FileName, FileSize, UploadDate,
                            ClinicDoctorId, ClinicDoctorName, ClinicDoctorLicense,
                            EmiratesId, MobileCountryCode, MobileNumber,
                            PatientFirstName, PatientLastName, ClinicLicense,
                            InsuranceCode, DepartmentName, SpecialityName,
                            AppointmentDateTime, MemberId
                        )
                        VALUES (?, ?, ?, GETDATE(), ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                        (
                            client_id,
                            file.filename,
                            file_size,
                            row.get("ClinicDoctorId", None),
                            row.get("ClinicDoctorName", None),
                            row.get("ClinicDoctorLicense", None),
                            row.get("EmiratesId", None),
                            row.get("MobileCountryCode", None),
                            row.get("MobileNumber", None),
                            row.get("PatientFirstName", None),
                            row.get("PatientLastName", None),
                            row.get("ClinicLicense", None),
                            row.get("InsuranceCode", None),
                            row.get("DepartmentName", None),
                            row.get("SpecialityName", None),
                            row.get("AppointmentDateTime", None),
                            row.get("MemberId", None),
                        ),
                    )
                    inserted_count += 1
                except Exception as e:
                    errors.append(f"Row {idx+2}: {str(e)}")
            conn.commit()
    except Exception as e:
        return templates.TemplateResponse(
            "datasource.html",
            {
                "request": request,
                "username": username,
                "user_role": user_role,
                "error": f"Database error: {str(e)}",
                "clients": get_clients(user_role, username),
                "upload_history": get_upload_history(user_role, username),
            },
        )

    # ---- Prepare message ----
    if inserted_count > 0:
        message = (
            f"✅ Successfully inserted {inserted_count} records into UploadHistory."
        )
        if errors:
            message += f" ⚠ {len(errors)} rows had errors."
        return templates.TemplateResponse(
            "datasource.html",
            {
                "request": request,
                "username": username,
                "user_role": user_role,
                "success": message,  # Bootstrap success alert
                "error_details": errors if errors else None,
                "clients": get_clients(user_role, username),
                "upload_history": get_upload_history(user_role, username),
            },
        )
    else:
        return templates.TemplateResponse(
            "datasource.html",
            {
                "request": request,
                "username": username,
                "user_role": user_role,
                "error": "❌ No records were inserted.",
                "error_details": errors if errors else None,
                "clients": get_clients(user_role, username),
                "upload_history": get_upload_history(user_role, username),
            },
        )


@app.get("/elig-results", response_class=HTMLResponse)
async def eligibility_results(request: Request):
    user_info = get_current_user_info(request)
    if isinstance(user_info, RedirectResponse):
        return user_info

    user_role = user_info["user_role"]
    username = user_info["username"]

    # Get user_id from Users table if needed
    user_id = None
    if user_role == "Client":
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT ID FROM Users WHERE Username = ?", (username,))
            row = cursor.fetchone()
            user_id = row[0] if row else None

    # Build query
    base_query = """
        SELECT
            er.EligibilityId,
            er.ClinicDoctorId,
            er.ClinicDoctorName,
            er.ClinicDoctorLicense,
            er.EmiratesId,
            er.MemberId,
            er.MobileCountryCode,
            er.MobileNumber,
            er.PatientFirstName,
            er.PatientLastName,
            er.ClinicLicense,
            im.InsuranceCode,
            u.ClientName,
            er.DepartmentName,
            er.SpecialityName,
            er.AppointmentDateTime,
            er.CreatedOn,
            ISNULL(resp.Is_Eligible, 'Pending') AS Status
        FROM EligibilityRequest er
        LEFT JOIN EligibilityResponse resp
            ON er.EligibilityId = resp.EligibilityRequestID
        INNER JOIN InsuranceMaster im
            ON er.InsuranceID = im.ID
        INNER JOIN Users u
            ON er.ClientID = u.ID
    """

    params = ()
    if user_role == "Client" and user_id:
        base_query += " WHERE er.ClientID = ?"
        params = (user_id,)

    base_query += " ORDER BY er.CreatedOn DESC"

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(base_query, params)
        rows = cursor.fetchall()

    return templates.TemplateResponse(
        "eligibility_results.html",
        {
            "request": request,
            "username": username,
            "data": rows,
            "user_role": user_role,
        },
    )


@app.get("/eligibility/recheck/{eligibility_id}")
async def get_insurances_for_recheck(request: Request, eligibility_id: int):
    user_info = get_current_user_info(request)
    if isinstance(user_info, RedirectResponse):
        return user_info

    user_role = user_info["user_role"]
    username = user_info["username"]

    with get_connection() as conn:
        cursor = conn.cursor()

        if user_role == "Client":
            cursor.execute("SELECT ID FROM Users WHERE Username = ?", (username,))
            client_row = cursor.fetchone()
            client_id = client_row[0] if client_row else None

            cursor.execute(
                """
                SELECT im.ID, im.InsuranceCode
                FROM ClientInsuranceConfiguration cic
                INNER JOIN InsuranceMaster im ON cic.InsuranceID = im.ID
                WHERE cic.ClientID = ? AND cic.IsActive = 1
            """,
                (client_id,),
            )
        else:  # SuperAdmin → show all insurances
            cursor.execute("SELECT ID, InsuranceCode FROM InsuranceMaster")

        insurances = [{"id": row[0], "name": row[1]} for row in cursor.fetchall()]

    return JSONResponse({"insurances": insurances})


@app.post("/eligibility/recheck")
async def recheck_eligibility(
    request: Request,
    eligibility_id: int = Form(...),
    insurance_company: int = Form(...),
    appointment_date: str = Form(...),
):
    user_info = get_current_user_info(request)
    if isinstance(user_info, RedirectResponse):
        return user_info

    username = user_info["username"]

    with get_connection() as conn:
        cursor = conn.cursor()

        # Get old record details
        cursor.execute(
            "SELECT * FROM EligibilityRequest WHERE EligibilityId = ?",
            (eligibility_id,),
        )
        old_row = cursor.fetchone()
        if not old_row:
            return JSONResponse(
                {"status": "error", "message": "Original request not found"},
                status_code=404,
            )

        # Build new request data
        new_request = (
            dict(old_row._asdict())
            if hasattr(old_row, "_asdict")
            else dict(zip([col[0] for col in cursor.description], old_row))
        )
        # Convert appointment_date (from form) to SQL format
        try:
            formatted_appt = datetime.strptime(appointment_date, "%Y-%m-%d").strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        except Exception:
            return JSONResponse(
                {"status": "error", "message": "Invalid appointment date format"},
                status_code=400,
            )
        new_request["AppointmentDateTime"] = formatted_appt
        new_request["InsuranceID"] = insurance_company

        # Insert new request record
        eligibility_id_new = save_to_eligibility_request_table(
            new_request, old_row.ClientID, insurance_company
        )

        # Fetch insurance credentials
        cursor.execute(
            """
            SELECT Username, Password 
            FROM ClientInsuranceConfiguration
            WHERE ClientID = ? AND InsuranceID = ? AND IsActive = 1
        """,
            (old_row.ClientID, insurance_company),
        )
        creds = cursor.fetchone()

        if not creds:
            return JSONResponse(
                {"status": "error", "message": "No active credentials found"},
                status_code=400,
            )
        # # import pdb; pdb.set_trace()

        # Prepare data for Selenium
        required_data = {
            "EmiratesId": new_request.get("EmiratesId"),
            "MobileNumber": new_request.get("MobileNumber"),
            "InsuranceCode": new_request.get("InsuranceID"),
        }
        # Trigger Selenium
        response = trigger_selenium_script(creds[0], creds[1], required_data)
        # Save response
        # save_to_eligibility_response_table(response, eligibility_id_new)

    return JSONResponse(
        {
            "status": "success",
            "message": "Recheck completed",
            "eligibility_id": eligibility_id_new,
        }
    )


# -------------------- Pydantic Model --------------------


class AppointmentRequest(BaseModel):
    ClinicDoctorId: str = None
    ClinicDoctorName: str = None
    ClinicDoctorLicense: str
    EmiratesId: str
    # MemberId: str
    MemberId: Optional[str] = None
    MobileCountryCode: str = "+971"
    MobileNumber: Optional[str] = None
    PatientFirstName: str = None
    PatientLastName: str = None
    ClinicLicense: str
    InsuranceCode: str
    ClientName: str = None
    DepartmentName: str = None
    SpecialityName: str = None
    AppointmentDateTime: str

    @validator("EmiratesId")
    def validate_emirates_id(cls, v):
        if not (v.startswith("784") and v.isdigit() and len(v) == 15):
            raise ValueError(
                "EmiratesId must start with 784, contain only digits, and be 15 digits long."
            )
        return v

    @validator("MobileNumber")
    def validate_mobile_number(cls, v):
        if not (v.isdigit() and len(v) == 9 and v.startswith("5")):
            raise ValueError(
                "MobileNumber must start with 5, contain only digits, and be 9 digits long."
            )
        return v

    @validator("AppointmentDateTime")
    def validate_appointment_datetime(cls, v):
        try:
            appointment_dt = datetime.strptime(v, "%d/%m/%Y %H:%M")
        except ValueError:
            raise ValueError("AppointmentDateTime must be in format dd/MM/yyyy HH:mm")
        if appointment_dt <= datetime.now():
            raise ValueError("AppointmentDateTime must be in the future.")
        return appointment_dt


# -------------------- Utility Functions --------------------
async def trigger_selenium_script(username, password, data: dict):
    """Run Selenium eligibility checker"""
    eid = data["EmiratesId"]
    mobile_num = data["MobileNumber"]

    service_network = data["InsuranceCode"]
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT InsuranceCode FROM InsuranceMaster WHERE ID = ?",
            (int(service_network),),
        )
        row = cursor.fetchone()

        if not row:
            return {"status": "error", "message": "Invalid Insurance ID"}

        service_network = row[0]  # ✅ now it's just "NAS"

    # select InsuranceCode from InsuranceMaster where ID = ty
    # # import pdb; pdb.set_trace()
    if service_network.lower() == "nextcare":
        # # import pdb; pdb.set_trace()
        checker = NextCareEligibilityChecker(username, password)
        response = await checker.run_async(
            eid
        )  # Pass only EmiratesId for now and await the result to be async
        # print({"eid": eid, "result": response})
        import pdb

        pdb.set_trace()
        return response
    else:
        return {
            "status": "skipped",
            "message": f"Automation not implemented for {service_network}",
        }


def save_to_eligibility_request_table(
    data: dict, client_id: int, insurance_id: int
) -> int:
    query = """
    INSERT INTO EligibilityRequest (
        ClinicDoctorId, ClinicDoctorName, ClinicDoctorLicense, EmiratesId,
        MobileCountryCode, MobileNumber, PatientFirstName, PatientLastName,
        ClinicLicense, InsuranceID, ClientID, DepartmentName, SpecialityName,
        AppointmentDateTime, CreatedOn
    ) 
    OUTPUT INSERTED.EligibilityId
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, GETDATE())
    """
    values = (
        data.get("ClinicDoctorId"),
        data.get("ClinicDoctorName"),
        data.get("ClinicDoctorLicense"),
        data.get("EmiratesId"),
        data.get("MobileCountryCode"),
        data.get("MobileNumber"),
        data.get("PatientFirstName"),
        data.get("PatientLastName"),
        data.get("ClinicLicense"),
        insurance_id,
        client_id,
        data.get("DepartmentName"),
        data.get("SpecialityName"),
        data.get("AppointmentDateTime"),
    )

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query, values)
        eligibility_id = cursor.fetchone()[0]
        conn.commit()
        return eligibility_id


def save_to_eligibility_response_table(data: dict, eligibility_request_id: int):
    member_policy = data.get("Member_Policy_Details", {}) or {}
    import pdb

    pdb.set_trace()

    def fix_date(val):
        if val is None or val == "" or str(val).lower() in ["none", "n/a", "invalid"]:
            return None
        if isinstance(val, datetime):
            return val.strftime("%Y-%m-%d %H:%M:%S")
        # Try to parse string to datetime, then format
        for fmt in (
            "%d/%m/%Y %H:%M",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d",
            "%d-%b-%Y %H:%M:%S",
            "%d-%b-%Y",
            "%d-%b-%Y %H:%M",
        ):
            try:
                return datetime.strptime(str(val), fmt).strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                continue
        return None

    query = """
    INSERT INTO EligibilityResponse (
        EligibilityRequestID, Reference_No, Request_Date, Effective_From, Effective_To, Effective_At,
        Is_Eligible, Coverage_Details, Notes, Emirates_ID, 
        TPA_Member_ID, Emirates_ID_Member, DHA_Member_ID, DOB, Gender, 
        Sub_Group, Category, Policy_Number, Client_Number, Policy_Authority, CreatedOn
    ) 
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, GETDATE())
    """
    values = (
        eligibility_request_id,
        data.get("Reference_No"),
        fix_date(data.get("Request_Date")),
        fix_date(data.get("Effective_From")),
        fix_date(data.get("Effective_To")),
        data.get("Effective_At"),
        data.get("Is_Eligible"),
        data.get("Coverage_Details"),
        data.get("Notes"),
        data.get("Emirates_ID"),
        member_policy.get("TPA_Member_ID"),
        member_policy.get("Emirates_ID"),
        member_policy.get("DHA_Member_ID"),
        fix_date(member_policy.get("DOB")),
        member_policy.get("Gender"),
        member_policy.get("Sub_Group"),
        member_policy.get("Category"),
        member_policy.get("Policy_Number"),
        member_policy.get("Client_Number"),
        member_policy.get("Policy_Authority"),
    )
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query, values)
        conn.commit()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
