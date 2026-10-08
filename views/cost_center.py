"""
views/cost_center.py
--------------------
Financial ledger and expense tracking view for G7 Fleet Portal Desktop.
Aggregates service costs and provides filtering by vendor and payment route.
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, 
    QPushButton, QTableWidget, QTableWidgetItem, QHeaderView, QFrame
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QColor

from db_manager import DatabaseManager
from utils.platform_helper import get_default_font_family

class CostCenterView(QWidget):
    def __init__(self, db_manager: DatabaseManager, parent=None):
        super().__init__(parent)
        self.db = db_manager
        self.init_ui()
        self.refresh_data()

    def init_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(15)

        # Header
        header_layout = QHBoxLayout()
        lbl_title = QLabel("💰 Global Cost Center")
        lbl_title.setFont(QFont(get_default_font_family(), 18, QFont.Bold))
        lbl_title.setStyleSheet("color: #CDD6F4;")
        header_layout.addWidget(lbl_title)
        header_layout.addStretch()

        # Summary Cards
        self.lbl_total_cost = QLabel("Total Spend: $0.00")
        self.lbl_total_cost.setFont(QFont(get_default_font_family(), 14, QFont.Bold))
        self.lbl_total_cost.setStyleSheet("color: #A6E3A1; background-color: #1E1E2E; padding: 10px; border-radius: 8px;")
        header_layout.addWidget(self.lbl_total_cost)
        main_layout.addLayout(header_layout)

        # Filters
        filter_frame = QFrame()
        filter_frame.setStyleSheet("background-color: #1E1E2E; border-radius: 10px;")
        filter_layout = QHBoxLayout(filter_frame)
        filter_layout.setContentsMargins(15, 12, 15, 12)

        self.cmb_route = QComboBox()
        self.cmb_route.addItems(["All Payment Routes", "Provider", "Out of Pocket", "Insurance"])
        self.cmb_route.setFixedHeight(35)
        self.cmb_route.setStyleSheet("background-color: #313244; color: #CDD6F4; border-radius: 6px; padding-left: 8px;")
        self.cmb_route.currentIndexChanged.connect(self.apply_filters)
        filter_layout.addWidget(self.cmb_route)

        main_layout.addWidget(filter_frame)

        # Ledger Table
        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(["Date", "Unit ID", "Vendor", "Service Type", "Payment Route", "Cost"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setStyleSheet("""
            QTableWidget { background-color: #1E1E2E; color: #CDD6F4; border: none; border-radius: 8px; }
            QHeaderView::section { background-color: #181825; color: #89B4FA; padding: 8px; font-weight: bold; border: none; }
        """)
        main_layout.addWidget(self.table)

    def refresh_data(self) -> None:
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT date, vehicle_id, vendor, service_type, payment_route, cost FROM service_logs ORDER BY id DESC")
            self.logs = [dict(r) for r in cursor.fetchall()]
        self.apply_filters()

    def apply_filters(self) -> None:
        route_filter = self.cmb_route.currentText()
        filtered_logs = [log for log in self.logs if route_filter == "All Payment Routes" or log.get('payment_route') == route_filter]

        self.table.setRowCount(len(filtered_logs))
        total_spent = 0.0

        for row_idx, log in enumerate(filtered_logs):
            self.table.setItem(row_idx, 0, QTableWidgetItem(str(log.get('date', ''))))
            self.table.setItem(row_idx, 1, QTableWidgetItem(str(log.get('vehicle_id', ''))))
            self.table.setItem(row_idx, 2, QTableWidgetItem(str(log.get('vendor', ''))))
            self.table.setItem(row_idx, 3, QTableWidgetItem(str(log.get('service_type', ''))))
            self.table.setItem(row_idx, 4, QTableWidgetItem(str(log.get('payment_route', 'Provider'))))
            
            cost = float(log.get('cost', 0.0))
            total_spent += cost
            cost_item = QTableWidgetItem(f"${cost:.2f}")
            cost_item.setForeground(QColor("#A6E3A1"))
            self.table.setItem(row_idx, 5, cost_item)

        self.lbl_total_cost.setText(f"Total Spend: ${total_spent:,.2f}")