"""
views/vehicle_profile.py
------------------------
Detailed profile view for a specific fleet unit. Displays specifications,
compliance status, current mileage, and a localized service history log.
"""

from typing import Dict, Any, List
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
    QFrame, QGridLayout, QTableWidget, QTableWidgetItem, QHeaderView
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QColor

from db_manager import DatabaseManager
from utils.platform_helper import get_default_font_family


class VehicleProfileView(QWidget):
    """Detailed view for a single vehicle, acting as a hub for unit operations."""

    # Signals for navigation and action routing
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
        lbl_title.setFont(QFont(get_default_font_family(), 18, QFont.Bold))
        lbl_title.setStyleSheet("color: #CDD6F4;")
        header_layout.addWidget(lbl_title)

        header_layout.addStretch()

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
        lbl_specs.setFont(QFont(get_default_font_family(), 12, QFont.Bold))
        lbl_specs.setStyleSheet("color: #89B4FA; margin-bottom: 10px;")
        specs_grid.addWidget(lbl_specs, 0, 0, 1, 2)

        spec_fields = [
            ("Make/Model:", f"{self.vehicle_data.get('make', '')} {self.vehicle_data.get('model', '')}"),
            ("Year:", self.vehicle_data.get('year', '')),
            ("VIN:", self.vehicle_data.get('vin', '')),
            ("License Plate:", f"{self.vehicle_data.get('plate', '')} ({self.vehicle_data.get('state', '')})"),
            ("Size Category:", self.vehicle_data.get('size', 'L'))
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
        lbl_status.setFont(QFont(get_default_font_family(), 12, QFont.Bold))
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
            
            # Highlight bad statuses
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
        lbl_history.setFont(QFont(get_default_font_family(), 14, QFont.Bold))
        lbl_history.setStyleSheet("color: #CDD6F4; margin-top: 10px;")
        main_layout.addWidget(lbl_history)

        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["Date", "Service Performed", "Mileage", "Vendor", "Cost"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
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