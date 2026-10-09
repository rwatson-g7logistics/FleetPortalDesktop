"""
FleetPortalDesktop/utils/qr_helper.py
------------------
QR Code generation and multi-page PDF grid export utilities.
Uploads generated QR sheets directly to Google Drive (Cloud-first storage).
Ensures strict VIN sanitization and displays clear sync/success/failure messages.
"""

import re
import tempfile
import os
from pathlib import Path
from typing import List, Dict, Any
import qrcode

from PySide6.QtGui import QTextDocument
from PySide6.QtPrintSupport import QPrinter
from PySide6.QtWidgets import QMessageBox

# --- CLOUD INTEGRATION & CONFIGURATION IMPORTS ---
from cloud_sync import upload_file_to_drive_sync
from config import SUBFOLDER_QR_CODES


def clean_vin(raw_vin: str) -> str:
    """
    Strips whitespace, invisible control characters, newlines, and 
    non-standard symbols to guarantee zero ghost characters in the QR payload.
    """
    if not raw_vin:
        return ""
    # Standard VINs are strictly 17 alphanumeric characters (A-Z, 0-9 excluding I, O, Q).
    cleaned = re.sub(r'[^A-HJ-NPR-Z0-9]', '', str(raw_vin).upper())
    return cleaned


def export_grid_to_pdf(items: List[Dict[str, str]], default_filename: str, parent_widget=None) -> str:
    """
    Renders items into an HTML 4x4 CSS Grid table, compiles to a temporary PDF,
    and uploads it directly to the isolated FPD / QR Codes Google Drive folder.
    """
    # 1. Generate HTML Grid Content
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

        # Generate QR Code embedding ONLY the sanitized VIN
        qr = qrcode.QRCode(version=1, box_size=8, border=1)
        qr.add_data(vin)
        qr.make(fit=True)
        img_qr = qr.make_image(fill_color="black", back_color="white")

        # Save QR chunk to temporary file
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

    # 2. Print temporary PDF locally on the fly for conversion
    pdf_fd, pdf_path = tempfile.mkstemp(suffix='.pdf')
    os.close(pdf_fd)
    temp_files_to_cleanup.append(pdf_path)

    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
    printer.setOutputFileName(pdf_path)

    doc = QTextDocument()
    doc.setHtml(html)
    doc.print_(printer)

    # 3. Upload to Google Drive into isolated FPD / QR Codes subfolder
    success, web_link, err_msg = upload_file_to_drive_sync(
        local_filepath=pdf_path,
        drive_filename=default_filename,
        subfolder_name=SUBFOLDER_QR_CODES
    )

    # 4. Cleanup temporary local images and PDF
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
            QMessageBox.critical(
                parent_widget,
                "Google Drive Sync Failed",
                f"🚨 Failed to upload QR Sheet to Google Drive.\n\n"
                f"Details: {err_msg}\n\n"
                f"Verify that FPD_ROOT_FOLDER_ID in config.py is correct and accessible."
            )

    return web_link