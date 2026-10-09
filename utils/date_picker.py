"""
FleetPortalDesktop/utils/date_picker.py
---------------------------------------
Reusable interactive date picker widget for G7 Fleet Command Center Desktop.
Combines a styled QLineEdit with a calendar popup dialog (QCalendarWidget).
Features a '01 . January' month selector, hides legacy arrow buttons,
and adheres to the Catppuccin Mocha color scheme.
"""

from typing import Optional
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLineEdit, QPushButton,
    QDialog, QCalendarWidget, QComboBox, QSpinBox
)
from PySide6.QtCore import Qt, QDate
from PySide6.QtGui import QFont

from utils.platform_helper import get_default_font_family


MONTH_NAMES = [
    "01 . January", "02 . February", "03 . March", "04 . April",
    "05 . May", "06 . June", "07 . July", "08 . August",
    "09 . September", "10 . October", "11 . November", "12 . December"
]


class CalendarDialog(QDialog):
    """Frameless popup dialog hosting a themed calendar without arrow buttons."""

    def __init__(self, current_date_str: str = "", date_format: str = "yyyy-MM-dd", parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.date_format = date_format
        self.selected_date_str = current_date_str
        self.init_ui(current_date_str)

    def init_ui(self, current_date_str: str) -> None:
        """Constructs the dark-themed calendar dialog layout."""
        self.setWindowTitle("Select Date")
        self.setWindowFlags(Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setStyleSheet("""
            QDialog {
                background-color: #181825;
                border: 1px solid #45475A;
                border-radius: 8px;
            }
            QCalendarWidget QWidget {
                alternate-background-color: #1E1E2E;
            }
            QCalendarWidget QAbstractItemView:enabled {
                color: #CDD6F4;
                background-color: #1E1E2E;
                selection-background-color: #89B4FA;
                selection-color: #11111B;
                border: none;
            }
            QCalendarWidget QAbstractItemView:disabled {
                color: #585B70;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # Parse Initial Date
        initial_qdate = QDate.currentDate()
        if current_date_str:
            parsed = QDate.fromString(current_date_str, self.date_format)
            if parsed.isValid():
                initial_qdate = parsed

        # --- 1. CUSTOM TOP NAVIGATION HEADER (NO ARROWS) ---
        nav_layout = QHBoxLayout()
        nav_layout.setSpacing(8)

        # Month Selector: "01 . January" format
        self.cmb_month = QComboBox()
        self.cmb_month.addItems(MONTH_NAMES)
        self.cmb_month.setCurrentIndex(initial_qdate.month() - 1)
        self.cmb_month.setFixedHeight(30)
        self.cmb_month.setStyleSheet("""
            QComboBox {
                background-color: #313244;
                color: #CDD6F4;
                border: 1px solid #45475A;
                border-radius: 5px;
                padding-left: 8px;
                font-weight: bold;
            }
            QComboBox QAbstractItemView {
                background-color: #1E1E2E;
                color: #CDD6F4;
                selection-background-color: #45475A;
                selection-color: #89B4FA;
            }
        """)
        self.cmb_month.currentIndexChanged.connect(self.sync_calendar_page)
        nav_layout.addWidget(self.cmb_month, stretch=2)

        # Year Selector
        self.spin_year = QSpinBox()
        self.spin_year.setRange(1980, 2050)
        self.spin_year.setValue(initial_qdate.year())
        self.spin_year.setFixedHeight(30)
        self.spin_year.setStyleSheet("""
            QSpinBox {
                background-color: #313244;
                color: #CDD6F4;
                border: 1px solid #45475A;
                border-radius: 5px;
                padding-left: 8px;
                font-weight: bold;
            }
        """)
        self.spin_year.valueChanged.connect(self.sync_calendar_page)
        nav_layout.addWidget(self.spin_year, stretch=1)

        layout.addLayout(nav_layout)

        # --- 2. CALENDAR GRID (ARROWS HIDDEN) ---
        self.calendar = QCalendarWidget()
        self.calendar.setGridVisible(True)
        self.calendar.setNavigationBarVisible(True)
        self.calendar.setFont(QFont(get_default_font_family(), 9))
        self.calendar.setSelectedDate(initial_qdate)
        self.calendar.setCurrentPage(initial_qdate.year(), initial_qdate.month())
        self.calendar.clicked.connect(self.on_date_clicked)
        layout.addWidget(self.calendar)

        # --- 3. BOTTOM ACTION BAR ---
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(6)

        btn_today = QPushButton("Today")
        btn_today.setFixedHeight(28)
        btn_today.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_today.setStyleSheet("background-color: #313244; color: #89B4FA; border-radius: 4px; font-weight: bold;")
        btn_today.clicked.connect(self.select_today)
        btn_layout.addWidget(btn_today)

        btn_clear = QPushButton("Clear")
        btn_clear.setFixedHeight(28)
        btn_clear.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_clear.setStyleSheet("background-color: #313244; color: #F38BA8; border-radius: 4px; font-weight: bold;")
        btn_clear.clicked.connect(self.clear_date)
        btn_layout.addWidget(btn_clear)

        btn_cancel = QPushButton("Close")
        btn_cancel.setFixedHeight(28)
        btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cancel.setStyleSheet("background-color: #45475A; color: #CDD6F4; border-radius: 4px;")
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancel)

        layout.addLayout(btn_layout)

    def sync_calendar_page(self) -> None:
        """Updates the calendar grid when the month or year controls change."""
        month = self.cmb_month.currentIndex() + 1
        year = self.spin_year.value()
        self.calendar.setCurrentPage(year, month)

    def on_date_clicked(self, qdate: QDate) -> None:
        """Captures date clicked on the grid and confirms dialog."""
        self.selected_date_str = qdate.toString(self.date_format)
        self.accept()

    def select_today(self) -> None:
        """Sets date to system current date and confirms dialog."""
        self.selected_date_str = QDate.currentDate().toString(self.date_format)
        self.accept()

    def clear_date(self) -> None:
        """Empties the date value and confirms dialog."""
        self.selected_date_str = ""
        self.accept()


class DatePickerEdit(QWidget):
    """Compound widget presenting an editable text field paired with a popup calendar button."""

    def __init__(
        self, 
        placeholder: str = "YYYY-MM-DD", 
        date_format: str = "yyyy-MM-dd", 
        default_today: bool = False, 
        parent: Optional[QWidget] = None
    ):
        super().__init__(parent)
        self.date_format = date_format

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # Direct text entry field
        self.txt_date = QLineEdit()
        self.txt_date.setPlaceholderText(placeholder)
        if default_today:
            self.txt_date.setText(QDate.currentDate().toString(self.date_format))

        # Popup calendar button
        self.btn_picker = QPushButton("📅")
        self.btn_picker.setFixedWidth(36)
        self.btn_picker.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_picker.setToolTip("Click to open calendar")
        self.btn_picker.clicked.connect(self.open_calendar)

        layout.addWidget(self.txt_date)
        layout.addWidget(self.btn_picker)

    def open_calendar(self) -> None:
        """Displays the popup calendar positioned directly under the input field."""
        dialog = CalendarDialog(
            current_date_str=self.txt_date.text().strip(),
            date_format=self.date_format,
            parent=self
        )
        pos = self.mapToGlobal(self.rect().bottomLeft())
        dialog.move(pos)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.txt_date.setText(dialog.selected_date_str)

    def text(self) -> str:
        """Returns the current date string."""
        return self.txt_date.text().strip()

    def setText(self, val: str) -> None:
        """Sets the date string."""
        self.txt_date.setText(val)

    def setFixedHeight(self, h: int) -> None:
        """Synchronizes heights across the container, line edit, and calendar button."""
        super().setFixedHeight(h)
        self.txt_date.setFixedHeight(h)
        self.btn_picker.setFixedHeight(h)

    def setStyleSheet(self, style: str) -> None:
        """Applies input styling to the internal QLineEdit and styles the companion button."""
        self.txt_date.setStyleSheet(style)
        self.btn_picker.setStyleSheet("""
            QPushButton {
                background-color: #313244;
                color: #89B4FA;
                border: 1px solid #45475A;
                border-radius: 5px;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #45475A;
                color: #A6E3A1;
            }
        """)