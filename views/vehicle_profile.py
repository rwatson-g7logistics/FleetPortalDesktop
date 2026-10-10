"""
views/vehicle_profile.py
------------------------
Detailed profile view for a specific fleet unit. Displays full specifications,
live compliance status, dynamic PM intervals, and localized service logs.
Includes one-click document viewers, unit QR printing, and retirement auditing.
"""

import os
from datetime import datetime
from typing import Dict, Any, List, Optional

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
    QFrame, QGridLayout, QTableWidget, QTableWidgetItem, QHeaderView,
    QDialog, QFormLayout, QLineEdit, QComboBox, QMessageBox, QSpinBox,
    QFileDialog, QScrollArea
)
from PySide6.QtCore import Qt, Signal, QUrl
from PySide6.QtGui import QFont, QColor, QDesktopServices

from db_manager import DatabaseManager
from utils.platform_helper import get_default_font_family, get_app_data_directory
from utils.date_picker import DatePickerEdit
from utils.pave import generate_pave_pdf
from utils.qr_helper import export_grid_to_pdf, clean_vin
from utils.rental_lifecycle import evaluate_rental_compliance
from cloud_sync import upload_file_to_drive_sync, retire_unit_cloud
from config import SUBFOLDER_PAVE


class RetireUnitDialog(QDialog):
    """Modal dialog to retire a unit with digital signature, final mileage, and PAVE outtake."""

    def __init__(self, vehicle_data: dict, parent=None):
        super().__init__(parent)
        self.v_data = vehicle_data
        self.retire_payload: dict = {}
        self.pave_source_path: str = ""

        uid = str(self.v_data.get('vehicle_id', ''))
        self.setWindowTitle(f"Retire Vehicle — {uid}")
        self.setFixedSize(540, 640)
        self.setStyleSheet("background-color: #1E1E2E; color: #CDD6F4;")
        self.init_ui()

    def init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)

        uid = str(self.v_data.get('vehicle_id', ''))
        display_num = str(self.v_data.get('unit_id') or uid.split('_')[-1])
        prov = str(self.v_data.get('provider', 'N/A'))
        spec = f"{self.v_data.get('make', '')} {self.v_data.get('model', '')}".strip() or "N/A"
        vin = str(self.v_data.get('vin', 'N/A'))

        lbl_warning = QLabel(
            f"⚠️ <b>Retiring Unit: {display_num} ({spec})</b><br>"
            f"<span style='color: #A6ADC8;'>Provider: {prov} | VIN: {vin} | Key: {uid}</span><br>"
            "This will archive the record to <b>FPD_Retired_Sheet</b> in Google Drive."
        )
        lbl_warning.setStyleSheet("color: #F38BA8; font-size: 12px; line-height: 1.4;")
        lbl_warning.setWordWrap(True)
        layout.addWidget(lbl_warning)

        form = QFormLayout()
        form.setVerticalSpacing(12)
        form.setHorizontalSpacing(16)

        # 1. Retirement Date Picker
        self.txt_date = DatePickerEdit(placeholder="YYYY-MM-DD", date_format="yyyy-MM-dd", default_today=True)

        # 2. Final Recorded Mileage
        raw_mil = str(self.v_data.get('mileage', 0)).replace(',', '').split('.')[0]
        cur_mil = int(raw_mil) if raw_mil.isdigit() else 0
        self.spin_final_mileage = QSpinBox()
        self.spin_final_mileage.setRange(0, 1000000)
        self.spin_final_mileage.setValue(cur_mil)

        # 3. Reason Selection
        self.cmb_reason = QComboBox()
        self.cmb_reason.addItems([
            "De-fleeted / End of Lease",
            "Total Loss / Accident",
            "Engine / Transmission Failure",
            "High Mileage / Wear",
            "Sold",
            "Other"
        ])

        # 4. Notes
        self.txt_notes = QLineEdit()
        self.txt_notes.setPlaceholderText("Disposition details, insurance claim #, etc.")

        # 5. Camera Uninstalled Status
        self.cmb_cam_uninstalled = QComboBox()
        self.cmb_cam_uninstalled.addItems(["No", "Yes"])

        # 6. PAVE Outtake Upload
        pave_widget = QWidget()
        pave_layout = QHBoxLayout(pave_widget)
        pave_layout.setContentsMargins(0, 0, 0, 0)
        pave_layout.setSpacing(8)

        self.lbl_pave_status = QLabel("No file attached")
        self.lbl_pave_status.setStyleSheet("color: #A6ADC8; font-size: 11px;")

        btn_browse_pave = QPushButton("📎 Attach Outtake")
        btn_browse_pave.setFixedHeight(32)
        btn_browse_pave.setFixedWidth(130)
        btn_browse_pave.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_browse_pave.setStyleSheet("background-color: #313244; color: #89B4FA; border-radius: 5px; font-weight: bold;")
        btn_browse_pave.clicked.connect(self.select_pave_file)

        pave_layout.addWidget(self.lbl_pave_status, stretch=1)
        pave_layout.addWidget(btn_browse_pave)

        # 7. Digital Signature
        self.txt_sig = QLineEdit()
        self.txt_sig.setPlaceholderText("Type Full Name to Sign")

        # Stylesheet application
        combo_style = """
            QComboBox {
                background-color: #313244;
                color: #CDD6F4;
                border: 1px solid #45475A;
                border-radius: 5px;
                padding: 4px 10px;
                padding-right: 25px;
                min-height: 32px;
                font-size: 13px;
            }
            QComboBox::drop-down {
                subcontrol-origin: padding;
                subcontrol-position: top right;
                width: 25px;
                border-left: 1px solid #45475A;
            }
            QComboBox QAbstractItemView {
                background-color: #181825;
                color: #CDD6F4;
                selection-background-color: #45475A;
                selection-color: #89B4FA;
                border: 1px solid #45475A;
                padding: 4px;
                outline: 0;
            }
            QComboBox QAbstractItemView::item {
                min-height: 32px;
                padding: 6px 10px;
            }
        """

        input_style = """
            background-color: #313244;
            color: #CDD6F4;
            border: 1px solid #45475A;
            border-radius: 5px;
            padding: 4px 10px;
            min-height: 32px;
            font-size: 13px;
        """

        for cb in (self.cmb_reason, self.cmb_cam_uninstalled):
            cb.setStyleSheet(combo_style)
            cb.setMaxVisibleItems(8)

        for w in (self.txt_date, self.spin_final_mileage, self.txt_notes, self.txt_sig):
            w.setStyleSheet(input_style)

        form.addRow("Retirement Date*:", self.txt_date)
        form.addRow("Final Mileage*:", self.spin_final_mileage)
        form.addRow("Reason*:", self.cmb_reason)
        form.addRow("Notes:", self.txt_notes)
        form.addRow("Camera Uninstalled*:", self.cmb_cam_uninstalled)
        form.addRow("PAVE Outtake:", pave_widget)
        form.addRow("Digital Signature*:", self.txt_sig)
        layout.addLayout(form)

        btns = QHBoxLayout()
        btn_cancel = QPushButton("Cancel")
        btn_cancel.setFixedHeight(36)
        btn_cancel.setStyleSheet("background-color: #45475A; color: #CDD6F4; border-radius: 6px;")
        btn_cancel.clicked.connect(self.reject)

        btn_retire = QPushButton("🚫 Confirm & Retire Unit")
        btn_retire.setFixedHeight(36)
        btn_retire.setStyleSheet("background-color: #F38BA8; color: #11111B; font-weight: bold; border-radius: 6px;")
        btn_retire.clicked.connect(self.validate_and_retire)

        btns.addWidget(btn_cancel)
        btns.addWidget(btn_retire)
        layout.addLayout(btns)

    def select_pave_file(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select PAVE Outtake Document", "", "Documents & Images (*.pdf *.png *.jpg *.jpeg *.heic)"
        )
        if file_path:
            self.pave_source_path = file_path
            filename = os.path.basename(file_path)
            self.lbl_pave_status.setText(filename[:22] + "..." if len(filename) > 25 else filename)

    def validate_and_retire(self) -> None:
        sig = self.txt_sig.text().strip()
        if not sig:
            QMessageBox.warning(self, "Signature Required", "You must provide a digital signature to retire this unit.")
            return

        uid = str(self.v_data.get('vehicle_id', ''))
        raw_uid = str(self.v_data.get('unit_id') or uid.split('_')[-1])
        pave_cloud_link = ""

        if self.pave_source_path:
            ext = os.path.splitext(self.pave_source_path)[1].lower()
            date_str = datetime.now().strftime("%m-%d-%y")
            pave_dest_name = f"{uid}_PAVE_Outtake_{date_str}.pdf"

            if ext == ".pdf":
                local_pave_pdf = self.pave_source_path
            else:
                paves_dir = str(get_app_data_directory() / "PAVES")
                local_pave_pdf = generate_pave_pdf(
                    unit_id=raw_uid,
                    source_image_path=self.pave_source_path,
                    output_dir=paves_dir
                )

            if local_pave_pdf and os.path.exists(local_pave_pdf):
                pave_ok, pave_url, _ = upload_file_to_drive_sync(
                    local_filepath=local_pave_pdf,
                    drive_filename=pave_dest_name,
                    subfolder_name=SUBFOLDER_PAVE
                )
                if pave_ok:
                    pave_cloud_link = pave_url

        self.retire_payload = {
            'vehicle_id': uid,
            'unit_id': raw_uid,
            'provider': self.v_data.get('provider', ''),
            'make': self.v_data.get('make', ''),
            'model': self.v_data.get('model', ''),
            'year': self.v_data.get('year', ''),
            'vin': self.v_data.get('vin', ''),
            'plate': self.v_data.get('plate', ''),
            'state': self.v_data.get('state', ''),
            'mileage': self.spin_final_mileage.value(),
            'retired_date': self.txt_date.text().strip(),
            'reason': self.cmb_reason.currentText().strip(),
            'notes': self.txt_notes.text().strip(),
            'camera_uninstalled': self.cmb_cam_uninstalled.currentText().strip(),
            'signature': sig,
            'pave_link': pave_cloud_link
        }
        self.accept()


class VehicleProfileView(QWidget):
    """Standardized Deep Dive view for a single vehicle, acting as an operational hub."""

    back_requested = Signal()
    log_service_requested = Signal(dict)

    def __init__(self, db_manager: DatabaseManager, vehicle_id: str, parent=None):
        super().__init__(parent)
        self.db = db_manager
        self.vehicle_id = str(vehicle_id)
        self.vehicle_data: Dict[str, Any] = {}
        self.service_history: List[Dict[str, Any]] = []

        self.load_data()
        self.init_ui()

    def load_data(self) -> None:
        """Fetches vehicle record handling compound slugs and numeric fallbacks."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            
            clean_num = self.vehicle_id.split('_')[-1].lstrip('0') or self.vehicle_id
            cursor.execute("""
                SELECT * FROM master_vehicles 
                WHERE vehicle_id = ? 
                   OR vehicle_id = ? 
                   OR vehicle_id LIKE ?
            """, (self.vehicle_id, clean_num, f"%_{clean_num}"))
            row = cursor.fetchone()

            if row:
                self.vehicle_data = dict(row)
            else:
                df = self.db.get_all_vehicles()
                match = df[
                    (df['vehicle_id'].astype(str) == self.vehicle_id) |
                    (df['vehicle_id'].astype(str).str.endswith(f"_{clean_num}"))
                ]
                if not match.empty:
                    self.vehicle_data = match.iloc[0].to_dict()
                else:
                    self.vehicle_data = {
                        "vehicle_id": self.vehicle_id,
                        "unit_id": clean_num,
                        "provider": "Unknown",
                        "make": "Unknown",
                        "status": "Active"
                    }

            cursor.execute("""
                SELECT date, service_type, mileage, vendor, cost 
                FROM service_logs 
                WHERE vehicle_id = ? OR vehicle_id = ?
                ORDER BY id DESC LIMIT 20
            """, (self.vehicle_id, clean_num))
            self.service_history = [dict(r) for r in cursor.fetchall()]

    def init_ui(self) -> None:
        """Constructs layout, specifications, compliance cards, and service tables."""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(24, 20, 24, 20)
        main_layout.setSpacing(16)

        # --- 1. HEADER BAR & CONTROLS ---
        header_layout = QHBoxLayout()

        btn_back = QPushButton("◀ Back to Fleet")
        btn_back.setFixedHeight(35)
        btn_back.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_back.setStyleSheet("background-color: #45475A; color: #CDD6F4; border-radius: 6px; padding: 0 16px; font-weight: bold;")
        btn_back.clicked.connect(self.back_requested.emit)
        header_layout.addWidget(btn_back)

        header_layout.addSpacing(14)

        display_num = str(self.vehicle_data.get('unit_id') or self.vehicle_id.split('_')[-1])
        prov = str(self.vehicle_data.get('provider', 'Fleet'))
        lbl_title = QLabel(f"Unit Profile: {display_num}")
        lbl_title.setFont(QFont(get_default_font_family(), 18, QFont.Weight.Bold))
        lbl_title.setStyleSheet("color: #CDD6F4;")
        header_layout.addWidget(lbl_title)

        lbl_tag = QLabel(f"[{prov} • {self.vehicle_data.get('unit_type', 'Fleet')}]")
        lbl_tag.setStyleSheet("color: #89B4FA; font-size: 13px; font-weight: bold; margin-left: 6px;")
        header_layout.addWidget(lbl_tag)

        header_layout.addStretch()

        # One-Click QR Label Button
        btn_qr = QPushButton("🖨️ Unit QR")
        btn_qr.setFixedHeight(35)
        btn_qr.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_qr.setStyleSheet("background-color: #313244; color: #89B4FA; border: 1px solid #89B4FA; font-weight: bold; border-radius: 6px; padding: 0 14px;")
        btn_qr.clicked.connect(self.print_single_qr)
        header_layout.addWidget(btn_qr)

        # One-Click PAVE Document Viewer (If Attached)
        pave_url = str(self.vehicle_data.get('pave_insp', '')).strip()
        if pave_url.startswith("http"):
            btn_pave = QPushButton("📄 View PAVE")
            btn_pave.setFixedHeight(35)
            btn_pave.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_pave.setStyleSheet("background-color: #313244; color: #A6E3A1; border: 1px solid #A6E3A1; font-weight: bold; border-radius: 6px; padding: 0 14px;")
            btn_pave.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(pave_url)))
            header_layout.addWidget(btn_pave)

        # Log Service Button
        btn_service = QPushButton("🛠️ Log Service")
        btn_service.setFixedHeight(35)
        btn_service.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_service.setStyleSheet("background-color: #A6E3A1; color: #11111B; font-weight: bold; border-radius: 6px; padding: 0 16px;")
        btn_service.clicked.connect(lambda: self.log_service_requested.emit(self.vehicle_data))
        header_layout.addWidget(btn_service)

        # Retire Unit Button
        self.btn_retire = QPushButton("🚫 Retire Unit")
        self.btn_retire.setFixedHeight(35)
        self.btn_retire.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_retire.setStyleSheet("""
            QPushButton {
                background-color: #313244; 
                color: #F38BA8; 
                border: 1px solid #F38BA8; 
                font-weight: bold; 
                border-radius: 6px; 
                padding: 0 16px;
            }
            QPushButton:hover {
                background-color: #F38BA8;
                color: #11111B;
            }
        """)
        self.btn_retire.clicked.connect(self.handle_retire_unit)
        header_layout.addWidget(self.btn_retire)

        main_layout.addLayout(header_layout)

        # --- 2. SPECIFICATIONS & TELEMETRY CARDS ---
        cards_layout = QHBoxLayout()
        cards_layout.setSpacing(16)

        # Left Card: Core Specifications
        card_specs = QFrame()
        card_specs.setStyleSheet("background-color: #1E1E2E; border-radius: 10px; border: 1px solid #313244;")
        specs_grid = QGridLayout(card_specs)
        specs_grid.setContentsMargins(18, 16, 18, 16)
        specs_grid.setVerticalSpacing(10)
        specs_grid.setHorizontalSpacing(16)

        lbl_specs = QLabel("Vehicle Specifications")
        lbl_specs.setFont(QFont(get_default_font_family(), 12, QFont.Weight.Bold))
        lbl_specs.setStyleSheet("color: #89B4FA; border: none; padding-bottom: 4px;")
        specs_grid.addWidget(lbl_specs, 0, 0, 1, 2)

        make_model = f"{self.vehicle_data.get('make', '')} {self.vehicle_data.get('model', '')}".strip() or "Unknown"
        spec_fields = [
            ("Provider / Type:", f"{prov} ({self.vehicle_data.get('unit_type', 'Fleet')})"),
            ("Make / Model:", make_model),
            ("Model Year:", str(self.vehicle_data.get('year', 'N/A'))),
            ("Vehicle Size:", str(self.vehicle_data.get('size', 'Standard'))),
            ("VIN Number:", str(self.vehicle_data.get('vin', 'N/A'))),
            ("License Plate:", f"{self.vehicle_data.get('plate', 'N/A')} ({self.vehicle_data.get('state', '')})"),
            ("Camera Installed:", str(self.vehicle_data.get('camera_status', 'No')))
        ]

        for i, (k_text, v_text) in enumerate(spec_fields, start=1):
            lbl_k = QLabel(k_text)
            lbl_k.setStyleSheet("color: #A6ADC8; font-weight: bold; border: none;")
            lbl_v = QLabel(str(v_text))
            lbl_v.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            lbl_v.setStyleSheet("color: #CDD6F4; font-size: 13px; border: none;")
            specs_grid.addWidget(lbl_k, i, 0)
            specs_grid.addWidget(lbl_v, i, 1)

        cards_layout.addWidget(card_specs, stretch=1)

        # Right Card: Operational Telemetry & Compliance
        card_status = QFrame()
        card_status.setStyleSheet("background-color: #1E1E2E; border-radius: 10px; border: 1px solid #313244;")
        status_grid = QGridLayout(card_status)
        status_grid.setContentsMargins(18, 16, 18, 16)
        status_grid.setVerticalSpacing(10)
        status_grid.setHorizontalSpacing(16)

        lbl_status_header = QLabel("Operational Telemetry & Status")
        lbl_status_header.setFont(QFont(get_default_font_family(), 12, QFont.Weight.Bold))
        lbl_status_header.setStyleSheet("color: #89B4FA; border: none; padding-bottom: 4px;")
        status_grid.addWidget(lbl_status_header, 0, 0, 1, 2)

        # Mileage & PM interval calculation
        raw_mil = str(self.vehicle_data.get('mileage', 0)).replace(',', '').split('.')[0]
        mileage = int(raw_mil) if raw_mil.isdigit() else 0
        raw_last_a = str(self.vehicle_data.get('last_a_service', 0)).replace(',', '').split('.')[0]
        last_a = int(raw_last_a) if raw_last_a.isdigit() else 0
        raw_int = str(self.vehicle_data.get('service_interval', 7500)).split('.')[0]
        interval = int(raw_int) if raw_int.isdigit() else 7500

        diff = mileage - last_a
        if diff >= interval:
            pm_text = f"🔴 {diff - interval:,}m Overdue"
        elif diff >= (interval - 500):
            pm_text = f"🟡 {interval - diff:,}m Due Soon"
        else:
            pm_text = f"🟢 {interval - diff:,}m Remaining"

        ret_date_str = str(self.vehicle_data.get('return_date', '')).strip()
        is_rental = (self.vehicle_data.get('unit_type') == 'Temp') or (prov in ["U-Haul", "Budget", "Enterprise", "LMR", "Hertz"])
        if is_rental and ret_date_str:
            eval_res = evaluate_rental_compliance(ret_date_str)
            ret_display = f"{ret_date_str} ({eval_res['badge']})"
        else:
            ret_display = ret_date_str if ret_date_str else "N/A (Fleet Permanent)"

        status_fields = [
            ("Roster Status:", str(self.vehicle_data.get('status', 'Active'))),
            ("Operating Base:", str(self.vehicle_data.get('location', 'WNC4'))),
            ("Current Odometer:", f"{mileage:,} mi"),
            ("Service Schedule:", pm_text),
            ("Registration:", str(self.vehicle_data.get('registration', 'Clear'))),
            ("Insurance Card:", str(self.vehicle_data.get('insurance', 'Clear'))),
            ("Return Schedule:", ret_display)
        ]

        for i, (k_text, v_text) in enumerate(status_fields, start=1):
            lbl_k = QLabel(k_text)
            lbl_k.setStyleSheet("color: #A6ADC8; font-weight: bold; border: none;")
            lbl_v = QLabel(str(v_text))
            lbl_v.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

            if "Overdue" in v_text or "Expired" in v_text:
                lbl_v.setStyleSheet("color: #F38BA8; font-weight: bold; font-size: 13px; border: none;")
            elif "Due Soon" in v_text or "Due Tomorrow" in v_text:
                lbl_v.setStyleSheet("color: #F9E2AF; font-weight: bold; font-size: 13px; border: none;")
            else:
                lbl_v.setStyleSheet("color: #CDD6F4; font-size: 13px; border: none;")

            status_grid.addWidget(lbl_k, i, 0)
            status_grid.addWidget(lbl_v, i, 1)

        cards_layout.addWidget(card_status, stretch=1)
        main_layout.addLayout(cards_layout)

        # --- 3. RECENT MAINTENANCE LOGS TABLE ---
        lbl_history = QLabel("Maintenance & Service History")
        lbl_history.setFont(QFont(get_default_font_family(), 13, QFont.Weight.Bold))
        lbl_history.setStyleSheet("color: #CDD6F4; margin-top: 6px;")
        main_layout.addWidget(lbl_history)

        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["Date", "Service Performed", "Mileage", "Vendor", "Cost"])
        
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Interactive)
        
        self.table.setColumnWidth(0, 110)
        self.table.setColumnWidth(2, 110)
        self.table.setColumnWidth(3, 160)
        self.table.setColumnWidth(4, 100)

        self.table.verticalHeader().setVisible(False)
        self.table.setStyleSheet("""
            QTableWidget {
                background-color: #1E1E2E;
                color: #CDD6F4;
                gridline-color: #313244;
                border: 1px solid #313244;
                border-radius: 8px;
            }
            QHeaderView::section {
                background-color: #181825;
                color: #89B4FA;
                padding: 8px;
                font-weight: bold;
                border: none;
                border-right: 1px solid #313244;
            }
        """)

        self.populate_service_history()
        main_layout.addWidget(self.table, stretch=1)

    def populate_service_history(self) -> None:
        """Populates localized SQLite service records or renders an empty placeholder."""
        if not self.service_history:
            self.table.setRowCount(1)
            item = QTableWidgetItem("No localized maintenance logs recorded for this unit.")
            item.setForeground(QColor("#A6ADC8"))
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(0, 1, item)
            return

        self.table.setRowCount(len(self.service_history))
        for row_idx, log in enumerate(self.service_history):
            self.table.setItem(row_idx, 0, QTableWidgetItem(str(log.get('date', ''))))
            self.table.setItem(row_idx, 1, QTableWidgetItem(str(log.get('service_type', ''))))

            mil = log.get('mileage', 0)
            self.table.setItem(row_idx, 2, QTableWidgetItem(f"{mil:,} mi" if str(mil).isdigit() else ""))
            self.table.setItem(row_idx, 3, QTableWidgetItem(str(log.get('vendor', ''))))

            cost_item = QTableWidgetItem(f"${log.get('cost', 0.0):.2f}")
            cost_item.setForeground(QColor("#A6E3A1"))
            self.table.setItem(row_idx, 4, cost_item)

    def print_single_qr(self) -> None:
        """Generates and exports an isolated QR label for this specific vehicle."""
        vin = clean_vin(str(self.vehicle_data.get('vin', '')))
        uid = str(self.vehicle_data.get('unit_id') or self.vehicle_id.split('_')[-1])
        if not vin:
            QMessageBox.warning(self, "QR Generation", "No valid VIN on record for this unit.")
            return

        filename = f"QR_Label_{uid}.pdf"
        export_grid_to_pdf([{"vehicle_id": uid, "vin": vin}], filename, parent_widget=self)
        QMessageBox.information(self, "QR Generated", f"✅ QR Label saved to FPD / QR Codes\nFile: {filename}")

    def handle_retire_unit(self) -> None:
        """Executes the retirement flow and returns to the fleet grid."""
        dialog = RetireUnitDialog(self.vehicle_data, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            unit_id = str(self.vehicle_data.get('vehicle_id') or self.vehicle_id)

            # 1. Cloud Move to FPD_Retired_Sheet
            cloud_ok, err = retire_unit_cloud(unit_id, dialog.retire_payload)
            if not cloud_ok:
                QMessageBox.warning(
                    self, 
                    "Cloud Sync Warning", 
                    f"Could not archive to Google Drive: {err}\nPurging local record."
                )

            # 2. Local Purge
            self.db.retire_vehicle(unit_id)

            QMessageBox.information(
                self,
                "Unit Retired",
                f"✅ Unit {unit_id} has been retired.\nArchived to FPD_Retired_Sheet in Google Drive."
            )

            # Signal return to Fleet Command view
            self.back_requested.emit()