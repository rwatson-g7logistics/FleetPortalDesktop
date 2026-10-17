"""
views/service_view.py
---------------------
Service Logging & Maintenance Entry View for G7 Fleet Portal Desktop.
Provides dynamic service categorization, shop/vendor selection, component wear tracking,
automatic inventory deduction, and direct Google Drive PDF upload.
"""

from typing import List, Dict, Any, Optional
from PySide6.QtWidgets import (
    QGridLayout, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QComboBox, QDoubleSpinBox, QSpinBox, QTextEdit,
    QCheckBox, QGroupBox, QFileDialog, QMessageBox, QFrame, QScrollArea
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont

from db_manager import DatabaseManager
from utils.platform_helper import get_app_data_directory, get_default_font_family
from utils.pdf_builder import create_service_report_pdf
from utils.date_picker import DatePickerEdit
from config import SUBFOLDER_SERVICE_REPORTS
from cloud_sync import upload_file_to_drive_sync
from utils.telemetry_sync import link_brake_spinboxes


class ServiceFormView(QWidget):
    """Interactive service logging form with dynamic tire inputs and auto-inventory triggers."""

    service_logged = Signal(str)
    cancel_requested = Signal()

    def __init__(self, db_manager: DatabaseManager, vehicle_data: Dict[str, Any], parent=None):
        super().__init__(parent)
        self.db = db_manager
        self.vehicle = vehicle_data
        self.selected_files: List[str] = []
        self.init_ui()

    def init_ui(self) -> None:
        """Constructs the scrollable service entry form."""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setStyleSheet("QScrollArea { border: none; background-color: #11111B; }")

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        # Header Title Bar
        header_bar = QHBoxLayout()
        lbl_title = QLabel(f"🛠️ Log New Service Event — {self.vehicle.get('vehicle_id', 'Unknown')}")
        lbl_title.setFont(QFont(get_default_font_family(), 16, QFont.Weight.Bold))
        lbl_title.setStyleSheet("color: #89B4FA;")
        header_bar.addWidget(lbl_title)
        header_bar.addStretch()

        btn_cancel_top = QPushButton("Cancel")
        btn_cancel_top.setFixedHeight(30)
        btn_cancel_top.setStyleSheet("background-color: #45475A; color: #CDD6F4; border-radius: 6px; padding: 0 15px;")
        btn_cancel_top.clicked.connect(self.cancel_requested.emit)
        header_bar.addWidget(btn_cancel_top)

        layout.addLayout(header_bar)

        # --- 1. CORE SERVICE METRICS ---
        grp_core = QGroupBox("1. Service Details & Cost")
        grp_core.setStyleSheet("""
            QGroupBox {
                color: #CDD6F4;
                font-weight: bold;
                border: 1px solid #313244;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 15px;
            }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; }
        """)
        core_layout = QVBoxLayout(grp_core)

        # Row A: Date Picker & Mileage
        row_a = QHBoxLayout()
        row_a.addWidget(QLabel("Service Date:"))
        
        self.txt_date = DatePickerEdit(placeholder="YYYY-MM-DD", date_format="yyyy-MM-dd", default_today=True)
        self.txt_date.setFixedHeight(35)
        self.txt_date.setStyleSheet("background-color: #313244; color: #CDD6F4; border-radius: 6px; padding-left: 8px;")
        row_a.addWidget(self.txt_date, stretch=1)

        row_a.addWidget(QLabel("Service Mileage:"))
        self.spin_mileage = QSpinBox()
        self.spin_mileage.setRange(0, 1000000)
        self.spin_mileage.setValue(int(self.vehicle.get('mileage', 0)))
        self.spin_mileage.setFixedHeight(35)
        self.spin_mileage.setStyleSheet("background-color: #313244; color: #CDD6F4; border-radius: 6px; padding-left: 8px;")
        row_a.addWidget(self.spin_mileage, stretch=1)

        core_layout.addLayout(row_a)

        # Row B: Service Type(s) Performed Container Frame
        svc_types_frame = QFrame()
        svc_types_frame.setStyleSheet("""
            QFrame {
                background-color: #181825;
                border: 1px solid #313244;
                border-radius: 8px;
            }
            QCheckBox {
                color: #CDD6F4;
                font-size: 13px;
                spacing: 8px;
                background: transparent;
                border: none;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
                border-radius: 4px;
                border: 1px solid #45475A;
                background-color: #313244;
            }
            QCheckBox::indicator:hover {
                border-color: #89B4FA;
            }
            QCheckBox::indicator:checked {
                background-color: #89B4FA;
                border-color: #89B4FA;
            }
        """)

        svc_grid = QGridLayout(svc_types_frame)
        svc_grid.setContentsMargins(14, 12, 14, 12)
        svc_grid.setVerticalSpacing(12)
        svc_grid.setHorizontalSpacing(20)

        # Checkbox Definitions
        self.chk_type_a = QCheckBox("A Service (Oil/Filter/Rotation)")
        self.chk_type_b = QCheckBox("B Service (Comprehensive)")
        self.chk_diagnostics = QCheckBox("General Diagnostics")
        self.chk_tires = QCheckBox("Tires")
        self.chk_brakes = QCheckBox("Brakes")
        self.chk_repair = QCheckBox("General Repair / Other")
        self.chk_tires.toggled.connect(self.toggle_tire_section)

        # Row 0: Scheduled PM & Diagnostics
        svc_grid.addWidget(self.chk_type_a, 0, 0)
        svc_grid.addWidget(self.chk_type_b, 0, 1)
        svc_grid.addWidget(self.chk_diagnostics, 0, 2)

        # Row 1: Wear Items & Repairs
        svc_grid.addWidget(self.chk_tires, 1, 0)
        svc_grid.addWidget(self.chk_brakes, 1, 1)
        svc_grid.addWidget(self.chk_repair, 1, 2)

        core_layout.addWidget(svc_types_frame)

        # Row C: Vendor, Location & Invoice Details
        row_c = QHBoxLayout()
        row_c.addWidget(QLabel("Vendor / Shop:"))
        self.cmb_vendor = QComboBox()
        self.populate_vendors()
        self.cmb_vendor.setFixedHeight(35)
        self.cmb_vendor.setStyleSheet("background-color: #313244; color: #CDD6F4; border-radius: 6px; padding-left: 8px;")
        row_c.addWidget(self.cmb_vendor, stretch=2)

        row_c.addWidget(QLabel("Location / Address:"))
        self.txt_location = QLineEdit()
        self.txt_location.setPlaceholderText("Shop address or On-Route location")
        self.txt_location.setFixedHeight(35)
        self.txt_location.setStyleSheet("background-color: #313244; color: #CDD6F4; border-radius: 6px; padding-left: 8px;")
        row_c.addWidget(self.txt_location, stretch=2)

        row_c.addWidget(QLabel("Invoice #:"))
        self.txt_invoice = QLineEdit()
        self.txt_invoice.setFixedHeight(35)
        self.txt_invoice.setStyleSheet("background-color: #313244; color: #CDD6F4; border-radius: 6px; padding-left: 8px;")
        row_c.addWidget(self.txt_invoice, stretch=1)

        row_c.addWidget(QLabel("Cost Type:"))
        self.cmb_payment_route = QComboBox()
        self.cmb_payment_route.addItems(["Provider", "Out of Pocket", "Insurance", "Warranty"])
        self.cmb_payment_route.setFixedHeight(35)
        self.cmb_payment_route.setStyleSheet("background-color: #313244; color: #CDD6F4; border-radius: 6px; padding-left: 8px;")
        row_c.addWidget(self.cmb_payment_route, stretch=1)

        row_c.addWidget(QLabel("Total Cost ($):"))
        self.spin_cost = QDoubleSpinBox()
        self.spin_cost.setRange(0.0, 50000.0)
        self.spin_cost.setDecimals(2)
        self.spin_cost.setFixedHeight(35)
        self.spin_cost.setStyleSheet("background-color: #313244; color: #CDD6F4; border-radius: 6px; padding-left: 8px;")
        row_c.addWidget(self.spin_cost, stretch=1)

        core_layout.addLayout(row_c)
        layout.addWidget(grp_core)

        # --- 2. COMPONENT WEAR & INSPECTION TELEMETRY ---
        grp_wear = QGroupBox("2. Component Wear & Inspection Telemetry")
        grp_wear.setStyleSheet(grp_core.styleSheet())
        wear_layout = QVBoxLayout(grp_wear)
        wear_layout.setSpacing(12)

        # A. 4-Corner Tread Depths (32nds)
        tread_frame = QFrame()
        tread_frame.setStyleSheet("background-color: #181825; border: 1px solid #313244; border-radius: 6px;")
        tread_layout = QHBoxLayout(tread_frame)
        tread_layout.setContentsMargins(12, 8, 12, 8)
        tread_layout.setSpacing(10)

        lbl_tread_title = QLabel("<b>Tread Depth (32nds):</b>")
        lbl_tread_title.setStyleSheet("color: #89B4FA; border: none;")
        tread_layout.addWidget(lbl_tread_title)

        spin_style = "background-color: #313244; color: #CDD6F4; border: 1px solid #45475A; border-radius: 4px; padding-left: 4px;"

        self.spin_tread_df = QSpinBox()
        self.spin_tread_pf = QSpinBox()
        self.spin_tread_dr = QSpinBox()
        self.spin_tread_pr = QSpinBox()

        for sp, name in [
            (self.spin_tread_df, "DF:"), (self.spin_tread_pf, "PF:"),
            (self.spin_tread_dr, "DR:"), (self.spin_tread_pr, "PR:")
        ]:
            sp.setRange(0, 20)
            sp.setValue(10)
            sp.setSuffix(" /32\"")
            sp.setFixedHeight(30)
            sp.setFixedWidth(75)
            sp.setStyleSheet(spin_style)
            lbl = QLabel(name)
            lbl.setStyleSheet("color: #CDD6F4; border: none; font-weight: bold;")
            tread_layout.addWidget(lbl)
            tread_layout.addWidget(sp)

        tread_layout.addStretch()
        wear_layout.addWidget(tread_frame)

        # B. Tire Replacement Details (Container toggled by "Tires" checkbox)
        self.frame_tire_replace = QFrame()
        self.frame_tire_replace.setStyleSheet("background-color: #181825; border: 1px dashed #45475A; border-radius: 6px;")
        self.frame_tire_replace.setVisible(False)
        tire_rep_lay = QHBoxLayout(self.frame_tire_replace)
        tire_rep_lay.setContentsMargins(12, 8, 12, 8)
        tire_rep_lay.setSpacing(12)

        lbl_rep_title = QLabel("<b>🛞 Replaced Tires:</b>")
        lbl_rep_title.setStyleSheet("color: #A6E3A1; border: none;")
        tire_rep_lay.addWidget(lbl_rep_title)

        self.spin_tire_cnt = QSpinBox()
        self.spin_tire_cnt.setRange(1, 4)
        self.spin_tire_cnt.setValue(2)
        self.spin_tire_cnt.setFixedHeight(30)
        self.spin_tire_cnt.setStyleSheet(spin_style)
        tire_rep_lay.addWidget(QLabel("Qty:"))
        tire_rep_lay.addWidget(self.spin_tire_cnt)

        self.chk_pos_df = QCheckBox("DF")
        self.chk_pos_pf = QCheckBox("PF")
        self.chk_pos_dr = QCheckBox("DR")
        self.chk_pos_pr = QCheckBox("PR")
        for pos in [self.chk_pos_df, self.chk_pos_pf, self.chk_pos_dr, self.chk_pos_pr]:
            pos.setStyleSheet("color: #CDD6F4; border: none;")
            tire_rep_lay.addWidget(pos)

        tire_rep_lay.addStretch()
        wear_layout.addWidget(self.frame_tire_replace)

        # C. Brake Life & Rotor Condition
        brake_frame = QFrame()
        brake_frame.setStyleSheet("background-color: #181825; border: 1px solid #313244; border-radius: 6px;")
        brake_layout = QHBoxLayout(brake_frame)
        brake_layout.setContentsMargins(12, 8, 12, 8)
        brake_layout.setSpacing(10)

        lbl_brake_title = QLabel("<b>Brakes & Rotors:</b>")
        lbl_brake_title.setStyleSheet("color: #89B4FA; border: none;")
        brake_layout.addWidget(lbl_brake_title)

        # Front Brakes
        self.spin_brake_f_mm = QSpinBox()
        self.spin_brake_f_mm.setRange(0, 20)
        self.spin_brake_f_mm.setValue(10)
        self.spin_brake_f_mm.setSuffix(" mm")
        self.spin_brake_f_mm.setFixedHeight(30)
        self.spin_brake_f_mm.setStyleSheet(spin_style)

        self.spin_brake_f_pct = QSpinBox()
        self.spin_brake_f_pct.setRange(0, 100)
        self.spin_brake_f_pct.setValue(90)
        self.spin_brake_f_pct.setSuffix(" %")
        self.spin_brake_f_pct.setFixedHeight(30)
        self.spin_brake_f_pct.setStyleSheet(spin_style)

        brake_layout.addWidget(QLabel("Front:"))
        brake_layout.addWidget(self.spin_brake_f_mm)
        brake_layout.addWidget(self.spin_brake_f_pct)

        # Rear Brakes
        self.spin_brake_r_mm = QSpinBox()
        self.spin_brake_r_mm.setRange(0, 20)
        self.spin_brake_r_mm.setValue(10)
        self.spin_brake_r_mm.setSuffix(" mm")
        self.spin_brake_r_mm.setFixedHeight(30)
        self.spin_brake_r_mm.setStyleSheet(spin_style)

        self.spin_brake_r_pct = QSpinBox()
        self.spin_brake_r_pct.setRange(0, 100)
        self.spin_brake_r_pct.setValue(90)
        self.spin_brake_r_pct.setSuffix(" %")
        self.spin_brake_r_pct.setFixedHeight(30)
        self.spin_brake_r_pct.setStyleSheet(spin_style)

        brake_layout.addWidget(QLabel("Rear:"))
        brake_layout.addWidget(self.spin_brake_r_mm)
        brake_layout.addWidget(self.spin_brake_r_pct)

        # Rotors
        self.cmb_rotors = QComboBox()
        self.cmb_rotors.addItems(["Good", "Turned / Resurfaced", "Grooved / Glazed", "Replaced", "Excessive Wear"])
        self.cmb_rotors.setFixedHeight(30)
        self.cmb_rotors.setStyleSheet(spin_style)
        brake_layout.addWidget(QLabel("Rotors:"))
        brake_layout.addWidget(self.cmb_rotors)

        brake_layout.addStretch()
        wear_layout.addWidget(brake_frame)

        # Wire Two-Way Bi-Directional MM <-> % Converters
        link_brake_spinboxes(self.spin_brake_f_mm, self.spin_brake_f_pct)
        link_brake_spinboxes(self.spin_brake_r_mm, self.spin_brake_r_pct)

        layout.addWidget(grp_wear)

        # --- 3. REPAIR DETAILS & ATTACHMENTS ---
        grp_details = QGroupBox("2. Technical Description & Files")
        grp_details.setStyleSheet(grp_core.styleSheet())
        details_layout = QVBoxLayout(grp_details)

        details_layout.addWidget(QLabel("Reported Issue (What went wrong?):"))
        self.txt_issue = QTextEdit()
        self.txt_issue.setFixedHeight(60)
        self.txt_issue.setStyleSheet("background-color: #313244; color: #CDD6F4; border-radius: 6px;")
        details_layout.addWidget(self.txt_issue)

        details_layout.addWidget(QLabel("Repair Performed (What was fixed/replaced?):"))
        self.txt_repair = QTextEdit()
        self.txt_repair.setFixedHeight(60)
        self.txt_repair.setStyleSheet("background-color: #313244; color: #CDD6F4; border-radius: 6px;")
        details_layout.addWidget(self.txt_repair)

        btn_files = QPushButton("📎 Attach Invoice PDFs / Photos")
        btn_files.setFixedHeight(35)
        btn_files.setStyleSheet("background-color: #45475A; color: #CDD6F4; border-radius: 6px;")
        btn_files.clicked.connect(self.attach_files)
        details_layout.addWidget(btn_files)

        self.lbl_files = QLabel("No files attached.")
        self.lbl_files.setStyleSheet("color: #A6ADC8; font-size: 11px;")
        details_layout.addWidget(self.lbl_files)

        layout.addWidget(grp_details)

        # --- 4. ACTION BUTTONS ---
        btn_box = QHBoxLayout()
        btn_cancel = QPushButton("Cancel")
        btn_cancel.setFixedHeight(45)
        btn_cancel.setFont(QFont(get_default_font_family(), 11, QFont.Weight.Bold))
        btn_cancel.setStyleSheet("background-color: #45475A; color: #CDD6F4; border-radius: 8px;")
        btn_cancel.clicked.connect(self.cancel_requested.emit)
        btn_box.addWidget(btn_cancel, stretch=1)

        btn_submit = QPushButton("💾 Save & Upload to Cloud")
        btn_submit.setFixedHeight(45)
        btn_submit.setFont(QFont(get_default_font_family(), 11, QFont.Weight.Bold))
        btn_submit.setStyleSheet("background-color: #A6E3A1; color: #11111B; border-radius: 8px;")
        btn_submit.clicked.connect(self.save_service_log)
        btn_box.addWidget(btn_submit, stretch=3)

        layout.addLayout(btn_box)

        scroll_area.setWidget(container)
        main_layout.addWidget(scroll_area)

    def toggle_tire_section(self, checked: bool) -> None:
        """Dynamically reveals tire replacement quantities and position selectors."""
        if hasattr(self, 'frame_tire_replace'):
            self.frame_tire_replace.setVisible(checked)

    def populate_vendors(self) -> None:
        """Loads vendor choices into the dropdown from local SQLite cache."""
        vendors = self.db.get_vendor_list()
        self.cmb_vendor.clear()
        self.cmb_vendor.addItems(vendors if vendors else ["In-House Shop", "Mavis Tire & Auto", "Take 5"])

    def attach_files(self) -> None:
        """Opens native OS file dialog for selecting invoice PDFs or repair photos."""
        files, _ = QFileDialog.getOpenFileNames(
            self, "Select Service Invoices/Photos", "", "Documents & Images (*.pdf *.png *.jpg *.jpeg *.heic)"
        )
        if files:
            self.selected_files = files
            self.lbl_files.setText(f"Attached {len(files)} file(s): " + ", ".join([f.split('/')[-1] for f in files]))

    def save_service_log(self) -> None:
        """Validates input, persists record, updates inventory, and uploads report PDF to Google Drive."""
        selected_types = []
        if self.chk_type_a.isChecked(): selected_types.append("A Service")
        if self.chk_type_b.isChecked(): selected_types.append("B Service")
        if self.chk_diagnostics.isChecked(): selected_types.append("Diagnostics")
        if self.chk_tires.isChecked(): selected_types.append("Tires")
        if self.chk_brakes.isChecked(): selected_types.append("Brakes")
        if self.chk_repair.isChecked(): selected_types.append("Repair / Other")

        svc_type_str = ", ".join(selected_types)
        invoice = self.txt_invoice.text().strip()
        issue = self.txt_issue.toPlainText().strip()
        repair = self.txt_repair.toPlainText().strip()

        # Input validation
        if not selected_types or not invoice or not issue or not repair:
            QMessageBox.critical(self, "Validation Error", "Service Type, Invoice #, Reported Issue, and Repair Performed are all mandatory.")
            return

        tire_cnt = self.spin_tire_cnt.value() if self.chk_tires.isChecked() else 0
        
        pos_list = []
        if self.chk_pos_df.isChecked(): pos_list.append("DF")
        if self.chk_pos_pf.isChecked(): pos_list.append("PF")
        if self.chk_pos_dr.isChecked(): pos_list.append("DR")
        if self.chk_pos_pr.isChecked(): pos_list.append("PR")
        pos_str = ", ".join(pos_list) if pos_list else "N/A"

        # Join selected checkboxes into comma-separated string
        svc_type_str = ", ".join(selected_types) if selected_types else "General Service"

        # Resolve vehicle dictionary reference safely
        v_dict = getattr(self, 'vehicle', None) or getattr(self, 'vehicle_data', {})

        # 1. Save to Local SQLite Cache & Mutation Queue
        service_data = {
            "vehicle_id": v_dict.get('vehicle_id', ''),
            "vin": v_dict.get('vin', ''),
            "date": self.txt_date.text().strip(),
            "service_type": svc_type_str,
            "mileage": self.spin_mileage.value(),
            "vendor": self.cmb_vendor.currentText(),
            "location": self.txt_location.text().strip() or "Commercial Shop",
            "invoice_num": invoice,
            "cost": self.spin_cost.value(),
            "payment_route": self.cmb_payment_route.currentText() if hasattr(self, 'cmb_payment_route') else "Provider",
            "notes": f"ISSUE: {issue}\nREPAIR: {repair}",
            "tire_count": tire_cnt,
            "tire_positions": pos_str,
            "tread_df": self.spin_tread_df.value(),
            "tread_pf": self.spin_tread_pf.value(),
            "tread_dr": self.spin_tread_dr.value(),
            "tread_pr": self.spin_tread_pr.value(),
            "brake_front_mm": self.spin_brake_f_mm.value(),
            "brake_front_pct": self.spin_brake_f_pct.value(),
            "brake_rear_mm": self.spin_brake_r_mm.value(),
            "brake_rear_pct": self.spin_brake_r_pct.value(),
            "rotor_condition": self.cmb_rotors.currentText()
        }
        self.db.save_service_record(service_data)

        # 2. Deduct from local inventory
        self.db.auto_deduct_inventory(
            service_types=svc_type_str,
            repair_text=f"{issue} {repair}",
            tire_count=tire_cnt,
            vehicle_make=self.vehicle.get('make', '')
        )

        # 3. Generate Local PDF Report
        report_dir = get_app_data_directory() / "Archived_Reports"
        report_dir.mkdir(exist_ok=True)
        
        safe_vid = self.vehicle.get('vehicle_id', 'UNK')
        safe_date = self.txt_date.text().strip().replace('/', '-')
        pdf_filename = f"ServiceReport_{safe_vid}_{safe_date}.pdf"
        local_pdf_path = str(report_dir / pdf_filename)
        
        try:
            create_service_report_pdf(service_data, self.selected_files, local_pdf_path)
        except Exception as e:
            QMessageBox.warning(self, "PDF Compilation Warning", f"Record saved, but local PDF build failed: {str(e)}")
            self.service_logged.emit(self.vehicle.get('vehicle_id', ''))
            return

        # 4. Upload to Google Drive: Unit Records / <vehicle_id> / Service / ShopRepairs
        from cloud_sync import upload_unit_file_to_drive_sync
        target_vid = str(v_dict.get('vehicle_id', '') or safe_vid)

        upload_ok, drive_link, upload_err = upload_unit_file_to_drive_sync(
            local_filepath=local_pdf_path,
            drive_filename=pdf_filename,
            vehicle_id=target_vid,
            sub_category="Service/ShopRepairs"
        )

        if upload_ok:
            QMessageBox.information(
                self, "Sync Complete",
                f"✅ Commercial service record saved & uploaded!\n\n"
                f"File: {pdf_filename}\n"
                f"Drive Folder: Unit Records / {target_vid} / Service / ShopRepairs\n"
                f"Link: {drive_link}"
            )
        else:
            QMessageBox.warning(
                self, "Drive Sync Warning",
                f"⚠️ Service logged to local cache, but Google Drive upload failed.\n\n"
                f"Details: {upload_err}\n\n"
                f"Local copy preserved at:\n{local_pdf_path}"
            )

        self.service_logged.emit(target_vid)