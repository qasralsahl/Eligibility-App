import pyodbc

# SQL Server connection string (update as per your environment)
conn_str = (
    "DRIVER={ODBC Driver 17 for SQL Server};"
    "SERVER=DevelopmentServer03;"
    "DATABASE=EligibilityAutomation;"
    "Trusted_Connection=Yes;"
    "TrustServerCertificate=Yes;"
)


# conn_str = (
#         'DRIVER={ODBC Driver 18 for SQL Server};'
#         'SERVER=DESKTOP-4S5B3UF\\SQLEXPRESS;'
#         'DATABASE=EligibilityAutomation;'
#         'Trusted_Connection=Yes;'
#         'TrustServerCertificate=Yes;'
#     )

def get_connection():
    """Return a new database connection."""
    try:
        return pyodbc.connect(conn_str)
    except Exception as e:
        print(f"[DB ERROR] Could not connect to database: {e}")
        raise
