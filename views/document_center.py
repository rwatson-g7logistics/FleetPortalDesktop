"""
views/document_center.py
------------------------
Document management interface for G7 Fleet Portal Desktop.
Organizes SOPs, lot maps, checklists, and manuals with upload/download capabilities.
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, 
    QPushButton, QTableWidget, QTableWidgetItem, QHeaderView, QFrame
)
from PySide6.QtGui import QFont

from utils.platform_helper import get_default_font_family

class DocumentCenterView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_ui()

    def init_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(15)

        # Header
        header_layout = QHBoxLayout()
        lbl_title = QLabel("📁 Operational Document Center")
        lbl_title.setFont(QFont(get_default_font_family(), 18, QFont.Bold))
        lbl_title.setStyleSheet("color: #CDD6F4;")
        header_layout.addWidget(lbl_title)
        
        header_layout.addStretch()

        btn_upload = QPushButton("☁️ Upload New Document")
        btn_upload.setFixedHeight(35)
        btn_upload.setStyleSheet("background-color: #A6E3A1; color: #11111B; font-weight: bold; border-radius: 6px; padding: 0 15px;")
        header_layout.addWidget(btn_upload)
        main_layout.addLayout(header_layout)

        # Filters
        filter_frame = QFrame()
        filter_frame.setStyleSheet("background-color: #1E1E2E; border-radius: 10px;")
        filter_layout = QHBoxLayout(filter_frame)
        filter_layout.setContentsMargins(15, 12, 15, 12)

        self.cmb_category = QComboBox()
        self.cmb_category.addItems(["All Categories", "SOPs", "Lot Maps", "Checklists", "Manuals", "General"])
        self.cmb_category.setFixedHeight(35)
        self.cmb_category.setStyleSheet("background-color: #313244; color: #CDD6F4; border-radius: 6px; padding-left: 8px;")
        filter_layout.addWidget(self.cmb_category)

        main_layout.addWidget(filter_frame)

        # Document Table
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Document Name", "Category", "Last Modified", "Action"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setStyleSheet("""
            QTableWidget { background-color: #1E1E2E; color: #CDD6F4; border: none; border-radius: 8px; }
            QHeaderView::section { background-color: #181825; color: #89B4FA; padding: 8px; font-weight: bold; border: none; }
        """)
        main_layout.addWidget(self.table)
        
        # Placeholder Data for Base UI
        self.table.setRowCount(1)
        self.table.setItem(0, 0, QTableWidgetItem("Awaiting Google Drive Sync..."))