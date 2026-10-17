"""
views/maintenance_table.py
--------------------------
Unified, interactive maintenance and service history ledger widget.
Consolidates history across VehicleProfileView and UnitServiceView.
Double-clicking any record opens the associated PDF report or inspection slip.
"""

import os
from typing import Optional
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QTableWidget, QTableWidgetItem, 
    QHeaderView, QMessageBox
)
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices

from utils.platform_helper import get_app_data_directory
from db_manager import DatabaseManager


class MaintenanceHistoryWidget(QWidget):
    """Unified maintenance ledger displaying Date, Service, Mileage, Vendor, Location, Invoice, and Cost Type."""

    def __init__(self, db_manager: DatabaseManager, vehicle_id: str, parent=None):
        super().__init__(parent)
        self.db = db_manager
        self.vehicle_id = str(vehicle_id)
        self.clean_uid = self.vehicle_id.split('_')[-1]
        self.records = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels([
            "Date", "Service Performed", "Mileage", "Vendor", 
            "Location", "Invoice #", "Cost Type"
        ])
        
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.Interactive)

        self.table.setColumnWidth(0, 100)
        self.table.setColumnWidth(2, 95)
        self.table.setColumnWidth(3, 140)
        self.table.setColumnWidth(4, 140)
        self.table.setColumnWidth(5, 105)
        self.table.setColumnWidth(6, 100)

        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setStyleSheet("""
            QTableWidget {
                background-color: #181825;
                color: #CDD6F4;
                gridline-color: #313244;
                border: 1px solid #313244;
                border-radius: 8px;
            }
            QHeaderView::section {
                background-color: #11111B;
                color: #89B4FA;
                padding: 6px;
                font-weight: bold;
                border: none;
                border-right: 1px solid #313244;
            }
            QTableWidget::item:selected {
                background-color: #45475A;
                color: #89B4FA;
            }
        """)

        self.table.cellDoubleClicked.connect(self.handle_row_launch)
        layout.addWidget(self.table)
        self.refresh()

    def refresh(self) -> None:
        """Pulls latest records for this unit and populates the table."""
        with self.db.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT date, service_type, mileage, vendor, location, invoice_num, payment_route, cost, notes 
                FROM service_logs 
                WHERE vehicle_id = ? OR vehicle_id = ?
                ORDER BY id DESC
            """, (self.vehicle_id, self.clean_uid))
            self.records = [dict(r) for r in cur.fetchall()]

        if not self.records:
            self.table.setRowCount(1)
            item = QTableWidgetItem("No localized maintenance logs recorded for this unit.")
            item.setForeground(QColor("#A6ADC8"))
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(0, 1, item)
            return

        self.table.setRowCount(len(self.records))
        for r_idx, r in enumerate(self.records):
            self.table.setItem(r_idx, 0, QTableWidgetItem(str(r.get('date', ''))))
            self.table.setItem(r_idx, 1, QTableWidgetItem(str(r.get('service_type', ''))))

            mil = r.get('mileage', 0)
            self.table.setItem(r_idx, 2, QTableWidgetItem(f"{mil:,} mi" if mil else ""))

            # Vendor formatting (InHouse / Shop [Name])
            raw_vendor = str(r.get('vendor', ''))
            vendor_display = "In-House" if "in-house" in raw_vendor.lower() else f"Shop ({raw_vendor})"
            item_vendor = QTableWidgetItem(vendor_display)
            item_vendor.setForeground(QColor("#A6E3A1") if "in-house" in raw_vendor.lower() else QColor("#89B4FA"))
            self.table.setItem(r_idx, 3, item_vendor)

            # Location formatting
            loc_val = str(r.get('location') or ('On Yard' if "in-house" in raw_vendor.lower() else 'Commercial Shop'))
            self.table.setItem(r_idx, 4, QTableWidgetItem(loc_val))

            # Invoice formatting
            inv_val = str(r.get('invoice_num') or ('IN-HOUSE' if "in-house" in raw_vendor.lower() else '—'))
            self.table.setItem(r_idx, 5, QTableWidgetItem(inv_val))

            # Cost Type (OoP, Provider, Insurance, Warranty)
            route_val = str(r.get('payment_route', 'Provider'))
            cost_type_map = {
                'out of pocket': 'OoP',
                'oop': 'OoP',
                'provider': 'Provider',
                'insurance': 'Insurance',
                'warranty': 'Warranty'
            }
            clean_cost_type = cost_type_map.get(route_val.lower(), route_val)
            item_cost_type = QTableWidgetItem(clean_cost_type)
            if clean_cost_type == 'OoP':
                item_cost_type.setForeground(QColor("#F9E2AF"))
            elif clean_cost_type == 'Provider':
                item_cost_type.setForeground(QColor("#89B4FA"))
            elif clean_cost_type == 'Warranty':
                item_cost_type.setForeground(QColor("#A6E3A1"))
            else:
                item_cost_type.setForeground(QColor("#CDD6F4"))
            self.table.setItem(r_idx, 6, item_cost_type)

    def handle_row_launch(self, row: int, col: int) -> None:
        """Launches the compiled PDF work order or in-house slip on double click."""
        if row >= len(self.records):
            return

        record = self.records[row]
        date_str = str(record.get('date', '')).replace('/', '-')
        inv = str(record.get('invoice_num', ''))

        report_dir = get_app_data_directory() / "Archived_Reports"
        possible_filenames = [
            f"ServiceReport_{self.vehicle_id}_{date_str}.pdf",
            f"ServiceReport_{self.clean_uid}_{date_str}.pdf",
            f"InHouse_Inspection_{self.clean_uid}_{date_str}.pdf",
            f"InHouse_Brake_{self.clean_uid}_{date_str}.pdf",
            f"InHouse_Tire_{self.clean_uid}_DF_{date_str}.pdf",
            f"InHouse_Tire_{self.clean_uid}_PF_{date_str}.pdf",
            f"InHouse_Tire_{self.clean_uid}_DR_{date_str}.pdf",
            f"InHouse_Tire_{self.clean_uid}_PR_{date_str}.pdf"
        ]

        found_path = None
        for fn in possible_filenames:
            target = report_dir / fn
            if target.exists():
                found_path = target
                break

        if found_path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(found_path)))
        else:
            notes = str(record.get('notes', 'No notes recorded.'))
            QMessageBox.information(
                self,
                f"Work Order Details — {record.get('service_type')}",
                f"<b>Unit:</b> {self.clean_uid}<br>"
                f"<b>Date:</b> {record.get('date')}<br>"
                f"<b>Mileage:</b> {record.get('mileage', 0):,} mi<br>"
                f"<b>Vendor:</b> {record.get('vendor')}<br>"
                f"<b>Location:</b> {record.get('location', 'On Yard')}<br>"
                f"<b>Invoice / Slip:</b> {inv}<br>"
                f"<b>Cost Type:</b> {record.get('payment_route', 'Provider')}<br><br>"
                f"<b>Work Order Notes:</b><br>{notes}"
            )