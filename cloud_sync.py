"""
FleetPortalDesktop/cloud_sync.py
------------
Handles asynchronous background workers and direct Google API integration.
Manages bidirectional sync, interactive OAuth, dynamic Google Drive subfolder
creation, and isolated document uploads.
"""

import os
import json
import gspread
import pandas as pd
from pathlib import Path
from typing import Optional, Tuple, Any, Dict

from PySide6.QtCore import QThread, Signal
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from config import (
    SCOPES, TOKEN_PATH, CREDENTIALS_PATH,
    FPD_ROOT_FOLDER_ID, STRICT_FOLDER_LOCK, FPD_SHEET_NAME, STRICT_FOLDER_LOCK
)
from db_manager import DatabaseManager

# In-memory folder lookup cache to eliminate redundant Drive API calls
_FOLDER_CACHE: Dict[Tuple[str, str], str] = {}


def get_gcp_credentials(interactive: bool = False) -> Optional[Any]:
    """Authenticates and returns Google OAuth credentials."""
    creds = None
    if os.path.exists(TOKEN_PATH):
        try:
            creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
        except Exception:
            creds = None

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                with open(TOKEN_PATH, 'w') as token_file:
                    token_file.write(creds.to_json())
                return creds
            except Exception:
                creds = None

        if not creds and interactive:
            if not os.path.exists(CREDENTIALS_PATH):
                return None

            flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_PATH), SCOPES)
            creds = flow.run_local_server(port=0)
            with open(TOKEN_PATH, 'w') as token_file:
                token_file.write(creds.to_json())

    return creds


def get_gspread_client() -> Optional[gspread.Client]:
    """Returns an authorized gspread client instance."""
    creds = get_gcp_credentials(interactive=False)
    return gspread.authorize(creds) if creds else None


def ensure_subfolder(service: Any, folder_name: str, parent_folder_id: str) -> str:
    """
    Checks if a subfolder exists inside parent_folder_id.
    Creates it if missing and caches the returned folder identifier.
    """
    cache_key = (parent_folder_id, folder_name)
    if cache_key in _FOLDER_CACHE:
        return _FOLDER_CACHE[cache_key]

    query = (
        f"'{parent_folder_id}' in parents and "
        f"name = '{folder_name}' and "
        f"mimeType = 'application/vnd.google-apps.folder' and "
        f"trashed = false"
    )
    results = service.files().list(q=query, spaces='drive', fields='files(id, name)').execute()
    files = results.get('files', [])

    if files:
        folder_id = files[0]['id']
    else:
        # Auto-create the subfolder
        folder_metadata = {
            'name': folder_name,
            'mimeType': 'application/vnd.google-apps.folder',
            'parents': [parent_folder_id]
        }
        created = service.files().create(body=folder_metadata, fields='id').execute()
        folder_id = created.get('id')

    _FOLDER_CACHE[cache_key] = folder_id
    return folder_id

# =====================================================================
# --- GOOGLE SHEET PROVISIONING & ROW INSERTION FOR FPD ---
# =====================================================================

FLEET_SHEET_HEADERS = [
    "Unit_ID", "Provider", "Status", "Restrictions", "Location",
    "Camera Status", "Make", "Model", "Year", "VIN",
    "Plate", "State", "Mileage", "PAVE_Insp", "Registration",
    "Insurance", "Size", "Service_Interval", "Return_Date"
]


def get_or_create_fpd_sheet(service: Any, client: gspread.Client) -> Tuple[gspread.Worksheet, str]:
    """
    Finds the FPD Master Spreadsheet in FPD_ROOT_FOLDER_ID or creates it
    with formatted column headers if it does not yet exist.
    Returns: (gspread.Worksheet, webViewLink)
    """
    cache_key = (FPD_ROOT_FOLDER_ID, "SPREADSHEET_MASTER")
    if cache_key in _FOLDER_CACHE:
        sheet_id = _FOLDER_CACHE[cache_key]
        spreadsheet = client.open_by_key(sheet_id)
        worksheet = spreadsheet.worksheet("MasterSheet")
        return worksheet, spreadsheet.url

    # 1. Search for existing spreadsheet file inside the FPD folder
    query = (
        f"'{FPD_ROOT_FOLDER_ID}' in parents and "
        f"name = '{FPD_SHEET_NAME}' and "
        f"mimeType = 'application/vnd.google-apps.spreadsheet' and "
        f"trashed = false"
    )
    results = service.files().list(q=query, spaces='drive', fields='files(id, name, webViewLink)').execute()
    files = results.get('files', [])

    if files:
        sheet_id = files[0]['id']
        web_link = files[0].get('webViewLink', '')
        spreadsheet = client.open_by_key(sheet_id)
        try:
            worksheet = spreadsheet.worksheet("MasterSheet")
        except gspread.WorksheetNotFound:
            worksheet = spreadsheet.sheet1
            worksheet.update_title("MasterSheet")
    else:
        # 2. Create brand-new Google Sheet directly inside the isolated folder
        file_metadata = {
            'name': FPD_SHEET_NAME,
            'mimeType': 'application/vnd.google-apps.spreadsheet',
            'parents': [FPD_ROOT_FOLDER_ID]
        }
        created = service.files().create(body=file_metadata, fields='id, webViewLink').execute()
        sheet_id = created.get('id')
        web_link = created.get('webViewLink', '')

        spreadsheet = client.open_by_key(sheet_id)
        worksheet = spreadsheet.sheet1
        worksheet.update_title("MasterSheet")

        # 3. Populate standard column headers
        worksheet.insert_row(FLEET_SHEET_HEADERS, index=1)

    _FOLDER_CACHE[cache_key] = sheet_id
    return worksheet, web_link


def sync_unit_to_fpd_sheet(unit_data: Dict[str, Any]) -> Tuple[bool, str, str]:
    """
    Appends a new unit record to the FPD Master Google Sheet.
    Creates the sheet and headers if they do not exist.
    Returns: (success: bool, web_sheet_link: str, error_message: str)
    """
    creds = get_gcp_credentials(interactive=False)
    client = get_gspread_client()
    if not creds or not client:
        return False, "", "Authentication missing. Please connect your Google account in the sidebar."

    try:
        service = build('drive', 'v3', credentials=creds)
        worksheet, sheet_url = get_or_create_fpd_sheet(service, client)

        # Build row aligned with FLEET_SHEET_HEADERS
        row = [
            str(unit_data.get('vehicle_id', '')),
            str(unit_data.get('provider', '')),
            str(unit_data.get('status', 'Active')),
            str(unit_data.get('restrictions', 'Clear')),
            str(unit_data.get('location', 'WNC4')),
            str(unit_data.get('camera_status', 'No')),
            str(unit_data.get('make', '')),
            str(unit_data.get('model', '')),
            str(unit_data.get('year', '')),
            str(unit_data.get('vin', '')),
            str(unit_data.get('plate', '')),
            str(unit_data.get('state', '')),
            int(unit_data.get('mileage', 0)),
            str(unit_data.get('pave_insp', '')),
            str(unit_data.get('registration', '')),
            str(unit_data.get('insurance', '')),
            str(unit_data.get('size', 'L')),
            int(unit_data.get('service_interval', 7500)),
            str(unit_data.get('return_date', ''))
        ]

        worksheet.append_row(row)
        return True, sheet_url, ""

    except Exception as err:
        return False, "", str(err)


def upload_file_to_drive_sync(
    local_filepath: str, 
    drive_filename: str, 
    subfolder_name: Optional[str] = None
) -> Tuple[bool, str, str]:
    """
    Synchronously uploads a local file into an isolated subfolder inside FPD_ROOT_FOLDER_ID.
    Automatically provisions the subfolder if it does not already exist.
    """
    if not os.path.exists(local_filepath):
        return False, "", f"Local file not found: {local_filepath}"

    if STRICT_FOLDER_LOCK and not FPD_ROOT_FOLDER_ID:
        return False, "", "Safety Guard: FPD_ROOT_FOLDER_ID is empty in config.py."

    creds = get_gcp_credentials(interactive=False)
    if not creds:
        return False, "", "Authentication missing. Please connect your Google account in the sidebar."

    try:
        service = build('drive', 'v3', credentials=creds)

        # Route to auto-provisioned subfolder or root FPD
        if subfolder_name:
            target_parent_id = ensure_subfolder(service, subfolder_name, FPD_ROOT_FOLDER_ID)
        else:
            target_parent_id = FPD_ROOT_FOLDER_ID

        file_metadata = {
            'name': drive_filename,
            'parents': [target_parent_id]
        }

        ext = Path(local_filepath).suffix.lower()
        mime = 'application/pdf' if ext == '.pdf' else 'application/octet-stream'
        media = MediaFileUpload(local_filepath, mimetype=mime, resumable=True)

        file_obj = service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id, webViewLink, name'
        ).execute()

        link = file_obj.get('webViewLink', '')
        return True, link, ""

    except Exception as err:
        return False, "", str(err)


class AuthWorker(QThread):
    auth_finished = Signal(bool, str)

    def run(self) -> None:
        if not os.path.exists(CREDENTIALS_PATH):
            self.auth_finished.emit(False, "Missing credentials.json at project root.")
            return
        try:
            creds = get_gcp_credentials(interactive=True)
            if creds and creds.valid:
                self.auth_finished.emit(True, "Successfully authenticated with Google Cloud!")
            else:
                self.auth_finished.emit(False, "Authentication was cancelled or failed.")
        except Exception as err:
            self.auth_finished.emit(False, f"Sign-in error: {str(err)}")


class DriveUploadWorker(QThread):
    upload_started = Signal(str)
    upload_finished = Signal(bool, str, str)

    def __init__(self, local_path: str, filename: str, subfolder_name: Optional[str] = None):
        super().__init__()
        self.local_path = local_path
        self.filename = filename
        self.subfolder_name = subfolder_name

    def run(self) -> None:
        self.upload_started.emit(self.filename)
        success, link, err = upload_file_to_drive_sync(self.local_path, self.filename, self.subfolder_name)
        if success:
            self.upload_finished.emit(True, self.filename, link)
        else:
            self.upload_finished.emit(False, self.filename, err)


class SyncWorker(QThread):
    sync_finished = Signal(bool, str)
    vehicles_loaded = Signal(int)

    def __init__(self, db_manager: DatabaseManager):
        super().__init__()
        self.db = db_manager

    def run(self) -> None:
        self.sync_finished.emit(True, "Local Cache Active")


class PushWorker(QThread):
    push_finished = Signal(bool, str)

    def __init__(self, db_manager: DatabaseManager):
        super().__init__()
        self.db = db_manager

    def run(self) -> None:
        pending = self.db.get_pending_mutations()
        if not pending:
            self.push_finished.emit(True, "Queue is empty.")
            return

        self.push_finished.emit(
            True, 
            f"FPD Isolated: {len(pending)} mutations stored safely in local SQLite. Upstream master writes blocked."
        )