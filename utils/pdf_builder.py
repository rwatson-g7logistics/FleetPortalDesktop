"""
FleetPortalDesktop/utils/pdf_builder.py
--------------------
Generates unified PDF service reports by combining form data and attached
images (including HEIC). Prevents storage bloat by compiling into a single document.
"""

import os
import tempfile
from pathlib import Path
from PIL import Image
import pillow_heif
from PySide6.QtGui import QTextDocument, QPdfWriter, QPageSize
from PySide6.QtCore import QMarginsF

# Enable HEIC support for Apple iPhone photos
pillow_heif.register_heif_opener()

def create_service_report_pdf(service_data: dict, file_paths: list, output_filepath: str) -> str:
    """
    Compiles the text report and converts any attached images (HEIC/PNG/JPG)
    into a single standardized PDF file.
    """
    # 1. Build the HTML Document Template
    html_content = f"""
    <html>
    <head>
        <style>
            body {{ font-family: Helvetica, Arial, sans-serif; font-size: 12pt; color: #000; }}
            h1 {{ color: #2C3E50; border-bottom: 2px solid #34495E; padding-bottom: 5px; }}
            .section {{ margin-bottom: 20px; }}
            .label {{ font-weight: bold; color: #34495E; }}
        </style>
    </head>
    <body>
        <h1>Service & Incident Report — Unit {service_data.get('vehicle_id', 'Unknown')}</h1>
        
        <div class="section">
            <p><span class="label">Date:</span> {service_data.get('date', '')}</p>
            <p><span class="label">Vendor:</span> {service_data.get('vendor', '')}</p>
            <p><span class="label">Invoice #:</span> {service_data.get('invoice_num', '')}</p>
            <p><span class="label">Total Cost:</span> ${service_data.get('cost', 0.0):.2f}</p>
            <p><span class="label">Service Mileage:</span> {service_data.get('mileage', 0):,}</p>
            <p><span class="label">Service Types:</span> {service_data.get('service_type', '')}</p>
        </div>
        
        <div class="section">
            <p><span class="label">Reported Issue & Repair Performed:</span></p>
            <p>{service_data.get('notes', '').replace(chr(10), '<br>')}</p>
        </div>
    """

    temp_files = []
    if file_paths:
        html_content += "<h2>Attached Documentation</h2>"
        
        for path in file_paths:
            ext = path.lower().split('.')[-1]
            
            # Note standard PDFs (we will merge these later if needed, but flag them for now)
            if ext == 'pdf':
                html_content += f"<p><i>[Pre-existing PDF Document Attached: {os.path.basename(path)}]</i></p>"
                continue
                
            # 2. Process and Compress Images (HEIC/PNG/JPG)
            try:
                img = Image.open(path)
                img = img.convert("RGB") # Strip Apple alpha channels and formats to standard
                img.thumbnail((800, 1200), Image.Resampling.LANCZOS) # Resize massive iPhone photos to standard document width
                
                # Save to a temporary JPEG buffer
                temp_fd, temp_path = tempfile.mkstemp(suffix='.jpg')
                os.close(temp_fd)
                temp_files.append(temp_path)
                
                img.save(temp_path, "JPEG", quality=80)
                
                # Inject the temporary JPEG into the PDF layout
                html_content += f'<div style="text-align: center; margin-top: 20px;"><img src="{temp_path}" width="600" /></div><br><hr>'
            except Exception as e:
                html_content += f"<p><i>[Failed to load image: {os.path.basename(path)} - Error: {str(e)}]</i></p>"

    html_content += "</body></html>"

    # 3. Print HTML to PDF Engine
    doc = QTextDocument()
    doc.setHtml(html_content)

    writer = QPdfWriter(output_filepath)
    writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    writer.setPageMargins(QMarginsF(15, 15, 15, 15))
    
    doc.print_(writer)

    # 4. Clean up the temporary local cache images
    for temp_file in temp_files:
        try:
            os.remove(temp_file)
        except OSError:
            pass

    return output_filepath