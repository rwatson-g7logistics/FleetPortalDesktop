"""
utils/vin_validator.py
----------------------
Centralized VIN validation and sanitization engine for G7 Fleet Portal Desktop.
Enforces federal/ISO 3779 standards, filters prohibited characters (I, O, Q),
blocks unassigned WMI regions ('0'), and verifies Make-to-WMI manufacturer patterns.
"""

import re
from typing import Tuple, Optional, Dict

# Allowed World Manufacturer Identifier (WMI) prefixes per commercial fleet make
MAKE_WMI_RULES: Dict[str, Tuple[str, ...]] = {
    # --- Commercial Cargo & Passenger Vans ---
    "Ford": ("1F", "2F", "3F", "NM"),             # USA (1F), Canada (2F), Mexico (3F), Turkey Transit Connect (NM)
    "Ram": ("1C", "2C", "3C"),                     # Saltillo Mexico (3C6 ProMaster), USA (1C), Canada (2C)
    "Mercedes-Benz": ("W", "4J", "55"),            # Germany (WD3/WD4/W1V Sprinter/Metris), Charleston SC (4JG/55S)
    "Chevrolet": ("1G", "2G", "3G"),               # Express Van (1GC/1GB), Canada/Mexico commercial cutaways
    "GMC": ("1G", "2G", "3G"),                     # Savana Van (1GT/1GD)
    "Nissan": ("1N", "3N", "JN"),                  # NV200 / NV2500 / NV3500 (USA 1N6/1N4, Japan JN)
    
    # --- Walk-In Step Vans & Heavy Box Trucks ---
    "Freightliner": ("1F", "4U", "2U", "3A"),      # FCCC Step Vans (4UZ MT45/MT55), Heavy commercial (1FV)
    "Morgan Olson": ("4M", "5M"),                  # Walk-in step van bodies (Sturgis / Virginia plants)
    "Workhorse": ("54", "1W"),                     # Step vans and electric chassis (54D/1WT)
    "International": ("1H", "2H", "3H", "4H"),     # Navistar medium-duty cutaways and DuraStar/MV box trucks
    "Isuzu": ("JA", "J8", "4A"),                   # NPR / NQR / NRR cab-over box trucks
    "Hino": ("5P", "JH"),                          # Toyota commercial truck division (USA 5PV, Japan JH)
    
    # --- Electric Delivery Vehicles (Last-Mile Fleet Additions) ---
    "Rivian": ("7F", "7P"),                        # EDV 500 / EDV 700 delivery vans (Normal, IL plant)
    "BrightDrop": ("1G", "2G"),                    # GM Zevo 600 / Zevo 400 delivery vans (CAMI Ingersoll)
}

def clean_vin(raw_vin: str) -> str:
    """Strips whitespace, control characters, and non-standard symbols."""
    if not raw_vin:
        return ""
    return re.sub(r'[^A-HJ-NPR-Z0-9]', '', str(raw_vin).upper())


# utils/vin_validator.py

def validate_vin(raw_vin: str, make: Optional[str] = None) -> Tuple[bool, str, str]:
    candidate = str(raw_vin or "").strip().upper()

    if not candidate:
        return False, "", "VIN number is required."

    # 1. Check for ISO/NHTSA prohibited letters (I, O, Q)
    banned_chars = [c for c in candidate if c in ('I', 'O', 'Q')]
    if banned_chars:
        bad_set = ", ".join(sorted(set(banned_chars)))
        return (
            False,
            candidate,
            f"Standard VINs cannot contain the letters 'I', 'O', or 'Q' (banned to avoid confusion with numbers 1 and 0).\n\n"
            f"Detected prohibited character(s): {bad_set}\n"
            f"Entered VIN: '{candidate}'"
        )

    # 2. Enforce exact 17-character sanitized length
    sanitized = clean_vin(candidate)
    if len(sanitized) != 17:
        return (
            False,
            sanitized,
            f"VIN must be exactly 17 characters.\n\n"
            f"Current length: {len(sanitized)} characters\n"
            f"Entered: '{candidate}'"
        )

    # 3. Block leading '0' (unassigned international WMI region)
    if sanitized.startswith('0'):
        return (
            False,
            sanitized,
            f"VIN cannot begin with '0'. Please enter a valid 17-character VIN.\n\n"
            f"Entered: '{sanitized}'"
        )

    # 4. Validate WMI prefix against selected vehicle make
    clean_make = str(make or "").strip()
    if clean_make in MAKE_WMI_RULES:
        allowed_prefixes = MAKE_WMI_RULES[clean_make]
        if not any(sanitized.startswith(pfx) for pfx in allowed_prefixes):
            pfx_str = ", ".join([f"'{p}'" for p in allowed_prefixes])
            return (
                False,
                sanitized,
                f"The entered VIN does not match the manufacturer pattern for <b>{clean_make}</b>.<br><br>"
                f"• Entered VIN: <b>{sanitized}</b> (Starts with '{sanitized[:2]}')<br>"
                f"• Expected prefixes for {clean_make}: <b>{pfx_str}</b><br><br>"
                f"Please verify that the correct vehicle <b>Make</b> and <b>VIN</b> were entered."
            )

    return True, sanitized, ""