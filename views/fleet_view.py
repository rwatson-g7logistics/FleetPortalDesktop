"""
views/fleet_view.py
-------------------
Fleet Command Center view module for G7 Fleet Portal Desktop.
Provides live search, multi-variable filtering, vehicle status indicators,
and quick inline mileage updates.
"""

import pandas as pd
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, 
    QPushButton, QTableWidget, QTableWidgetItem, QComboBox, 
    QHeaderView, QDialog, QSpinBox, QMessageBox, QFrame, QFormLayout,
    QMenu, QInputDialog
)
from utils.qr_helper import export_grid_to_pdf, clean_vin
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QColor
from datetime import datetime

from db_manager import DatabaseManager
from utils.platform_helper import get_default_font_family


class AddUnitDialog(QDialog):
    """Modal dialog to manually add a new unit to the fleet."""

    def __init__(self, db_manager: DatabaseManager, parent=None):
        super().__init__(parent)
        self.db = db_manager
        self.init_ui()

    def init_ui(self) -> None:
        """Constructs the add unit modal interface."""
        self.setWindowTitle("Add New Fleet Unit")
        self.setFixedSize(400, 450)
        self.setStyleSheet("background-color: #1E1E2E; color: #CDD6F4;")

        layout = QVBoxLayout(self)
        form_layout = QFormLayout()

        self.txt_vid = QLineEdit()
        self.txt_make = QLineEdit()
        self.txt_model = QLineEdit()
        self.txt_vin = QLineEdit()
        self.txt_plate = QLineEdit()
        self.txt_state = QLineEdit()
        self.txt_prov = QLineEdit()
        self.cmb_cam = QComboBox()
        self.cmb_cam.addItems(["No", "Yes"])

        # Apply styling to text inputs only
        text_inputs = [self.txt_vid, self.txt_make, self.txt_model, self.txt_vin, self.txt_plate, self.txt_state, self.txt_prov]
        for widget in text_inputs:
            widget.setFixedHeight(35)
            widget.setStyleSheet("""
                background-color: #313244; 
                color: #CDD6F4; 
                border: 1px solid #45475A; 
                border-radius: 6px; 
                padding-left: 8px;
            """)

        # Apply specific styling to the ComboBox to fix the dropdown menu visibility
        self.cmb_cam.setFixedHeight(30)
        self.cmb_cam.setFixedWidth(75)
        self.cmb_cam.setStyleSheet("""
            QComboBox {
                background-color: #313244; 
                color: #CDD6F4; 
                border: 1px solid #45475A; 
                border-radius: 6px; 
                padding-left: 8px;
            }
            QComboBox QAbstractItemView {
                background-color: #1E1E2E;
                color: #CDD6F4;
                selection-background-color: #45475A;
                selection-color: #89B4FA;
                outline: none;
                border: 1px solid #45475A;
            }
        """)

        form_layout.addRow("Unit ID:", self.txt_vid)
        form_layout.addRow("Provider:", self.txt_prov)
        form_layout.addRow("Make:", self.txt_make)
        form_layout.addRow("Model:", self.txt_model)
        form_layout.addRow("VIN:", self.txt_vin)
        form_layout.addRow("Plate #:", self.txt_plate)
        form_layout.addRow("State:", self.txt_state)
        form_layout.addRow("Camera Installed:", self.cmb_cam)

        layout.addLayout(form_layout)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_save = QPushButton("💾 Save Unit")
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

    def save_unit(self) -> None:
        """Validates and packages new unit data into a DataFrame for the DB Manager."""
        vid = self.txt_vid.text().strip()
        if not vid:
            QMessageBox.warning(self, "Validation Error", "Unit ID is required.")
            return

        # Package as DataFrame to reuse the existing bulk save logic
        new_unit_df = pd.DataFrame([{
            'Vehicle_ID': vid,
            'Provider': self.txt_prov.text().strip(),
            'Make': self.txt_make.text().strip(),
            'Model': self.txt_model.text().strip(),
            'VIN': self.txt_vin.text().strip(),
            'Plate': self.txt_plate.text().strip(),
            'State': self.txt_state.text().strip(),
            'Camera Status': self.cmb_cam.currentText(),
            'Status': 'Active',
            'Location': 'WNC4',  # Defaulting location as it was removed from UI
            'Mileage': 0,
            'Service_Interval': 7500
        }])
        
        self.db.save_vehicles_bulk(new_unit_df)
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
        self.setWindowTitle(f"Update Mileage - {self.vehicle_id}")
        self.setFixedSize(320, 180)
        self.setStyleSheet("background-color: #1E1E2E; color: #CDD6F4;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)

        lbl_info = QLabel(f"Current Mileage: {self.current_mileage:,} mi")
        lbl_info.setFont(QFont(get_default_font_family(), 10, QFont.Bold))
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

    # Signal emitted when a vehicle row 'Open Profile' button is clicked
    vehicle_selected = Signal(str)

    def __init__(self, db_manager: DatabaseManager, parent=None):
        super().__init__(parent)
        self.db = db_manager
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
        lbl_title.setFont(QFont(get_default_font_family(), 18, QFont.Bold))
        lbl_title.setStyleSheet("color: #CDD6F4;")
        header_layout.addWidget(lbl_title)

        header_layout.addStretch()

        # QR Actions Dropdown Menu Button
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
        
        # Change from Stretch to Interactive to allow resizing and scrolling
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.horizontalHeader().setStretchLastSection(True) # Fills any leftover dead space on the right
        
        # Set clean default widths for each column (in pixels)
        self.table.setColumnWidth(0, 80)   # Unit ID
        self.table.setColumnWidth(1, 100)  # Provider
        self.table.setColumnWidth(2, 160)  # VIN
        self.table.setColumnWidth(3, 100)  # Plate #
        self.table.setColumnWidth(4, 60)   # State
        self.table.setColumnWidth(5, 80)   # Camera
        self.table.setColumnWidth(6, 110)  # Mileage
        self.table.setColumnWidth(7, 160)  # Service Status
        self.table.setColumnWidth(8, 120)  # Restrictions
        self.table.setColumnWidth(9, 250)  # Compliance / Return
        
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows) # Highlights the whole row on click
        self.table.setStyleSheet("""
            QTableWidget { background-color: #1E1E2E; color: #CDD6F4; gridline-color: #313244; border: none; border-radius: 8px; }
            QHeaderView::section { background-color: #181825; color: #89B4FA; padding: 8px; font-weight: bold; border: none; border-right: 1px solid #313244; }
            QTableWidget::item:selected { background-color: #45475A; color: #89B4FA; }
        """)
        main_layout.addWidget(self.table)

    def refresh_data(self) -> None:
        """Loads vehicle records from SQLite and updates the table view."""
        self.vehicles_df = self.db.get_all_vehicles()
        self.apply_filters()

    def handle_bulk_qr_export(self) -> None:
        """Exports all fleet units into a 4x4 grid printable PDF."""
        df = self.db.get_all_vehicles()
        if df.empty:
            QMessageBox.warning(self, "No Units", "No vehicles found in the local database cache.")
            return

        items = [{"vehicle_id": str(row.get('vehicle_id', '')), "vin": str(row.get('vin', ''))} for _, row in df.iterrows()]
        export_grid_to_pdf(items, "Fleet_QR_Codes_Bulk_4x4.pdf", self)

    def handle_selected_qr_export(self) -> None:
        """Exports currently selected table rows into a grid printable PDF."""
        selected_rows = self.table.selectionModel().selectedRows()
        if not selected_rows:
            QMessageBox.warning(self, "Selection Required", "Please select one or more rows in the fleet table first.")
            return

        items = []
        for index in selected_rows:
            row_idx = index.row()
            vid = self.table.item(row_idx, 0).text()
            vin = self.table.item(row_idx, 2).text()
            items.append({"vehicle_id": vid, "vin": vin})

        export_grid_to_pdf(items, "Fleet_QR_Codes_Selected.pdf", self)

    def handle_manual_qr_input(self) -> None:
        """Opens prompt dialogs to manually enter a Vehicle ID and VIN string."""
        vid, ok1 = QInputDialog.getText(self, "Manual QR Input", "Enter Vehicle ID (e.g., VAN-88):")
        if not ok1 or not vid.strip():
            return

        vin, ok2 = QInputDialog.getText(self, "Manual QR Input", f"Enter 17-character VIN for {vid.strip()}:")
        if not ok2 or not vin.strip():
            return

        sanitized_vin = clean_vin(vin)
        export_grid_to_pdf([{"vehicle_id": vid.strip(), "vin": sanitized_vin}], f"QR_Label_{vid.strip()}.pdf", self)
    
    def open_add_unit_dialog(self) -> None:
        """Opens the modal dialog for adding a new unit."""
        dialog = AddUnitDialog(self.db, self)
        if dialog.exec() == QDialog.Accepted:
            self.refresh_data()

    def apply_filters(self) -> None:
        if self.vehicles_df.empty:
            self.table.setRowCount(0)
            return

        df = self.vehicles_df.copy()

        query = self.txt_search.text().strip().lower()
        if query:
            df = df[
                df['vehicle_id'].str.lower().str.contains(query, na=False) |
                df['vin'].str.lower().str.contains(query, na=False) |
                df['plate'].str.lower().str.contains(query, na=False)
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
            mileage = int(row_data.get('mileage', 0))
            last_a = int(row_data.get('last_a_service', 0))
            interval = int(row_data.get('service_interval', 7500))
            
            # Compliance fields
            ret_date_str = str(row_data.get('return_date', ''))
            reg_val = str(row_data.get('registration', ''))
            ins_val = str(row_data.get('insurance', ''))

            # 1. Service Status Calculation
            diff = mileage - last_a
            if diff >= interval: svc_status = f"🔴 {diff - interval:,}m Overdue"
            elif diff >= (interval - 500): svc_status = f"🟡 {interval - diff:,}m Due Soon"
            else: svc_status = f"🟢 {interval - diff:,}m Left"

            # 2. Unified Compliance Tracker (Hover Tooltip Logic)
            is_critical = False
            is_warning = False
            tooltip_lines = []

            # A. Check Temp Unit Return Decay
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

            # B. Check Registration & Insurance (30-Day Warning Logic)
            for doc_name, doc_data in [("Registration", reg_val), ("Insurance", ins_val)]:
                if doc_data and doc_data not in ['Unknown', 'Clear', 'OK']:
                    try:
                        # Attempt to parse as date to calculate expiration
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
                        # If the cell just contains text (e.g. "Missing Card"), just display it
                        tooltip_lines.append(f"ℹ️ {doc_name}: {doc_data}")

            # C. Build the Compliance Badge
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

            # Apply underline to hint it is interactive, and inject the rich tooltip
            font = comp_item.font()
            font.setUnderline(True)
            comp_item.setFont(font)
            comp_item.setToolTip("\n".join(tooltip_lines))

            # 3. Render Table Rows
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

        self.table.cellDoubleClicked.connect(self.handle_cell_double_click)

    def handle_cell_double_click(self, row: int, col: int) -> None:
        """Routes double-clicks: edits mileage if in the mileage column, otherwise opens unit profile."""
        vid = self.table.item(row, 0).text()
        
        if col == 6:  # Mileage Column
            current_str = self.table.item(row, 6).text().replace(" mi", "").replace(",", "")
            current_mil = int(current_str) if current_str.isdigit() else 0
            dialog = MileageUpdateDialog(vid, current_mil, self)
            if dialog.exec() == QDialog.Accepted:
                # self.db.update_vehicle_mileage(vid, dialog.new_mileage)
                self.refresh_data()
        else:
            # Any other column opens the Vehicle Profile
            self.vehicle_selected.emit(vid)