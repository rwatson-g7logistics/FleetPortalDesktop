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
from utils.qr_helper import export_grid_to_pdf, QRGeneratorDialog
from utils.vin_validator import validate_vin, clean_vin
from utils.pave import generate_pave_pdf
from utils.date_picker import DatePickerEdit
from utils.rental_lifecycle import (
    evaluate_rental_compliance, ExtendRentalDialog, check_and_auto_retire_rentals
)
from utils.service_tracker import evaluate_vehicle_health
from utils.provider_sop import get_sop_for_provider

# --- CLOUD SYNC & FOLDER CONSTANTS ---
from cloud_sync import upload_file_to_drive_sync, sync_unit_to_fpd_sheet, push_unsynced_vehicles_to_cloud
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

        self.spin_intake_mileage = QSpinBox()
        self.spin_intake_mileage.setRange(0, 1000000)
        self.spin_intake_mileage.setValue(0)

        self.txt_year = QLineEdit()
        self.txt_year.setPlaceholderText("YYYY")

        self.txt_vin = QLineEdit()
        self.txt_vin.setMaxLength(17)
        self.txt_vin.setPlaceholderText("17-Character VIN (No I, O, Q)")
        self.txt_vin.textChanged.connect(lambda t: self.txt_vin.setText(t.upper()) if t != t.upper() else None)

        self.txt_plate = QLineEdit()
        self.txt_plate.setPlaceholderText("License Plate #")
        self.txt_plate.textChanged.connect(lambda t: self.txt_plate.setText(t.upper()) if t != t.upper() else None)

        self.txt_state = QLineEdit()
        self.txt_state.setPlaceholderText("State (e.g. NC)")
        self.txt_state.textChanged.connect(lambda t: self.txt_state.setText(t.upper()) if t != t.upper() else None)

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

        text_widgets = [self.txt_vid, self.txt_year, self.txt_vin, self.txt_plate, self.txt_state, self.spin_intake_mileage, self.txt_reg, self.txt_ins, self.txt_ret]
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
        form_layout.addRow("Intake Mileage*:", self.spin_intake_mileage)
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
        """Validates vehicle inputs, enforces uniqueness, generates QR/PAVE assets, and commits to cache and cloud."""
        raw_uid = self.txt_vid.text().strip()
        raw_vin = self.txt_vin.text().strip()
        vin = clean_vin(raw_vin)

        # --- 1. UNIT NUMBER VALIDATION & IDENTIFIER CONSTRUCTION ---
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
        clean_prov_tag = prov.lower().replace(' ', '_').replace('-', '_')
        vehicle_id = f"{clean_prov_tag}_{clean_unit_id}"

        # --- 2. DECOUPLED VIN VALIDATION ---
        selected_make = self.cmb_make.currentText().strip()
        is_valid_vin, vin, vin_error = validate_vin(self.txt_vin.text(), make=selected_make)
        if not is_valid_vin:
            QMessageBox.warning(self, "VIN Validation", vin_error)
            return

        # --- 3. DUPLICATE VALIDATION SAFEGUARDS (UNIT ID, VIN, PLATE) ---
        existing_df = self.db.get_all_vehicles()
        if not existing_df.empty:
            # Check Unit ID collision under the same provider
            dup_id = existing_df[existing_df['vehicle_id'].astype(str).str.lower() == vehicle_id.lower()]
            if not dup_id.empty:
                QMessageBox.warning(
                    self, 
                    "Duplicate Unit", 
                    f"Unit '{clean_unit_id}' already exists under provider '{prov}'!\n(Vehicle ID: {vehicle_id})"
                )
                return

            # Check VIN duplication
            dup_vin = existing_df[existing_df['vin'].astype(str).str.upper() == vin.upper()]
            if not dup_vin.empty:
                v_row = dup_vin.iloc[0]
                assigned_id = v_row.get('unit_id') or v_row.get('vehicle_id', 'Unknown')
                assigned_prov = v_row.get('provider', 'Unknown')
                QMessageBox.warning(
                    self, 
                    "Duplicate VIN", 
                    f"VIN '{vin}' is already registered to Unit {assigned_id} ({assigned_prov})!"
                )
                return

            # Check Plate duplication (if entered)
            plate_val = self.txt_plate.text().strip().upper()
            if plate_val:
                dup_plate = existing_df[existing_df['plate'].astype(str).str.upper() == plate_val]
                if not dup_plate.empty:
                    v_row = dup_plate.iloc[0]
                    assigned_id = v_row.get('unit_id') or v_row.get('vehicle_id', 'Unknown')
                    assigned_prov = v_row.get('provider', 'Unknown')
                    QMessageBox.warning(
                        self, 
                        "Duplicate License Plate", 
                        f"License Plate '{plate_val}' is already registered to Unit {assigned_id} ({assigned_prov})!"
                    )
                    return

        # --- 4. PAVE INTAKE DOCUMENT UPLOAD ---
        pave_cloud_link = ""
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

        # --- 5. CONSOLIDATED MASTER QR SHEET GENERATION ---
        if vin:
            all_units = self.db.get_all_vehicles()
            qr_roster = []
            if not all_units.empty:
                for _, r in all_units.iterrows():
                    v_vin = clean_vin(str(r.get('vin', '')))
                    v_uid = str(r.get('unit_id') or r.get('vehicle_id', '')).split('_')[-1]
                    if v_vin:
                        qr_roster.append({"vehicle_id": v_uid, "vin": v_vin})

            # Append the unit being created if not already in roster
            if not any(item['vin'] == vin for item in qr_roster):
                qr_roster.append({"vehicle_id": clean_unit_id, "vin": vin})

            # Sort roster numerically by Unit ID
            qr_roster.sort(key=lambda x: int(x['vehicle_id']) if str(x['vehicle_id']).isdigit() else 9999)

            master_qr_filename = "Master_Fleet_QR_Labels.pdf"
            export_grid_to_pdf(qr_roster, master_qr_filename, parent_widget=None)

        prov_sop = self.db.get_provider_sop(prov)
        oil_interval = int(prov_sop.get('oil_pm_interval', 7500))

        # --- 6. PAYLOAD CONSTRUCTION ---
        unit_payload = {
            'vehicle_id': vehicle_id,
            'unit_id': clean_unit_id,
            'unit_type': self.cmb_type.currentText().strip(),
            'provider': prov,
            'make': self.cmb_make.currentText().strip(),
            'model': self.cmb_model.currentText().strip(),
            'size': self.cmb_size.currentText().strip(),
            'year': self.txt_year.text().strip(),
            'vin': vin,
            'plate': self.txt_plate.text().strip().upper(),
            'state': self.txt_state.text().strip().upper(),
            'camera_status': self.cmb_cam.currentText(),
            'registration': self.txt_reg.text().strip(),
            'insurance': self.txt_ins.text().strip(),
            'return_date': self.txt_ret.text().strip(),
            'pave_insp': pave_cloud_link,
            'status': 'Active',
            'mileage': self.spin_intake_mileage.value()
        }

        # --- 7. SAVE TO LOCAL SQLITE CACHE & SYNC TO CLOUD SHEET ---
        new_unit_df = pd.DataFrame([unit_payload])
        self.db.save_vehicles_bulk(new_unit_df)

        sheet_ok, sheet_url, sheet_err = sync_unit_to_fpd_sheet(unit_payload)
        # If offline or cloud sync failed, queue mutation for background auto-push
        if not sheet_ok:
            self.db.enqueue_mutation(
                action_type="ADD_UNIT",
                target_id=vehicle_id,
                payload=unit_payload
            )

        # --- 8. SUMMARY NOTIFICATION & DIALOG ACCEPT ---
        status_lines = [
            f"✅ Unit {clean_unit_id} ({prov}) added successfully!",
            f"• Identifier: {vehicle_id}",
            f"• Vehicle: {unit_payload['make']} {unit_payload['model']} ({unit_payload['size']})",
            f"• Intake Mileage: {unit_payload['mileage']:,} mi",
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
    service_hub_requested = Signal(str)

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
        lbl_title = QLabel("📊 Fleet Overview")
        lbl_title.setFont(QFont(get_default_font_family(), 18, QFont.Weight.Bold))
        lbl_title.setStyleSheet("color: #CDD6F4;")
        header_layout.addWidget(lbl_title)

        header_layout.addStretch()

        # Dynamic Provider SOP Configurator Button
        btn_sop = QPushButton("⚙️ Provider SOPs")
        btn_sop.setFixedHeight(35)
        btn_sop.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_sop.setStyleSheet("""
            QPushButton {
                background-color: #313244; 
                color: #F9E2AF; 
                border: 1px solid #45475A;
                font-weight: bold; 
                border-radius: 6px; 
                padding: 0 14px;
            }
            QPushButton:hover {
                background-color: #45475A;
                color: #F5E0DC;
            }
        """)
        btn_sop.clicked.connect(self.open_sop_config_dialog)
        header_layout.addWidget(btn_sop)

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

        # --- 1B. KPI TELEMETRY BANNER ---
        kpi_frame = QFrame()
        kpi_frame.setStyleSheet("background-color: #181825; border: 1px solid #313244; border-radius: 8px;")
        kpi_layout = QHBoxLayout(kpi_frame)
        kpi_layout.setContentsMargins(16, 10, 16, 10)
        kpi_layout.setSpacing(24)

        self.lbl_kpi_health = QLabel("Fleet Health: —")
        self.lbl_kpi_health.setFont(QFont(get_default_font_family(), 12, QFont.Weight.Bold))
        self.lbl_kpi_health.setStyleSheet("color: #A6E3A1; border: none;")

        self.lbl_kpi_cameras = QLabel("Cameras Installed: —")
        self.lbl_kpi_cameras.setFont(QFont(get_default_font_family(), 12, QFont.Weight.Bold))
        self.lbl_kpi_cameras.setStyleSheet("color: #89B4FA; border: none;")

        self.lbl_kpi_rentals = QLabel("Active Rentals: —")
        self.lbl_kpi_rentals.setFont(QFont(get_default_font_family(), 12, QFont.Weight.Bold))
        self.lbl_kpi_rentals.setStyleSheet("color: #F9E2AF; border: none;")

        kpi_layout.addWidget(self.lbl_kpi_health)
        kpi_layout.addWidget(self.lbl_kpi_cameras)
        kpi_layout.addWidget(self.lbl_kpi_rentals)
        kpi_layout.addStretch()

        main_layout.addWidget(kpi_frame)

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
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
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
        self.update_kpi_banner()
        self.apply_filters()

    def update_kpi_banner(self) -> None:
        """Calculates live fleet health, camera compliance, and rental metrics."""
        if self.vehicles_df.empty:
            self.lbl_kpi_health.setText("Fleet Health: 0/0 (0%)")
            self.lbl_kpi_cameras.setText("Cameras: 0/0 (0%)")
            self.lbl_kpi_rentals.setText("Active Rentals: 0")
            return

        df = self.vehicles_df
        total_units = len(df)
        active_units = len(df[df['status'].astype(str).str.lower() == 'active'])
        health_pct = int((active_units / total_units) * 100) if total_units > 0 else 0

        # Cameras installed on active units
        active_df = df[df['status'].astype(str).str.lower() == 'active']
        cams_installed = len(active_df[active_df['camera_status'].astype(str).str.lower().isin(['yes', 'y'])])
        cam_pct = int((cams_installed / len(active_df)) * 100) if not active_df.empty else 0

        # Rentals count (Temp or rental provider)
        rental_providers = ["u-haul", "budget", "enterprise", "lmr", "hertz"]
        rentals_count = len(df[
            (df['unit_type'].astype(str).str.lower() == 'temp') |
            (df['provider'].astype(str).str.lower().isin(rental_providers))
        ])

        self.lbl_kpi_health.setText(f"Fleet Health: {active_units}/{total_units} Active ({health_pct}%)")
        self.lbl_kpi_cameras.setText(f"Cameras: {cams_installed}/{len(active_df)} Installed ({cam_pct}%)")
        self.lbl_kpi_rentals.setText(f"Active Rentals: {rentals_count}")

    def sync_from_cloud_with_feedback(self) -> None:
        """Pulls authoritative data from Google Sheets, updates SQLite, and shows status feedback."""
        from cloud_sync import pull_fpd_master_sheet

        self.btn_refresh.setEnabled(False)
        self.btn_refresh.setText("⏳ Syncing...")

        # Safeguard: Push offline local records upstream before overwriting SQLite cache
        push_unsynced_vehicles_to_cloud(self.db)
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

    def open_sop_config_dialog(self) -> None:
        """Opens modal dialog to customize vendor maintenance and reimbursement rules."""
        from utils.provider_sop import ProviderSOPEditDialog
        dialog = ProviderSOPEditDialog(self.db, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.refresh_data()

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

            # Multi-point Service Status Tracking (Oil, Tires, Brakes, Alignment)
            health_eval = evaluate_vehicle_health({str(k): v for k, v in row_data.items()}, self.db)
            svc_status = health_eval['badge']
            svc_color = health_eval['color']
            svc_tooltip = health_eval['tooltip']

            # Compliance Tracker: Standardized Return Date & Document Expiration for ALL Units
            tooltip_lines = []
            
            # 1. Return Date Flagging (Applies to both Fleet & Temp if a date is set)
            if ret_date_str and ret_date_str not in ['None', 'N/A', 'Clear', '', 'Unknown']:
                eval_res = evaluate_rental_compliance(ret_date_str)
                comp_badge = eval_res['badge']
                comp_color = eval_res['color']
                tooltip_lines.append(eval_res['tooltip'])
            else:
                comp_badge = "✅ Compliant"
                comp_color = "#A6E3A1"

            # 2. Registration and Insurance Expiration Tracking
            for doc_name, doc_data in [("Registration", reg_val), ("Insurance", ins_val)]:
                if doc_data and doc_data not in ['Unknown', 'Clear', 'OK', 'N/A']:
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
            item_mil.setFlags(item_mil.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row_idx, 6, item_mil)

            item_svc = QTableWidgetItem(svc_status)
            item_svc.setForeground(QColor(svc_color))
            item_svc.setToolTip(svc_tooltip)
            font_svc = item_svc.font()
            font_svc.setUnderline(True)
            item_svc.setFont(font_svc)
            self.table.setItem(row_idx, 7, item_svc)
            self.table.setItem(row_idx, 8, QTableWidgetItem(str(row_data.get('restrictions', 'Clear'))))
            self.table.setItem(row_idx, 9, comp_item)

    def handle_cell_click(self, row: int, col: int) -> None:
        """Routes single-clicks: opens service telemetry on col 7, rental extension on col 9."""
        item_vid = self.table.item(row, 0)
        if not item_vid:
            return
        vid = str(item_vid.data(Qt.ItemDataRole.UserRole) or item_vid.text()).strip()

        print(f"[CLICK DEBUG] Row={row}, Col={col}, VID={vid}")

        # Column 7: Service Status -> Open Dedicated Service Telemetry Hub
        if col == 7:
            print(f"[CLICK DEBUG] Emitting service_hub_requested for {vid}")
            self.service_hub_requested.emit(vid)
            return

        # Column 9: Compliance / Return Date
        if col == 9:
            matches = self.vehicles_df[self.vehicles_df['vehicle_id'] == vid]
            if not matches.empty:
                v_data = matches.iloc[0].to_dict()
                # Single-click opens the Unified Compliance Manager for any vehicle
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
                new_mil = dialog.new_mileage
                self.db.update_vehicle_mileage(vehicle_id, new_mil)
                
                # Push odometer change to Google Sheets so force-refresh won't overwrite it
                from cloud_sync import update_cloud_vehicle_mileage
                update_cloud_vehicle_mileage(vehicle_id, new_mil)

                self.refresh_data()
                self.data_mutated.emit()
        else:
            self.vehicle_selected.emit(vehicle_id)