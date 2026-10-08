"""
utils/qr_helper.py
------------------
QR Code generation and multi-page PDF grid export utilities.
Uploads generated QR sheets directly to Google Drive (Cloud-first storage).
Ensures strict VIN sanitization (stripping whitespace, control characters, ghost characters).
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

# Google API imports for cloud upload
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from cloud_sync import get_gcp_credentials
from config import PARENT_FOLDER_ID


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
    and uploads it directly to the Master User's Google Drive Cloud Storage.
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
        img_qr.save(tmp_path)
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

    printer = QPrinter(QPrinter.HighResolution)
    printer.setOutputFormat(QPrinter.PdfFormat)
    printer.setOutputFileName(pdf_path)

    doc = QTextDocument()
    doc.setHtml(html)
    doc.print_(printer)

    # 3. Upload directly to Master User's Google Drive
    uploaded_file_url = ""
    try:
        creds = get_gcp_credentials()
        if creds:
            service = build('drive', 'v3', credentials=creds)
            
            file_metadata = {
                'name': default_filename,
                'parents': [PARENT_FOLDER_ID] if PARENT_FOLDER_ID else []
            }
            media = MediaFileUpload(pdf_path, mimetype='application/pdf', resumable=True)
            
            file = service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id, webViewLink, name'
            ).execute()
            
            uploaded_file_url = file.get('webViewLink', '')
    except Exception as e:
        print(f"Cloud upload warning: {e}")

    # 4. Cleanup temporary files
    for p in temp_files_to_cleanup:
        try:
            Path(p).unlink()
        except OSError:
            pass

    if parent_widget:
        if uploaded_file_url:
            QMessageBox.information(
                parent_widget, 
                "Cloud Sync Success", 
                f"QR Code sheet successfully compiled and uploaded to your Master Google Drive Account!\n\nFile: {default_filename}"
            )
        else:
            QMessageBox.warning(
                parent_widget, 
                "Cloud Warning", 
                "PDF generated, but cloud upload failed. Check your token credentials."
            )

    return uploaded_file_url