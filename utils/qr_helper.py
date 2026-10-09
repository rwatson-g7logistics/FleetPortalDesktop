"""
FleetPortalDesktop/utils/qr_helper.py
-------------------------------------
Unified QR Code Engine and Dialog for G7 Fleet Portal Desktop.
Contains VIN sanitization, HTML-to-PDF grid generation, Google Drive upload,
and the unified interactive QR Generator modal (Single, Multi-select, Custom Paste).
"""

import re
import tempfile
import os
from pathlib import Path
from typing import List, Dict, Any, Optional
import qrcode

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QTextDocument
from PySide6.QtPrintSupport import QPrinter
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, QWidget,
    QLabel, QLineEdit, QTextEdit, QPushButton, QTableWidget,
    QTableWidgetItem, QHeaderView, QMessageBox
)

from cloud_sync import upload_file_to_drive_sync
from config import SUBFOLDER_QR_CODES
from db_manager import DatabaseManager
from utils.platform_helper import get_default_font_family


# =====================================================================
# --- 1. CORE RENDERING ENGINE ---
# =====================================================================

def clean_vin(raw_vin: str) -> str:
    """
    Strips whitespace, control characters, newlines, and non-standard
    symbols to ensure zero ghost characters in the QR payload.
    """
    if not raw_vin:
        return ""
    return re.sub(r'[^A-HJ-NPR-Z0-9]', '', str(raw_vin).upper())


def export_grid_to_pdf(items: List[Dict[str, str]], default_filename: str, parent_widget: Optional[QWidget] = None) -> str:
    """
    Renders items into an HTML 4x4 table, compiles to PDF, and uploads
    directly to the isolated FPD / QR Codes Google Drive folder.
    """
    html = """
    <html>
    <head>
        <style>
            body { font-family: Helvetica, Arial, sans-serif; background: #fff; color: #000; }
            h1 { text-align: center; font-size: 18pt; margin-bottom: 20px; }
            table { width: 100%; border-collapse: collapse; }
            td { text-align: center; vertical-align: middle; padding: 20px; width: 25%; border: 1px dashed #ccc; }
            .vid { font-size: 14pt; font-weight: bold; margin-bottom: 8px; color: #111; }
            .vin { font-size: 8pt; color: #555; margin-top: 5px; font-family: monospace; }
            img { width: 140px; height: 140px; }
        </style>
    </head>
    <body>
        <h1>G7 Fleet Command — VIN QR Code Labels</h1>
        <table>
    """

    temp_files_to_cleanup = []
    col_count = 0
    html += "<tr>"

    for item in items:
        vid = item.get('vehicle_id', '')
        raw_vin = item.get('vin', '')
        vin = clean_vin(raw_vin)

        if not vin:
            continue

        qr = qrcode.QRCode(version=1, box_size=8, border=1)
        qr.add_data(vin)
        qr.make(fit=True)
        img_qr = qr.make_image(fill_color="black", back_color="white")

        fd, tmp_path = tempfile.mkstemp(suffix='.png')
        os.close(fd)
        with open(tmp_path, "wb") as f_out:
            img_qr.save(f_out)
        temp_files_to_cleanup.append(tmp_path)

        html += f"""
            <td>
                <div class="vid">{vid}</div>
                <img src="{tmp_path}" />
                <div class="vin">{vin}</div>
            </td>
        """

        col_count += 1
        if col_count % 4 == 0:
            html += "</tr><tr>"

    while col_count % 4 != 0:
        html += "<td></td>"
        col_count += 1

    html += "</tr></table></body></html>"

    pdf_fd, pdf_path = tempfile.mkstemp(suffix='.pdf')
    os.close(pdf_fd)
    temp_files_to_cleanup.append(pdf_path)

    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
    printer.setOutputFileName(pdf_path)

    doc = QTextDocument()
    doc.setHtml(html)
    doc.print_(printer)

    success, web_link, err_msg = upload_file_to_drive_sync(
        local_filepath=pdf_path,
        drive_filename=default_filename,
        subfolder_name=SUBFOLDER_QR_CODES
    )

    for p in temp_files_to_cleanup:
        try:
            Path(p).unlink()
        except OSError:
            pass

    if parent_widget:
        if success:
            QMessageBox.information(
                parent_widget,
                "Google Drive Sync Complete",
                f"✅ QR Code Sheet uploaded to Google Drive successfully!\n\n"
                f"File: {default_filename}\n\nLink: {web_link}"
            )
        else:
            QMessageBox.warning(
                parent_widget,
                "Google Drive Sync Warning",
                f"🚨 Failed to upload QR Sheet to Google Drive.\n\n"
                f"Details: {err_msg}"
            )

    return web_link


# =====================================================================
# --- 2. UNIFIED INTERACTIVE QR DIALOG ---
# =====================================================================

class QRGeneratorDialog(QDialog):
    """Unified modal supporting Multi-select Fleet Roster, Single Unit, and Custom Paste."""

    def __init__(self, db_manager: DatabaseManager, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.db = db_manager
        self.setWindowTitle("QR Code Label Generator")
        self.resize(680, 520)
        self.setStyleSheet("background-color: #1E1E2E; color: #CDD6F4;")
        self.init_ui()

    def init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        lbl_header = QLabel("🖨️ Fleet QR Code Generator")
        lbl_header.setFont(QFont(get_default_font_family(), 14, QFont.Weight.Bold))
        lbl_header.setStyleSheet("color: #89B4FA;")
        layout.addWidget(lbl_header)

        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("""
            QTabWidget::pane { border: 1px solid #313244; border-radius: 6px; }
            QTabBar::tab {
                background: #181825; color: #CDD6F4; padding: 8px 16px;
                border-top-left-radius: 4px; border-top-right-radius: 4px;
            }
            QTabBar::tab:selected { background: #313244; color: #89B4FA; font-weight: bold; }
        """)

        # Tab 1: Fleet Multi-Select
        self.tab_roster = QWidget()
        self.init_roster_tab()
        self.tabs.addTab(self.tab_roster, "Fleet Selection")

        # Tab 2: Single Unit Search
        self.tab_single = QWidget()
        self.init_single_tab()
        self.tabs.addTab(self.tab_single, "Single Unit")

        # Tab 3: Custom Raw VIN Paste
        self.tab_custom = QWidget()
        self.init_custom_tab()
        self.tabs.addTab(self.tab_custom, "Custom Paste")

        layout.addWidget(self.tabs)

        btn_close = QPushButton("Close")
        btn_close.setFixedHeight(34)
        btn_close.setStyleSheet("background-color: #45475A; color: #CDD6F4; border-radius: 5px;")
        btn_close.clicked.connect(self.reject)
        layout.addWidget(btn_close)

    def init_roster_tab(self) -> None:
        tab_layout = QVBoxLayout(self.tab_roster)
        tab_layout.setContentsMargins(12, 12, 12, 12)

        ctrl_layout = QHBoxLayout()
        btn_select_all = QPushButton("Select All")
        btn_select_all.clicked.connect(lambda: self.set_table_selection(True))
        btn_clear_all = QPushButton("Clear Selection")
        btn_clear_all.clicked.connect(lambda: self.set_table_selection(False))

        ctrl_layout.addWidget(btn_select_all)
        ctrl_layout.addWidget(btn_clear_all)
        ctrl_layout.addStretch()

        btn_gen_roster = QPushButton("⚡ Generate PDF Sheet")
        btn_gen_roster.setStyleSheet("background-color: #A6E3A1; color: #11111B; font-weight: bold; border-radius: 5px; padding: 6px 12px;")
        btn_gen_roster.clicked.connect(self.generate_from_roster)
        ctrl_layout.addWidget(btn_gen_roster)

        tab_layout.addLayout(ctrl_layout)

        self.tbl_units = QTableWidget()
        self.tbl_units.setColumnCount(3)
        self.tbl_units.setHorizontalHeaderLabels(["Print?", "Unit ID", "VIN"])
        self.tbl_units.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.tbl_units.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.tbl_units.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.tbl_units.setStyleSheet("background-color: #181825; gridline-color: #313244; color: #CDD6F4;")
        tab_layout.addWidget(self.tbl_units)

        self.populate_roster()

    def populate_roster(self) -> None:
        df = self.db.get_all_vehicles()
        if df.empty:
            return

        self.tbl_units.setRowCount(len(df))
        for row_idx, (_, row) in enumerate(df.iterrows()):
            vid = str(row.get('vehicle_id', ''))
            vin = clean_vin(str(row.get('vin', '')))

            item_chk = QTableWidgetItem()
            item_chk.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            item_chk.setCheckState(Qt.CheckState.Checked)

            item_vid = QTableWidgetItem(vid)
            item_vin = QTableWidgetItem(vin)

            self.tbl_units.setItem(row_idx, 0, item_chk)
            self.tbl_units.setItem(row_idx, 1, item_vid)
            self.tbl_units.setItem(row_idx, 2, item_vin)

    def set_table_selection(self, check: bool) -> None:
        state = Qt.CheckState.Checked if check else Qt.CheckState.Unchecked
        for r in range(self.tbl_units.rowCount()):
            item = self.tbl_units.item(r, 0)
            if item:
                item.setCheckState(state)

    def generate_from_roster(self) -> None:
        selected_items = []
        for r in range(self.tbl_units.rowCount()):
            chk = self.tbl_units.item(r, 0)
            if chk and chk.checkState() == Qt.CheckState.Checked:
                vid = self.tbl_units.item(r, 1).text()
                vin = self.tbl_units.item(r, 2).text()
                if vin:
                    selected_items.append({"vehicle_id": vid, "vin": vin})

        if not selected_items:
            QMessageBox.warning(self, "No Units Selected", "Select at least one unit.")
            return

        export_grid_to_pdf(selected_items, "Fleet_Selected_QR_Labels.pdf", parent_widget=self)

    def init_single_tab(self) -> None:
        tab_layout = QVBoxLayout(self.tab_single)
        tab_layout.setContentsMargins(12, 12, 12, 12)
        tab_layout.setSpacing(10)

        tab_layout.addWidget(QLabel("Unit ID:"))
        self.txt_single_vid = QLineEdit()
        self.txt_single_vid.setFixedHeight(32)
        self.txt_single_vid.setStyleSheet("background-color: #313244; color: #CDD6F4; border-radius: 5px; padding-left: 8px;")
        tab_layout.addWidget(self.txt_single_vid)

        tab_layout.addWidget(QLabel("VIN (17 Characters):"))
        self.txt_single_vin = QLineEdit()
        self.txt_single_vin.setFixedHeight(32)
        self.txt_single_vin.setStyleSheet("background-color: #313244; color: #CDD6F4; border-radius: 5px; padding-left: 8px;")
        tab_layout.addWidget(self.txt_single_vin)

        tab_layout.addStretch()

        btn_single_gen = QPushButton("⚡ Generate Single Label")
        btn_single_gen.setFixedHeight(38)
        btn_single_gen.setStyleSheet("background-color: #A6E3A1; color: #11111B; font-weight: bold; border-radius: 5px;")
        btn_single_gen.clicked.connect(self.generate_single)
        tab_layout.addWidget(btn_single_gen)

    def generate_single(self) -> None:
        vid = self.txt_single_vid.text().strip()
        vin = clean_vin(self.txt_single_vin.text().strip())
        if not vid or not vin:
            QMessageBox.warning(self, "Validation Error", "Unit ID and VIN are required.")
            return

        export_grid_to_pdf([{"vehicle_id": vid, "vin": vin}], f"QR_Label_{vid}.pdf", parent_widget=self)

    def init_custom_tab(self) -> None:
        tab_layout = QVBoxLayout(self.tab_custom)
        tab_layout.setContentsMargins(12, 12, 12, 12)
        tab_layout.setSpacing(8)

        tab_layout.addWidget(QLabel("Paste raw VINs or 'UnitID, VIN' rows (one per line):"))
        self.txt_custom_input = QTextEdit()
        self.txt_custom_input.setPlaceholderText("VAN-101, 1FTNE2EW0KDC...\nVAN-102, 1FTNE2EW1KDC...\n1FTNE2EW2KDC...")
        self.txt_custom_input.setStyleSheet("background-color: #181825; color: #CDD6F4; border: 1px solid #313244; border-radius: 5px;")
        tab_layout.addWidget(self.txt_custom_input)

        btn_custom_gen = QPushButton("⚡ Parse & Generate Bulk Grid")
        btn_custom_gen.setFixedHeight(38)
        btn_custom_gen.setStyleSheet("background-color: #A6E3A1; color: #11111B; font-weight: bold; border-radius: 5px;")
        btn_custom_gen.clicked.connect(self.generate_custom)
        tab_layout.addWidget(btn_custom_gen)

    def generate_custom(self) -> None:
        lines = self.txt_custom_input.toPlainText().strip().split("\n")
        items = []
        for idx, line in enumerate(lines, start=1):
            line = line.strip()
            if not line:
                continue

            if "," in line:
                parts = line.split(",", 1)
                vid = parts[0].strip()
                vin = clean_vin(parts[1].strip())
            else:
                vid = f"Unit-{idx}"
                vin = clean_vin(line)

            if vin:
                items.append({"vehicle_id": vid, "vin": vin})

        if not items:
            QMessageBox.warning(self, "Empty Input", "No valid VINs could be parsed.")
            return

        export_grid_to_pdf(items, "Custom_Batch_QR_Labels.pdf", parent_widget=self)