"""
utils/rental_lifecycle.py
-------------------------
Manages temporary rental compliance decay, automated retirement execution,
contract date extensions, and cloud un-retirement workflows.
"""

import os
from datetime import datetime, date
from typing import Optional, Dict, Any, Tuple

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
    QFormLayout, QMessageBox, QFileDialog, QWidget, QLineEdit
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QColor

from utils.date_picker import DatePickerEdit
from utils.platform_helper import get_default_font_family, get_app_data_directory
from utils.pave import generate_pave_pdf
from cloud_sync import (
    retire_unit_cloud, restore_unit_from_retirement, 
    update_cloud_return_date, upload_file_to_drive_sync
)
from config import SUBFOLDER_PAVE


def evaluate_rental_compliance(return_date_str: str) -> Dict[str, Any]:
    """
    Evaluates return date thresholds:
    - delta > 3 days: Compliant
    - delta in [2, 3] days: Warning
    - delta == 1 day: Critical Warning
    - delta <= 0 days: Auto-Retire Trigger
    """
    if not return_date_str or return_date_str in ['Unknown', 'Clear', 'OK', 'N/A']:
        return {
            'status': 'NONE',
            'badge': '—',
            'color': '#A6ADC8',
            'tooltip': 'No rental return date specified.',
            'days_left': 999
        }

    try:
        clean_date = return_date_str.split(' ')[0].strip()
        ret_date = datetime.strptime(clean_date, "%Y-%m-%d").date()
        today = datetime.today().date()
        days_left = (ret_date - today).days

        if days_left > 3:
            return {
                'status': 'COMPLIANT',
                'badge': '✅ Compliant',
                'color': '#A6E3A1',
                'tooltip': f"Rental Active: {days_left} days remaining ({clean_date})\n(Click to extend return date)",
                'days_left': days_left
            }
        elif days_left in (2, 3):
            return {
                'status': 'WARNING',
                'badge': f'⚠️ {days_left}d Left',
                'color': '#F9E2AF',
                'tooltip': f"⚠️ RETURN WARNING: Due in {days_left} days ({clean_date})\n(Click to extend return date)",
                'days_left': days_left
            }
        elif days_left == 1:
            return {
                'status': 'CRITICAL',
                'badge': '🚨 Due Tomorrow',
                'color': '#F38BA8',
                'tooltip': f"🚨 CRITICAL: Return scheduled for tomorrow ({clean_date})!\n(Click to extend return date)",
                'days_left': days_left
            }
        else:
            return {
                'status': 'EXPIRED',
                'badge': '🚨 Return Due Today' if days_left == 0 else f'🚨 {abs(days_left)}d Overdue',
                'color': '#F38BA8',
                'tooltip': f"🚨 SCHEDULED RETURN REACHED ({clean_date})\nEligible for automated de-fleet.",
                'days_left': days_left
            }
    except ValueError:
        return {
            'status': 'INVALID',
            'badge': '⚠️ Date Error',
            'color': '#F9E2AF',
            'tooltip': f"Malformed date string: '{return_date_str}'",
            'days_left': 999
        }


class ExtendRentalDialog(QDialog):
    """Modal to extend rental contract, attach agreement docs, or restore a retired unit."""

    def __init__(self, db_manager, vehicle_data: dict, is_retired: bool = False, parent=None):
        super().__init__(parent)
        self.db = db_manager
        self.v_data = vehicle_data
        self.is_retired = is_retired
        self.doc_source_path: str = ""

        self.vehicle_id = str(vehicle_data.get('vehicle_id', ''))
        self.unit_id = str(vehicle_data.get('unit_id') or self.vehicle_id.split('_')[-1])

        self.setWindowTitle(f"Extend Rental — Unit {self.unit_id}")
        self.setFixedSize(460, 420)
        self.setStyleSheet("background-color: #1E1E2E; color: #CDD6F4;")
        self.init_ui()

    def init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        lbl_header = QLabel(
            f"🔄 <b>Extend Rental Contract: Unit {self.unit_id}</b><br>"
            f"<span style='color: #A6ADC8;'>Provider: {self.v_data.get('provider', 'Temp')} | ID: {self.vehicle_id}</span>"
        )
        layout.addWidget(lbl_header)

        form = QFormLayout()

        # Date Picker for New Return Date (pulls standard calendar popup)
        self.txt_new_date = DatePickerEdit(placeholder="YYYY-MM-DD", date_format="yyyy-MM-dd", default_today=True)
        self.txt_new_date.setFixedHeight(34)
        self.txt_new_date.setStyleSheet("background-color: #313244; color: #CDD6F4; border: 1px solid #45475A; border-radius: 5px; padding-left: 8px;")

        # Document / Contract Upload Widget
        doc_widget = QWidget()
        doc_layout = QHBoxLayout(doc_widget)
        doc_layout.setContentsMargins(0, 0, 0, 0)
        doc_layout.setSpacing(6)

        self.lbl_doc_status = QLabel("No agreement attached")
        self.lbl_doc_status.setStyleSheet("color: #A6ADC8; font-size: 11px;")

        btn_browse_doc = QPushButton("📎 Attach Doc")
        btn_browse_doc.setFixedHeight(30)
        btn_browse_doc.setFixedWidth(110)
        btn_browse_doc.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_browse_doc.setStyleSheet("background-color: #313244; color: #89B4FA; border-radius: 4px; font-weight: bold;")
        btn_browse_doc.clicked.connect(self.select_doc_file)

        doc_layout.addWidget(self.lbl_doc_status, stretch=1)
        doc_layout.addWidget(btn_browse_doc)

        self.txt_notes = QLineEdit()
        self.txt_notes.setPlaceholderText("Extension terms, weekly rate update, etc.")
        self.txt_notes.setFixedHeight(34)
        self.txt_notes.setStyleSheet("background-color: #313244; color: #CDD6F4; border: 1px solid #45475A; border-radius: 5px; padding-left: 8px;")

        form.addRow("New Return Date*:", self.txt_new_date)
        form.addRow("Agreement Doc:", doc_widget)
        form.addRow("Extension Notes:", self.txt_notes)
        layout.addLayout(form)

        btns = QHBoxLayout()
        btn_confirm = QPushButton("💾 Apply Extension & Sync Cloud")
        btn_confirm.setFixedHeight(36)
        btn_confirm.setStyleSheet("background-color: #A6E3A1; color: #11111B; font-weight: bold; border-radius: 6px;")
        btn_confirm.clicked.connect(self.save_extension)

        btn_cancel = QPushButton("Cancel")
        btn_cancel.setFixedHeight(36)
        btn_cancel.setStyleSheet("background-color: #45475A; color: #CDD6F4; border-radius: 6px;")
        btn_cancel.clicked.connect(self.reject)

        btns.addWidget(btn_cancel)
        btns.addWidget(btn_confirm)
        layout.addLayout(btns)

    def select_doc_file(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Rental Extension Document", "", "Documents (*.pdf *.png *.jpg *.jpeg)"
        )
        if file_path:
            self.doc_source_path = file_path
            filename = os.path.basename(file_path)
            self.lbl_doc_status.setText(filename[:20] + "..." if len(filename) > 23 else filename)

    def save_extension(self) -> None:
        new_date = self.txt_new_date.text().strip()
        if not new_date:
            QMessageBox.warning(self, "Validation Error", "A new return date is required.")
            return

        doc_link = ""
        if self.doc_source_path:
            ext = os.path.splitext(self.doc_source_path)[1].lower()
            date_str = datetime.now().strftime("%m-%d-%y")
            dest_name = f"{self.vehicle_id}_Rental_Extension_{date_str}.pdf"

            if ext == ".pdf":
                local_pdf = self.doc_source_path
            else:
                paves_dir = str(get_app_data_directory() / "PAVES")
                local_pdf = generate_pave_pdf(self.unit_id, self.doc_source_path, paves_dir)

            if local_pdf and os.path.exists(local_pdf):
                ok, url, _ = upload_file_to_drive_sync(local_pdf, dest_name, SUBFOLDER_PAVE)
                if ok:
                    doc_link = url

        if self.is_retired:
            # 1. Reverse retirement: move row from FPD_Retired_Sheet back to FPD_Master_Sheet
            success, restored_dict, err = restore_unit_from_retirement(self.vehicle_id, new_date, doc_link)
            if not success:
                QMessageBox.warning(self, "Cloud Sync Warning", f"Could not restore row in Google Sheets: {err}")
                return

            # Re-insert vehicle into local active cache
            restored_dict['return_date'] = new_date
            restored_dict['status'] = 'Active'
            import pandas as pd
            self.db.save_vehicles_bulk(pd.DataFrame([restored_dict]))

            QMessageBox.information(
                self, 
                "Retirement Cancelled", 
                f"✅ Unit {self.unit_id} restored to active fleet!\nReturn Date set to: {new_date}"
            )
        else:
            # Standard active extension
            ok, err = update_cloud_return_date(self.vehicle_id, new_date)
            if not ok:
                QMessageBox.warning(self, "Cloud Warning", f"Could not update return date in Google Sheets: {err}")

            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE master_vehicles SET return_date = ? WHERE vehicle_id = ?",
                    (new_date, self.vehicle_id)
                )
                conn.commit()

            QMessageBox.information(
                self, 
                "Rental Extended", 
                f"✅ Return date for Unit {self.unit_id} extended to {new_date}."
            )

        self.accept()


def check_and_auto_retire_rentals(db_manager, parent_widget=None) -> None:
    """
    Scans cached vehicles for expired rental contracts (days_left <= 0).
    Auto-retires matching units to FPD_Retired_Sheet and displays an interactive prompt.
    """
    df = db_manager.get_all_vehicles()
    if df.empty:
        return

    expired_units = []
    for _, row in df.iterrows():
        unit_type = str(row.get('unit_type', '')).strip()
        prov = str(row.get('provider', '')).strip()
        ret_date = str(row.get('return_date', '')).strip()

        is_rental = (unit_type == 'Temp') or (prov in ["U-Haul", "Budget", "Enterprise", "LMR", "Hertz"])
        if is_rental and ret_date:
            compliance = evaluate_rental_compliance(ret_date)
            if compliance['status'] == 'EXPIRED':
                expired_units.append(dict(row))

    if not expired_units:
        return

    # Process automated retirement for expired units
    for unit in expired_units:
        vid = str(unit.get('vehicle_id', ''))
        raw_uid = str(unit.get('unit_id') or vid.split('_')[-1])

        retire_payload = {
            'vehicle_id': vid,
            'unit_id': raw_uid,
            'provider': unit.get('provider', 'Temp'),
            'make': unit.get('make', ''),
            'model': unit.get('model', ''),
            'year': unit.get('year', ''),
            'vin': unit.get('vin', ''),
            'plate': unit.get('plate', ''),
            'state': unit.get('state', ''),
            'mileage': unit.get('mileage', 0),
            'retired_date': datetime.now().strftime("%Y-%m-%d"),
            'reason': "Rental Expired (Scheduled Return Date Reached)",
            'notes': f"Auto-retired on scheduled return date ({unit.get('return_date')})",
            'camera_uninstalled': 'No',
            'signature': "SYSTEM AUTO-RETIRE",
            'pave_link': ''
        }

        # 1. Cloud migration: move to FPD_Retired_Sheet
        retire_unit_cloud(vid, retire_payload)

        # 2. Local database purge
        db_manager.retire_vehicle(vid)

    # Display interactive popup with option to immediately extend/restore
    unit_ids_str = ", ".join([str(u.get('unit_id') or u.get('vehicle_id')) for u in expired_units])
    
    msg_box = QMessageBox(parent_widget)
    msg_box.setWindowTitle("Scheduled Rental Auto-Retirement")
    msg_box.setIcon(QMessageBox.Icon.Warning)
    msg_box.setStyleSheet("background-color: #1E1E2E; color: #CDD6F4;")
    msg_box.setText(
        f"<b>⚠️ Rental Units Reached Scheduled Return Date:</b><br><br>"
        f"The following units have been automatically moved to <b>FPD_Retired_Sheet</b>:<br>"
        f"<span style='color: #F38BA8; font-weight: bold;'>{unit_ids_str}</span><br><br>"
        f"To cancel retirement and restore any unit to the active fleet, click <b>Extend Rental</b> below."
    )
    btn_extend = msg_box.addButton("🔄 Extend / Cancel Retirement", QMessageBox.ButtonRole.ActionRole)
    btn_ok = msg_box.addButton("Acknowledge", QMessageBox.ButtonRole.AcceptRole)

    msg_box.exec()

    if msg_box.clickedButton() == btn_extend:
        # Open extension dialog for the first expired unit
        target_unit = expired_units[0]
        dlg = ExtendRentalDialog(db_manager, target_unit, is_retired=True, parent=parent_widget)
        dlg.exec()