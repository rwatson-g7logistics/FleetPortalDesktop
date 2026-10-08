"""
cloud_sync.py
------------
Handles asynchronous background workers and direct Google API integration.
Executes read/write tasks against Google Sheets and Drive using PySide6 QThread worker workers.
"""

import os
import json
import gspread
import pandas as pd

from PySide6.QtCore import QThread, Signal
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from typing import Optional
from config import SHEET_ID, USERS_SHEET_ID, SCOPES, TOKEN_PATH
from db_manager import DatabaseManager


def get_gcp_credentials() -> Optional[Credentials]:
    """Authenticates and returns Google OAuth credentials."""
    if os.path.exists(TOKEN_PATH):
        return Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
    return None


def get_gspread_client() -> Optional[gspread.Client]:
    """Returns an authorized gspread client instance."""
    creds = get_gcp_credentials()
    return gspread.authorize(creds) if creds else None


class SyncWorker(QThread):
    """Background worker thread to fetch upstream Google Sheets data without blocking the UI."""

    # Qt Signals for UI notification
    sync_finished = Signal(bool, str)
    vehicles_loaded = Signal(int)

    def __init__(self, db_manager: DatabaseManager):
        super().__init__()
        self.db = db_manager

    def run(self) -> None:
        """Executes the cloud sync process in a separate thread."""
        try:
            client = get_gspread_client()
            if not client:
                self.sync_finished.emit(False, "Authentication Failed: Token missing or invalid.")
                return

            # Fetch MasterSheet
            sheet = client.open_by_key(SHEET_ID).worksheet("MasterSheet")
            records = sheet.get_all_records()
            df_vehicles = pd.DataFrame(records).astype(str)

            if not df_vehicles.empty:
                df_vehicles.columns = df_vehicles.columns.str.strip()
                # Save into local SQLite cache
                self.db.save_vehicles_bulk(df_vehicles)
                self.vehicles_loaded.emit(len(df_vehicles))

            self.sync_finished.emit(True, "Sync Completed Successfully.")

        except Exception as err:
            self.sync_finished.emit(False, f"Sync Failed: {str(err)}")