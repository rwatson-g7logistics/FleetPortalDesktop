"""
views/fleet_view.py
-------------------
Fleet Command Center view module for G7 Fleet Portal Desktop.
Provides live search, multi-variable filtering, vehicle status indicators,
quick inline mileage updates, dynamic provider/make/model lookups, and unified QR label generation.
"""

import os
import pandas as pd
from datetime import datetime
from typing import Optional


# --- PYQT6 / PYSIDE6 IMPORTS ---
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, 
    QPushButton, QTableWidget, QTableWidgetItem, QComboBox, 
    QHeaderView, QDialog, QSpinBox, QMessageBox, QFrame, QFormLayout,
    QAbstractItemView, QFileDialog, QInputDialog, QScrollArea
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QColor

# --- UTILITY MODULE IMPORTS ---
from db_manager import DatabaseManager
from utils.platform_helper import get_default_font_family, get_app_data_directory
from utils.qr_helper import export_grid_to_pdf, clean_vin, QRGeneratorDialog
from utils.pave import generate_pave_pdf
from utils.date_picker import DatePickerEdit
from utils.rental_lifecycle import (
    evaluate_rental_compliance, ExtendRentalDialog, check_and_auto_retire_rentals
)

# --- CLOUD SYNC & FOLDER CONSTANTS ---
from cloud_sync import upload_file_to_drive_sync, sync_unit_to_fpd_sheet
from config import SUBFOLDER_PAVE, SUBFOLDER_QR_CODES, FPD_SHEET_NAME


# =====================================================================
# --- MAKE / MODEL LOOKUP REGISTRATION DIALOG ---
# =====================================================================

class AddMakeModelDialog(QDialog):
    """Modal dialog to register a new Make and Model combination."""

    def __init__(self, db_manager: DatabaseManager, parent=None):
        super().__init__(parent)
        self.db = db_manager
        self.setWindowTitle("Add Vehicle Make & Model")
        self.setFixedSize(380, 210)
        self.setStyleSheet("background-color: #1E1E2E; color: #CDD6F4;")
        self.init_ui()

    def init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        form = QFormLayout()

        self.cmb_existing_make = QComboBox()
        self.cmb_existing_make.setEditable(True)
        self.cmb_existing_make.setPlaceholderText("Select or type new Make...")
        self.cmb_existing_make.addItems(self.db.get_makes())

        self.txt_new_model = QLineEdit()
        self.txt_new_model.setPlaceholderText("e.g. Transit 350, MT45")

        for w in (self.cmb_existing_make, self.txt_new_model):
            w.setFixedHeight(32)
            w.setStyleSheet(
                "background-color: #313244; color: #CDD6F4; "
                "border: 1px solid #45475A; border-radius: 5px; padding-left: 8px;"
            )

        form.addRow("Make:", self.cmb_existing_make)
        form.addRow("Model:", self.txt_new_model)
        layout.addLayout(form)

        btns = QHBoxLayout()
        btn_save = QPushButton("Save Specification")
        btn_save.setFixedHeight(34)
        btn_save.setStyleSheet("background-color: #A6E3A1; color: #11111B; font-weight: bold; border-radius: 5px;")
        btn_save.clicked.connect(self.save)

        btn_cancel = QPushButton("Cancel")
        btn_cancel.setFixedHeight(34)
        btn_cancel.setStyleSheet("background-color: #45475A; color: #CDD6F4; border-radius: 5px;")
        btn_cancel.clicked.connect(self.reject)

        btns.addWidget(btn_cancel)
        btns.addWidget(btn_save)
        layout.addLayout(btns)

    def save(self) -> None:
        make = self.cmb_existing_make.currentText().strip()
        model = self.txt_new_model.text().strip()
        if not make or not model:
            QMessageBox.warning(self, "Validation Error", "Both Make and Model are required.")
            return
        self.db.add_make_model(make, model)
        self.accept()

class AddUnitDialog(QDialog):
    """Modal dialog to manually add a new unit with lookup dropdowns and cloud syncing."""

    def __init__(self, db_manager: DatabaseManager, parent=None):
        super().__init__(parent)
        self.db = db_manager
        self.pave_source_path: str = ""
        self.init_ui()

    def init_ui(self) -> None:
        self.setWindowTitle("Add New Fleet Unit")
        self.setFixedSize(540, 680)
        self.setStyleSheet("background-color: #1E1E2E; color: #CDD6F4;")

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(12)

        # Scrollable form container
        scroll_area = QScrollArea(self)
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        scroll_area.setStyleSheet("""
            QScrollArea {
                background-color: transparent;
                border: none;
            }
            QScrollBar:vertical {
                background-color: #181825;
                width: 10px;
                border-radius: 5px;
                margin: 0px;
            }
            QScrollBar::handle:vertical {
                background-color: #45475A;
                min-height: 25px;
                border-radius: 5px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #585B70;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
        """)

        scroll_content = QWidget()
        scroll_content.setStyleSheet("background-color: transparent;")
        form_layout = QFormLayout(scroll_content)
        form_layout.setContentsMargins(4, 4, 12, 8)
        form_layout.setVerticalSpacing(12)
        form_layout.setHorizontalSpacing(14)

        # 1. Unit ID
        self.txt_vid = QLineEdit()
        self.txt_vid.setPlaceholderText("e.g. 1, 42 (No leading 0)")

        # Provider Container (Type + Provider dropdowns side-by-side)
        self.cmb_type = QComboBox()
        self.cmb_type.addItems(["Fleet", "Temp"])
        self.cmb_type.currentTextChanged.connect(self.on_unit_type_changed)

        self.cmb_prov = QComboBox()
        self.refresh_providers()

        prov_widget = QWidget()
        prov_layout = QHBoxLayout(prov_widget)
        prov_layout.setContentsMargins(0, 0, 0, 0)
        prov_layout.setSpacing(8)
        prov_layout.addWidget(self.cmb_type, stretch=1)
        prov_layout.addWidget(self.cmb_prov, stretch=2)

        btn_add_prov = QPushButton("➕")
        btn_add_prov.setFixedSize(30, 32)
        btn_add_prov.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_add_prov.setStyleSheet("background-color: #313244; color: #89B4FA; font-weight: bold; border-radius: 5px;")
        btn_add_prov.clicked.connect(self.prompt_add_provider)
        prov_layout.addWidget(btn_add_prov)

        # Make & Model Container (Make + Model dropdowns + Add button)
        self.cmb_make = QComboBox()
        self.cmb_model = QComboBox()

        self.cmb_make.currentTextChanged.connect(self.on_make_changed)
        self.refresh_makes_and_models()

        make_widget = QWidget()
        make_layout = QHBoxLayout(make_widget)
        make_layout.setContentsMargins(0, 0, 0, 0)
        make_layout.setSpacing(8)
        make_layout.addWidget(self.cmb_make, stretch=1)
        make_layout.addWidget(self.cmb_model, stretch=1)

        if hasattr(self, 'prompt_add_make_model'):
            btn_add_make = QPushButton("➕")
            btn_add_make.setFixedSize(30, 32)
            btn_add_make.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_add_make.setStyleSheet("background-color: #313244; color: #89B4FA; font-weight: bold; border-radius: 5px;")
            btn_add_make.clicked.connect(self.prompt_add_make_model)
            make_layout.addWidget(btn_add_make)

        # 2. Size & Specifications
        self.cmb_size = QComboBox()
        self.cmb_size.addItems(["Standard", "High Roof", "Extended", "Box Truck"])

        self.txt_year = QLineEdit()
        self.txt_year.setPlaceholderText("YYYY")

        self.txt_vin = QLineEdit()
        self.txt_vin.setMaxLength(17)
        self.txt_vin.setPlaceholderText("17-Character VIN")

        self.txt_plate = QLineEdit()
        self.txt_plate.setPlaceholderText("License Plate #")

        self.txt_state = QLineEdit()
        self.txt_state.setPlaceholderText("State (e.g. NC)")

        self.cmb_cam = QComboBox()
        self.cmb_cam.addItems(["No", "Yes"])

        # 3. Dates
        self.txt_reg = DatePickerEdit(placeholder="YYYY-MM-DD", date_format="yyyy-MM-dd")
        self.txt_ins = DatePickerEdit(placeholder="YYYY-MM-DD", date_format="yyyy-MM-dd")
        self.txt_ret = DatePickerEdit(placeholder="YYYY-MM-DD", date_format="yyyy-MM-dd")

        # 4. PAVE Intake Upload Widget
        pave_widget = QWidget()
        pave_layout = QHBoxLayout(pave_widget)
        pave_layout.setContentsMargins(0, 0, 0, 0)
        pave_layout.setSpacing(8)

        self.lbl_pave_status = QLabel("No document attached")
        self.lbl_pave_status.setStyleSheet("color: #A6ADC8; font-size: 11px;")

        btn_browse_pave = QPushButton("📎 Attach PAVE")
        btn_browse_pave.setFixedHeight(30)
        btn_browse_pave.setFixedWidth(120)
        btn_browse_pave.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_browse_pave.setStyleSheet("background-color: #313244; color: #89B4FA; border-radius: 4px; font-weight: bold;")
        btn_browse_pave.clicked.connect(self.select_pave_file)

        pave_layout.addWidget(self.lbl_pave_status, stretch=1)
        pave_layout.addWidget(btn_browse_pave)

        # Apply standard field styling
        combo_style = """
            QComboBox {
                background-color: #313244;
                color: #CDD6F4;
                border: 1px solid #45475A;
                border-radius: 6px;
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
            border-radius: 6px;
            padding: 4px 10px;
            min-height: 32px;
            font-size: 13px;
        """

        combo_widgets = [self.cmb_type, self.cmb_prov, self.cmb_make, self.cmb_model, self.cmb_size, self.cmb_cam]
        for cb in combo_widgets:
            cb.setStyleSheet(combo_style)
            cb.setMaxVisibleItems(10)

        text_widgets = [self.txt_vid, self.txt_year, self.txt_vin, self.txt_plate, self.txt_state, self.txt_reg, self.txt_ins, self.txt_ret]
        for tw in text_widgets:
            tw.setStyleSheet(input_style)

        # Build Form Rows
        form_layout.addRow("Unit ID*:", self.txt_vid)
        form_layout.addRow("Unit Type*:", self.cmb_type)
        form_layout.addRow("Provider:", prov_widget)
        form_layout.addRow("Make:", make_widget)
        form_layout.addRow("Model:", self.cmb_model)
        form_layout.addRow("Vehicle Size*:", self.cmb_size)
        form_layout.addRow("Year:", self.txt_year)
        form_layout.addRow("VIN:", self.txt_vin)
        form_layout.addRow("Plate #:", self.txt_plate)
        form_layout.addRow("State:", self.txt_state)
        form_layout.addRow("Camera Installed:", self.cmb_cam)
        form_layout.addRow("Registration Exp:", self.txt_reg)
        form_layout.addRow("Insurance Exp:", self.txt_ins)
        form_layout.addRow("Return Date:", self.txt_ret)
        form_layout.addRow("PAVE Intake:", pave_widget)

        scroll_area.setWidget(scroll_content)
        main_layout.addWidget(scroll_area, stretch=1)

        # Action Buttons (Pinned to bottom)
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
        main_layout.addLayout(btn_layout)

    def on_unit_type_changed(self, unit_type: str) -> None:
        """Repopulates the provider dropdown whenever Unit Type changes."""
        self.refresh_providers()

    def refresh_providers(self, select_name: Optional[str] = None) -> None:
        """Fetches and displays providers strictly matching the active Unit Type."""
        current_type = self.cmb_type.currentText().strip()
        self.cmb_prov.blockSignals(True)
        self.cmb_prov.clear()
        providers = self.db.get_providers(provider_type=current_type)
        self.cmb_prov.addItems(providers)
        if select_name and select_name in providers:
            self.cmb_prov.setCurrentText(select_name)
        self.cmb_prov.blockSignals(False)

    def prompt_add_provider(self) -> None:
        """Adds a new vendor categorized under the active Unit Type."""
        current_type = self.cmb_type.currentText().strip()
        name, ok = QInputDialog.getText(
            self,
            f"Add {current_type} Provider",
            f"Enter New {current_type} Provider Name (e.g. {'Fleet-Lease' if current_type == 'Fleet' else 'Ryder'}):"
        )
        if ok and name.strip():
            clean_name = name.strip()
            self.db.add_provider(clean_name, provider_type=current_type)
            self.refresh_providers(select_name=clean_name)

    def refresh_makes_and_models(self) -> None:
        """Reloads Makes and cascades into Models."""
        current_make = self.cmb_make.currentText()
        self.cmb_make.blockSignals(True)
        self.cmb_make.clear()
        makes = self.db.get_makes()
        self.cmb_make.addItems(makes)
        if current_make in makes:
            self.cmb_make.setCurrentText(current_make)
        self.cmb_make.blockSignals(False)
        self.on_make_changed(self.cmb_make.currentText())

    def on_make_changed(self, make_name: str) -> None:
        """Cascades models when Make changes."""
        self.cmb_model.clear()
        if make_name:
            models = self.db.get_models_for_make(make_name)
            self.cmb_model.addItems(models)

    def prompt_add_make_model(self) -> None:
        """Opens modal to add Make/Model combination."""
        dialog = AddMakeModelDialog(self.db, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.refresh_makes_and_models()

    def select_pave_file(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select PAVE Image/Document", "", "Documents & Images (*.pdf *.png *.jpg *.jpeg *.heic)"
        )
        if file_path:
            self.pave_source_path = file_path
            filename = os.path.basename(file_path)
            self.lbl_pave_status.setText(filename[:22] + "..." if len(filename) > 25 else filename)
          
    
    def save_unit(self) -> None:
        raw_uid = self.txt_vid.text().strip()
        raw_vin = self.txt_vin.text().strip()
        vin = clean_vin(raw_vin)

        # --- REPLACE UNIT ID VALIDATION & PAYLOAD KEY WITH THIS: ---

        if not raw_uid:
            QMessageBox.warning(self, "Validation Error", "Unit Number is required.")
            return

        # Lock out leading zeros
        if raw_uid.startswith('0') and raw_uid != '0':
            QMessageBox.warning(
                self, 
                "Naming Rule", 
                "Unit numbers cannot start with '0' (e.g. use '1' instead of '001')."
            )
            return

        clean_unit_id = raw_uid.lstrip('0') or raw_uid
        prov = self.cmb_prov.currentText().strip()

        # Enforce exact 17-character VIN requirement
        if len(vin) != 17:
            QMessageBox.warning(
                self,
                "Invalid VIN",
                f"VIN must be exactly 17 characters.\n\nCurrent length: {len(vin)} characters\nEntered: '{vin}'"
            )
            return
        
        # Build deterministic Vehicle_ID: e.g. "merchants_1", "kingbee_42", "u-haul_8803"
        clean_prov_tag = prov.lower().replace(' ', '_').replace('-', '_')
        vehicle_id = f"{clean_prov_tag}_{clean_unit_id}"

        pave_cloud_link = ""

        # 1. PAVE File Upload
        if self.pave_source_path:
            ext = os.path.splitext(self.pave_source_path)[1].lower()
            date_str = datetime.now().strftime("%m-%d-%y")
            pave_dest_name = f"{vehicle_id}_PAVE_{date_str}.pdf"

            if ext == ".pdf":
                local_pave_pdf = self.pave_source_path
            else:
                paves_dir = str(get_app_data_directory() / "PAVES")
                local_pave_pdf = generate_pave_pdf(
                    unit_id=clean_unit_id,
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

        # 2. QR Code Generation
        if vin:
            qr_filename = f"QR_Label_{vehicle_id}.pdf"
            export_grid_to_pdf([{"vehicle_id": vehicle_id, "vin": vin}], qr_filename, parent_widget=None)

        # 3. Payload Construction
        unit_payload = {
            'vehicle_id': vehicle_id,
            'unit_id': clean_unit_id,
            'unit_type': self.cmb_type.currentText().strip(),
            'provider': self.cmb_prov.currentText().strip(),
            'make': self.cmb_make.currentText().strip(),
            'model': self.cmb_model.currentText().strip(),
            'size': self.cmb_size.currentText().strip(),
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

        # 4. Save to Local SQLite Cache & Cloud Sheet
        new_unit_df = pd.DataFrame([unit_payload])
        self.db.save_vehicles_bulk(new_unit_df)

        sheet_ok, sheet_url, sheet_err = sync_unit_to_fpd_sheet(unit_payload)

        # 5. Summary Message
        status_lines = [
            f"✅ Unit {vehicle_id} added successfully!",
            f"• Type: {unit_payload['unit_type']} | Provider: {unit_payload['provider']}",
            f"• Vehicle: {unit_payload['make']} {unit_payload['model']} ({unit_payload['size']})",
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

        # Unified QR Generator Button
        self.btn_qr = QPushButton("🖨️ QR Generator")
        self.btn_qr.setFixedHeight(35)
        self.btn_qr.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_qr.setStyleSheet("""
            QPushButton {
                background-color: #89B4FA; 
                color: #11111B; 
                font-weight: bold; 
                border-radius: 6px; 
                padding: 0 15px;
            }
            QPushButton:hover {
                background-color: #B4BEFE;
            }
        """)
        self.btn_qr.clicked.connect(self.open_qr_menu)
        header_layout.addWidget(self.btn_qr)

        btn_add_unit = QPushButton("➕ Add Unit")
        btn_add_unit.setFixedHeight(35)
        btn_add_unit.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_add_unit.setStyleSheet("background-color: #A6E3A1; color: #11111B; font-weight: bold; border-radius: 6px; padding: 0 15px;")
        btn_add_unit.clicked.connect(self.open_add_unit_dialog)
        header_layout.addWidget(btn_add_unit)

        self.btn_refresh = QPushButton("🔄 Refresh Cloud Cache")
        self.btn_refresh.setFixedHeight(35)
        self.btn_refresh.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_refresh.setStyleSheet("background-color: #313244; color: #CDD6F4; border-radius: 6px; padding: 0 15px;")
        self.btn_refresh.clicked.connect(self.sync_from_cloud_with_feedback)
        header_layout.addWidget(self.btn_refresh)

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
        self.table.cellClicked.connect(self.handle_cell_click)

    def refresh_data(self) -> None:
        """Runs automated lifecycle checks, loads vehicle records, and updates the table view."""
        check_and_auto_retire_rentals(self.db, parent_widget=self)
        self.vehicles_df = self.db.get_all_vehicles()
        self.apply_filters()

    def sync_from_cloud_with_feedback(self) -> None:
        """Pulls authoritative data from Google Sheets, updates SQLite, and shows status feedback."""
        from cloud_sync import pull_fpd_master_sheet

        self.btn_refresh.setEnabled(False)
        self.btn_refresh.setText("⏳ Syncing...")

        success, cloud_df, err = pull_fpd_master_sheet()

        self.btn_refresh.setEnabled(True)
        self.btn_refresh.setText("🔄 Refresh Cloud Cache")

        if success:
            self.db.replace_all_vehicles(cloud_df)
            self.refresh_data()
            QMessageBox.information(
                self,
                "Cloud Sync Complete",
                f"✅ Successfully synchronized with Google Sheets!\n\n"
                f"Active Units Loaded: {len(cloud_df)}"
            )
        else:
            self.refresh_data()
            QMessageBox.warning(
                self,
                "Cloud Sync Notice",
                f"⚠️ Could not pull latest changes from Google Drive.\n\n"
                f"Reason: {err}\n\n"
                f"Displaying local cache."
            )

    def open_qr_menu(self) -> None:
        """Opens the unified QR Generator modal."""
        dialog = QRGeneratorDialog(self.db, parent=self)
        dialog.exec()

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
            display_num = str(row_data.get('unit_id', '')) or vid.split('_')[-1]
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

            # Compliance Tracker Logic using rental lifecycle evaluator
            tooltip_lines = []
            is_rental = (
                str(row_data.get('unit_type', '')).strip() == 'Temp' or 
                prov in ["U-Haul", "Budget", "Enterprise", "LMR", "Hertz"]
            )

            if is_rental and ret_date_str:
                eval_res = evaluate_rental_compliance(ret_date_str)
                comp_badge = eval_res['badge']
                comp_color = eval_res['color']
                tooltip_lines.append(eval_res['tooltip'])
            else:
                comp_badge = "✅ Compliant"
                comp_color = "#A6E3A1"

            # Check registration and insurance expiration
            for doc_name, doc_data in [("Registration", reg_val), ("Insurance", ins_val)]:
                if doc_data and doc_data not in ['Unknown', 'Clear', 'OK']:
                    try:
                        doc_date = datetime.strptime(doc_data.split(' ')[0], "%Y-%m-%d").date()
                        doc_delta = (doc_date - today).days
                        if doc_delta < 0:
                            comp_badge = "🚨 EXPIRED"
                            comp_color = "#F38BA8"
                            tooltip_lines.append(f"🚨 EXPIRED {doc_name}: {abs(doc_delta)} days ago ({doc_data})")
                        elif doc_delta <= 30:
                            if comp_badge not in ["🚨 EXPIRED", "🚨 Due Tomorrow", "🚨 Return Due Today"]:
                                comp_badge = "⚠️ EXPIRING"
                                comp_color = "#F9E2AF"
                            tooltip_lines.append(f"⚠️ EXPIRING {doc_name}: In {doc_delta} days ({doc_data})")
                        else:
                            tooltip_lines.append(f"✅ {doc_name}: Valid ({doc_data})")
                    except ValueError:
                        tooltip_lines.append(f"ℹ️ {doc_name}: {doc_data}")

            comp_item = QTableWidgetItem(comp_badge)
            comp_item.setForeground(QColor(comp_color))
            font = comp_item.font()
            font.setUnderline(True)
            comp_item.setFont(font)
            comp_item.setToolTip("\n".join(tooltip_lines))

            # Populate row
            item_id = QTableWidgetItem(display_num)
            item_id.setData(Qt.ItemDataRole.UserRole, vid)
            self.table.setItem(row_idx, 0, item_id)
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

    def handle_cell_click(self, row: int, col: int) -> None:
        """Single click on column 9 (Compliance / Return) opens Extend Rental dialog."""
        if col == 9:
            item_vid = self.table.item(row, 0)
            vid = str(item_vid.data(Qt.ItemDataRole.UserRole) or item_vid.text() if item_vid else "")
            
            # Find matching vehicle dictionary
            matches = self.vehicles_df[self.vehicles_df['vehicle_id'] == vid]
            if not matches.empty:
                v_data = matches.iloc[0].to_dict()
                prov = str(v_data.get('provider', ''))
                unit_type = str(v_data.get('unit_type', ''))
                
                # Check if unit is a rental
                if unit_type == 'Temp' or prov in ["U-Haul", "Budget", "Enterprise", "LMR", "Hertz"]:
                    dialog = ExtendRentalDialog(self.db, v_data, is_retired=False, parent=self)
                    if dialog.exec() == QDialog.DialogCode.Accepted:
                        self.refresh_data()
                        self.data_mutated.emit()

    def handle_cell_double_click(self, row: int, col: int) -> None:
        """Routes double-clicks: edits mileage if in col 6, else opens profile."""
        item_vid = self.table.item(row, 0)
        # Pulls the exact "merchants_1" vehicle_id from stored item data
        vehicle_id = str(item_vid.data(Qt.ItemDataRole.UserRole) or item_vid.text() if item_vid else "")

        if col == 6:  # Mileage Column
            item_mil = self.table.item(row, 6)
            raw_str = (item_mil.text() if item_mil else "").replace(" mi", "").replace(",", "")
            current_mil = int(raw_str) if raw_str.isdigit() else 0
            dialog = MileageUpdateDialog(vehicle_id, current_mil, self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self.db.update_vehicle_mileage(vehicle_id, dialog.new_mileage)
                self.refresh_data()
                self.data_mutated.emit()
        else:
            self.vehicle_selected.emit(vehicle_id)