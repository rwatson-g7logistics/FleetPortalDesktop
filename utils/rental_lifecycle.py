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
    update_cloud_return_date, update_cloud_compliance_docs, upload_file_to_drive_sync,
    upload_unit_file_to_drive_sync
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

        # Track initial dates to enforce document upload on changes
        self.orig_reg = str(vehicle_data.get('registration', '')).split(' ')[0].strip()
        self.orig_ins = str(vehicle_data.get('insurance', '')).split(' ')[0].strip()
        self.orig_ret = str(vehicle_data.get('return_date', '')).split(' ')[0].strip()

        # Dedicated document file paths
        self.reg_doc_path: str = ""
        self.ins_doc_path: str = ""
        self.ret_doc_path: str = ""

        self.setWindowTitle(f"Compliance & Documentation — Unit {self.unit_id}")
        self.setFixedSize(520, 560)
        self.setStyleSheet("background-color: #1E1E2E; color: #CDD6F4;")
        self.init_ui()

    def init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        prov = self.v_data.get('provider', 'Fleet')
        u_type = self.v_data.get('unit_type', 'Fleet')
        lbl_header = QLabel(
            f"📋 <b>Compliance & Expiration Manager: Unit {self.unit_id}</b><br>"
            f"<span style='color: #89B4FA;'>Provider: {prov} ({u_type}) | ID: {self.vehicle_id}</span>"
        )
        layout.addWidget(lbl_header)

        form = QFormLayout()
        form.setVerticalSpacing(10)

        input_style = "background-color: #313244; color: #CDD6F4; border: 1px solid #45475A; border-radius: 5px; padding-left: 8px;"
        btn_style = "background-color: #313244; color: #89B4FA; border: 1px solid #45475A; border-radius: 4px; font-weight: bold; font-size: 11px;"

        def create_doc_widget(btn_text: str, click_handler):
            w = QWidget()
            lay = QHBoxLayout(w)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(6)
            lbl = QLabel("No file attached")
            lbl.setStyleSheet("color: #A6ADC8; font-size: 11px;")
            btn = QPushButton(btn_text)
            btn.setFixedHeight(28)
            btn.setFixedWidth(115)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(btn_style)
            btn.clicked.connect(click_handler)
            lay.addWidget(lbl, stretch=1)
            lay.addWidget(btn)
            return w, lbl

        # 1. Registration
        self.txt_reg = DatePickerEdit(placeholder="YYYY-MM-DD", date_format="yyyy-MM-dd")
        if self.orig_reg and self.orig_reg not in ['Unknown', 'Clear', 'OK', 'N/A']:
            self.txt_reg.setText(self.orig_reg)
        self.txt_reg.setFixedHeight(34)
        self.txt_reg.setStyleSheet(input_style)
        reg_doc_widget, self.lbl_reg_status = create_doc_widget("📎 Attach Reg", self.select_reg_file)

        # 2. Insurance
        self.txt_ins = DatePickerEdit(placeholder="YYYY-MM-DD", date_format="yyyy-MM-dd")
        if self.orig_ins and self.orig_ins not in ['Unknown', 'Clear', 'OK', 'N/A']:
            self.txt_ins.setText(self.orig_ins)
        self.txt_ins.setFixedHeight(34)
        self.txt_ins.setStyleSheet(input_style)
        ins_doc_widget, self.lbl_ins_status = create_doc_widget("📎 Attach Ins", self.select_ins_file)

        # 3. Return Date / Agreement
        self.txt_return_date = DatePickerEdit(placeholder="YYYY-MM-DD", date_format="yyyy-MM-dd")
        if self.orig_ret and self.orig_ret not in ['Unknown', 'Clear', 'OK', 'N/A']:
            self.txt_return_date.setText(self.orig_ret)
        self.txt_return_date.setFixedHeight(34)
        self.txt_return_date.setStyleSheet(input_style)
        ret_doc_widget, self.lbl_ret_status = create_doc_widget("📎 Attach Agr", self.select_ret_file)

        # 4. Notes / Details
        self.txt_notes = QLineEdit()
        self.txt_notes.setPlaceholderText("Policy #, renewal notes, extension terms...")
        self.txt_notes.setFixedHeight(34)
        self.txt_notes.setStyleSheet(input_style)

        form.addRow("Registration Exp:", self.txt_reg)
        form.addRow("Registration Doc*:", reg_doc_widget)
        form.addRow("Insurance Exp:", self.txt_ins)
        form.addRow("Insurance Doc*:", ins_doc_widget)
        form.addRow("Return Date:", self.txt_return_date)
        form.addRow("Agreement Doc*:", ret_doc_widget)
        form.addRow("Notes / Details:", self.txt_notes)
        layout.addLayout(form)

        btns = QHBoxLayout()
        btn_cancel = QPushButton("Cancel")
        btn_cancel.setFixedHeight(36)
        btn_cancel.setStyleSheet("background-color: #45475A; color: #CDD6F4; border-radius: 6px;")
        btn_cancel.clicked.connect(self.reject)

        btn_confirm = QPushButton("💾 Apply & Sync Cloud")
        btn_confirm.setFixedHeight(36)
        btn_confirm.setStyleSheet("background-color: #A6E3A1; color: #11111B; font-weight: bold; border-radius: 6px; padding: 0 16px;")
        btn_confirm.clicked.connect(self.save_extension)

        btns.addWidget(btn_cancel)
        btns.addWidget(btn_confirm)
        layout.addLayout(btns)

    def select_reg_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Select Registration Document", "", "Documents & Images (*.pdf *.png *.jpg *.jpeg *.heic)")
        if path:
            self.reg_doc_path = path
            name = os.path.basename(path)
            self.lbl_reg_status.setText(name[:20] + "..." if len(name) > 23 else name)

    def select_ins_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Select Insurance Document", "", "Documents & Images (*.pdf *.png *.jpg *.jpeg *.heic)")
        if path:
            self.ins_doc_path = path
            name = os.path.basename(path)
            self.lbl_ins_status.setText(name[:20] + "..." if len(name) > 23 else name)

    def select_ret_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Select Rental Agreement / Contract", "", "Documents & Images (*.pdf *.png *.jpg *.jpeg *.heic)")
        if path:
            self.ret_doc_path = path
            name = os.path.basename(path)
            self.lbl_ret_status.setText(name[:20] + "..." if len(name) > 23 else name)

    def _convert_and_upload(self, src_path: str, doc_type: str) -> str:
        """Converts image to PDF if necessary and saves into the unit's dedicated Drive folder."""
        ext = os.path.splitext(src_path)[1].lower()
        date_str = datetime.now().strftime("%m-%d-%y")
        dest_filename = f"{self.vehicle_id}_{doc_type}_{date_str}.pdf"

        if ext == ".pdf":
            local_pdf = src_path
        else:
            paves_dir = str(get_app_data_directory() / "Compliance_Docs")
            local_pdf = generate_pave_pdf(self.unit_id, src_path, paves_dir)

        if local_pdf and os.path.exists(local_pdf):
            ok, url, err = upload_unit_file_to_drive_sync(
                local_filepath=local_pdf, 
                drive_filename=dest_filename, 
                vehicle_id=self.vehicle_id, 
                sub_category="Compliance"
            )
            if ok:
                return url
            print(f"[COMPLIANCE UPLOAD WARNING] {doc_type} upload issue: {err}")
        return ""

    def save_extension(self) -> None:
        new_reg = self.txt_reg.text().strip()
        new_ins = self.txt_ins.text().strip()
        new_return = self.txt_return_date.text().strip()

        # Enforce document requirement on any new or modified date
        if new_reg and (new_reg != self.orig_reg) and not self.reg_doc_path:
            QMessageBox.warning(self, "Document Required", "A supporting document is required when entering or changing the Registration Expiration date.")
            return

        if new_ins and (new_ins != self.orig_ins) and not self.ins_doc_path:
            QMessageBox.warning(self, "Document Required", "An insurance card or binder is required when entering or changing the Insurance Expiration date.")
            return

        if new_return and (new_return != self.orig_ret) and not self.ret_doc_path:
            QMessageBox.warning(self, "Document Required", "A rental agreement or contract document is required when entering or extending the Return Date.")
            return

        # Upload files into Unit Records / <vehicle_id> / folder
        reg_url = self._convert_and_upload(self.reg_doc_path, "Registration") if self.reg_doc_path else ""
        ins_url = self._convert_and_upload(self.ins_doc_path, "Insurance") if self.ins_doc_path else ""
        ret_url = self._convert_and_upload(self.ret_doc_path, "Rental_Contract") if self.ret_doc_path else ""

        if self.is_retired:
            success, restored_dict, err = restore_unit_from_retirement(self.vehicle_id, new_return, ret_url)
            if not success:
                QMessageBox.warning(self, "Cloud Sync Warning", f"Could not restore row in Google Sheets: {err}")
                return

            restored_dict['registration'] = new_reg
            restored_dict['insurance'] = new_ins
            restored_dict['return_date'] = new_return
            restored_dict['status'] = 'Active'
            import pandas as pd
            self.db.save_vehicles_bulk(pd.DataFrame([restored_dict]))

            QMessageBox.information(self, "Retirement Cancelled", f"✅ Unit {self.unit_id} restored to active fleet!\nUploaded documents saved to unit folder.")
        else:
            # Update cloud sheet columns
            cloud_ok, cloud_err = update_cloud_compliance_docs(
                self.vehicle_id,
                registration=new_reg if new_reg else None,
                insurance=new_ins if new_ins else None,
                return_date=new_return if new_return else None
            )
            if not cloud_ok:
                QMessageBox.warning(self, "Cloud Warning", f"Could not update Google Sheets: {cloud_err}")

            # Update SQLite cache
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE master_vehicles 
                    SET registration = COALESCE(NULLIF(?, ''), registration),
                        insurance = COALESCE(NULLIF(?, ''), insurance),
                        return_date = COALESCE(NULLIF(?, ''), return_date)
                    WHERE vehicle_id = ?
                """, (new_reg, new_ins, new_return, self.vehicle_id))
                conn.commit()

            msg = [f"✅ Compliance records updated for Unit {self.unit_id}!"]
            if reg_url or ins_url or ret_url:
                msg.append(f"• Attached documents saved to Drive: Unit Records / {self.vehicle_id} / Compliance")
            QMessageBox.information(self, "Compliance Updated", "\n".join(msg))

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