"""
app.py
------
Main application window for G7 Fleet Command Center Desktop.
Uses PySide6 (Qt) to provide a responsive, cross-platform interface (macOS & Windows).
"""

import sys
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QPushButton, QLabel, QStackedWidget, QFrame, QProgressBar
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

from config import APP_TITLE, WINDOW_SIZE, MIN_WINDOW_SIZE
from db_manager import DatabaseManager
from cloud_sync import SyncWorker
from utils.platform_helper import get_default_font_family

# --- IMPORT ACTIVE VIEWS ---
from views.fleet_view import FleetView
from views.inventory_view import InventoryView
from views.vehicle_profile import VehicleProfileView
from views.service_view import ServiceFormView
from views.cost_center import CostCenterView
from views.document_center import DocumentCenterView


class FleetPortalApp(QMainWindow):
    """Main Desktop Window managing layout, navigation sidebar, and frame stacking."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(*WINDOW_SIZE)
        self.setMinimumSize(*MIN_WINDOW_SIZE)
        self.setStyleSheet("background-color: #11111B; color: #CDD6F4;")

        # Initialize Local Database Engine
        self.db = DatabaseManager()

        # Track dynamically created view indices to prevent memory leaks
        self.dynamic_views = []

        # Build GUI Layout
        self.init_ui()

        # Trigger Initial Background Sync
        self.start_background_sync()

    def init_ui(self) -> None:
        """Builds the main sidebar and content area frame."""
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QHBoxLayout(main_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # --- 1. LEFT NAVIGATION SIDEBAR ---
        sidebar = QFrame()
        sidebar.setFixedWidth(240)
        sidebar.setStyleSheet("background-color: #181825; color: #CDD6F4; border-right: 1px solid #313244;")
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(15, 20, 15, 20)
        sidebar_layout.setSpacing(10)

        # App Title / Header
        lbl_title = QLabel("🚀 G7 FLEET\nCOMMAND")
        lbl_title.setFont(QFont(get_default_font_family(), 14, QFont.Bold))
        lbl_title.setStyleSheet("color: #89B4FA; margin-bottom: 20px;")
        sidebar_layout.addWidget(lbl_title)

        # Navigation Buttons
        self.btn_fleet = QPushButton("📊 Fleet Command")
        self.btn_cost = QPushButton("💰 Cost Center")
        self.btn_inventory = QPushButton("📦 Parts & Inventory")
        self.btn_docs = QPushButton("📁 Document Center")

        nav_buttons = [self.btn_fleet, self.btn_cost, self.btn_inventory, self.btn_docs]
        for idx, btn in enumerate(nav_buttons):
            btn.setFixedHeight(45)
            btn.setFont(QFont(get_default_font_family(), 11, QFont.Medium))
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet("""
                QPushButton {
                    background-color: transparent;
                    color: #CDD6F4;
                    border: none;
                    border-radius: 6px;
                    text-align: left;
                    padding-left: 12px;
                }
                QPushButton:hover {
                    background-color: #313244;
                    color: #89B4FA;
                }
            """)
            btn.clicked.connect(lambda _, i=idx: self.switch_view(i))
            sidebar_layout.addWidget(btn)

        sidebar_layout.addStretch()

        # Status & Sync Indicator Bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(6)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                background-color: #313244;
                border-radius: 3px;
            }
            QProgressBar::chunk {
                background-color: #89B4FA;
                border-radius: 3px;
            }
        """)
        sidebar_layout.addWidget(self.progress_bar)

        self.lbl_status = QLabel("Local Cache Ready")
        self.lbl_status.setFont(QFont(get_default_font_family(), 9))
        self.lbl_status.setStyleSheet("color: #A6ADC8; margin-top: 5px;")
        sidebar_layout.addWidget(self.lbl_status)

        main_layout.addWidget(sidebar)

        # --- 2. RIGHT CONTENT AREA (STACKED WIDGET) ---
        self.content_stack = QStackedWidget()
        self.content_stack.setStyleSheet("background-color: #11111B; color: #CDD6F4;")

        # Instantiate Views
        self.fleet_view = FleetView(self.db)
        self.fleet_view.vehicle_selected.connect(self.open_vehicle_profile)

        self.cost_center_view = CostCenterView(self.db)
        self.inventory_view = InventoryView(self.db)
        self.document_center_view = DocumentCenterView()

        # Add to Stack matching nav button indices:
        # Index 0: Fleet Command Center
        self.content_stack.addWidget(self.fleet_view)
        # Index 1: Global Cost Center
        self.content_stack.addWidget(self.cost_center_view)
        # Index 2: Parts & Inventory Tracker
        self.content_stack.addWidget(self.inventory_view)
        # Index 3: Document Center
        self.content_stack.addWidget(self.document_center_view)

        main_layout.addWidget(self.content_stack)

        # Highlight default tab
        self.update_nav_styles(0)

    def switch_view(self, index: int) -> None:
        """Switches current visible frame in the content stacked widget to a primary tab."""
        self.content_stack.setCurrentIndex(index)
        self.update_nav_styles(index)
        
        # Cleanup dynamically added profile/service views when returning to main tabs
        self.cleanup_dynamic_views()

    def update_nav_styles(self, active_index: int) -> None:
        """Highlights the active button in the sidebar navigation."""
        buttons = [self.btn_fleet, self.btn_cost, self.btn_inventory, self.btn_docs]
        for idx, btn in enumerate(buttons):
            if idx == active_index:
                btn.setStyleSheet("""
                    QPushButton {
                        background-color: #313244;
                        color: #89B4FA;
                        font-weight: bold;
                        border: none;
                        border-radius: 6px;
                        text-align: left;
                        padding-left: 12px;
                    }
                """)
            else:
                btn.setStyleSheet("""
                    QPushButton {
                        background-color: transparent;
                        color: #CDD6F4;
                        border: none;
                        border-radius: 6px;
                        text-align: left;
                        padding-left: 12px;
                    }
                    QPushButton:hover {
                        background-color: #313244;
                        color: #89B4FA;
                    }
                """)

    def open_vehicle_profile(self, vehicle_id: str) -> None:
        """Instantiates and transitions to a detailed vehicle profile view."""
        profile_view = VehicleProfileView(self.db, vehicle_id)
        
        # Connect signals for internal routing
        profile_view.back_requested.connect(lambda: self.switch_view(0))
        profile_view.log_service_requested.connect(self.open_service_form)
        
        idx = self.content_stack.addWidget(profile_view)
        self.dynamic_views.append(profile_view)
        self.content_stack.setCurrentIndex(idx)

    def open_service_form(self, vehicle_data: dict) -> None:
        """Instantiates and transitions to the service entry form for a specific unit."""
        service_form = ServiceFormView(self.db, vehicle_data)
        
        # Once service is logged, route back to that unit's profile
        service_form.service_logged.connect(lambda vid: self.open_vehicle_profile(vid))
        
        idx = self.content_stack.addWidget(service_form)
        self.dynamic_views.append(service_form)
        self.content_stack.setCurrentIndex(idx)

    def cleanup_dynamic_views(self) -> None:
        """Removes temporary profile and service widgets from memory when navigating away."""
        for view in self.dynamic_views:
            self.content_stack.removeWidget(view)
            view.deleteLater()
        self.dynamic_views.clear()

    def start_background_sync(self) -> None:
        """Triggers asynchronous cloud sync without locking the desktop UI."""
        self.lbl_status.setText("Syncing with Google Cloud...")
        self.progress_bar.setRange(0, 0) # Pulse animation

        self.sync_worker = SyncWorker(self.db)
        self.sync_worker.sync_finished.connect(self.on_sync_finished)
        self.sync_worker.vehicles_loaded.connect(self.on_vehicles_loaded)
        self.sync_worker.start()

    def on_vehicles_loaded(self, count: int) -> None:
        """Callback when vehicle records are updated in SQLite."""
        self.lbl_status.setText(f"Cached {count} vehicles locally.")
        self.fleet_view.refresh_data()
        self.inventory_view.refresh_data()

    def on_sync_finished(self, success: bool, message: str) -> None:
        """Callback when background cloud synchronization completes."""
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100)
        if success:
            self.lbl_status.setText("Cloud Sync: Up to Date")
        else:
            self.lbl_status.setText("Cloud Sync: Offline Mode")


# --- ENTRY POINT ---
if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = FleetPortalApp()
    window.show()
    sys.exit(app.exec())