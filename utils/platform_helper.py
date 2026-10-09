"""
FleetPortalDesktop/utils/platform_helper.py
------------------------
Platform utility helper for G7 Fleet Command Center Desktop.
Handles OS identification, cross-platform path resolution, 
and system-specific configuration directories.
"""

import sys
import os
from pathlib import Path


def get_platform_name() -> str:
    """Returns a simplified string indicating the current operating system."""
    if sys.platform == "win32":
        return "Windows"
    elif sys.platform == "darwin":
        return "macOS"
    else:
        return "Linux"


def get_app_data_directory() -> Path:
    """
    Returns the OS-appropriate local directory for caching SQLite database files,
    logs, and temporary assets.
    
    Windows: %LOCALAPPDATA%\\G7FleetCommand
    macOS:   ~/Library/Application Support/G7FleetCommand
    """
    if sys.platform == "win32":
        base_dir = Path(os.environ.get("LOCALAPPDATA", Path.home()))
    elif sys.platform == "darwin":
        base_dir = Path.home() / "Library" / "Application Support"
    else:
        base_dir = Path.home() / ".config"

    app_dir = base_dir / "G7FleetCommand"
    app_dir.mkdir(parents=True, exist_ok=True)
    return app_dir


def get_default_font_family() -> str:
    """Returns standard system fonts matching native OS aesthetics."""
    if sys.platform == "darwin":
        return ".AppleSystemUIFont"  # macOS SF Pro default
    elif sys.platform == "win32":
        return "Segoe UI"            # Windows standard font
    else:
        return "DejaVu Sans"