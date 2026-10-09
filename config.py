"""
FleetPortal/config.py
---------
Configuration module for FleetPortal Desktop Application.
Stores API scopes, isolated Google Drive folder mappings,
and local file paths used across the system.
"""

import os
from pathlib import Path

# --- APPLICATION PATHS ---
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = DATA_DIR / "fleet_portal_cache.db"
TOKEN_PATH = BASE_DIR / "token.json"
CREDENTIALS_PATH = BASE_DIR / "credentials.json"

# --- ISOLATED GOOGLE DRIVE HIERARCHY ---
# Paste the folder ID from your FPD URL here:
FPD_ROOT_FOLDER_ID = "1-YxQs5gmU5qQS3yCkBByAJ1oiYgHKbvl"

# Dedicated Master Sheet name created inside the FPD root folder
FPD_SHEET_NAME = "FPD_Master_Sheet"

# Auto-provisioned subfolder directory names inside FPD
SUBFOLDER_SERVICE_REPORTS = "Service Reports"
SUBFOLDER_QR_CODES = "QR Codes"
SUBFOLDER_PAVE = "PAVE Inspections"
SUBFOLDER_DOCS = "Document Center"

# --- SAFETY SWITCHES ---
ENABLE_LIVE_WRITES = False
STRICT_FOLDER_LOCK = True

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/documents"
]

# --- UI APP STYLING ---
APP_TITLE = "G7 Fleet Command Center (Desktop Edition)"
WINDOW_SIZE = (1280, 800)
MIN_WINDOW_SIZE = (1024, 600)