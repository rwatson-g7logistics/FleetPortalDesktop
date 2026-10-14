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
import urllib.request
from packaging import version
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
    FPD_ROOT_FOLDER_ID, STRICT_FOLDER_LOCK, FPD_SHEET_NAME, STRICT_FOLDER_LOCK, APP_VERSION, GITHUB_LATEST_RELEASE_URL
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

def parse_vehicle_id(vehicle_id: str) -> Tuple[str, str]:
    """
    Safely decomposes Vehicle_ID into (canonical_provider, unit_id).
    Prevents truncation on multi-word providers (e.g. 'u_haul_1' -> 'U-Haul', '1').
    """
    if '_' not in vehicle_id:
        return 'Fleet', vehicle_id

    prov_tag, unit_id = vehicle_id.rsplit('_', 1)
    canonical_map = {
        'u_haul': 'U-Haul',
        'merchants': 'Merchants',
        'amzn': 'AMZN',
        'kingbee': 'Kingbee',
        'budget': 'Budget',
        'enterprise': 'Enterprise',
        'lmr': 'LMR',
        'hertz': 'Hertz',
    }
    clean_tag = prov_tag.lower().strip()
    provider = canonical_map.get(clean_tag, prov_tag.replace('_', '-').title())
    return provider, unit_id


def build_vehicle_id(provider: str, unit_id: str) -> str:
    """Builds compound Vehicle_ID slug from provider and unit number."""
    clean_prov = provider.lower().replace(' ', '_').replace('-', '_')
    clean_unit = str(unit_id).lstrip('0') or str(unit_id)
    return f"{clean_prov}_{clean_unit}"

def pull_fpd_master_sheet() -> tuple[bool, pd.DataFrame, str]:
    """
    Downstream sync: Pulls all current records from FPD_Fleet_Master Google Sheet.
    Returns (success, dataframe, error_message).
    """
    creds = get_gcp_credentials(interactive=False)
    client = get_gspread_client()
    if not creds or not client:
        return False, pd.DataFrame(), "Authentication missing. Connect Google account in sidebar."

    try:
        service = build('drive', 'v3', credentials=creds)
        folder_id = FPD_ROOT_FOLDER_ID

        query = (
            f"name = '{FPD_SHEET_NAME}' and "
            f"'{folder_id}' in parents and "
            f"mimeType = 'application/vnd.google-apps.spreadsheet' and "
            f"trashed = false"
        )
        res = service.files().list(q=query, spaces='drive', fields='files(id, name)').execute()
        files = res.get('files', [])

        if not files:
            return False, pd.DataFrame(), f"'{FPD_SHEET_NAME}' not found in Google Drive."

        sheet_id = files[0]['id']
        spreadsheet = client.open_by_key(sheet_id)
        worksheet = spreadsheet.sheet1

        data = worksheet.get_all_records()
        if not data:
            return True, pd.DataFrame(), ""

        df = pd.DataFrame(data)

        column_map = {
            'Unit_ID': 'vehicle_id',
            'Unit ID': 'vehicle_id',
            'Provider': 'provider',
            'Status': 'status',
            'Restrictions': 'restrictions',
            'Location': 'location',
            'Camera Status': 'camera_status',
            'Make': 'make',
            'Model': 'model',
            'Year': 'year',
            'VIN': 'vin',
            'Plate': 'plate',
            'State': 'state',
            'Mileage': 'mileage',
            'PAVE_Insp': 'pave_insp',
            'Registration': 'registration',
            'Insurance': 'insurance',
            'Return_Date': 'return_date',
            'Return Date': 'return_date',
            'Unit_Type': 'unit_type',
            'Unit Type': 'unit_type',
            'Size': 'size'
        }
        df = df.rename(columns=column_map)
        if 'vehicle_id' in df.columns and 'provider' in df.columns:
            df['unit_id'] = df['vehicle_id'].astype(str)
            df['vehicle_id'] = df.apply(
                lambda r: f"{str(r['provider']).lower().replace(' ', '_').replace('-', '_')}_{str(r['unit_id'])}"
                if '_' not in str(r['vehicle_id']) else str(r['vehicle_id']),
                axis=1
            )
        return True, df, ""

    except Exception as e:
        return False, pd.DataFrame(), str(e)

def retire_unit_cloud(unit_id: str, retire_data: dict) -> tuple[bool, str]:
    """
    Moves a vehicle row from FPD_Master_Sheet to FPD_Retired_Sheet.
    Saves full vehicle specifications (Make, Model, Year, VIN, Plate, State).
    """
    creds = get_gcp_credentials(interactive=False)
    client = get_gspread_client()
    if not creds or not client:
        return False, "Authentication missing. Connect Google account in sidebar."

    try:
        service = build('drive', 'v3', credentials=creds)
        folder_id = FPD_ROOT_FOLDER_ID

        # 1. Locate row in FPD_Master_Sheet
        query_master = (
            f"name = '{FPD_SHEET_NAME}' and "
            f"'{folder_id}' in parents and "
            f"mimeType = 'application/vnd.google-apps.spreadsheet' and "
            f"trashed = false"
        )
        res = service.files().list(q=query_master, spaces='drive', fields='files(id, name)').execute()
        files = res.get('files', [])
        if not files:
            return False, "Master sheet not found."

        master_ss = client.open_by_key(files[0]['id'])
        master_ws = master_ss.sheet1

        prov_hint, raw_uid = parse_vehicle_id(unit_id)
        if retire_data.get('provider'):
            prov_hint = str(retire_data.get('provider')).strip()

        all_rows = master_ws.get_all_values()
        target_row_idx = None
        row_values = []

        for idx, row in enumerate(all_rows[1:], start=2):
            if len(row) >= 2:
                row_uid = str(row[0]).strip()
                row_prov = str(row[1]).strip()
                if (row_uid == raw_uid and (not prov_hint or row_prov.lower() == prov_hint.lower())) or row_uid == unit_id:
                    target_row_idx = idx
                    row_values = row
                    break

        if not target_row_idx:
            cell = master_ws.find(raw_uid)
            if cell:
                target_row_idx = cell.row
                row_values = master_ws.row_values(cell.row)
            else:
                return False, f"Unit {unit_id} not found in Google Sheet."

        # 2. Open or Create FPD_Retired_Sheet with 14 Standard Headers
        retired_sheet_name = "FPD_Retired_Sheet"
        query_retired = (
            f"name = '{retired_sheet_name}' and "
            f"'{folder_id}' in parents and "
            f"mimeType = 'application/vnd.google-apps.spreadsheet' and "
            f"trashed = false"
        )
        res_ret = service.files().list(q=query_retired, spaces='drive', fields='files(id, name)').execute()
        ret_files = res_ret.get('files', [])

        retired_headers = [
            'Vehicle_ID', 'Make', 'Model', 'Year', 'VIN', 'Plate', 'State',
            'Final_Mileage', 'Retired_Date', 'Reason', 'Notes',
            'Camera_Uninstalled', 'Digital_Signature', 'PAVE_Outtake'
        ]

        if ret_files:
            retired_ss = client.open_by_key(ret_files[0]['id'])
            retired_ws = retired_ss.sheet1
            # Auto-align header row if it is missing columns
            current_headers = retired_ws.row_values(1)
            if current_headers != retired_headers:
                retired_ws.update('A1:N1', [retired_headers])
        else:
            file_meta = {
                'name': retired_sheet_name,
                'mimeType': 'application/vnd.google-apps.spreadsheet',
                'parents': [folder_id]
            }
            created = service.files().create(body=file_meta, fields='id').execute()
            retired_ss = client.open_by_key(created['id'])
            retired_ws = retired_ss.sheet1
            retired_ws.append_row(retired_headers)

        # 3. Compile Full 14-Column Payload (Strictly 1:1 with retired_headers)
        combined_vid = build_vehicle_id(prov_hint, raw_uid)
        make = str(retire_data.get('make') or (row_values[6] if len(row_values) > 6 else ''))
        model = str(retire_data.get('model') or (row_values[7] if len(row_values) > 7 else ''))
        year = str(retire_data.get('year') or (row_values[8] if len(row_values) > 8 else ''))
        vin = str(retire_data.get('vin') or (row_values[9] if len(row_values) > 9 else ''))
        plate = str(retire_data.get('plate') or (row_values[10] if len(row_values) > 10 else ''))
        state = str(retire_data.get('state') or (row_values[11] if len(row_values) > 11 else ''))

        raw_mil = retire_data.get('mileage', 0)
        final_mil = int(raw_mil) if str(raw_mil).isdigit() else 0
        if final_mil == 0 and len(row_values) > 12:
            cloud_mil = str(row_values[12]).replace(',', '').split('.')[0]
            final_mil = int(cloud_mil) if cloud_mil.isdigit() else 0

        retired_payload = [
            combined_vid,
            make,
            model,
            year,
            vin,
            plate,
            state,
            final_mil,
            str(retire_data.get('retired_date', '')),
            str(retire_data.get('reason', '')),
            str(retire_data.get('notes', '')),
            str(retire_data.get('camera_uninstalled', 'No')),
            str(retire_data.get('signature', '')),
            str(retire_data.get('pave_link', ''))
        ]
        retired_ws.append_row(retired_payload)

        # 4. Remove active record from Master Sheet
        master_ws.delete_rows(target_row_idx)
        return True, ""

    except Exception as e:
        return False, str(e)

def restore_unit_from_retirement(vehicle_id: str, new_return_date: str, doc_link: str = "") -> Tuple[bool, dict, str]:
    """
    Moves an auto-retired unit from FPD_Retired_Sheet back to FPD_Master_Sheet.
    Reverses Vehicle_ID into canonical Provider and Unit_ID and restores Make, Model, Year, Plate, and State.
    """
    creds = get_gcp_credentials(interactive=False)
    client = get_gspread_client()
    if not creds or not client:
        return False, {}, "Authentication missing."

    try:
        service = build('drive', 'v3', credentials=creds)
        folder_id = FPD_ROOT_FOLDER_ID

        # 1. Open FPD_Retired_Sheet
        q_ret = f"name = 'FPD_Retired_Sheet' and '{folder_id}' in parents and trashed = false"
        res_ret = service.files().list(q=q_ret, spaces='drive', fields='files(id)').execute()
        r_files = res_ret.get('files', [])
        if not r_files:
            return False, {}, "FPD_Retired_Sheet not found."

        ret_ss = client.open_by_key(r_files[0]['id'])
        ret_ws = ret_ss.sheet1

        cell = ret_ws.find(vehicle_id)
        if not cell:
            cell = ret_ws.find(vehicle_id.split('_')[-1])
        if not cell:
            return False, {}, f"Unit {vehicle_id} not found in FPD_Retired_Sheet."

        row_vals = ret_ws.row_values(cell.row)

        # 2. Reverse Vehicle_ID slug into full canonical Provider and Unit ID
        clean_vid = str(row_vals[0])
        prov, unit_num = parse_vehicle_id(clean_vid)

        make = str(row_vals[1] if len(row_vals) > 1 else '')
        model = str(row_vals[2] if len(row_vals) > 2 else '')
        year = str(row_vals[3] if len(row_vals) > 3 else '')
        vin = str(row_vals[4] if len(row_vals) > 4 else '')
        plate = str(row_vals[5] if len(row_vals) > 5 else '')
        state = str(row_vals[6] if len(row_vals) > 6 else '')
        mil = int(row_vals[7]) if len(row_vals) > 7 and str(row_vals[7]).isdigit() else 0

        # 3. Append to FPD_Master_Sheet
        worksheet, _ = get_or_create_fpd_sheet(service, client)
        restored_row = [
            unit_num, prov, 'Active', 'Clear', 'WNC4', 'No',
            make, model, year, vin, plate, state, mil, doc_link, '', '', 'Standard', 7500, new_return_date
        ]
        worksheet.append_row(restored_row)

        # 4. Remove archived record from Retired Sheet
        ret_ws.delete_rows(cell.row)

        restored_dict = {
            'vehicle_id': clean_vid,
            'unit_id': unit_num,
            'provider': prov,
            'make': make,
            'model': model,
            'year': year,
            'vin': vin,
            'plate': plate,
            'state': state,
            'mileage': mil,
            'return_date': new_return_date,
            'unit_type': 'Temp',
            'status': 'Active'
        }
        return True, restored_dict, ""

    except Exception as e:
        return False, {}, str(e)

def update_cloud_vehicle_mileage(vehicle_id: str, new_mileage: int) -> Tuple[bool, str]:
    """
    Directly updates Column M (Mileage, Column 13) in FPD_Master_Sheet.
    Prevents cache refreshes from rolling back local odometer changes.
    """
    creds = get_gcp_credentials(interactive=False)
    client = get_gspread_client()
    if not creds or not client:
        return False, "Authentication missing."

    try:
        service = build('drive', 'v3', credentials=creds)
        worksheet, _ = get_or_create_fpd_sheet(service, client)

        clean_uid = vehicle_id.split('_')[-1].lstrip('0') or vehicle_id.split('_')[-1]
        
        # Locate row by display Unit ID or compound Vehicle ID
        cell = worksheet.find(clean_uid)
        if not cell:
            cell = worksheet.find(vehicle_id)
        if not cell:
            return False, f"Unit '{vehicle_id}' not found in FPD_Master_Sheet."

        # Update Column 13 (Column M: Mileage)
        worksheet.update_cell(cell.row, 13, int(new_mileage))
        return True, ""
    except Exception as e:
        return False, str(e)

def update_cloud_return_date(vehicle_id: str, new_return_date: str) -> Tuple[bool, str]:
    """Updates the Return_Date cell for an active unit in FPD_Master_Sheet."""
    creds = get_gcp_credentials(interactive=False)
    client = get_gspread_client()
    if not creds or not client:
        return False, "Authentication missing."

    try:
        service = build('drive', 'v3', credentials=creds)
        worksheet, _ = get_or_create_fpd_sheet(service, client)

        unit_num = vehicle_id.split('_')[-1]
        cell = worksheet.find(unit_num)
        if not cell:
            cell = worksheet.find(vehicle_id)
        if not cell:
            return False, f"Unit {vehicle_id} not found in FPD_Master_Sheet."

        # Return_Date is Column 19 (Column S)
        worksheet.update_cell(cell.row, 19, new_return_date)
        return True, ""
    except Exception as e:
        return False, str(e)
    
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
        display_unit_id = str(unit_data.get('unit_id') or str(unit_data.get('vehicle_id', '')).split('_')[-1])

        # Build row aligned with FLEET_SHEET_HEADERS
        row = [
            display_unit_id,
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


class UpdateCheckWorker(QThread):
    """Pings GitHub API to compare current client build against remote releases."""
    update_available = Signal(str, str, str)  # latest_ver, changelog, download_url
    check_finished = Signal(bool, str)

    def run(self) -> None:
        try:
            req = urllib.request.Request(
                GITHUB_LATEST_RELEASE_URL, 
                headers={"User-Agent": "FleetPortalDesktop-Updater"}
            )
            with urllib.request.urlopen(req, timeout=5) as response:
                if response.status != 200:
                    self.check_finished.emit(False, f"HTTP Error {response.status}")
                    return
                data = json.loads(response.read().decode())

            remote_tag = data.get("tag_name", "").lstrip("v")
            body = data.get("body", "No changelog provided.")
            assets = data.get("assets", [])

            # Identify platform binary asset (e.g., .exe or .zip)
            download_url = ""
            for asset in assets:
                name = asset.get("name", "").lower()
                if name.endswith(".exe") or name.endswith(".zip"):
                    download_url = asset.get("browser_download_url", "")
                    break

            if version.parse(remote_tag) > version.parse(APP_VERSION):
                self.update_available.emit(remote_tag, body, download_url)
                self.check_finished.emit(True, f"New version {remote_tag} found.")
            else:
                self.check_finished.emit(True, "Application up to date.")

        except Exception as err:
            self.check_finished.emit(False, f"Update check failed: {str(err)}")

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