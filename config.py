"""
config.py
---------
Configuration module for FleetPortal Desktop Application.
Stores API scopes, Google Spreadsheet IDs, Drive Parent Folder IDs, 
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

# --- GOOGLE WORKSPACE CONFIGURATION ---
SHEET_ID = "17P21L6idqNHodbUK3NuiuUn5dn8BfdmW4fn2jaHKoO8"
USERS_SHEET_ID = "10oCsQAonC-8HKAQbB5Xl3dBHIghNAEVAovo50Y6HHSo"
PARENT_FOLDER_ID = "14Yak5LLZwQi_Lk1u2rUfmrRe40MHe55f"
DOCS_FOLDER_ID = "1clXwNSgF-LsWgJX8oEukz0me8ENR-mEH"

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/documents"
]

# --- UI APP STYLING ---
APP_TITLE = "G7 Fleet Command Center (Desktop Edition)"
WINDOW_SIZE = (1280, 800)
MIN_WINDOW_SIZE = (1024, 600)