"""
views/fleet_view.py
-------------------
Fleet Command Center view module for G7 Fleet Portal Desktop.
Provides live search, multi-variable filtering, vehicle status indicators,
and quick inline mileage updates.
"""

import os
import pandas as pd
from datetime import datetime
# --- PYQT6 / PYSIDE6 IMPORTS ---
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, 
    QPushButton, QTableWidget, QTableWidgetItem, QComboBox, 
    QHeaderView, QDialog, QSpinBox, QMessageBox, QFrame, QFormLayout,
    QMenu, QInputDialog, QAbstractItemView, QFileDialog
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QColor

# --- UTILITY MODULE IMPORTS ---
from db_manager import DatabaseManager
from utils.platform_helper import get_default_font_family, get_app_data_directory
from utils.qr_helper import export_grid_to_pdf, clean_vin
from utils.pave import generate_pave_pdf
from utils.date_picker import DatePickerEdit

# --- CLOUD SYNC & FOLDER CONSTANTS ---
from cloud_sync import upload_file_to_drive_sync, sync_unit_to_fpd_sheet
from config import SUBFOLDER_PAVE, SUBFOLDER_QR_CODES, FPD_SHEET_NAME

class AddUnitDialog(QDialog):
    """Modal dialog to manually add a new unit, generate its QR code, and upload intake PAVE files."""

    def __init__(self, db_manager: DatabaseManager, parent=None):
        super().__init__(parent)
        self.db = db_manager
        self.pave_source_path: str = ""
        self.init_ui()

    def init_ui(self) -> None:
        """Constructs the add unit modal interface."""
        self.setWindowTitle("Add New Fleet Unit")
        self.setFixedSize(460, 580)
        self.setStyleSheet("background-color: #1E1E2E; color: #CDD6F4;")

        layout = QVBoxLayout(self)
        form_layout = QFormLayout()

        self.txt_vid = QLineEdit()
        self.txt_prov = QLineEdit()
        self.txt_make = QLineEdit()
        self.txt_model = QLineEdit()
        self.txt_year = QLineEdit()
        self.txt_vin = QLineEdit()
        self.txt_plate = QLineEdit()
        self.txt_state = QLineEdit()
        self.cmb_cam = QComboBox()
        self.cmb_cam.addItems(["No", "Yes"])

        self.txt_reg = DatePickerEdit(placeholder="YYYY-MM-DD", date_format="yyyy-MM-dd", default_today=False)
        self.txt_ins = DatePickerEdit(placeholder="YYYY-MM-DD", date_format="yyyy-MM-dd", default_today=False)
        self.txt_ret = DatePickerEdit(placeholder="YYYY-MM-DD (Rentals Only)", date_format="yyyy-MM-dd", default_today=False)

        # PAVE Intake File Picker
        pave_widget = QWidget()
        pave_layout = QHBoxLayout(pave_widget)
        pave_layout.setContentsMargins(0, 0, 0, 0)
        pave_layout.setSpacing(6)

        self.lbl_pave_status = QLabel("No file attached")
        self.lbl_pave_status.setStyleSheet("color: #A6ADC8; font-size: 11px;")
        
        btn_browse_pave = QPushButton("📎 Attach")
        btn_browse_pave.setFixedHeight(30)
        btn_browse_pave.setFixedWidth(80)
        btn_browse_pave.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_browse_pave.setStyleSheet("background-color: #313244; color: #89B4FA; border-radius: 4px; font-weight: bold;")
        btn_browse_pave.clicked.connect(self.select_pave_file)

        pave_layout.addWidget(self.lbl_pave_status, stretch=1)
        pave_layout.addWidget(btn_browse_pave)

        text_inputs = [
            self.txt_vid, self.txt_prov, self.txt_make, self.txt_model,
            self.txt_year, self.txt_vin, self.txt_plate, self.txt_state,
            self.txt_reg, self.txt_ins, self.txt_ret
        ]
        for widget in text_inputs:
            widget.setFixedHeight(32)
            widget.setStyleSheet("""
                background-color: #313244; 
                color: #CDD6F4; 
                border: 1px solid #45475A; 
                border-radius: 5px; 
                padding-left: 8px;
            """)

        self.cmb_cam.setFixedHeight(32)
        self.cmb_cam.setStyleSheet("""
            QComboBox {
                background-color: #313244; 
                color: #CDD6F4; 
                border: 1px solid #45475A; 
                border-radius: 5px; 
                padding-left: 8px;
            }
        """)

        form_layout.addRow("Unit ID*:", self.txt_vid)
        form_layout.addRow("Provider:", self.txt_prov)
        form_layout.addRow("Make:", self.txt_make)
        form_layout.addRow("Model:", self.txt_model)
        form_layout.addRow("Year:", self.txt_year)
        form_layout.addRow("VIN:", self.txt_vin)
        form_layout.addRow("Plate #:", self.txt_plate)
        form_layout.addRow("State:", self.txt_state)
        form_layout.addRow("Camera Installed:", self.cmb_cam)
        form_layout.addRow("Registration Exp:", self.txt_reg)
        form_layout.addRow("Insurance Exp:", self.txt_ins)
        form_layout.addRow("Return Date:", self.txt_ret)
        form_layout.addRow("PAVE Intake:", pave_widget)

        layout.addLayout(form_layout)

        # Dialog Buttons
        btn_layout = QHBoxLayout()
        btn_save = QPushButton("💾 Save & Upload to Cloud")
        btn_save.setFixedHeight(35)
        btn_save.setStyleSheet("background-color: #A6E3A1; color: #11111B; font-weight: bold; border-radius: 6px;")
        btn_save.clicked.connect(self.save_unit)

        btn_cancel = QPushButton("Cancel")
        btn_cancel.setFixedHeight(35)
        btn_cancel.setStyleSheet("background-color: #45475A; color: #CDD6F4; border-radius: 6px;")
        btn_cancel.clicked.connect(self.reject)

        btn_layout.addWidget(btn_cancel)
        btn_layout.addWidget(btn_save)
        layout.addLayout(btn_layout)

    def select_pave_file(self) -> None:
        """Opens native file picker to attach a PAVE inspection document or photo."""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select PAVE Image/Document", "", "Documents & Images (*.pdf *.png *.jpg *.jpeg *.heic)"
        )
        if file_path:
            self.pave_source_path = file_path
            filename = os.path.basename(file_path)
            self.lbl_pave_status.setText(filename[:22] + "..." if len(filename) > 25 else filename)

    def save_unit(self) -> None:
        """Validates input, processes PAVE/QR cloud uploads, writes to Google Sheets, and updates local cache."""
        uid = self.txt_vid.text().strip()
        raw_vin = self.txt_vin.text().strip()
        vin = clean_vin(raw_vin)

        if not uid:
            QMessageBox.warning(self, "Validation Error", "Unit ID is required.")
            return

        pave_cloud_link = ""

        # 1. Compile & Upload PAVE File to FPD / PAVE Inspections
        if self.pave_source_path:
            ext = os.path.splitext(self.pave_source_path)[1].lower()
            date_str = datetime.now().strftime("%m-%d-%y")
            pave_dest_name = f"{uid}_PAVE_{date_str}.pdf"

            if ext == ".pdf":
                local_pave_pdf = self.pave_source_path
            else:
                paves_dir = str(get_app_data_directory() / "PAVES")
                local_pave_pdf = generate_pave_pdf(
                    unit_id=uid,
                    source_image_path=self.pave_source_path,
                    output_dir=paves_dir
                )

            if local_pave_pdf and os.path.exists(local_pave_pdf):
                pave_ok, pave_url, pave_err = upload_file_to_drive_sync(
                    local_filepath=local_pave_pdf,
                    drive_filename=pave_dest_name,
                    subfolder_name=SUBFOLDER_PAVE
                )
                if pave_ok:
                    pave_cloud_link = pave_url
                else:
                    QMessageBox.warning(self, "PAVE Upload Warning", f"Could not upload PAVE to Drive: {pave_err}")

        # 2. Automatically Generate and Upload Individual QR Label to FPD / QR Codes
        if vin:
            qr_filename = f"QR_Label_{uid}.pdf"
            export_grid_to_pdf([{"vehicle_id": uid, "vin": vin}], qr_filename, parent_widget=None)

        # 3. Build Unit Payload Dictionary
        unit_payload = {
            'vehicle_id': uid,
            'provider': self.txt_prov.text().strip(),
            'make': self.txt_make.text().strip(),
            'model': self.txt_model.text().strip(),
            'year': self.txt_year.text().strip(),
            'vin': vin,
            'plate': self.txt_plate.text().strip(),
            'state': self.txt_state.text().strip(),
            'camera_status': self.cmb_cam.currentText(),
            'registration': self.txt_reg.text().strip(),
            'insurance': self.txt_ins.text().strip(),
            'return_date': self.txt_ret.text().strip(),
            'pave_insp': pave_cloud_link,
            'status': 'Active',
            'mileage': 0,
            'service_interval': 7500
        }

        # 4. Save to Local SQLite Database Cache
        new_unit_df = pd.DataFrame([{k: [v] for k, v in unit_payload.items()}])
        self.db.save_vehicles_bulk(new_unit_df)

        # 5. Create / Update Isolated Google Sheet in FPD Folder
        sheet_ok, sheet_url, sheet_err = sync_unit_to_fpd_sheet(unit_payload)

        # 6. Display Completion Summary
        status_lines = [
            f"✅ Unit {uid} added successfully!",
            "",
            "• Local Cache: Updated",
            "• QR Label: Saved to FPD / QR Codes"
        ]
        if pave_cloud_link:
            status_lines.append("• PAVE Inspection: Saved to FPD / PAVE Inspections")
        if sheet_ok:
            status_lines.append(f"• Google Sheet: Synced ({FPD_SHEET_NAME})")
        else:
            status_lines.append(f"⚠️ Google Sheet Warning: {sheet_err}")

        QMessageBox.information(self, "Unit Intake Complete", "\n".join(status_lines))
        self.accept()


class MileageUpdateDialog(QDialog):
    """Modal dialog for quick inline mileage updates with validation."""

    def __init__(self, vehicle_id: str, current_mileage: int, parent=None):
        super().__init__(parent)
        self.vehicle_id = vehicle_id
        self.current_mileage = current_mileage
        self.new_mileage = current_mileage
        self.init_ui()

    def init_ui(self) -> None:
        """Constructs the mileage update modal interface."""
        self.setWindowTitle(f"Update Mileage — {self.vehicle_id}")
        self.setFixedSize(320, 180)
        self.setStyleSheet("background-color: #1E1E2E; color: #CDD6F4;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)

        lbl_info = QLabel(f"Current Mileage: {self.current_mileage:,} mi")
        lbl_info.setFont(QFont(get_default_font_family(), 10, QFont.Weight.Bold))
        layout.addWidget(lbl_info)

        lbl_input = QLabel("Enter New Mileage:")
        layout.addWidget(lbl_input)

        self.spin_mileage = QSpinBox()
        self.spin_mileage.setRange(0, 1000000)
        self.spin_mileage.setValue(self.current_mileage)
        self.spin_mileage.setFixedHeight(35)
        self.spin_mileage.setStyleSheet("""
            QSpinBox {
                background-color: #313244;
                color: #CDD6F4;
                border: 1px solid #45475A;
                border-radius: 6px;
                padding-left: 10px;
            }
        """)
        layout.addWidget(self.spin_mileage)

        btn_layout = QHBoxLayout()
        btn_save = QPushButton("Save Changes")
        btn_save.setFixedHeight(35)
        btn_save.setStyleSheet("background-color: #89B4FA; color: #11111B; font-weight: bold; border-radius: 6px;")
        btn_save.clicked.connect(self.validate_and_accept)

        btn_cancel = QPushButton("Cancel")
        btn_cancel.setFixedHeight(35)
        btn_cancel.setStyleSheet("background-color: #45475A; color: #CDD6F4; border-radius: 6px;")
        btn_cancel.clicked.connect(self.reject)

        btn_layout.addWidget(btn_cancel)
        btn_layout.addWidget(btn_save)
        layout.addLayout(btn_layout)

    def validate_and_accept(self) -> None:
        """Validates that new mileage does not regress backwards."""
        val = self.spin_mileage.value()
        if val < self.current_mileage:
            QMessageBox.warning(self, "Invalid Input", "Mileage cannot be decreased.")
            return
        self.new_mileage = val
        self.accept()


class FleetView(QWidget):
    """Main Fleet Command view widget displaying the active vehicle grid."""

    vehicle_selected = Signal(str)
    data_mutated = Signal()

    def __init__(self, db_manager: DatabaseManager, parent=None):
        super().__init__(parent)
        self.db = db_manager
        self.vehicles_df = pd.DataFrame()
        self.init_ui()
        self.refresh_data()

    def init_ui(self) -> None:
        """Constructs the Fleet Command layout, filters, and vehicle table widget."""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(15)

        # --- 1. HEADER BAR & CONTROLS ---
        header_layout = QHBoxLayout()
        lbl_title = QLabel("📊 Fleet Command Center")
        lbl_title.setFont(QFont(get_default_font_family(), 18, QFont.Weight.Bold))
        lbl_title.setStyleSheet("color: #CDD6F4;")
        header_layout.addWidget(lbl_title)

        header_layout.addStretch()

        self.btn_qr_menu = QPushButton("🖨️ QR Actions ▼")
        self.btn_qr_menu.setFixedHeight(35)
        self.btn_qr_menu.setStyleSheet("""
            QPushButton {
                background-color: #89B4FA; 
                color: #11111B; 
                font-weight: bold; 
                border-radius: 6px; 
                padding: 0 15px;
            }
            QPushButton::menu-indicator { image: none; }
        """)
        
        qr_menu = QMenu(self)
        qr_menu.setStyleSheet("""
            QMenu { background-color: #1E1E2E; color: #CDD6F4; border: 1px solid #45475A; border-radius: 6px; padding: 5px; }
            QMenu::item { padding: 8px 20px; border-radius: 4px; }
            QMenu::item:selected { background-color: #45475A; color: #89B4FA; }
        """)
        
        act_bulk = qr_menu.addAction("📦 Bulk Fleet Sheet (4x4 Grid)")
        act_selected = qr_menu.addAction("🔍 Generate for Selected Units")
        act_manual = qr_menu.addAction("✍️ Manual VIN / ID Input")
        
        act_bulk.triggered.connect(self.handle_bulk_qr_export)
        act_selected.triggered.connect(self.handle_selected_qr_export)
        act_manual.triggered.connect(self.handle_manual_qr_input)

        self.btn_qr_menu.setMenu(qr_menu)
        header_layout.addWidget(self.btn_qr_menu)

        btn_add_unit = QPushButton("➕ Add Unit")
        btn_add_unit.setFixedHeight(35)
        btn_add_unit.setStyleSheet("background-color: #A6E3A1; color: #11111B; font-weight: bold; border-radius: 6px; padding: 0 15px;")
        btn_add_unit.clicked.connect(self.open_add_unit_dialog)
        header_layout.addWidget(btn_add_unit)

        btn_refresh = QPushButton("🔄 Refresh Local Cache")
        btn_refresh.setFixedHeight(35)
        btn_refresh.setStyleSheet("background-color: #313244; color: #CDD6F4; border-radius: 6px; padding: 0 15px;")
        btn_refresh.clicked.connect(self.refresh_data)
        header_layout.addWidget(btn_refresh)

        main_layout.addLayout(header_layout)

        # --- 2. FILTER & SEARCH BAR ---
        filter_frame = QFrame()
        filter_frame.setStyleSheet("background-color: #1E1E2E; border-radius: 10px;")
        filter_layout = QHBoxLayout(filter_frame)
        filter_layout.setContentsMargins(15, 12, 15, 12)

        self.txt_search = QLineEdit()
        self.txt_search.setPlaceholderText("🔍 Search Unit #, VIN, or Plate...")
        self.txt_search.setFixedHeight(35)
        self.txt_search.setStyleSheet("""
            QLineEdit {
                background-color: #313244;
                color: #CDD6F4;
                border: 1px solid #45475A;
                border-radius: 6px;
                padding-left: 10px;
            }
        """)
        self.txt_search.textChanged.connect(self.apply_filters)
        filter_layout.addWidget(self.txt_search, stretch=2)

        self.cmb_status = QComboBox()
        self.cmb_status.addItems(["All Statuses", "Active", "Inactive", "Retired"])
        self.cmb_status.setFixedHeight(35)
        self.cmb_status.setStyleSheet("background-color: #313244; color: #CDD6F4; border-radius: 6px; padding-left: 8px;")
        self.cmb_status.currentIndexChanged.connect(self.apply_filters)
        filter_layout.addWidget(self.cmb_status, stretch=1)

        main_layout.addWidget(filter_frame)

        # --- 3. VEHICLES TABLE WIDGET ---
        self.table = QTableWidget()
        self.table.setColumnCount(10)
        self.table.setHorizontalHeaderLabels([
            "Unit ID", "Provider", "VIN", "Plate #", "State", 
            "Camera", "Mileage", "Service Status", "Restrictions", "Compliance / Return"
        ])
        
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setStretchLastSection(True)
        
        self.table.setColumnWidth(0, 80)
        self.table.setColumnWidth(1, 100)
        self.table.setColumnWidth(2, 160)
        self.table.setColumnWidth(3, 100)
        self.table.setColumnWidth(4, 60)
        self.table.setColumnWidth(5, 80)
        self.table.setColumnWidth(6, 110)
        self.table.setColumnWidth(7, 160)
        self.table.setColumnWidth(8, 120)
        self.table.setColumnWidth(9, 250)
        
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setStyleSheet("""
            QTableWidget { background-color: #1E1E2E; color: #CDD6F4; gridline-color: #313244; border: none; border-radius: 8px; }
            QHeaderView::section { background-color: #181825; color: #89B4FA; padding: 8px; font-weight: bold; border: none; border-right: 1px solid #313244; }
            QTableWidget::item:selected { background-color: #45475A; color: #89B4FA; }
        """)
        self.table.cellDoubleClicked.connect(self.handle_cell_double_click)
        main_layout.addWidget(self.table)

    def refresh_data(self) -> None:
        """Loads vehicle records from SQLite and updates the table view."""
        self.vehicles_df = self.db.get_all_vehicles()
        self.apply_filters()

    def handle_bulk_qr_export(self) -> None:
        """Exports all fleet units into a 4x4 grid printable PDF."""
        df = self.db.get_all_vehicles()
        if df.empty:
            QMessageBox.warning(self, "No Units", "No vehicles found in local cache.")
            return

        items = [{"vehicle_id": str(row.get('vehicle_id', '')), "vin": str(row.get('vin', ''))} for _, row in df.iterrows()]
        export_grid_to_pdf(items, "Fleet_QR_Codes_Bulk_4x4.pdf", self)

    def handle_selected_qr_export(self) -> None:
        """Exports currently selected table rows into a grid printable PDF."""
        selected_rows = self.table.selectionModel().selectedRows()
        if not selected_rows:
            QMessageBox.warning(self, "Selection Required", "Please select one or more rows first.")
            return

        items = []
        for index in selected_rows:
            row_idx = index.row()
            item_vid = self.table.item(row_idx, 0)
            item_vin = self.table.item(row_idx, 2)
            vid = item_vid.text() if item_vid else ""
            vin = item_vin.text() if item_vin else ""
            items.append({"vehicle_id": vid, "vin": vin})

        export_grid_to_pdf(items, "Fleet_QR_Codes_Selected.pdf", self)

    def handle_manual_qr_input(self) -> None:
        """Prompts manually for Vehicle ID and VIN to compile a label."""
        vid, ok1 = QInputDialog.getText(self, "Manual QR Input", "Enter Vehicle ID (e.g. VAN-88):")
        if not ok1 or not vid.strip():
            return

        vin, ok2 = QInputDialog.getText(self, "Manual QR Input", f"Enter 17-character VIN for {vid.strip()}:")
        if not ok2 or not vin.strip():
            return

        sanitized_vin = clean_vin(vin)
        export_grid_to_pdf([{"vehicle_id": vid.strip(), "vin": sanitized_vin}], f"QR_Label_{vid.strip()}.pdf", self)

    def open_add_unit_dialog(self) -> None:
        """Opens modal dialog for adding a new unit."""
        dialog = AddUnitDialog(self.db, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.refresh_data()
            self.data_mutated.emit()

    def apply_filters(self) -> None:
        """Filters cached DataFrame and renders rows with compliance badges."""
        if self.vehicles_df.empty:
            self.table.setRowCount(0)
            return

        df = self.vehicles_df.copy()
        query = self.txt_search.text().strip().lower()
        if query:
            df = df[
                df['vehicle_id'].astype(str).str.lower().str.contains(query, na=False) |
                df['vin'].astype(str).str.lower().str.contains(query, na=False) |
                df['plate'].astype(str).str.lower().str.contains(query, na=False)
            ]

        stat = self.cmb_status.currentText()
        if stat != "All Statuses":
            df = df[df['status'] == stat]

        self.table.setRowCount(len(df))
        today = datetime.today().date()

        for row_idx, (_, row_data) in enumerate(df.iterrows()):
            vid = str(row_data.get('vehicle_id', ''))
            prov = str(row_data.get('provider', ''))
            vin = str(row_data.get('vin', ''))
            plate = str(row_data.get('plate', ''))
            state = str(row_data.get('state', ''))
            camera = str(row_data.get('camera_status', 'No'))
            
            raw_mil = str(row_data.get('mileage', 0)).replace(',', '').split('.')[0]
            mileage = int(raw_mil) if raw_mil.isdigit() else 0

            raw_last_a = str(row_data.get('last_a_service', 0)).replace(',', '').split('.')[0]
            last_a = int(raw_last_a) if raw_last_a.isdigit() else 0

            raw_int = str(row_data.get('service_interval', 7500)).split('.')[0]
            interval = int(raw_int) if raw_int.isdigit() else 7500

            ret_date_str = str(row_data.get('return_date', ''))
            reg_val = str(row_data.get('registration', ''))
            ins_val = str(row_data.get('insurance', ''))

            # PM Status Calculation
            diff = mileage - last_a
            if diff >= interval:
                svc_status = f"🔴 {diff - interval:,}m Overdue"
            elif diff >= (interval - 500):
                svc_status = f"🟡 {interval - diff:,}m Due Soon"
            else:
                svc_status = f"🟢 {interval - diff:,}m Left"

            # Compliance Tracker Logic
            is_critical = False
            is_warning = False
            tooltip_lines = []

            if prov in ["Uhaul", "Budget", "Enterprise", "Other"] and ret_date_str:
                try:
                    ret_date = datetime.strptime(ret_date_str.split(' ')[0], "%Y-%m-%d").date()
                    delta = (ret_date - today).days
                    if delta < 0:
                        is_critical = True
                        tooltip_lines.append(f"🚨 OVERDUE: Return was {abs(delta)} days ago ({ret_date_str})")
                    elif delta <= 2:
                        is_warning = True
                        tooltip_lines.append(f"⚠️ RETURN SOON: Due in {delta} days ({ret_date_str})")
                    else:
                        tooltip_lines.append(f"ℹ️ Return Date: {delta} days left ({ret_date_str})")
                except ValueError:
                    tooltip_lines.append(f"ℹ️ Return Date: {ret_date_str}")

            for doc_name, doc_data in [("Registration", reg_val), ("Insurance", ins_val)]:
                if doc_data and doc_data not in ['Unknown', 'Clear', 'OK']:
                    try:
                        doc_date = datetime.strptime(doc_data.split(' ')[0], "%Y-%m-%d").date()
                        doc_delta = (doc_date - today).days
                        if doc_delta < 0:
                            is_critical = True
                            tooltip_lines.append(f"🚨 EXPIRED {doc_name}: {abs(doc_delta)} days ago ({doc_data})")
                        elif doc_delta <= 30:
                            is_warning = True
                            tooltip_lines.append(f"⚠️ EXPIRING {doc_name}: In {doc_delta} days ({doc_data})")
                        else:
                            tooltip_lines.append(f"✅ {doc_name}: Valid ({doc_data})")
                    except ValueError:
                        tooltip_lines.append(f"ℹ️ {doc_name}: {doc_data}")

            if is_critical:
                comp_item = QTableWidgetItem("🚨 CRITICAL")
                comp_item.setForeground(QColor("#F38BA8"))
            elif is_warning:
                comp_item = QTableWidgetItem("⚠️ WARNING")
                comp_item.setForeground(QColor("#F9E2AF"))
            else:
                comp_item = QTableWidgetItem("✅ Compliant")
                comp_item.setForeground(QColor("#A6E3A1"))
                if not tooltip_lines:
                    tooltip_lines.append("All compliance checks passed.")

            font = comp_item.font()
            font.setUnderline(True)
            comp_item.setFont(font)
            comp_item.setToolTip("\n".join(tooltip_lines))

            # Populate row
            self.table.setItem(row_idx, 0, QTableWidgetItem(vid))
            self.table.setItem(row_idx, 1, QTableWidgetItem(prov))
            self.table.setItem(row_idx, 2, QTableWidgetItem(vin))
            self.table.setItem(row_idx, 3, QTableWidgetItem(plate))
            self.table.setItem(row_idx, 4, QTableWidgetItem(state))

            item_cam = QTableWidgetItem(camera)
            item_cam.setForeground(QColor("#A6E3A1") if camera.lower() in ['yes', 'y'] else QColor("#F38BA8"))
            self.table.setItem(row_idx, 5, item_cam)

            item_mil = QTableWidgetItem(f"{mileage:,} mi")
            item_mil.setForeground(QColor("#89B4FA"))
            self.table.setItem(row_idx, 6, item_mil)

            self.table.setItem(row_idx, 7, QTableWidgetItem(svc_status))
            self.table.setItem(row_idx, 8, QTableWidgetItem(str(row_data.get('restrictions', 'Clear'))))
            self.table.setItem(row_idx, 9, comp_item)

    def handle_cell_double_click(self, row: int, col: int) -> None:
        """Routes double-clicks: edits mileage if in col 6, else opens profile."""
        item_vid = self.table.item(row, 0)
        vid = item_vid.text() if item_vid else ""

        if col == 6:  # Mileage Column
            item_mil = self.table.item(row, 6)
            raw_str = (item_mil.text() if item_mil else "").replace(" mi", "").replace(",", "")
            current_mil = int(raw_str) if raw_str.isdigit() else 0
            dialog = MileageUpdateDialog(vid, current_mil, self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self.db.update_vehicle_mileage(vid, dialog.new_mileage)
                self.refresh_data()
                self.data_mutated.emit()
        else:
            self.vehicle_selected.emit(vid)