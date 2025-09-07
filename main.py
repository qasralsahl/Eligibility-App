from fastapi import FastAPI, HTTPException, Request, Form, Depends, UploadFile, File
from fastapi.responses import RedirectResponse, HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, validator
from starlette.status import HTTP_303_SEE_OTHER
from datetime import datetime, timedelta
import pandas as pd
import asyncio
import io
import os
import bcrypt
from jose import jwt
from functools import wraps
import logging
from concurrent.futures import ThreadPoolExecutor

# Local imports
from database import get_connection
from eligibility_checker import EligibilityChecker
from routes import insurance
from routes import client
from routes import registration

from config import SECRET_KEY, ALGORITHM  # ✅ Safe, no circular imports
from utils.auth import get_user_info as get_current_user_info  # ✅ centralized auth

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

# -------------------- Logging Configuration --------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("app.log", encoding="utf-8")
    ]
)

# -------------------- App Setup --------------------
app = FastAPI()
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")
executor = ThreadPoolExecutor(max_workers=5)

# Include modular routes
app.include_router(insurance.router)
app.include_router(client.router)
app.include_router(registration.router)

# -------------------- Authentication Functions --------------------
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))

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
        cursor.execute("""
            SELECT DISTINCT 
                u.ID, 
                u.ClientName
            FROM ClientInsuranceConfiguration cic
            JOIN Users u ON cic.ClientID = u.ID
            WHERE cic.IsActive = 1 AND u.IsActive = 1 AND u.Role = 'Client'
            ORDER BY u.ClientName
        """)
        clients = cursor.fetchall()
        logging.info(f"get_clients - Role: {user_role}, Username: {username}, Found: {len(clients)} clients")
        return clients

def get_upload_history(user_role: str, username: str):
    """Get upload history based on user role"""
    with get_connection() as conn:
        cursor = conn.cursor()
        if user_role == "SuperAdmin":
            cursor.execute("""
                SELECT uh.ID, u.ClientName, uh.FileName, uh.UploadDate 
                FROM UploadHistory uh
                JOIN Users u ON uh.ClientID = u.ID
                ORDER BY uh.UploadDate DESC
            """)
        else:
            cursor.execute("""
                SELECT uh.ID, u.ClientName, uh.FileName, uh.UploadDate 
                FROM UploadHistory uh
                JOIN Users u ON uh.ClientID = u.ID
                WHERE u.Username = ?
                ORDER BY uh.UploadDate DESC
            """, (username,))
        return cursor.fetchall()

def get_patient_data(user_role: str, username: str):
    """Get patient data based on user role with required columns"""
    with get_connection() as conn:
        cursor = conn.cursor()
        if user_role == "SuperAdmin":
            cursor.execute("""
                SELECT TOP 10 
                    er.EligibilityId as PatientID, 
                    er.AppointmentDateTime as AppointmentDate, 
                    im.InsuranceCode as InsuranceCode,
                    u.ClientName as ClientName,
                    CASE 
                        WHEN ers.ID IS NULL THEN 'Pending' 
                        WHEN ers.Is_Eligible = 1 THEN 'Eligible' 
                        ELSE 'Not Eligible' 
                    END as Status,
                    er.CreatedOn as UploadedDate
                FROM EligibilityRequest er
                LEFT JOIN EligibilityResponse ers ON er.EligibilityId = ers.EligibilityRequestID
                JOIN Users u ON er.ClientID = u.ID
                JOIN InsuranceMaster im ON er.InsuranceID = im.ID
                ORDER BY er.CreatedOn DESC
            """)
        else:
            cursor.execute("""
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
                    er.CreatedOn as UploadedDate
                FROM EligibilityRequest er
                LEFT JOIN EligibilityResponse ers ON er.EligibilityId = ers.EligibilityRequestID
                JOIN Users u ON er.ClientID = u.ID
                JOIN InsuranceMaster im ON er.InsuranceID = im.ID
                WHERE u.Username = ?
                ORDER BY er.CreatedOn DESC
            """, (username,))
        return cursor.fetchall()
    
# -------------------- Authentication Routes --------------------
@app.get("/")
def root_redirect():
    """Redirect root path to login"""
    return RedirectResponse("/login")


@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


@app.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT ID, Username, Password, Role FROM Users WHERE Username = ? AND IsActive = 1",
            (username,)
        )
        user = cursor.fetchone()

    if not user or not verify_password(password, user[2]):
        return templates.TemplateResponse("login.html", {
            "request": request,
            "error": "Invalid username or password"
        })

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
    client_name: str = Form(None)
):
    # Check password match
    if password != confirm_password:
        return templates.TemplateResponse("signup.html", {
            "request": request,
            "error": "Passwords do not match"
        })

    hashed_pw = hash_password(password)

    try:
        with get_connection() as conn:
            cursor = conn.cursor()

            # Check existing user
            cursor.execute("SELECT ID FROM Users WHERE Username = ?", (username,))
            if cursor.fetchone():
                return templates.TemplateResponse("signup.html", {
                    "request": request,
                    "error": "Username already exists"
                })

            # Default new users to "Client"
            cursor.execute("""
                INSERT INTO Users (ClientName, Username, Password, Role, IsActive, CreatedOn)
                VALUES (?, ?, ?, ?, 1, GETDATE())
            """, (client_name, username, hashed_pw, "Client"))
            conn.commit()

            # Get newly created user
            cursor.execute("SELECT ID, Username, Role FROM Users WHERE Username = ?", (username,))
            new_user = cursor.fetchone()

    except Exception as e:
        return templates.TemplateResponse("signup.html", {
            "request": request,
            "error": f"Error creating account: {str(e)}"
        })

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
    username = user_info["username"]
    user_role = user_info["user_role"]
    
    with get_connection() as conn:
        cursor = conn.cursor()
        
        # Get dashboard stats
        cursor.execute("SELECT COUNT(*) FROM InsuranceMaster WHERE IsActive = 1")
        total_insurance = cursor.fetchone()[0]
        
        if user_role == "SuperAdmin":
            cursor.execute("SELECT COUNT(*) FROM Users WHERE IsActive = 1 AND Role = 'Client'")
            active_clients = cursor.fetchone()[0]
            
            cursor.execute("""
                SELECT COUNT(*) FROM EligibilityRequest 
                WHERE CAST(CreatedOn AS DATE) = CAST(GETDATE() AS DATE)
            """)
            eligibility_today = cursor.fetchone()[0]
            
            cursor.execute("""
                SELECT COUNT(*) FROM EligibilityRequest 
                WHERE EligibilityId NOT IN (SELECT EligibilityRequestID FROM EligibilityResponse)
            """)
            pending_actions = cursor.fetchone()[0]
            
            # Get recent activity for SuperAdmin
            cursor.execute("""
                SELECT TOP 5 er.EligibilityId, u.ClientName, im.InsuranceName, er.CreatedOn,
                    CASE WHEN ers.ID IS NULL THEN 'Pending' ELSE 'Completed' END as Status
                FROM EligibilityRequest er
                LEFT JOIN EligibilityResponse ers ON er.EligibilityId = ers.EligibilityRequestID
                JOIN Users u ON er.ClientID = u.ID
                JOIN InsuranceMaster im ON er.InsuranceID = im.ID
                ORDER BY er.CreatedOn DESC
            """)
        else:
            # For Client users, we need to find their client ID from Users
            cursor.execute("SELECT ID FROM Users WHERE ClientName = ? AND Role = 'Client'", (username,))
            client_result = cursor.fetchone()
            client_id = client_result[0] if client_result else None
            
            if not client_id:
                active_clients = 0
                eligibility_today = 0
                pending_actions = 0
                recent_activity = []
            else:
                cursor.execute("SELECT COUNT(*) FROM Users WHERE ID = ? AND IsActive = 1 AND Role = 'Client'", (client_id,))
                active_clients = cursor.fetchone()[0]
                
                cursor.execute("""
                    SELECT COUNT(*) FROM EligibilityRequest 
                    WHERE ClientID = ? AND CAST(CreatedOn AS DATE) = CAST(GETDATE() AS DATE)
                """, (client_id,))
                eligibility_today = cursor.fetchone()[0]
                
                cursor.execute("""
                    SELECT COUNT(*) FROM EligibilityRequest 
                    WHERE ClientID = ? AND EligibilityId NOT IN (SELECT EligibilityRequestID FROM EligibilityResponse)
                """, (client_id,))
                pending_actions = cursor.fetchone()[0]
                
                # Get recent activity for Client
                cursor.execute("""
                    SELECT TOP 5 er.EligibilityId, u.ClientName, im.InsuranceName, er.CreatedOn, 
                           CASE WHEN ers.ID IS NULL THEN 'Pending' ELSE 'Completed' END as Status
                    FROM EligibilityRequest er
                    LEFT JOIN EligibilityResponse ers ON er.EligibilityId = ers.EligibilityRequestID
                    JOIN Users u ON er.ClientID = u.ID
                    JOIN InsuranceMaster im ON er.InsuranceID = im.ID
                    WHERE er.ClientID = ?
                    ORDER BY er.CreatedOn DESC
                """, (client_id,))
        
        recent_activity = cursor.fetchall()
        
        # Get system status
        cursor.execute("""
            SELECT TOP 1 CreatedOn FROM EligibilityResponse ORDER BY CreatedOn DESC
        """)
        last_run = cursor.fetchone()
        last_run_time = last_run[0] if last_run else None
        
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "username": username,
        "user_role": user_role,
        "total_insurance": total_insurance,
        "active_clients": active_clients,
        "eligibility_today": eligibility_today,
        "pending_actions": pending_actions,
        "recent_activity": recent_activity,
        "last_run_time": last_run_time
    })

# -------------------- Data Source Route --------------------
@app.get("/datasource")
def datasource_page(request: Request):
    # import pdb; pdb.set_trace()
    user_info = get_current_user_info(request)
    username = user_info["username"]
    user_role = user_info["user_role"]
    
    clients = get_clients(user_role, username)
    upload_history = get_upload_history(user_role, username)
    patient_data = get_patient_data(user_role, username)
    
    return templates.TemplateResponse("datasource.html", {
        "request": request,
        "username": username,
        "user_role": user_role,
        "clients": clients,
        "upload_history": upload_history,
        "patient_data": patient_data
    })



# -------------------- File Upload Route --------------------
@app.post("/upload")
async def upload_file(
    request: Request, 
    client_id: int = Form(...),
    file: UploadFile = File(...)
):
    """Handle Excel file upload and process patient data"""
    user_info = get_current_user_info(request)
    username = user_info["username"]
    user_role = user_info["user_role"]
    
    
    
    # Validate file type
    if not file.filename.endswith(('.xlsx', '.xls')):
        return templates.TemplateResponse("datasource.html", {
            "request": request,
            "username": username,
            "user_role": user_role,
            "error": "Only Excel files are allowed",
            "clients": get_clients(user_role, username),
            "upload_history": get_upload_history(user_role, username),
            "patient_data": get_patient_data(user_role, username)
        })
    
    # Read file content once and validate size
    try:
        file_content = await file.read()
        file_size = len(file_content)
    except Exception as e:
        return templates.TemplateResponse("datasource.html", {
            "request": request,
            "username": username,
            "user_role": user_role,
            "error": f"Error reading file: {str(e)}",
            "clients": get_clients(user_role, username),
            "upload_history": get_upload_history(user_role, username),
            "patient_data": get_patient_data(user_role, username)
        })
    
    # Validate file size (10MB max)
    if file_size > 10 * 1024 * 1024:
        return templates.TemplateResponse("datasource.html", {
            "request": request,
            "username": username,
            "user_role": user_role,
            "error": "File size exceeds 10MB limit",
            "clients": get_clients(user_role, username),
            "upload_history": get_upload_history(user_role, username),
            "patient_data": get_patient_data(user_role, username)
        })
    
    # Save file to upload directory
    file_path = os.path.join(UPLOAD_DIR, file.filename)
    try:
        with open(file_path, "wb") as buffer:
            buffer.write(file_content)
    except Exception as e:
        return templates.TemplateResponse("datasource.html", {
            "request": request,
            "username": username,
            "user_role": user_role,
            "error": f"Error saving file: {str(e)}",
            "clients": get_clients(user_role, username),
            "upload_history": get_upload_history(user_role, username),
            "patient_data": get_patient_data(user_role, username)
        })
    # Save upload record to database
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO UploadHistory (ClientID, FileName, FileSize, UploadDate) VALUES (?, ?, ?, GETDATE())",
                (client_id, file.filename, file_size)
            )
            conn.commit()
    except Exception as e:
        os.remove(file_path)  # Clean up file if DB operation fails
        return templates.TemplateResponse("datasource.html", {
            "request": request,
            "username": username,
            "user_role": user_role,
            "error": f"Error saving upload record: {str(e)}",
            "clients": get_clients(user_role, username),
            "upload_history": get_upload_history(user_role, username),
            "patient_data": get_patient_data(user_role, username)
        })
    
    # Process the Excel file
    try:
        # Read the Excel file with multiple engine fallbacks for better compatibility
        try:
            # First try with openpyxl (better for .xlsx files)
            df = pd.read_excel(io.BytesIO(file_content), engine='openpyxl')
        except Exception as openpyxl_error:
            try:
                # Fallback to xlrd (better for .xls files)
                df = pd.read_excel(io.BytesIO(file_content), engine='xlrd')
            except Exception as xlrd_error:
                try:
                    # Final fallback - let pandas auto-detect
                    df = pd.read_excel(io.BytesIO(file_content))
                except Exception as auto_error:
                    raise Exception(f"Failed to read Excel file. Openpyxl error: {openpyxl_error}, Xlrd error: {xlrd_error}, Auto error: {auto_error}")
        
        # Validate that the file is not empty
        if df.empty:
            os.remove(file_path)
            return templates.TemplateResponse("datasource.html", {
                "request": request,
                "username": username,
                "user_role": user_role,
                "error": "Uploaded file is empty or contains no data",
                "clients": get_clients(user_role, username),
                "upload_history": get_upload_history(user_role, username),
                "patient_data": get_patient_data(user_role, username)
            })
        
        # Get client name for processing
        try:
            with get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT ClientName FROM Users WHERE ID = ?", (client_id,))
                client_name_result = cursor.fetchone()
                client_name = client_name_result[0] if client_name_result else "Unknown"
        except Exception as e:
            client_name = "Unknown"
        
        # Initialize processing variables
        grid_data = []
        processed_count = 0
        error_messages = []
        
        # Loop through all rows in Excel
        for index, row in df.iterrows():
            try:
                data = row.to_dict()
                print(f"[DEBUG] Row {index+2} InsuranceCode: {data.get('InsuranceCode')}")
                
                # Clean data: convert NaN/None to empty strings
                for key, value in data.items():
                    if pd.isna(value):
                        data[key] = ""
                    elif isinstance(value, (int, float)):
                        data[key] = str(value).strip()
                    elif isinstance(value, str):
                        data[key] = value.strip()
                
                # Add ClientName to data since we know it from the form
                data["ClientName"] = client_name
                
                # ---------------- Step 2: Validate required fields ----------------
                required_fields = [
                    "ClinicDoctorId", "ClinicDoctorName", "ClinicDoctorLicense", "EmiratesId",
                    "MobileCountryCode", "MobileNumber", "PatientFirstName", "PatientLastName",
                    "ClinicLicense", "InsuranceCode", "DepartmentName", "SpecialityName",
                    "AppointmentDateTime"
                ]
                
                missing = [f for f in required_fields if not data.get(f)]
                if missing:
                    error_messages.append(f"Row {index+2}: Missing required fields: {', '.join(missing)}")
                    continue
                
                # ---------------- Step 3: Lookup Client + Insurance ----------------
                with get_connection() as conn:
                    cursor = conn.cursor()
                    
                    # Validate client
                    cursor.execute("SELECT ID FROM Users WHERE ClientName=? AND IsActive=1 AND Role='Client'", (data["ClientName"],))
                    client_row = cursor.fetchone()
                    if not client_row:
                        error_messages.append(f"Row {index+2}: Client '{data['ClientName']}' not found or inactive.")
                        continue
                    client_id_db = client_row[0]
                    
                    # Validate insurance
                    cursor.execute("SELECT ID, InsuranceCode FROM InsuranceMaster WHERE InsuranceCode=? AND IsActive=1", (data["InsuranceCode"],))
                    ins_row = cursor.fetchone()
                    if not ins_row:
                        error_messages.append(f"Row {index+2}: Insurance code '{data['InsuranceCode']}' not found or inactive.")
                        continue
                    insurance_id, insurance_code = ins_row
                    
                    # Get portal credentials
                    cursor.execute("""
                        SELECT Username, Password FROM ClientInsuranceConfiguration 
                        WHERE ClientID=? AND InsuranceID=? AND IsActive=1
                    """, (client_id_db, insurance_id))
                    cred_row = cursor.fetchone()
                    if not cred_row:
                        error_messages.append(f"Row {index+2}: Active registration not found for client-insurance combination.")
                        continue
                    portal_username, portal_password = cred_row
                # import pdb; pdb.set_trace()
                
                # ---------------- Step 4: Insert into EligibilityRequest ----------------
                insert_request_query = """
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
                    data["ClinicDoctorId"], data["ClinicDoctorName"], data["ClinicDoctorLicense"], data["EmiratesId"],
                    data["MobileCountryCode"], data["MobileNumber"], data["PatientFirstName"], data["PatientLastName"],
                    data["ClinicLicense"], insurance_id, client_id_db, data["DepartmentName"], data["SpecialityName"],
                    data["AppointmentDateTime"]
                )
                
                with get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute(insert_request_query, values)
                    eligibility_request_id = cursor.fetchone()[0]
                    conn.commit()
                
                # ---------------- Step 5: Run Selenium Automation ----------------
                loop = asyncio.get_event_loop()
                response_data = await loop.run_in_executor(
                    executor,
                    trigger_selenium_script,
                    portal_username,
                    portal_password,
                    data
                )
                
                if not response_data:
                    error_messages.append(f"Row {index+2}: Failed to trigger automation script.")
                    continue
                
                # ---------------- Step 6: Insert into EligibilityResponse ----------------
                member_policy = response_data.get("Member_Policy_Details", {}) or {}
                
                insert_response_query = """
                INSERT INTO EligibilityResponse (
                    EligibilityRequestID, Reference_No, Request_Date, Effective_From, Effective_To, Effective_At,
                    Is_Eligible, Coverage_Details, Notes, Emirates_ID, 
                    TPA_Member_ID, Emirates_ID_Member, DHA_Member_ID, DOB, Gender, 
                    Sub_Group, Category, Policy_Number, Client_Number, Policy_Authority, CreatedOn
                ) 
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, GETDATE())
                """
                
                response_values = (
                    eligibility_request_id,
                    response_data.get("Reference_No"),
                    response_data.get("Request_Date"),
                    response_data.get("Effective_From"),
                    response_data.get("Effective_To"),
                    response_data.get("Effective_At"),
                    response_data.get("Is_Eligible"),
                    response_data.get("Coverage_Details"),
                    response_data.get("Notes"),
                    response_data.get("Emirates_ID"),
                    member_policy.get("TPA_Member_ID"),
                    member_policy.get("Emirates_ID"),
                    member_policy.get("DHA_Member_ID"),
                    member_policy.get("DOB"),
                    member_policy.get("Gender"),
                    member_policy.get("Sub_Group"),
                    member_policy.get("Category"),
                    member_policy.get("Policy_Number"),
                    member_policy.get("Client_Number"),
                    member_policy.get("Policy_Authority"),
                )
                
                with get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute(insert_response_query, response_values)
                    conn.commit()
                
                processed_count += 1
                
            except Exception as e:
                error_messages.append(f"Row {index+2}: {str(e)}")
                continue
        
        # Prepare success/error message
        if processed_count > 0:
            message = f"Successfully processed {processed_count} records"
            if error_messages:
                message += f". {len(error_messages)} records had errors."
        else:
            message = "No records were processed successfully."
        
        # Get updated patient data for display using the updated query
        updated_patient_data = get_patient_data(user_role, username)
        
        return templates.TemplateResponse("datasource.html", {
            "request": request,
            "username": username,
            "user_role": user_role,
            "message": message,
            "clients": get_clients(user_role, username),
            "upload_history": get_upload_history(user_role, username),
            "patient_data": updated_patient_data,
            "error_details": error_messages if error_messages else None
        })
        
    except Exception as e:
        # Clean up file on error
        if os.path.exists(file_path):
            os.remove(file_path)
        
        return templates.TemplateResponse("datasource.html", {
            "request": request,
            "username": username,
            "user_role": user_role,
            "error": f"Error processing file: {str(e)}",
            "clients": get_clients(user_role, username),
            "upload_history": get_upload_history(user_role, username),
            "patient_data": get_patient_data(user_role, username)
        })


# -------------------- Pydantic Model --------------------
class AppointmentRequest(BaseModel):
    ClinicDoctorId: str = None
    ClinicDoctorName: str = None
    ClinicDoctorLicense: str
    EmiratesId: str
    MobileCountryCode: str
    MobileNumber: str
    PatientFirstName: str = None
    PatientLastName: str = None
    ClinicLicense: str
    InsuranceCode: str
    ClientName: str
    DepartmentName: str = None
    SpecialityName: str = None
    AppointmentDateTime: str

    @validator("EmiratesId")
    def validate_emirates_id(cls, v):
        if not (v.startswith("784") and v.isdigit() and len(v) == 15):
            raise ValueError("EmiratesId must start with 784, contain only digits, and be 15 digits long.")
        return v

    @validator("MobileNumber")
    def validate_mobile_number(cls, v):
        if not (v.isdigit() and len(v) == 9 and v.startswith("5")):
            raise ValueError("MobileNumber must start with 5, contain only digits, and be 9 digits long.")
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
def trigger_selenium_script(username, password, data: dict):
    """Run Selenium eligibility checker"""
    eid = data["EmiratesId"]
    mobile_num = data["MobileNumber"]
    service_network = data["InsuranceCode"]

    checker = EligibilityChecker(username, password)
    response = checker.run(eid, mobile_num, service_network)
    return response

def save_to_eligibility_request_table(data: dict, client_id: int, insurance_id: int) -> int:
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
        data.get("Request_Date"),
        data.get("Effective_From"),
        data.get("Effective_To"),
        data.get("Effective_At"),
        data.get("Is_Eligible"),
        data.get("Coverage_Details"),
        data.get("Notes"),
        data.get("Emirates_ID"),
        member_policy.get("TPA_Member_ID"),
        member_policy.get("Emirates_ID"),
        member_policy.get("DHA_Member_ID"),
        member_policy.get("DOB"),
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