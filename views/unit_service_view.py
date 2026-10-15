"""
views/unit_service_view.py
--------------------------
Dedicated Unit Service Hub displaying 4-corner tire position telemetry (DF, PF, DR, PR),
subsystem milestone status (Oil, Brakes, Alignment), and direct invoice lookups.
"""
from datetime import datetime

from PySide6.QtWidgets import (
    QDialog, QSpinBox, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox,
    QFrame, QGridLayout, QTableWidget, QTableWidgetItem, QHeaderView, QRadioButton, QButtonGroup, QMessageBox
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QColor

from db_manager import DatabaseManager
from utils.platform_helper import get_default_font_family
from utils.service_tracker import get_tire_position_telemetry, get_subsystem_milestones
from utils.telemetry_sync import link_brake_spinboxes


class UnitServiceView(QWidget):
    """Dedicated screen showing individual unit service milestones and 4-wheel tire positions."""

    back_requested = Signal()
    log_service_requested = Signal(dict)

    def __init__(self, db_manager: DatabaseManager, vehicle_id: str, parent=None):
        super().__init__(parent)
        self.db = db_manager
        self.vehicle_id = str(vehicle_id)
        self.v_data = {}
        self.load_vehicle()
        self.init_ui()

    def load_vehicle(self) -> None:
        clean_num = self.vehicle_id.split('_')[-1]
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM master_vehicles 
                WHERE vehicle_id = ? OR vehicle_id = ? OR vehicle_id LIKE ?
            """, (self.vehicle_id, clean_num, f"%_{clean_num}"))
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

        raw_uid = str(self.v_data.get('unit_id') or self.vehicle_id.split('_')[-1])
        lbl_title = QLabel(f"🛠️ Service Status — Unit {raw_uid}")
        lbl_title.setFont(QFont(get_default_font_family(), 16, QFont.Weight.Bold))
        lbl_title.setStyleSheet("color: #CDD6F4;")
        hdr_layout.addWidget(lbl_title)

        hdr_layout.addStretch()

        raw_mil = str(self.v_data.get('mileage', 0)).replace(',', '').split('.')[0]
        cur_mil = int(raw_mil) if raw_mil.isdigit() else 0

        lbl_odo = QLabel(f"Odometer: {cur_mil:,} mi")
        lbl_odo.setFont(QFont(get_default_font_family(), 13, QFont.Weight.Bold))
        lbl_odo.setStyleSheet("color: #89B4FA; padding-right: 10px;")
        hdr_layout.addWidget(lbl_odo)

        btn_log = QPushButton("🛠️ Log Service")
        btn_log.setFixedHeight(34)
        btn_log.setStyleSheet("background-color: #A6E3A1; color: #11111B; font-weight: bold; border-radius: 6px; padding: 0 16px;")
        btn_log.clicked.connect(lambda: self.log_service_requested.emit(self.v_data))
        hdr_layout.addWidget(btn_log)

        main_layout.addLayout(hdr_layout)

        # 2. Main Analytics Cards (Left: 4-Corner Tires | Right: Subsystem Milestones)
        cards_layout = QHBoxLayout()
        cards_layout.setSpacing(14)

        # --- LEFT: 4-CORNER TIRE TELEMETRY MAP ---
        tire_data = get_tire_position_telemetry(self.vehicle_id, cur_mil, self.db)
        tire_frame = QFrame()
        tire_frame.setStyleSheet("background-color: #181825; border: 1px solid #313244; border-radius: 8px;")
        tire_layout = QVBoxLayout(tire_frame)
        tire_layout.setContentsMargins(14, 12, 14, 12)
        tire_layout.setSpacing(10)

        lbl_tire_hdr = QLabel("🛞 Tire Wear & Provider SOP Matrix")
        lbl_tire_hdr.setFont(QFont(get_default_font_family(), 11, QFont.Weight.Bold))
        lbl_tire_hdr.setStyleSheet("color: #89B4FA; border: none;")
        tire_layout.addWidget(lbl_tire_hdr)

        tire_grid = QGridLayout()
        tire_grid.setSpacing(10)

        # Maps the 4 corners to a 2x2 grid (DF=Top-Left, PF=Top-Right, DR=Bottom-Left, PR=Bottom-Right)
        coords = {'DF': (0, 0), 'PF': (0, 1), 'DR': (1, 0), 'PR': (1, 1)}

        for pos_code, (r, c) in coords.items():
            t_info = tire_data[pos_code]

            # 1. Outer Box for this wheel position
            box = QFrame()
            box.setStyleSheet("background-color: #1E1E2E; border: 1px solid #45475A; border-radius: 6px; padding: 6px;")
            box_lay = QVBoxLayout(box)
            box_lay.setContentsMargins(8, 6, 8, 6)
            box_lay.setSpacing(4)

            # 2. Position Label
            lbl_pos = QLabel(f"<b>[{pos_code}]</b> {t_info['label']}")
            lbl_pos.setStyleSheet("color: #CDD6F4; font-size: 11px; border: none;")

            # 3. Provider SOP Mileage Counter
            lbl_sop = QLabel(f"SOP: {t_info['miles_on_tire']:,} mi — <span style='color:{t_info['sop_color']}; font-weight:bold;'>{t_info['sop_badge']}</span>")
            lbl_sop.setStyleSheet("color: #CDD6F4; font-size: 10px; border: none;")

            # 4. Physical Tread Depth
            lbl_depth = QLabel(f"Tread: <span style='color:{t_info['depth_color']}; font-weight:bold;'>{t_info['depth_badge']}</span>")
            lbl_depth.setStyleSheet("color: #CDD6F4; font-size: 10px; border: none;")

            # 5. Datestamp & Last Invoice #
            lbl_meta = QLabel(f"Date: {t_info['date']} | Inv: {t_info['invoice']}")
            lbl_meta.setStyleSheet("color: #89B4FA; font-size: 10px; border: none;")

            # 6. Action Button: Opens the audit/replace modal for this specific tire
            btn_audit = QPushButton("✏️ Audit / Replace")
            btn_audit.setFixedHeight(26)
            btn_audit.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_audit.setStyleSheet("background-color: #313244; color: #89B4FA; border: 1px solid #45475A; border-radius: 4px; font-size: 10px; font-weight: bold;")
            btn_audit.clicked.connect(lambda _, p=pos_code, l=t_info['label'], d=t_info['tread_depth']: self.open_tire_dialog(p, l, d))

            # Assemble box
            box_lay.addWidget(lbl_pos)
            box_lay.addWidget(lbl_sop)
            box_lay.addWidget(lbl_depth)
            box_lay.addWidget(lbl_meta)
            box_lay.addWidget(btn_audit)

            # Place box in 2x2 grid
            tire_grid.addWidget(box, r, c)

        tire_layout.addLayout(tire_grid)
        cards_layout.addWidget(tire_frame, stretch=3)

        # --- RIGHT: OIL, BRAKES, ALIGNMENT MILESTONES ---
        ms_data = get_subsystem_milestones(self.vehicle_id, cur_mil, self.db)
        ms_frame = QFrame()
        ms_frame.setStyleSheet("background-color: #181825; border: 1px solid #313244; border-radius: 8px;")
        ms_layout = QVBoxLayout(ms_frame)
        ms_layout.setContentsMargins(14, 12, 14, 12)
        ms_layout.setSpacing(10)

        lbl_ms_hdr = QLabel("⚙️ Subsystem Lifecycle Milestones")
        lbl_ms_hdr.setFont(QFont(get_default_font_family(), 11, QFont.Weight.Bold))
        lbl_ms_hdr.setStyleSheet("color: #89B4FA; border: none;")
        ms_layout.addWidget(lbl_ms_hdr)

        # 1. Engine Oil Card
        oil = ms_data.get('oil', {})
        box_oil = QFrame()
        box_oil.setStyleSheet("background-color: #1E1E2E; border: 1px solid #45475A; border-radius: 6px; padding: 6px;")
        lay_oil = QVBoxLayout(box_oil)
        lay_oil.setContentsMargins(8, 6, 8, 6)
        lay_oil.setSpacing(2)
        oil_mil = oil.get('last_mileage', 0)
        lay_oil.addWidget(QLabel(f"<b>Engine Oil (PM)</b>: Last Serviced @ {oil_mil:,} mi" if oil_mil else "<b>Engine Oil (PM)</b>: None on Record"))
        lay_oil.addWidget(QLabel(f"<span style='color:#89B4FA;'>Date: {oil.get('date', 'N/A')} | Invoice: {oil.get('invoice', '—')}</span>"))
        ms_layout.addWidget(box_oil)

        # 2. Comprehensive Brake System Card
        brk = ms_data.get('brakes', {})
        box_brk = QFrame()
        box_brk.setStyleSheet("background-color: #1E1E2E; border: 1px solid #45475A; border-radius: 6px; padding: 6px;")
        lay_brk = QVBoxLayout(box_brk)
        lay_brk.setContentsMargins(8, 6, 8, 6)
        lay_brk.setSpacing(3)

        rotor_val = brk.get('rotors', 'Good')
        rotor_color = "#A6E3A1" if rotor_val == "Good" else "#F9E2AF" if "Turn" in rotor_val else "#F38BA8"
        brk_mil = brk.get('last_mileage', 0)

        top_brk = QHBoxLayout()
        top_brk.addWidget(QLabel(f"<b>Brake System</b>: Checked @ {brk_mil:,} mi" if brk_mil else "<b>Brake System</b>: None on Record"))
        
        btn_audit_brakes = QPushButton("✏️ Audit")
        btn_audit_brakes.setFixedSize(50, 22)
        btn_audit_brakes.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_audit_brakes.setStyleSheet("background-color: #313244; color: #89B4FA; border-radius: 4px; font-size: 10px; font-weight: bold;")
        btn_audit_brakes.clicked.connect(self.open_brake_dialog)
        top_brk.addWidget(btn_audit_brakes)
        lay_brk.addLayout(top_brk)

        lay_brk.addWidget(QLabel(
            f"Front: <b>{brk.get('front_mm', 0)} mm ({brk.get('front_pct', 0)}%)</b> | "
            f"Rear: <b>{brk.get('rear_mm', 0)} mm ({brk.get('rear_pct', 0)}%)</b>"
        ))
        lay_brk.addWidget(QLabel(
            f"Rotors: <span style='color:{rotor_color}; font-weight:bold;'>{rotor_val}</span> | "
            f"<span style='color:#89B4FA;'>Date: {brk.get('date', 'N/A')} | Inv: {brk.get('invoice', '—')}</span>"
        ))
        ms_layout.addWidget(box_brk)

        # 3. Alignment Card
        align = ms_data.get('alignment', {})
        box_align = QFrame()
        box_align.setStyleSheet("background-color: #1E1E2E; border: 1px solid #45475A; border-radius: 6px; padding: 6px;")
        lay_align = QVBoxLayout(box_align)
        lay_align.setContentsMargins(8, 6, 8, 6)
        lay_align.setSpacing(2)
        align_mil = align.get('last_mileage', 0)
        lay_align.addWidget(QLabel(f"<b>Chassis Alignment</b>: Last Checked @ {align_mil:,} mi" if align_mil else "<b>Chassis Alignment</b>: None on Record"))
        lay_align.addWidget(QLabel(f"<span style='color:#89B4FA;'>Date: {align.get('date', 'N/A')} | Invoice: {align.get('invoice', '—')}</span>"))
        ms_layout.addWidget(box_align)

        cards_layout.addWidget(ms_frame, stretch=2)
        main_layout.addLayout(cards_layout)

        # 3. Unit Service Log History Table
        lbl_log_hdr = QLabel("Recent Maintenance Logs for this Unit")
        lbl_log_hdr.setFont(QFont(get_default_font_family(), 12, QFont.Weight.Bold))
        lbl_log_hdr.setStyleSheet("color: #CDD6F4; margin-top: 4px;")
        main_layout.addWidget(lbl_log_hdr)

        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(["Date", "Service Performed", "Mileage", "Tire Pos", "Vendor", "Invoice #"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setStyleSheet("""
            QTableWidget { background-color: #181825; color: #CDD6F4; gridline-color: #313244; border: none; border-radius: 6px; }
            QHeaderView::section { background-color: #11111B; color: #89B4FA; padding: 6px; font-weight: bold; border: none; }
        """)
        self.populate_logs()
        main_layout.addWidget(self.table, stretch=1)

    def populate_logs(self) -> None:
        clean_uid = self.vehicle_id.split('_')[-1]
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT date, service_type, mileage, tire_positions, vendor, invoice_num 
                FROM service_logs 
                WHERE vehicle_id = ? OR vehicle_id = ?
                ORDER BY id DESC
            """, (self.vehicle_id, clean_uid))
            records = cursor.fetchall()

        self.table.setRowCount(len(records))
        for r_idx, r in enumerate(records):
            self.table.setItem(r_idx, 0, QTableWidgetItem(str(r['date'] or '')))
            self.table.setItem(r_idx, 1, QTableWidgetItem(str(r['service_type'] or '')))
            mil = r['mileage'] or 0
            self.table.setItem(r_idx, 2, QTableWidgetItem(f"{mil:,} mi" if mil else ""))
            self.table.setItem(r_idx, 3, QTableWidgetItem(str(r['tire_positions'] or '—')))
            self.table.setItem(r_idx, 4, QTableWidgetItem(str(r['vendor'] or '')))
            self.table.setItem(r_idx, 5, QTableWidgetItem(str(r['invoice_num'] or '—')))

    def open_tire_dialog(self, pos_code: str, pos_label: str, current_depth: int) -> None:
        """Opens popup dialog to measure tread depth or record single-tire replacement."""
        v_make = str(self.v_data.get('make', 'Ford'))
        dialog = TireInspectionDialog(
            db_manager=self.db,
            vehicle_id=self.vehicle_id,
            pos_code=pos_code,
            pos_label=pos_label,
            current_depth=current_depth,
            vehicle_make=v_make,
            parent=self
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.load_vehicle()
            self.populate_logs()
            # Parent stack refresh if window is active
            if hasattr(self.window(), 'fleet_view'):
                self.window().fleet_view.refresh_data()

    def open_brake_dialog(self) -> None:
        """Opens popup dialog to audit brake friction material and rotor condition."""
        dialog = BrakeInspectionDialog(
            db_manager=self.db,
            vehicle_id=self.vehicle_id,
            parent=self
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.load_vehicle()
            self.populate_logs()
            if hasattr(self.window(), 'fleet_view'):
                self.window().fleet_view.refresh_data()

class TireInspectionDialog(QDialog):
    """Modal to update tread measurement or log single-tire replacement with inventory deduction."""

    def __init__(self, db_manager, vehicle_id: str, pos_code: str, pos_label: str, current_depth: int, vehicle_make: str, parent=None):
        super().__init__(parent)
        self.db = db_manager
        self.vehicle_id = vehicle_id
        self.clean_uid = vehicle_id.split('_')[-1]
        self.pos_code = pos_code
        self.pos_label = pos_label
        self.vehicle_make = vehicle_make

        self.setWindowTitle(f"Tire Inspection — [{pos_code}] {pos_label}")
        self.setFixedSize(380, 290)
        self.setStyleSheet("background-color: #1E1E2E; color: #CDD6F4;")
        self.init_ui(current_depth)

    def init_ui(self, current_depth: int) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        lbl_hdr = QLabel(f"🛞 <b>Position: [{self.pos_code}]</b> {self.pos_label}<br><span style='color: #89B4FA;'>Unit: {self.clean_uid}</span>")
        lbl_hdr.setStyleSheet("font-size: 13px; line-height: 1.4;")
        layout.addWidget(lbl_hdr)

        # Mode Selection: Audit vs. Replace
        mode_box = QFrame()
        mode_box.setStyleSheet("background-color: #181825; border: 1px solid #313244; border-radius: 6px;")
        mode_lay = QHBoxLayout(mode_box)
        
        self.radio_audit = QRadioButton("Measure Tread")
        self.radio_replace = QRadioButton("Mark Replaced (New Tire)")
        self.radio_audit.setChecked(True)
        self.radio_audit.setStyleSheet("color: #CDD6F4;")
        self.radio_replace.setStyleSheet("color: #A6E3A1; font-weight: bold;")

        btn_grp = QButtonGroup(self)
        btn_grp.addButton(self.radio_audit)
        btn_grp.addButton(self.radio_replace)
        mode_lay.addWidget(self.radio_audit)
        mode_lay.addWidget(self.radio_replace)
        layout.addWidget(mode_box)

        # Tread Depth SpinBox
        tread_row = QHBoxLayout()
        tread_row.addWidget(QLabel("Tread Depth (32nds):"))
        self.spin_depth = QSpinBox()
        self.spin_depth.setRange(0, 20)
        self.spin_depth.setValue(current_depth if current_depth > 0 else 10)
        self.spin_depth.setSuffix(" /32\"")
        self.spin_depth.setFixedHeight(34)
        self.spin_depth.setStyleSheet("background-color: #313244; color: #CDD6F4; border: 1px solid #45475A; border-radius: 5px; padding-left: 8px;")
        tread_row.addWidget(self.spin_depth)
        layout.addLayout(tread_row)

        self.radio_replace.toggled.connect(lambda chk: self.spin_depth.setValue(11 if chk else current_depth))

        self.lbl_inv_notice = QLabel("ℹ️ Marking 'Replaced' will auto-deduct 1 tire from local shop inventory.")
        self.lbl_inv_notice.setStyleSheet("color: #F9E2AF; font-size: 11px;")
        self.lbl_inv_notice.setWordWrap(True)
        layout.addWidget(self.lbl_inv_notice)

        btns = QHBoxLayout()
        btn_cancel = QPushButton("Cancel")
        btn_cancel.setFixedHeight(34)
        btn_cancel.setStyleSheet("background-color: #45475A; color: #CDD6F4; border-radius: 5px;")
        btn_cancel.clicked.connect(self.reject)

        btn_save = QPushButton("💾 Commit Update")
        btn_save.setFixedHeight(34)
        btn_save.setStyleSheet("background-color: #A6E3A1; color: #11111B; font-weight: bold; border-radius: 5px;")
        btn_save.clicked.connect(self.commit_entry)

        btns.addWidget(btn_cancel)
        btns.addWidget(btn_save)
        layout.addLayout(btns)

    def commit_entry(self) -> None:
        depth = self.spin_depth.value()
        is_replacement = self.radio_replace.isChecked()
        today_str = datetime.now().strftime("%Y-%m-%d")

        # Resolve current vehicle mileage
        with self.db.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT mileage FROM master_vehicles WHERE vehicle_id = ? OR vehicle_id = ?", (self.vehicle_id, self.clean_uid))
            row = cur.fetchone()
            cur_mil = row['mileage'] if row else 0

        # Construct specific column update for this wheel position
        col_name = f"tread_{self.pos_code.lower()}"
        svc_type = f"Tire Replacement ({self.pos_code})" if is_replacement else f"Tire Audit ({self.pos_code})"
        notes = f"In-Shop Audit: {self.pos_label} set to {depth}/32\""
        if is_replacement:
            notes = f"In-Shop Replacement: Mounted new tire on {self.pos_label} ({depth}/32\"). Deducted from shop stock."

        # Insert inspection record into service_logs
        service_data = {
            "vehicle_id": self.vehicle_id,
            "vin": "",
            "date": today_str,
            "service_type": svc_type,
            "mileage": cur_mil,
            "vendor": "In-House Shop",
            "invoice_num": "IN-HOUSE",
            "cost": 0.0,
            "notes": notes,
            "tire_count": 1 if is_replacement else 0,
            "tire_positions": self.pos_code,
            "tread_df": depth if self.pos_code == 'DF' else 0,
            "tread_pf": depth if self.pos_code == 'PF' else 0,
            "tread_dr": depth if self.pos_code == 'DR' else 0,
            "tread_pr": depth if self.pos_code == 'PR' else 0,
            "brake_front_mm": 0, "brake_front_pct": 0, "brake_rear_mm": 0, "brake_rear_pct": 0,
            "rotor_condition": "Good"
        }
        self.db.save_service_record(service_data)

        # If replaced, auto-deduct 1 tire matching this make from inventory
        if is_replacement:
            self.db.auto_deduct_inventory(
                service_types="Tires",
                repair_text="Tire Replacement",
                tire_count=1,
                vehicle_make=self.vehicle_make
            )

        QMessageBox.information(
            self,
            "Tire Logged",
            f"✅ [{self.pos_code}] updated to {depth}/32\"." +
            ("\n• 1 tire deducted from local stock." if is_replacement else "")
        )
        self.accept()

class BrakeInspectionDialog(QDialog):
    """Modal to record brake pad measurements (% and mm) and rotor condition."""

    def __init__(self, db_manager, vehicle_id: str, parent=None):
        super().__init__(parent)
        self.db = db_manager
        self.vehicle_id = vehicle_id
        self.clean_uid = vehicle_id.split('_')[-1]

        self.setWindowTitle(f"Brake & Rotor Audit — Unit {self.clean_uid}")
        self.setFixedSize(380, 280)
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

        # Connect Bi-Directional Converters
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
            cur.execute("SELECT mileage FROM master_vehicles WHERE vehicle_id = ? OR vehicle_id = ?", (self.vehicle_id, self.clean_uid))
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
            "payment_route": "Provider",
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
        QMessageBox.information(self, "Brakes Logged", "✅ Brake inspection saved successfully.")
        self.accept()