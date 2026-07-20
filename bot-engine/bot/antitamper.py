"""
Anti-Tampering Module
Detects if the .exe or its files have been modified/tampered with.
Prevents users from bypassing the license system by modifying files.
"""
from __future__ import annotations

import hashlib
import os
import sys
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def _is_frozen() -> bool:
    """Check if running as PyInstaller .exe (frozen) vs Python script."""
    return getattr(sys, "frozen", False)


def get_exe_hash() -> str:
    """Get SHA256 hash of the running .exe file.
    Returns empty string if not running as .exe."""
    if not _is_frozen():
        return ""
    try:
        exe_path = sys.executable
        h = hashlib.sha256()
        with open(exe_path, "rb") as f:
            while True:
                chunk = f.read(8192)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()[:32]
    except Exception as e:
        logger.warning(f"Could not hash exe: {e}")
        return ""


def check_integrity() -> dict:
    """Run integrity checks. Returns dict with 'ok' bool and 'warnings' list."""
    warnings = []
    ok = True

    # Check 1: Are we running as frozen .exe?
    if not _is_frozen():
        warnings.append("Running in dev mode (not .exe) - license protection weak")
        # This is OK during development

    # Check 2: licenses.dat should not be readable as plain text
    licenses_file = Path("licenses.dat")
    if licenses_file.exists():
        try:
            with open(licenses_file, "rb") as f:
                header = f.read(4)
            if header != b"ENC1":
                warnings.append("licenses.dat is NOT encrypted! Someone may have tampered.")
                ok = False
        except Exception:
            pass

    # Check 3: config.json should be valid JSON (not tampered)
    config_file = Path("config.json")
    if config_file.exists():
        try:
            import json
            with open(config_file, "r", encoding="utf-8") as f:
                json.load(f)
        except Exception as e:
            warnings.append(f"config.json corrupted: {e}")
            # Not fatal - we'll just reset to defaults

    # Check 4: .local_activation.dat should be encrypted (if exists)
    local_file = Path(".local_activation.dat")
    if local_file.exists():
        try:
            with open(local_file, "rb") as f:
                header = f.read(4)
            if header != b"ENC1":
                warnings.append(".local_activation.dat is NOT encrypted - tampered!")
                ok = False
        except Exception:
            pass

    return {"ok": ok, "warnings": warnings, "exe_hash": get_exe_hash()}


def is_debugger_present() -> bool:
    """Detect if a debugger is attached (basic check).
    Advanced users can bypass this, but it stops casual reverse engineering."""
    try:
        import sys
        # sys.tracehooklimit is set when tracing
        if sys.gettrace() is not None:
            return True
        # Check common debug indicators on Windows
        if os.name == "nt":
            try:
                import ctypes
                is_debugger = ctypes.windll.kernel32.IsDebuggerPresent()
                if is_debugger:
                    return True
            except Exception:
                pass
        return False
    except Exception:
        return False
