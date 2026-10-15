"""
FleetPortalDesktop/utils/qr_helper.py
-------------------------------------
Unified QR Code Engine and Dialog for G7 Fleet Portal Desktop.
Contains VIN sanitization, HTML-to-PDF grid generation (4-across, 1.4" x 1.4" labels),
Google Drive cloud sync, and the unified interactive QR Generator modal.
"""

import re
import tempfile
import os
from pathlib import Path
from typing import List, Dict, Any, Optional
import qrcode
from qrcode.constants import ERROR_CORRECT_M

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
from utils.platform_helper import get_default_font_family, get_app_data_directory


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
    Renders items into an HTML 4-across grid formatted for 1.4" x 1.4" sticker badges,
    compiles to PDF via QPrinter, preserves the local file in FPD / QR Codes,
    and uploads to the isolated FPD / QR Codes Google Drive folder.
    """
    # 1. Resolve Local Output Directory & Filepath
    qr_dir = get_app_data_directory() / SUBFOLDER_QR_CODES
    os.makedirs(qr_dir, exist_ok=True)
    pdf_path = str(qr_dir / default_filename)

    # 2. Base HTML & CSS Setup (4 Columns, 1.4" x 1.4" Envelope, 24 Labels Per Page)
    html = """
    <html>
    <head>
        <style>
            @page {
                size: letter;
                margin: 0.35in;
            }
            body {
                font-family: Arial, Helvetica, sans-serif;
                margin: 0;
                padding: 0;
                background-color: #ffffff;
            }
            table {
                width: 100%;
                border-collapse: separate;
                border-spacing: 6px;
            }
            tr {
                page-break-inside: avoid;
            }
            td {
                width: 25%;
                vertical-align: top;
                text-align: center;
                padding: 2px;
            }
            .badge {
                border: 1px solid #45475A;
                border-radius: 6px;
                padding: 6px 4px;
                background-color: #ffffff;
                text-align: center;
            }
            .vid {
                font-size: 9pt;
                font-weight: bold;
                color: #11111B;
                margin-bottom: 3px;
            }
            img {
                width: 95px;
                height: 95px;
                display: block;
                margin: 0 auto;
            }
            .vin {
                font-size: 6pt;
                font-family: "Courier New", Courier, monospace;
                font-weight: bold;
                color: #313244;
                margin-top: 3px;
            }
        </style>
    </head>
    <body>
        <table>
    """

    temp_images_to_cleanup = []
    col_count = 0
    html += "<tr>"

    # 3. Build Label Grid
    for item in items:
        raw_uid = str(item.get('vehicle_id', '') or item.get('unit_id', '')).strip()
        display_uid = raw_uid.split('_')[-1]
        raw_vin = item.get('vin', '')
        vin = clean_vin(raw_vin)

        if not vin:
            continue

        # Generate Scannable QR Matrix
        qr = qrcode.QRCode(
            version=1,
            error_correction=ERROR_CORRECT_M,
            box_size=6,
            border=1
        )
        qr.add_data(vin)
        qr.make(fit=True)
        img_qr = qr.make_image(fill_color="black", back_color="white")

        fd, tmp_png = tempfile.mkstemp(suffix='.png')
        os.close(fd)
        with open(tmp_png, "wb") as f_out:
            img_qr.save(f_out)
        temp_images_to_cleanup.append(tmp_png)

        # 1.4" x 1.4" Label Badge Layout
        html += f"""
            <td>
                <div class="badge">
                    <div class="vid">UNIT {display_uid}</div>
                    <img src="{tmp_png}" />
                    <div class="vin">{vin}</div>
                </div>
            </td>
        """

        col_count += 1
        if col_count % 4 == 0:
            html += "</tr><tr>"

    # Fill remaining columns in the final row to preserve table geometry
    if col_count % 4 != 0:
        while col_count % 4 != 0:
            html += "<td></td>"
            col_count += 1

    html += "</tr></table></body></html>"

    # 4. Compile HTML Document to Native PDF
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
    printer.setOutputFileName(pdf_path)

    doc = QTextDocument()
    doc.setHtml(html)
    doc.print_(printer)

    # 5. Clean Up Temporary PNG Images
    for p in temp_images_to_cleanup:
        try:
            Path(p).unlink(missing_ok=True)
        except OSError:
            pass

    # 6. Upload Compiled PDF to Google Drive
    success, web_link, err_msg = upload_file_to_drive_sync(
        local_filepath=pdf_path,
        drive_filename=default_filename,
        subfolder_name=SUBFOLDER_QR_CODES
    )

    # 7. Feedback Notification
    if parent_widget:
        if success:
            QMessageBox.information(
                parent_widget,
                "Google Drive Sync Complete",
                f"✅ QR Code Sheet generated and uploaded successfully!\n\n"
                f"File: {default_filename}\n\nLink: {web_link}"
            )
        else:
            QMessageBox.warning(
                parent_widget,
                "Google Drive Sync Warning",
                f"⚠️ QR Sheet saved locally, but failed to upload to Google Drive.\n\n"
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

        # Sort roster numerically by Unit ID
        def sort_key(row):
            uid = str(row.get('unit_id') or str(row.get('vehicle_id', '')).split('_')[-1])
            return int(uid) if uid.isdigit() else 999999

        records = df.to_dict('records')
        records.sort(key=sort_key)

        self.tbl_units.setRowCount(len(records))
        for row_idx, row in enumerate(records):
            vid = str(row.get('unit_id') or str(row.get('vehicle_id', '')).split('_')[-1])
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
                item_vid = self.tbl_units.item(r, 1)
                item_vin = self.tbl_units.item(r, 2)
                if item_vid and item_vin:
                    vid = item_vid.text().strip()
                    vin = item_vin.text().strip()
                    if vin:
                        selected_items.append({"vehicle_id": vid, "vin": vin})

        if not selected_items:
            QMessageBox.warning(self, "No Units Selected", "Select at least one unit.")
            return

        export_grid_to_pdf(selected_items, "Master_Fleet_QR_Labels.pdf", parent_widget=self)

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
        self.txt_single_vin.setMaxLength(17)
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