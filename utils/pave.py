"""
FleetPortalDesktop/utils/pave.py
--------------------
Converts a PAVE inspection/assessment image into a PDF with standard naming:
UID_[Unit_ID]_[MM-DD-YY].pdf
    
Returns the absolute local path to the generated PDF.
"""

import os
from datetime import datetime
from pathlib import Path
from PIL import Image

def generate_pave_pdf(unit_id: str, source_image_path: str, output_dir: str = "PAVES") -> str:
    
    if not source_image_path or not os.path.exists(source_image_path):
        return ""

    # Ensure output folder exists
    paves_folder = Path(output_dir)
    paves_folder.mkdir(parents=True, exist_ok=True)

    # Generate filename: e.g., 001_10-08-26.pdf
    date_str = datetime.now().strftime("%m-%d-%y")
    clean_unit_id = str(unit_id).strip().replace(" ", "_")
    pdf_filename = f"{clean_unit_id}_{date_str}.pdf"
    pdf_path = paves_folder / pdf_filename

    # Convert image to RGB and export as PDF
    image = Image.open(source_image_path)
    if image.mode != "RGB":
        image = image.convert("RGB")
        
    image.save(pdf_path, "PDF", resolution=100.0)
    return str(pdf_path.resolve())