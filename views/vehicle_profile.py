"""
views/vehicle_profile.py
------------------------
Detailed profile view for a specific fleet unit. Displays specifications,
compliance status, current mileage, and a localized service history log.
"""

from typing import Dict, Any, List
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
    QFrame, QGridLayout, QTableWidget, QTableWidgetItem, QHeaderView,
    QDialog, QFormLayout, QLineEdit, QComboBox, QMessageBox
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QColor

from db_manager import DatabaseManager
from utils.platform_helper import get_default_font_family
from utils.date_picker import DatePickerEdit


class RetireUnitDialog(QDialog):
    """Modal dialog to retire a unit with digital signature and audit fields."""

    def __init__(self, vehicle_data: dict, parent=None):
        super().__init__(parent)
        self.v_data = vehicle_data
        self.retire_payload: dict = {}
        self.setWindowTitle(f"Retire Vehicle — {self.v_data.get('vehicle_id')}")
        self.setFixedSize(480, 480)
        self.setStyleSheet("background-color: #1E1E2E; color: #CDD6F4;")
        self.init_ui()

    def init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        lbl_warning = QLabel(
            f"⚠️ You are removing Unit {self.v_data.get('vehicle_id')} from the active fleet.\n"
            "This will archive the record to FPD_Retired_Master in Google Drive."
        )
        lbl_warning.setStyleSheet("color: #F38BA8; font-weight: bold;")
        lbl_warning.setWordWrap(True)
        layout.addWidget(lbl_warning)

        form = QFormLayout()

        # 1. Date
        self.txt_date = DatePickerEdit(placeholder="YYYY-MM-DD", date_format="yyyy-MM-dd", default_today=True)

        # 2. Reason Dropdown
        self.cmb_reason = QComboBox()
        self.cmb_reason.addItems([
            "De-fleeted / End of Lease",
            "Total Loss / Accident",
            "Engine / Transmission Failure",
            "High Mileage / Wear",
            "Sold",
            "Other"
        ])

        # 3. Notes
        self.txt_notes = QLineEdit()
        self.txt_notes.setPlaceholderText("Disposition details, insurance claim #, etc.")

        # 4. Camera Uninstalled Dropdown
        self.cmb_cam_uninstalled = QComboBox()
        self.cmb_cam_uninstalled.addItems(["No", "Yes"])

        # 5. Digital Signature
        self.txt_sig = QLineEdit()
        self.txt_sig.setPlaceholderText("Type Full Name to Sign")

        # Style fields
        for w in (self.txt_date, self.cmb_reason, self.txt_notes, self.cmb_cam_uninstalled, self.txt_sig):
            w.setFixedHeight(34)
            w.setStyleSheet("background-color: #313244; color: #CDD6F4; border: 1px solid #45475A; border-radius: 5px; padding-left: 8px;")

        form.addRow("Retirement Date*:", self.txt_date)
        form.addRow("Reason*:", self.cmb_reason)
        # need to add Final Mileage* functionality later, but for now we will just use the current mileage from the vehicle data
        # form.addRow("Final Mileage*:", self.spin_final_mileage)
        form.addRow("Notes:", self.txt_notes)
        form.addRow("Camera Uninstalled*:", self.cmb_cam_uninstalled)
        form.addRow("Digital Signature*:", self.txt_sig)
        layout.addLayout(form)

        btns = QHBoxLayout()
        btn_retire = QPushButton("🚫 Confirm & Retire Unit")
        btn_retire.setFixedHeight(36)
        btn_retire.setStyleSheet("background-color: #F38BA8; color: #11111B; font-weight: bold; border-radius: 6px;")
        btn_retire.clicked.connect(self.validate_and_retire)

        btn_cancel = QPushButton("Cancel")
        btn_cancel.setFixedHeight(36)
        btn_cancel.setStyleSheet("background-color: #45475A; color: #CDD6F4; border-radius: 6px;")
        btn_cancel.clicked.connect(self.reject)

        btns.addWidget(btn_cancel)
        btns.addWidget(btn_retire)
        layout.addLayout(btns)

    def validate_and_retire(self) -> None:
        sig = self.txt_sig.text().strip()
        if not sig:
            QMessageBox.warning(self, "Signature Required", "You must provide a digital signature to retire this unit.")
            return

        self.retire_payload = {
            'provider': self.v_data.get('provider', ''),
            'make': self.v_data.get('make', ''),
            'model': self.v_data.get('model', ''),
            'vin': self.v_data.get('vin', ''),
            'mileage': self.v_data.get('mileage', 0),
            'retired_date': self.txt_date.text().strip(),
            'reason': self.cmb_reason.currentText().strip(),
            'notes': self.txt_notes.text().strip(),
            'camera_uninstalled': self.cmb_cam_uninstalled.currentText().strip(),
            'signature': sig
        }
        self.accept()


class VehicleProfileView(QWidget):
    """Detailed view for a single vehicle, acting as a hub for unit operations."""

    back_requested = Signal()
    log_service_requested = Signal(dict)

    def __init__(self, db_manager: DatabaseManager, vehicle_id: str, parent=None):
        super().__init__(parent)
        self.db = db_manager
        self.vehicle_id = vehicle_id
        self.vehicle_data: Dict[str, Any] = {}
        self.service_history: List[Dict[str, Any]] = []

        self.load_data()
        self.init_ui()

    def load_data(self) -> None:
        """Fetches the specific vehicle record and recent service logs from SQLite."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            
            # Fetch Master Record
            cursor.execute("SELECT * FROM master_vehicles WHERE vehicle_id = ?", (self.vehicle_id,))
            row = cursor.fetchone()
            if row:
                self.vehicle_data = dict(row)
            else:
                self.vehicle_data = {"vehicle_id": self.vehicle_id, "make": "Unknown"}

            # Fetch Recent Service History
            cursor.execute("""
                SELECT date, service_type, mileage, vendor, cost 
                FROM service_logs 
                WHERE vehicle_id = ? 
                ORDER BY id DESC LIMIT 15
            """, (self.vehicle_id,))
            self.service_history = [dict(r) for r in cursor.fetchall()]

    def handle_retire_unit(self) -> None:
        """Executes the retirement flow and returns to the fleet grid."""
        from cloud_sync import retire_unit_cloud

        dialog = RetireUnitDialog(self.vehicle_data, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            # Guarantees a strictly-typed string to satisfy Pylance
            unit_id = str(self.vehicle_data.get('vehicle_id') or self.vehicle_id)

            # 1. Cloud Move
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
                f"✅ Unit {unit_id} has been retired.\nArchived to FPD_Retired_Master in Google Drive."
            )

            # Signal back to Fleet Command view
            self.back_requested.emit()

    def init_ui(self) -> None:
        """Constructs the profile layout, specification grids, and history table."""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(15)

        # --- 1. HEADER & NAVIGATION ---
        header_layout = QHBoxLayout()
        
        btn_back = QPushButton("◀ Back to Fleet")
        btn_back.setFixedHeight(35)
        btn_back.setStyleSheet("background-color: #45475A; color: #CDD6F4; border-radius: 6px; padding: 0 15px; font-weight: bold;")
        btn_back.clicked.connect(self.back_requested.emit)
        header_layout.addWidget(btn_back)

        header_layout.addSpacing(15)

        lbl_title = QLabel(f"Unit Profile: {self.vehicle_id}")
        lbl_title.setFont(QFont(get_default_font_family(), 18, QFont.Weight.Bold))
        lbl_title.setStyleSheet("color: #CDD6F4;")
        header_layout.addWidget(lbl_title)

        header_layout.addStretch()

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
                padding: 0 15px;
            }
            QPushButton:hover {
                background-color: #F38BA8;
                color: #11111B;
            }
        """)
        self.btn_retire.clicked.connect(self.handle_retire_unit)
        header_layout.addWidget(self.btn_retire)

        # Service Button
        btn_service = QPushButton("🛠️ Log New Service")
        btn_service.setFixedHeight(35)
        btn_service.setStyleSheet("background-color: #A6E3A1; color: #11111B; font-weight: bold; border-radius: 6px; padding: 0 15px;")
        btn_service.clicked.connect(lambda: self.log_service_requested.emit(self.vehicle_data))
        header_layout.addWidget(btn_service)

        main_layout.addLayout(header_layout)

        # --- 2. VEHICLE DETAILS WIDGETS ---
        details_layout = QHBoxLayout()

        # Left Card: Core Specifications
        card_specs = QFrame()
        card_specs.setStyleSheet("background-color: #1E1E2E; border-radius: 10px;")
        specs_grid = QGridLayout(card_specs)
        specs_grid.setContentsMargins(15, 15, 15, 15)
        specs_grid.setSpacing(10)

        lbl_specs = QLabel("Vehicle Specifications")
        lbl_specs.setFont(QFont(get_default_font_family(), 12, QFont.Weight.Bold))
        lbl_specs.setStyleSheet("color: #89B4FA; margin-bottom: 10px;")
        specs_grid.addWidget(lbl_specs, 0, 0, 1, 2)

        spec_fields = [
            ("Make/Model:", f"{self.vehicle_data.get('make', '')} {self.vehicle_data.get('model', '')}"),
            ("Year:", self.vehicle_data.get('year', '')),
            ("VIN:", self.vehicle_data.get('vin', '')),
            ("License Plate:", f"{self.vehicle_data.get('plate', '')} ({self.vehicle_data.get('state', '')})"),
            ("Size Category:", self.vehicle_data.get('size', 'Standard'))
        ]

        for i, (label_text, value_text) in enumerate(spec_fields, start=1):
            lbl_key = QLabel(label_text)
            lbl_key.setStyleSheet("color: #A6ADC8; font-weight: bold;")
            lbl_val = QLabel(str(value_text))
            lbl_val.setStyleSheet("color: #CDD6F4;")
            specs_grid.addWidget(lbl_key, i, 0)
            specs_grid.addWidget(lbl_val, i, 1)

        details_layout.addWidget(card_specs, stretch=1)

        # Right Card: Status & Compliance
        card_status = QFrame()
        card_status.setStyleSheet("background-color: #1E1E2E; border-radius: 10px;")
        status_grid = QGridLayout(card_status)
        status_grid.setContentsMargins(15, 15, 15, 15)
        status_grid.setSpacing(10)

        lbl_status = QLabel("Operational Status")
        lbl_status.setFont(QFont(get_default_font_family(), 12, QFont.Weight.Bold))
        lbl_status.setStyleSheet("color: #89B4FA; margin-bottom: 10px;")
        status_grid.addWidget(lbl_status, 0, 0, 1, 2)

        mileage = self.vehicle_data.get('mileage', 0)
        status_fields = [
            ("Current Status:", self.vehicle_data.get('status', 'Active')),
            ("Location:", self.vehicle_data.get('location', 'WNC4')),
            ("Odometer:", f"{int(mileage):,} mi" if str(mileage).isdigit() else "0 mi"),
            ("Registration:", self.vehicle_data.get('registration', 'Unknown')),
            ("Insurance:", self.vehicle_data.get('insurance', 'Unknown'))
        ]

        for i, (label_text, value_text) in enumerate(status_fields, start=1):
            lbl_key = QLabel(label_text)
            lbl_key.setStyleSheet("color: #A6ADC8; font-weight: bold;")
            lbl_val = QLabel(str(value_text))
            
            if value_text in ["Inactive", "Retired", "Expired"]:
                lbl_val.setStyleSheet("color: #F38BA8; font-weight: bold;")
            else:
                lbl_val.setStyleSheet("color: #CDD6F4;")
                
            status_grid.addWidget(lbl_key, i, 0)
            status_grid.addWidget(lbl_val, i, 1)

        details_layout.addWidget(card_status, stretch=1)
        main_layout.addLayout(details_layout)

        # --- 3. RECENT SERVICE HISTORY TABLE ---
        lbl_history = QLabel("Recent Maintenance Logs")
        lbl_history.setFont(QFont(get_default_font_family(), 14, QFont.Weight.Bold))
        lbl_history.setStyleSheet("color: #CDD6F4; margin-top: 10px;")
        main_layout.addWidget(lbl_history)

        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["Date", "Service Performed", "Mileage", "Vendor", "Cost"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setStyleSheet("""
            QTableWidget {
                background-color: #1E1E2E;
                color: #CDD6F4;
                gridline-color: #313244;
                border: none;
                border-radius: 8px;
            }
            QHeaderView::section {
                background-color: #181825;
                color: #89B4FA;
                padding: 8px;
                font-weight: bold;
                border: none;
            }
        """)
        
        self.populate_service_history()
        main_layout.addWidget(self.table)

    def populate_service_history(self) -> None:
        """Renders the local SQLite service logs for this specific vehicle into the table."""
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