"""
views/unit_service_view.py
--------------------------
In-House Inspection & Telemetry Hub for G7 Fleet Portal Desktop.
Tracks 4-corner tire physical tread wear & Provider SOP reimbursement windows,
subsystem milestones (Oil, Brakes, Alignment), live repair taxonomy summaries,
and handles yard/road-call inspections with direct Google Drive archival.
"""

import os
from datetime import datetime
from typing import Dict, Any, Optional

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
    QFrame, QGridLayout, QDialog, QSpinBox, QComboBox, 
    QCheckBox, QRadioButton, QButtonGroup, QMessageBox, QLineEdit, QTextEdit
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QColor

from db_manager import DatabaseManager
from utils.platform_helper import get_default_font_family, get_app_data_directory
from utils.service_tracker import get_tire_position_telemetry, get_subsystem_milestones
from utils.telemetry_sync import link_brake_spinboxes
from utils.pdf_builder import create_service_report_pdf
from cloud_sync import upload_unit_file_to_drive_sync
from views.maintenance_table import MaintenanceHistoryWidget


class InHouseInspectionDialog(QDialog):
    """Full 4-Corner Yard and Road-Call Inspection Dialog with consumable parts deductions."""

    def __init__(self, db_manager: DatabaseManager, vehicle_id: str, focus_corner: Optional[str] = None, parent=None):
        super().__init__(parent)
        self.db = db_manager
        self.vehicle_id = vehicle_id
        self.clean_uid = vehicle_id.split('_')[-1]
        self.focus_corner = focus_corner

        with self.db.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT make, mileage FROM master_vehicles WHERE vehicle_id = ? OR vehicle_id LIKE ?", (self.vehicle_id, f"%_{self.clean_uid}"))
            row = cur.fetchone()
            self.vehicle_make = row['make'] if row else "Ford"
            self.cur_mileage = row['mileage'] if row else 0

        self.setWindowTitle(f"In-House Yard Inspection — Unit {self.clean_uid}")
        self.setFixedSize(540, 600)
        self.setStyleSheet("background-color: #1E1E2E; color: #CDD6F4;")
        self.init_ui()

    def init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        lbl_hdr = QLabel(f"🛠️ <b>In-House Safety & Wear Inspection: Unit {self.clean_uid}</b>")
        lbl_hdr.setFont(QFont(get_default_font_family(), 12, QFont.Weight.Bold))
        lbl_hdr.setStyleSheet("color: #89B4FA;")
        layout.addWidget(lbl_hdr)

        # 1. Location & Environment Container
        loc_box = QFrame()
        loc_box.setStyleSheet("background-color: #181825; border: 1px solid #313244; border-radius: 6px;")
        loc_lay = QVBoxLayout(loc_box)
        loc_lay.setContentsMargins(10, 8, 10, 8)
        loc_lay.setSpacing(6)

        radio_lay = QHBoxLayout()
        self.radio_yard = QRadioButton("🏢 On Yard")
        self.radio_route = QRadioButton("🚨 On Route (Road Call)")
        self.radio_yard.setChecked(True)
        self.radio_yard.setStyleSheet("color: #A6E3A1; font-weight: bold;")
        self.radio_route.setStyleSheet("color: #F9E2AF; font-weight: bold;")

        btn_grp = QButtonGroup(self)
        btn_grp.addButton(self.radio_yard)
        btn_grp.addButton(self.radio_route)
        radio_lay.addWidget(self.radio_yard)
        radio_lay.addWidget(self.radio_route)
        radio_lay.addStretch()
        loc_lay.addLayout(radio_lay)

        self.txt_loc_detail = QLineEdit()
        self.txt_loc_detail.setPlaceholderText("Road-Call Address") # Lets make this Required if On Route is selected
        self.txt_loc_detail.setFixedHeight(28)
        self.txt_loc_detail.setStyleSheet("background-color: #313244; color: #CDD6F4; border-radius: 4px; padding-left: 6px;")
        loc_lay.addWidget(self.txt_loc_detail)
        layout.addWidget(loc_box)

        # 2. Comprehensive 4-Corner Tire Grid
        tread_box = QFrame()
        tread_box.setStyleSheet("background-color: #181825; border: 1px solid #313244; border-radius: 6px;")
        tread_lay = QVBoxLayout(tread_box)
        tread_lay.setContentsMargins(10, 8, 10, 8)
        tread_lay.setSpacing(6)

        lbl_tread_title = QLabel("<b>🛞 4-Corner Tire Inspection (Tread Depth & Swaps):</b>")
        lbl_tread_title.setStyleSheet("color: #89B4FA;")
        tread_lay.addWidget(lbl_tread_title)

        grid_tires = QGridLayout()
        grid_tires.setSpacing(8)

        # Fetch current depths
        cur_t_data = get_tire_position_telemetry(self.vehicle_id, self.cur_mileage, self.db)
        self.corner_widgets = {}

        spin_style = "background-color: #313244; color: #CDD6F4; border: 1px solid #45475A; border-radius: 4px; padding-left: 4px;"
        coords = {'DF': (0, 0, "Driver Front [DF]"), 'PF': (0, 1, "Passenger Front [PF]"),
                  'DR': (1, 0, "Driver Rear [DR]"), 'PR': (1, 1, "Passenger Rear [PR]")}

        for pos, (r, c, name) in coords.items():
            cell_frame = QFrame()
            is_focused = (pos == self.focus_corner)
            cell_frame.setStyleSheet(
                f"background-color: #1E1E2E; border: 1px solid {'#89B4FA' if is_focused else '#313244'}; border-radius: 6px; padding: 4px;"
            )
            c_lay = QVBoxLayout(cell_frame)
            c_lay.setContentsMargins(6, 4, 6, 4)
            c_lay.setSpacing(3)

            lbl_pos_name = QLabel(f"<b>{name}</b>")
            lbl_pos_name.setStyleSheet("color: #CDD6F4; font-size: 10px; border: none;")

            input_row = QHBoxLayout()
            sp_depth = QSpinBox()
            sp_depth.setRange(0, 20)
            initial_depth = cur_t_data.get(pos, {}).get('tread_depth', 10)
            sp_depth.setValue(initial_depth if initial_depth > 0 else 10)
            sp_depth.setSuffix(" /32\"")
            sp_depth.setFixedHeight(26)
            sp_depth.setStyleSheet(spin_style)

            chk_rep = QCheckBox("Replaced")
            chk_rep.setStyleSheet("color: #A6E3A1; font-size: 10px; font-weight: bold; border: none;")
            chk_rep.toggled.connect(lambda chk, s=sp_depth: s.setValue(11 if chk else 10))

            input_row.addWidget(sp_depth)
            input_row.addWidget(chk_rep)

            c_lay.addWidget(lbl_pos_name)
            c_lay.addLayout(input_row)
            grid_tires.addWidget(cell_frame, r, c)

            self.corner_widgets[pos] = {'spin': sp_depth, 'chk': chk_rep}

        tread_lay.addLayout(grid_tires)
        layout.addWidget(tread_box)

        # 3. Consumables & Yard Repairs
        repair_box = QFrame()
        repair_box.setStyleSheet("background-color: #181825; border: 1px solid #313244; border-radius: 6px;")
        repair_lay = QVBoxLayout(repair_box)
        repair_lay.setContentsMargins(10, 8, 10, 8)
        repair_lay.setSpacing(6)

        self.chk_other_repairs = QCheckBox("Other Repairs Made / Parts Replaced")
        self.chk_other_repairs.setStyleSheet("color: #CDD6F4; font-weight: bold;")
        repair_lay.addWidget(self.chk_other_repairs)

        parts_row = QHBoxLayout()
        parts_row.addWidget(QLabel("Part:"))
        self.cmb_parts = QComboBox()
        self.cmb_parts.addItems(["None", "Wiper Blades", "Headlight/Bulb", "Engine Oil (Top-off)", "Coolant", "Air Filter"])
        self.cmb_parts.setFixedHeight(28)
        self.cmb_parts.setStyleSheet(spin_style)
        parts_row.addWidget(self.cmb_parts, stretch=2)

        parts_row.addWidget(QLabel("Qty:"))
        self.spin_parts_qty = QSpinBox()
        self.spin_parts_qty.setRange(0, 10)
        self.spin_parts_qty.setValue(0)
        self.spin_parts_qty.setFixedHeight(28)
        self.spin_parts_qty.setStyleSheet(spin_style)
        parts_row.addWidget(self.spin_parts_qty, stretch=1)
        repair_lay.addLayout(parts_row)

        self.chk_other_repairs.toggled.connect(lambda chk: self.cmb_parts.setEnabled(chk))
        self.cmb_parts.setEnabled(False)
        layout.addWidget(repair_box)

        # 4. Notes
        layout.addWidget(QLabel("Inspection & Repair Notes:"))
        self.txt_notes = QTextEdit()
        self.txt_notes.setFixedHeight(50)
        self.txt_notes.setPlaceholderText("Condition found, repairs completed, technician notes...")
        self.txt_notes.setStyleSheet("background-color: #181825; color: #CDD6F4; border: 1px solid #45475A; border-radius: 6px;")
        layout.addWidget(self.txt_notes)

        # Action Buttons
        btns = QHBoxLayout()
        btn_cancel = QPushButton("Cancel")
        btn_cancel.setFixedHeight(34)
        btn_cancel.setStyleSheet("background-color: #45475A; color: #CDD6F4; border-radius: 5px;")
        btn_cancel.clicked.connect(self.reject)

        btn_save = QPushButton("💾 Commit Inspection")
        btn_save.setFixedHeight(34)
        btn_save.setStyleSheet("background-color: #A6E3A1; color: #11111B; font-weight: bold; border-radius: 5px;")
        btn_save.clicked.connect(self.commit_entry)

        btns.addWidget(btn_cancel)
        btns.addWidget(btn_save)
        layout.addLayout(btns)

    def commit_entry(self) -> None:
        today_str = datetime.now().strftime("%Y-%m-%d")
        loc_type = "On Yard" if self.radio_yard.isChecked() else "On Route"
        loc_detail = self.txt_loc_detail.text().strip()
        location_record = f"{loc_type} ({loc_detail})" if loc_detail else loc_type

        replaced_positions = []
        depth_values = {}
        for pos, w in self.corner_widgets.items():
            depth_values[pos] = w['spin'].value()
            if w['chk'].isChecked():
                replaced_positions.append(pos)

        # Determine Service Title
        if replaced_positions:
            pos_joined = ", ".join(replaced_positions)
            svc_type = f"Tire Replacement ({pos_joined})"
            # Deduct inventory for replaced tires
            self.db.auto_deduct_inventory("Tires", "Tire Replacement", len(replaced_positions), self.vehicle_make)
        else:
            svc_type = "Yard Safety & Tread Audit"

        # Check unit tire cost from inventory
        tire_cost_total = 0.0
        if replaced_positions:
            with self.db.get_connection() as conn:
                cur = conn.cursor()
                cur.execute("SELECT notes FROM inventory WHERE category = 'Tires' AND item_name LIKE ?", (f"%{self.vehicle_make}%",))
                row = cur.fetchone()
                if row and row['notes']:
                    try:
                        unit_c = float(str(row['notes']).replace('$', '').strip())
                        tire_cost_total = unit_c * len(replaced_positions)
                    except ValueError:
                        tire_cost_total = 0.0

        notes_body = self.txt_notes.toPlainText().strip()
        part_name = self.cmb_parts.currentText()
        part_qty = self.spin_parts_qty.value()
        if self.chk_other_repairs.isChecked() and part_name != "None" and part_qty > 0:
            self.db.auto_deduct_inventory(part_name, part_name, part_qty, self.vehicle_make)
            svc_type += f", {part_name}"
            notes_body += f"\n• Consumables Replaced: {part_qty}x {part_name}"

        full_notes = f"[{location_record}] {notes_body}".strip()

        # Insert inspection record into SQLite service_logs (Marked as Out of Pocket)
        service_data = {
            "vehicle_id": self.vehicle_id,
            "vin": "",
            "date": today_str,
            "service_type": svc_type,
            "mileage": self.cur_mileage,
            "vendor": "In-House Shop",
            "location": location_record,
            "invoice_num": "IN-HOUSE",
            "cost": tire_cost_total,
            "notes": full_notes,
            "payment_route": "Out of Pocket",
            "tire_count": len(replaced_positions),
            "tire_positions": ", ".join(replaced_positions) if replaced_positions else "DF, PF, DR, PR",
            "tread_df": depth_values['DF'],
            "tread_pf": depth_values['PF'],
            "tread_dr": depth_values['DR'],
            "tread_pr": depth_values['PR'],
            "brake_front_mm": 0, "brake_front_pct": 0, "brake_rear_mm": 0, "brake_rear_pct": 0,
            "rotor_condition": "Good"
        }
        self.db.save_service_record(service_data)

        # Generate Inspection Slip & Upload to Service/InHouse/
        report_dir = get_app_data_directory() / "Archived_Reports"
        report_dir.mkdir(parents=True, exist_ok=True)
        slip_name = f"InHouse_Inspection_{self.clean_uid}_{today_str}.pdf"
        local_slip_path = str(report_dir / slip_name)

        try:
            create_service_report_pdf(service_data, [], local_slip_path)
            upload_unit_file_to_drive_sync(
                local_filepath=local_slip_path,
                drive_filename=slip_name,
                vehicle_id=self.vehicle_id,
                sub_category="Service/InHouse"
            )
        except Exception as e:
            print(f"[INSPECTION SLIP NOTICE] Cloud upload deferred: {e}")

        QMessageBox.information(
            self,
            "Inspection Logged",
            f"✅ Inspection saved for Unit {self.clean_uid}!\n"
            f"• Action: {svc_type}\n"
            f"• Location: {location_record}\n"
            f"• Cloud Archive: Unit Records / {self.vehicle_id} / Service / InHouse"
        )
        self.accept()


class BrakeInspectionDialog(QDialog):
    """Modal to record brake pad measurements (% and mm) and rotor condition."""

    def __init__(self, db_manager: DatabaseManager, vehicle_id: str, parent=None):
        super().__init__(parent)
        self.db = db_manager
        self.vehicle_id = vehicle_id
        self.clean_uid = vehicle_id.split('_')[-1]

        self.setWindowTitle(f"Brake & Rotor Audit — Unit {self.clean_uid}")
        self.setFixedSize(380, 290)
        self.setStyleSheet("background-color: #1E1E2E; color: #CDD6F4;")
        self.init_ui()

    def init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        lbl_hdr = QLabel(f"🛑 <b>Brake Inspection: Unit {self.clean_uid}</b>")
        lbl_hdr.setStyleSheet("font-size: 13px; color: #89B4FA;")
        layout.addWidget(lbl_hdr)

        spin_style = "background-color: #313244; color: #CDD6F4; border: 1px solid #45475A; border-radius: 4px; padding-left: 4px;"

        # Front Brakes
        f_row = QHBoxLayout()
        f_row.addWidget(QLabel("Front Pads:"))
        self.spin_f_mm = QSpinBox()
        self.spin_f_mm.setRange(0, 15)
        self.spin_f_mm.setValue(10)
        self.spin_f_mm.setSuffix(" mm")
        self.spin_f_mm.setStyleSheet(spin_style)

        self.spin_f_pct = QSpinBox()
        self.spin_f_pct.setRange(0, 100)
        self.spin_f_pct.setValue(83)
        self.spin_f_pct.setSuffix(" %")
        self.spin_f_pct.setStyleSheet(spin_style)

        f_row.addWidget(self.spin_f_mm)
        f_row.addWidget(self.spin_f_pct)
        layout.addLayout(f_row)

        # Rear Brakes
        r_row = QHBoxLayout()
        r_row.addWidget(QLabel("Rear Pads:"))
        self.spin_r_mm = QSpinBox()
        self.spin_r_mm.setRange(0, 15)
        self.spin_r_mm.setValue(10)
        self.spin_r_mm.setSuffix(" mm")
        self.spin_r_mm.setStyleSheet(spin_style)

        self.spin_r_pct = QSpinBox()
        self.spin_r_pct.setRange(0, 100)
        self.spin_r_pct.setValue(83)
        self.spin_r_pct.setSuffix(" %")
        self.spin_r_pct.setStyleSheet(spin_style)

        r_row.addWidget(self.spin_r_mm)
        r_row.addWidget(self.spin_r_pct)
        layout.addLayout(r_row)

        link_brake_spinboxes(self.spin_f_mm, self.spin_f_pct)
        link_brake_spinboxes(self.spin_r_mm, self.spin_r_pct)

        # Rotors
        rot_row = QHBoxLayout()
        rot_row.addWidget(QLabel("Rotors:"))
        self.cmb_rotors = QComboBox()
        self.cmb_rotors.addItems(["Good", "Turned / Resurfaced", "Grooved / Glazed", "Replaced", "Excessive Wear"])
        self.cmb_rotors.setStyleSheet(spin_style)
        rot_row.addWidget(self.cmb_rotors)
        layout.addLayout(rot_row)

        btns = QHBoxLayout()
        btn_cancel = QPushButton("Cancel")
        btn_cancel.setFixedHeight(34)
        btn_cancel.setStyleSheet("background-color: #45475A; color: #CDD6F4; border-radius: 5px;")
        btn_cancel.clicked.connect(self.reject)

        btn_save = QPushButton("💾 Commit Audit")
        btn_save.setFixedHeight(34)
        btn_save.setStyleSheet("background-color: #A6E3A1; color: #11111B; font-weight: bold; border-radius: 5px;")
        btn_save.clicked.connect(self.commit_entry)

        btns.addWidget(btn_cancel)
        btns.addWidget(btn_save)
        layout.addLayout(btns)

    def commit_entry(self) -> None:
        today_str = datetime.now().strftime("%Y-%m-%d")
        with self.db.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT mileage FROM master_vehicles WHERE vehicle_id = ? OR vehicle_id LIKE ?", (self.vehicle_id, f"%_{self.clean_uid}"))
            row = cur.fetchone()
            cur_mil = row['mileage'] if row else 0

        service_data = {
            "vehicle_id": self.vehicle_id,
            "vin": "",
            "date": today_str,
            "service_type": "Brake Inspection",
            "mileage": cur_mil,
            "vendor": "In-House Shop",
            "invoice_num": "IN-HOUSE",
            "cost": 0.0,
            "notes": f"In-Shop Audit: Front {self.spin_f_mm.value()}mm ({self.spin_f_pct.value()}%), Rear {self.spin_r_mm.value()}mm ({self.spin_r_pct.value()}%), Rotors: {self.cmb_rotors.currentText()}",
            "payment_route": "Out of Pocket",
            "tire_count": 0,
            "tire_positions": "N/A",
            "tread_df": 0, "tread_pf": 0, "tread_dr": 0, "tread_pr": 0,
            "brake_front_mm": self.spin_f_mm.value(),
            "brake_front_pct": self.spin_f_pct.value(),
            "brake_rear_mm": self.spin_r_mm.value(),
            "brake_rear_pct": self.spin_r_pct.value(),
            "rotor_condition": self.cmb_rotors.currentText()
        }
        self.db.save_service_record(service_data)

        report_dir = get_app_data_directory() / "Archived_Reports"
        report_dir.mkdir(parents=True, exist_ok=True)
        slip_name = f"InHouse_Brake_{self.clean_uid}_{today_str}.pdf"
        local_slip_path = str(report_dir / slip_name)

        try:
            create_service_report_pdf(service_data, [], local_slip_path)
            upload_unit_file_to_drive_sync(
                local_filepath=local_slip_path,
                drive_filename=slip_name,
                vehicle_id=self.vehicle_id,
                sub_category="Service/Inhouse"
            )
        except Exception as e:
            print(f"[BRAKE SLIP NOTICE] Local slip saved, cloud upload deferred: {e}")

        QMessageBox.information(
            self, "Brakes Logged", 
            f"✅ Brake audit saved successfully.\n• Cloud Archive: Unit Records / {self.vehicle_id} / Service / Inhouse"
        )
        self.accept()


class UnitServiceView(QWidget):
    """In-House Inspection & Telemetry Hub with dynamic cards and unified ledger."""

    back_requested = Signal()
    log_service_requested = Signal(dict)

    def __init__(self, db_manager: DatabaseManager, vehicle_id: str, parent=None):
        super().__init__(parent)
        self.db = db_manager
        self.vehicle_id = str(vehicle_id)
        self.clean_uid = self.vehicle_id.split('_')[-1]
        self.v_data = {}

        # DYNAMIC LABEL REGISTRY: Stores references so UI updates without reloading
        self.tire_card_labels = {}

        self.load_vehicle()
        self.init_ui()

    def load_vehicle(self) -> None:
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM master_vehicles 
                WHERE vehicle_id = ? OR vehicle_id = ? OR vehicle_id LIKE ?
            """, (self.vehicle_id, self.clean_uid, f"%_{self.clean_uid}"))
            row = cursor.fetchone()
            self.v_data = dict(row) if row else {'vehicle_id': self.vehicle_id, 'mileage': 0}

    def init_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(14)

        # 1. Header Bar
        hdr_layout = QHBoxLayout()
        btn_back = QPushButton("◀ Back to Fleet Overview")
        btn_back.setFixedHeight(34)
        btn_back.setStyleSheet("background-color: #45475A; color: #CDD6F4; font-weight: bold; border-radius: 6px; padding: 0 14px;")
        btn_back.clicked.connect(self.back_requested.emit)
        hdr_layout.addWidget(btn_back)

        hdr_layout.addSpacing(12)

        lbl_title = QLabel(f"🛠️ In-House Inspection & Telemetry — Unit {self.clean_uid}")
        lbl_title.setFont(QFont(get_default_font_family(), 16, QFont.Weight.Bold))
        lbl_title.setStyleSheet("color: #CDD6F4;")
        hdr_layout.addWidget(lbl_title)

        hdr_layout.addStretch()

        cur_mil = int(self.v_data.get('mileage', 0))
        self.lbl_odo = QLabel(f"Odometer: {cur_mil:,} mi")
        self.lbl_odo.setFont(QFont(get_default_font_family(), 13, QFont.Weight.Bold))
        self.lbl_odo.setStyleSheet("color: #89B4FA; padding-right: 10px;")
        hdr_layout.addWidget(self.lbl_odo)

        btn_inspect = QPushButton("📋 Yard Inspection")
        btn_inspect.setFixedHeight(34)
        btn_inspect.setStyleSheet("background-color: #89B4FA; color: #11111B; font-weight: bold; border-radius: 6px; padding: 0 14px;")
        btn_inspect.clicked.connect(lambda: self.open_tire_dialog(None))
        hdr_layout.addWidget(btn_inspect)

        btn_log = QPushButton("🛠️ Log Commercial Service")
        btn_log.setFixedHeight(34)
        btn_log.setStyleSheet("background-color: #A6E3A1; color: #11111B; font-weight: bold; border-radius: 6px; padding: 0 14px;")
        btn_log.clicked.connect(lambda: self.log_service_requested.emit(self.v_data))
        hdr_layout.addWidget(btn_log)

        main_layout.addLayout(hdr_layout)

        # 2. Main Analytics Cards
        cards_layout = QHBoxLayout()
        cards_layout.setSpacing(14)

        # --- LEFT: 4-CORNER TIRE MATRIX ---
        tire_frame = QFrame()
        tire_frame.setStyleSheet("background-color: #181825; border: 1px solid #313244; border-radius: 8px;")
        tire_layout = QVBoxLayout(tire_frame)
        tire_layout.setContentsMargins(14, 12, 14, 12)
        tire_layout.setSpacing(10)

        lbl_tire_hdr = QLabel("🛞 Tire Wear & Provider SOP Matrix (Two-Clock)")
        lbl_tire_hdr.setFont(QFont(get_default_font_family(), 11, QFont.Weight.Bold))
        lbl_tire_hdr.setStyleSheet("color: #89B4FA; border: none;")
        tire_layout.addWidget(lbl_tire_hdr)

        tire_grid = QGridLayout()
        tire_grid.setSpacing(10)

        coords = {'DF': (0, 0), 'PF': (0, 1), 'DR': (1, 0), 'PR': (1, 1)}
        for pos_code, (r, c) in coords.items():
            box = QFrame()
            box.setStyleSheet("background-color: #1E1E2E; border: 1px solid #45475A; border-radius: 6px; padding: 6px;")
            box_lay = QVBoxLayout(box)
            box_lay.setContentsMargins(8, 6, 8, 6)
            box_lay.setSpacing(3)

            lbl_pos = QLabel(f"<b>[{pos_code}]</b>")
            lbl_pos.setStyleSheet("color: #CDD6F4; font-size: 11px; border: none;")

            lbl_sop = QLabel("SOP: Calculating...")
            lbl_sop.setStyleSheet("color: #CDD6F4; font-size: 10px; border: none;")

            lbl_depth = QLabel("Tread: Calculating...")
            lbl_depth.setStyleSheet("color: #CDD6F4; font-size: 10px; border: none;")

            lbl_meta = QLabel("Date: N/A | Inv: —")
            lbl_meta.setStyleSheet("color: #89B4FA; font-size: 10px; border: none;")

            btn_audit = QPushButton("✏️ Audit / Replace")
            btn_audit.setFixedHeight(24)
            btn_audit.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_audit.setStyleSheet("background-color: #313244; color: #89B4FA; border: 1px solid #45475A; border-radius: 4px; font-size: 10px; font-weight: bold;")
            btn_audit.clicked.connect(lambda _, p=pos_code: self.open_tire_dialog(p))

            box_lay.addWidget(lbl_pos)
            box_lay.addWidget(lbl_sop)
            box_lay.addWidget(lbl_depth)
            box_lay.addWidget(lbl_meta)
            box_lay.addWidget(btn_audit)

            tire_grid.addWidget(box, r, c)
            # Store label references for live updates
            self.tire_card_labels[pos_code] = {'sop': lbl_sop, 'depth': lbl_depth, 'meta': lbl_meta}

        tire_layout.addLayout(tire_grid)
        cards_layout.addWidget(tire_frame, stretch=3)

        # --- RIGHT: BRAKE & SUBSYSTEM MILESTONES ---
        ms_frame = QFrame()
        ms_frame.setStyleSheet("background-color: #181825; border: 1px solid #313244; border-radius: 8px;")
        ms_layout = QVBoxLayout(ms_frame)
        ms_layout.setContentsMargins(14, 12, 14, 12)
        ms_layout.setSpacing(8)

        lbl_ms_hdr = QLabel("⚙️ Subsystem Lifecycle Milestones")
        lbl_ms_hdr.setFont(QFont(get_default_font_family(), 11, QFont.Weight.Bold))
        lbl_ms_hdr.setStyleSheet("color: #89B4FA; border: none;")
        ms_layout.addWidget(lbl_ms_hdr)

        # Oil Card
        box_oil = QFrame()
        box_oil.setStyleSheet("background-color: #1E1E2E; border: 1px solid #45475A; border-radius: 6px; padding: 6px;")
        lay_oil = QVBoxLayout(box_oil)
        lay_oil.setContentsMargins(8, 6, 8, 6)
        lay_oil.setSpacing(2)
        self.lbl_oil_main = QLabel("<b>Engine Oil (PM):</b> Loading...")
        self.lbl_oil_sub = QLabel("Date: N/A | Inv: —")
        self.lbl_oil_sub.setStyleSheet("color: #89B4FA; font-size: 10px; border: none;")
        lay_oil.addWidget(self.lbl_oil_main)
        lay_oil.addWidget(self.lbl_oil_sub)
        ms_layout.addWidget(box_oil)

        # Brake Card
        box_brk = QFrame()
        box_brk.setStyleSheet("background-color: #1E1E2E; border: 1px solid #45475A; border-radius: 6px; padding: 6px;")
        lay_brk = QVBoxLayout(box_brk)
        lay_brk.setContentsMargins(8, 6, 8, 6)
        lay_brk.setSpacing(2)

        top_brk = QHBoxLayout()
        self.lbl_brk_title = QLabel("<b>Brake System:</b> Loading...")
        btn_audit_brakes = QPushButton("✏️ Audit")
        btn_audit_brakes.setFixedSize(50, 22)
        btn_audit_brakes.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_audit_brakes.setStyleSheet("background-color: #313244; color: #89B4FA; border-radius: 4px; font-size: 10px; font-weight: bold;")
        btn_audit_brakes.clicked.connect(self.open_brake_dialog)
        top_brk.addWidget(self.lbl_brk_title)
        top_brk.addWidget(btn_audit_brakes)
        lay_brk.addLayout(top_brk)

        self.lbl_brk_pads = QLabel("Front: — | Rear: —")
        self.lbl_brk_rotors = QLabel("Rotors: —")
        self.lbl_brk_rotors.setStyleSheet("color: #89B4FA; font-size: 10px; border: none;")
        lay_brk.addWidget(self.lbl_brk_pads)
        lay_brk.addWidget(self.lbl_brk_rotors)
        ms_layout.addWidget(box_brk)

        # Alignment Card
        box_align = QFrame()
        box_align.setStyleSheet("background-color: #1E1E2E; border: 1px solid #45475A; border-radius: 6px; padding: 6px;")
        lay_align = QVBoxLayout(box_align)
        lay_align.setContentsMargins(8, 6, 8, 6)
        lay_align.setSpacing(2)
        self.lbl_align_main = QLabel("<b>Chassis Alignment:</b> Loading...")
        self.lbl_align_sub = QLabel("Date: N/A | Inv: —")
        self.lbl_align_sub.setStyleSheet("color: #89B4FA; font-size: 10px; border: none;")
        lay_align.addWidget(self.lbl_align_main)
        lay_align.addWidget(self.lbl_align_sub)
        ms_layout.addWidget(box_align)

        cards_layout.addWidget(ms_frame, stretch=2)
        main_layout.addLayout(cards_layout)

        # 3. Cumulative Repair Taxonomy Banner
        self.taxonomy_frame = QFrame()
        self.taxonomy_frame.setStyleSheet("background-color: #181825; border: 1px solid #313244; border-radius: 8px;")
        tax_layout = QVBoxLayout(self.taxonomy_frame)
        tax_layout.setContentsMargins(14, 8, 14, 8)
        self.lbl_tax_cats = QLabel("Categories: Loading...")
        self.lbl_tax_cats.setStyleSheet("color: #CDD6F4; font-size: 11px; border: none;")
        self.lbl_tax_split = QLabel("Operations: Loading...")
        self.lbl_tax_split.setStyleSheet("color: #CDD6F4; font-size: 11px; border: none;")
        tax_row = QHBoxLayout()
        tax_row.addWidget(self.lbl_tax_cats)
        tax_row.addStretch()
        tax_row.addWidget(self.lbl_tax_split)
        tax_layout.addLayout(tax_row)
        main_layout.addWidget(self.taxonomy_frame)

        # 4. Unified Interactive Maintenance Table (Replaces old duplicate table)
        lbl_tbl_hdr = QLabel("Maintenance History (Double-click any record to open Report/Slip)")
        lbl_tbl_hdr.setFont(QFont(get_default_font_family(), 11, QFont.Weight.Bold))
        lbl_tbl_hdr.setStyleSheet("color: #89B4FA; margin-top: 4px;")
        main_layout.addWidget(lbl_tbl_hdr)

        self.history_widget = MaintenanceHistoryWidget(self.db, self.vehicle_id, parent=self)
        main_layout.addWidget(self.history_widget, stretch=1)

        # Initial data render
        self.refresh_telemetry()

    def refresh_telemetry(self) -> None:
        """Re-queries database and updates card values dynamically."""
        self.load_vehicle()
        cur_mil = int(self.v_data.get('mileage', 0))
        self.lbl_odo.setText(f"Odometer: {cur_mil:,} mi")

        # 1. Update 4-Corner Tire Labels (Two-Clock Architecture)
        tire_data = get_tire_position_telemetry(self.vehicle_id, cur_mil, self.db)
        for pos, labels in self.tire_card_labels.items():
            t = tire_data.get(pos, {})
            labels['sop'].setText(
                f"SOP Clock: <b>{t.get('sop_miles', 0):,} mi</b> — "
                f"<span style='color:{t.get('sop_color', '#A6ADC8')}; font-weight:bold;'>{t.get('sop_badge', '—')}</span>"
            )
            labels['depth'].setText(
                f"Tread: <span style='color:{t.get('depth_color', '#A6ADC8')}; font-weight:bold;'>{t.get('depth_badge', '—')}</span> "
                f"<span style='color:#A6ADC8;'>({t.get('physical_miles', 0):,} mi on tire)</span>"
            )
            labels['meta'].setText(t.get('meta_str', 'Date: N/A | Inv: —'))

        # 2. Update Subsystem Milestones
        ms_data = get_subsystem_milestones(self.vehicle_id, cur_mil, self.db)
        oil = ms_data.get('oil', {})
        oil_mil = oil.get('last_mileage', 0)
        self.lbl_oil_main.setText(f"<b>Engine Oil (PM):</b> Last @ {oil_mil:,} mi" if oil_mil else "<b>Engine Oil (PM):</b> None on Record")
        self.lbl_oil_sub.setText(f"Date: {oil.get('date', 'N/A')} | Inv: {oil.get('invoice', '—')}")

        brk = ms_data.get('brakes', {})
        brk_mil = brk.get('last_mileage', 0)
        self.lbl_brk_title.setText(f"<b>Brake System:</b> Last @ {brk_mil:,} mi" if brk_mil else "<b>Brake System:</b> None on Record")
        self.lbl_brk_pads.setText(f"Front: <b>{brk.get('front_mm', 0)} mm ({brk.get('front_pct', 0)}%)</b> | Rear: <b>{brk.get('rear_mm', 0)} mm ({brk.get('rear_pct', 0)}%)</b>")
        rotor_val = brk.get('rotors', 'Good')
        r_color = "#A6E3A1" if rotor_val == "Good" else "#F9E2AF" if "Turn" in rotor_val else "#F38BA8"
        self.lbl_brk_rotors.setText(f"Rotors: <span style='color:{r_color}; font-weight:bold;'>{rotor_val}</span> | Date: {brk.get('date', 'N/A')} | Inv: {brk.get('invoice', '—')}")

        align = ms_data.get('alignment', {})
        align_mil = align.get('last_mileage', 0)
        self.lbl_align_main.setText(f"<b>Chassis Alignment:</b> Last @ {align_mil:,} mi" if align_mil else "<b>Chassis Alignment:</b> None on Record")
        self.lbl_align_sub.setText(f"Date: {align.get('date', 'N/A')} | Inv: {align.get('invoice', '—')}")

        # 3. Update Taxonomy Banner
        tax_counts = {"PM": 0, "Tires": 0, "Brakes": 0, "Diag": 0, "General": 0}
        inhouse_cnt = 0
        shop_cnt = 0
        total_spend = 0.0

        with self.db.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT service_type, vendor, cost FROM service_logs WHERE vehicle_id = ? OR vehicle_id = ?", (self.vehicle_id, self.clean_uid))
            for l in cur.fetchall():
                st = str(l['service_type'] or '').lower()
                ven = str(l['vendor'] or '').lower()
                c = float(l['cost'] or 0.0)
                total_spend += c
                if "in-house" in ven: inhouse_cnt += 1
                else: shop_cnt += 1
                if "a service" in st or "b service" in st: tax_counts["PM"] += 1
                if "tire" in st: tax_counts["Tires"] += 1
                if "brake" in st: tax_counts["Brakes"] += 1
                if "diag" in st: tax_counts["Diag"] += 1
                if "repair" in st or "other" in st: tax_counts["General"] += 1

        self.lbl_tax_cats.setText(f"<b>Categories:</b> PMs: <span style='color:#A6E3A1;'>{tax_counts['PM']}</span> | Tires: <span style='color:#F9E2AF;'>{tax_counts['Tires']}</span> | Brakes: <span style='color:#F38BA8;'>{tax_counts['Brakes']}</span> | Diag: <span style='color:#89B4FA;'>{tax_counts['Diag']}</span> | General: <span style='color:#CDD6F4;'>{tax_counts['General']}</span>")
        self.lbl_tax_split.setText(f"<b>Operations:</b> In-House: <span style='color:#A6E3A1;'>{inhouse_cnt}</span> | Commercial Shop: <span style='color:#89B4FA;'>{shop_cnt}</span> | Spend: <span style='color:#A6E3A1; font-weight:bold;'>${total_spend:,.2f}</span>")

        # 4. Refresh Unified History Table
        self.history_widget.refresh()

    def open_tire_dialog(self, pos_code: Optional[str] = None) -> None:
        """Opens the full 4-corner in-house yard inspection and repair dialog."""
        dialog = InHouseInspectionDialog(
            db_manager=self.db,
            vehicle_id=self.vehicle_id,
            focus_corner=pos_code,
            parent=self
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.refresh_telemetry()
            if hasattr(self.window(), 'fleet_view'):
                self.window().fleet_view.refresh_data()

    def open_brake_dialog(self) -> None:
        """Opens brake friction material and rotor inspection modal."""
        dialog = BrakeInspectionDialog(db_manager=self.db, vehicle_id=self.vehicle_id, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            # LIVE INSTANT REFRESH
            self.refresh_telemetry()
            if hasattr(self.window(), 'fleet_view'):
                self.window().fleet_view.refresh_data()