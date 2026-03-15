#!/usr/bin/env python3
"""
SMART Feature Diagnostic Tool
Analyzes Self-Monitoring, Analysis, and Reporting Technology (SMART) data
for all storage devices regardless of interface type (SATA, USB, NVMe, SAS, etc.)
"""

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

# ─────────────────────────────────────────────
# ANSI colour helpers (no external deps)
# ─────────────────────────────────────────────
COLORS = {
    "reset": "\033[0m", "bold": "\033[1m",
    "red": "\033[91m", "green": "\033[92m",
    "yellow": "\033[93m", "blue": "\033[94m",
    "cyan": "\033[96m", "white": "\033[97m",
    "grey": "\033[90m",
}

def colorize(text: str, *styles: str, no_color: bool = False) -> str:
    if no_color or not sys.stdout.isatty():
        return text
    prefix = "".join(COLORS.get(s, "") for s in styles)
    return f"{prefix}{text}{COLORS['reset']}"

# ─────────────────────────────────────────────
# SMART attribute reference table
# ─────────────────────────────────────────────
SMART_ATTR_INFO: dict[int, dict] = {
    1:   {"name": "Raw Read Error Rate",          "critical": True,  "lower_better": True},
    2:   {"name": "Throughput Performance",        "critical": False, "lower_better": False},
    3:   {"name": "Spin-Up Time",                 "critical": False, "lower_better": True},
    4:   {"name": "Start/Stop Count",             "critical": False, "lower_better": False},
    5:   {"name": "Reallocated Sector Count",      "critical": True,  "lower_better": True},
    7:   {"name": "Seek Error Rate",              "critical": True,  "lower_better": True},
    8:   {"name": "Seek Time Performance",        "critical": False, "lower_better": False},
    9:   {"name": "Power-On Hours",               "critical": False, "lower_better": False},
    10:  {"name": "Spin Retry Count",             "critical": True,  "lower_better": True},
    11:  {"name": "Calibration Retry Count",      "critical": False, "lower_better": True},
    12:  {"name": "Power Cycle Count",            "critical": False, "lower_better": False},
    13:  {"name": "Read Soft Error Rate",         "critical": False, "lower_better": True},
    22:  {"name": "Current Helium Level",         "critical": True,  "lower_better": False},
    100: {"name": "Erase/Program Cycles",         "critical": False, "lower_better": False},
    160: {"name": "Uncorrectable Sector Count",   "critical": True,  "lower_better": True},
    161: {"name": "Valid Spare Block Count",      "critical": True,  "lower_better": False},
    163: {"name": "Initial Invalid Block Count",  "critical": False, "lower_better": True},
    164: {"name": "Total Erase Count",            "critical": False, "lower_better": False},
    165: {"name": "Max Erase Count",              "critical": False, "lower_better": False},
    166: {"name": "Min Erase Count",              "critical": False, "lower_better": False},
    167: {"name": "Average Erase Count",          "critical": False, "lower_better": False},
    168: {"name": "Max Erase Count of Spec",      "critical": False, "lower_better": False},
    169: {"name": "Remaining Life Percentage",    "critical": True,  "lower_better": False},
    170: {"name": "Available Reserved Space",     "critical": True,  "lower_better": False},
    171: {"name": "SSD Program Fail Count",       "critical": True,  "lower_better": True},
    172: {"name": "SSD Erase Fail Count",         "critical": True,  "lower_better": True},
    173: {"name": "SSD Wear Leveling Count",      "critical": True,  "lower_better": True},
    174: {"name": "Unexpected Power Loss Count",  "critical": False, "lower_better": True},
    175: {"name": "Power Loss Protection Failure","critical": True,  "lower_better": True},
    176: {"name": "Erase Fail Count (chip)",      "critical": True,  "lower_better": True},
    177: {"name": "Wear Leveling Count",          "critical": True,  "lower_better": True},
    178: {"name": "Used Reserved Block Count",    "critical": True,  "lower_better": True},
    179: {"name": "Used Reserved Block Count Total","critical": True,"lower_better": True},
    180: {"name": "Unused Reserved Block Count",  "critical": True,  "lower_better": False},
    181: {"name": "Program Fail Count Total",     "critical": True,  "lower_better": True},
    182: {"name": "Erase Fail Count Total",       "critical": True,  "lower_better": True},
    183: {"name": "Runtime Bad Block Total",      "critical": True,  "lower_better": True},
    184: {"name": "End-to-End Error Count",       "critical": True,  "lower_better": True},
    185: {"name": "Head Stability",               "critical": False, "lower_better": False},
    186: {"name": "Induced Op-Vibration Detection","critical": False,"lower_better": True},
    187: {"name": "Reported Uncorrectable Errors","critical": True,  "lower_better": True},
    188: {"name": "Command Timeout",              "critical": True,  "lower_better": True},
    189: {"name": "High Fly Writes",              "critical": False, "lower_better": True},
    190: {"name": "Airflow Temperature",          "critical": False, "lower_better": False},
    191: {"name": "G-Sense Error Rate",           "critical": False, "lower_better": True},
    192: {"name": "Unsafe Shutdown Count",        "critical": False, "lower_better": True},
    193: {"name": "Load Cycle Count",             "critical": False, "lower_better": False},
    194: {"name": "Temperature",                  "critical": False, "lower_better": False},
    195: {"name": "Hardware ECC Recovered",       "critical": False, "lower_better": False},
    196: {"name": "Reallocation Event Count",     "critical": True,  "lower_better": True},
    197: {"name": "Current Pending Sector Count", "critical": True,  "lower_better": True},
    198: {"name": "Offline Uncorrectable Sectors","critical": True,  "lower_better": True},
    199: {"name": "UDMA CRC Error Count",         "critical": True,  "lower_better": True},
    200: {"name": "Multi-Zone Error Rate",        "critical": True,  "lower_better": True},
    201: {"name": "Soft Read Error Rate",         "critical": False, "lower_better": True},
    202: {"name": "Data Address Mark Errors",     "critical": False, "lower_better": True},
    203: {"name": "Run Out Cancel",               "critical": False, "lower_better": True},
    204: {"name": "Soft ECC Correction",          "critical": False, "lower_better": True},
    205: {"name": "Thermal Asperity Rate",        "critical": False, "lower_better": True},
    206: {"name": "Flying Height",                "critical": False, "lower_better": False},
    207: {"name": "Spin High Current",            "critical": False, "lower_better": True},
    208: {"name": "Spin Buzz",                    "critical": False, "lower_better": True},
    209: {"name": "Offline Seek Performance",     "critical": False, "lower_better": False},
    210: {"name": "Vibration During Write",       "critical": False, "lower_better": True},
    211: {"name": "Vibration During Read",        "critical": False, "lower_better": True},
    212: {"name": "Shock During Write",           "critical": False, "lower_better": True},
    220: {"name": "Disk Shift",                   "critical": False, "lower_better": True},
    221: {"name": "G-Sense Error Rate",           "critical": False, "lower_better": True},
    222: {"name": "Loaded Hours",                 "critical": False, "lower_better": False},
    223: {"name": "Load/Unload Retry Count",      "critical": False, "lower_better": True},
    224: {"name": "Load Friction",                "critical": False, "lower_better": True},
    225: {"name": "Load/Unload Cycle Count",      "critical": False, "lower_better": False},
    226: {"name": "Load-in Time",                 "critical": False, "lower_better": False},
    227: {"name": "Torque Amplification Count",   "critical": False, "lower_better": True},
    228: {"name": "Power-Off Retract Cycle",      "critical": False, "lower_better": False},
    230: {"name": "Drive Life Protection Status", "critical": True,  "lower_better": False},
    231: {"name": "Life Left (SSD)",              "critical": True,  "lower_better": False},
    232: {"name": "Available Reserved Space",     "critical": True,  "lower_better": False},
    233: {"name": "Media Wearout Indicator",      "critical": True,  "lower_better": False},
    234: {"name": "Average erase count",          "critical": False, "lower_better": False},
    235: {"name": "Good Block Count",             "critical": True,  "lower_better": False},
    240: {"name": "Head Flying Hours",            "critical": False, "lower_better": False},
    241: {"name": "Total LBAs Written",           "critical": False, "lower_better": False},
    242: {"name": "Total LBAs Read",              "critical": False, "lower_better": False},
    243: {"name": "Total LBAs Written Expanded",  "critical": False, "lower_better": False},
    244: {"name": "Total LBAs Read Expanded",     "critical": False, "lower_better": False},
    249: {"name": "NAND Writes (1GiB)",           "critical": False, "lower_better": False},
    250: {"name": "Read Error Retry Rate",        "critical": False, "lower_better": True},
    251: {"name": "Minimum Spares Remaining",     "critical": True,  "lower_better": False},
    252: {"name": "Newly Added Bad Flash Block",  "critical": True,  "lower_better": True},
    254: {"name": "Free Fall Protection",         "critical": False, "lower_better": True},
}

# Critical thresholds for warnings
CRITICAL_ATTR_THRESHOLDS: dict[int, int] = {
    5:   0,    # Reallocated sectors — any non-zero is concerning
    10:  0,    # Spin retry
    184: 0,    # End-to-end errors
    187: 0,    # Reported uncorrectable errors
    188: 0,    # Command timeouts
    196: 0,    # Reallocation events
    197: 0,    # Current pending sectors
    198: 0,    # Offline uncorrectable sectors
    199: 50,   # UDMA CRC errors — small number is OK
}

# ─────────────────────────────────────────────
# Data classes
# ─────────────────────────────────────────────
@dataclass
class SmartAttribute:
    attr_id: int
    name: str
    flags: str
    value: int
    worst: int
    threshold: int
    raw_value: int
    raw_string: str
    failed: str
    info: dict = field(default_factory=dict)

    @property
    def is_critical(self) -> bool:
        return self.info.get("critical", False)

    @property
    def status(self) -> str:
        """Return OK / WARNING / CRITICAL based on value vs threshold and raw value."""
        if self.failed and self.failed not in ("-", ""):
            return "CRITICAL"
        if self.threshold > 0 and self.value <= self.threshold:
            return "CRITICAL"
        # Additional raw-value checks for critical attributes
        threshold_raw = CRITICAL_ATTR_THRESHOLDS.get(self.attr_id)
        if threshold_raw is not None and self.raw_value > threshold_raw:
            return "WARNING"
        return "OK"


@dataclass
class NvmeAttribute:
    name: str
    value: str


@dataclass
class DeviceInfo:
    path: str
    model: str = "Unknown"
    serial: str = "Unknown"
    firmware: str = "Unknown"
    capacity_bytes: int = 0
    rpm: int = 0                 # 0 = SSD / NVMe
    interface: str = "Unknown"
    protocol: str = "Unknown"    # ATA, NVMe, SCSI, USB…
    form_factor: str = "Unknown"
    smart_supported: bool = False
    smart_enabled: bool = False
    smart_passed: Optional[bool] = None
    power_on_hours: int = 0
    power_cycles: int = 0
    temperature: int = 0
    attributes: list[SmartAttribute] = field(default_factory=list)
    nvme_attributes: list[NvmeAttribute] = field(default_factory=list)
    test_results: list[dict] = field(default_factory=list)
    raw_json: dict = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    # ── derived ──────────────────────────────
    @property
    def capacity_gb(self) -> float:
        return round(self.capacity_bytes / 1e9, 1) if self.capacity_bytes else 0.0

    @property
    def is_ssd(self) -> bool:
        return self.rpm == 0 and self.protocol not in ("NVMe",)

    @property
    def is_nvme(self) -> bool:
        return self.protocol == "NVMe"

    @property
    def is_hdd(self) -> bool:
        return self.rpm > 0

    @property
    def health_score(self) -> int:
        """0–100 health score derived from SMART attributes."""
        if not self.smart_supported:
            return -1
        if self.smart_passed is False:
            return 0

        score = 100
        for attr in self.attributes:
            s = attr.status
            if s == "CRITICAL":
                score -= 30 if attr.is_critical else 15
            elif s == "WARNING":
                score -= 10 if attr.is_critical else 5
        return max(0, min(100, score))

    @property
    def critical_attributes(self) -> list[SmartAttribute]:
        return [a for a in self.attributes if a.status != "OK"]

    @property
    def power_on_duration(self) -> str:
        if not self.power_on_hours:
            return "N/A"
        td = timedelta(hours=self.power_on_hours)
        days = td.days
        years, rem_days = divmod(days, 365)
        parts = []
        if years:
            parts.append(f"{years}y")
        if rem_days:
            parts.append(f"{rem_days}d")
        parts.append(f"{td.seconds // 3600}h")
        return " ".join(parts)


# ─────────────────────────────────────────────
# Device discovery
# ─────────────────────────────────────────────

def _run(cmd: list[str], timeout: int = 30) -> tuple[int, str, str]:
    """Run a command, return (returncode, stdout, stderr)."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except FileNotFoundError:
        return -1, "", f"Command not found: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return -1, "", f"Command timed out: {' '.join(cmd)}"


def check_smartctl() -> bool:
    rc, out, _ = _run(["smartctl", "--version"])
    return rc == 0


def discover_devices(include_usb: bool = True, extra_args: list[str] | None = None) -> list[str]:
    """Return a list of device paths using smartctl --scan-open."""
    args = ["smartctl", "--scan-open"]
    if extra_args:
        args += extra_args
    rc, out, err = _run(args)
    devices: list[str] = []
    if rc not in (0, 1, 2, 4):   # smartctl uses bitmask exit codes
        # fallback: scan common paths
        for pat in ["/dev/sd?", "/dev/nvme?", "/dev/hd?"]:
            import glob
            devices.extend(glob.glob(pat))
        return sorted(set(devices))

    for line in out.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        dev = line.split()[0]
        if not include_usb and "usb" in line.lower():
            continue
        devices.append(dev)

    # Also pick up NVMe drives via /dev/nvme* if not already found
    import glob
    for nv in glob.glob("/dev/nvme[0-9]"):
        if nv not in devices:
            devices.append(nv)

    return sorted(set(devices))


# ─────────────────────────────────────────────
# SMART data parsing
# ─────────────────────────────────────────────

def _parse_attributes(ata_attrs: list[dict]) -> list[SmartAttribute]:
    attrs: list[SmartAttribute] = []
    for entry in ata_attrs:
        attr_id = entry.get("id", 0)
        info = SMART_ATTR_INFO.get(attr_id, {})
        raw = entry.get("raw", {})
        raw_val = raw.get("value", 0) if isinstance(raw, dict) else 0
        raw_str = raw.get("string", str(raw_val)) if isinstance(raw, dict) else str(raw_val)
        attrs.append(SmartAttribute(
            attr_id=attr_id,
            name=entry.get("name", info.get("name", f"Attr {attr_id}")),
            flags=entry.get("flags", {}).get("string", "------") if isinstance(entry.get("flags"), dict) else str(entry.get("flags", "")),
            value=entry.get("value", 0),
            worst=entry.get("worst", 0),
            threshold=entry.get("thresh", 0),
            raw_value=raw_val,
            raw_string=raw_str,
            failed=str(entry.get("when_failed", "-")),
            info=info,
        ))
    return attrs


def _parse_nvme_attrs(nvme_health: dict) -> list[NvmeAttribute]:
    mapping = [
        ("critical_warning",              "Critical Warning"),
        ("temperature",                   "Temperature (°C)"),
        ("available_spare",               "Available Spare (%)"),
        ("available_spare_threshold",     "Available Spare Threshold (%)"),
        ("percentage_used",               "Percentage Used (%)"),
        ("data_units_read",               "Data Units Read"),
        ("data_units_written",            "Data Units Written"),
        ("host_reads",                    "Host Read Commands"),
        ("host_writes",                   "Host Write Commands"),
        ("controller_busy_time",          "Controller Busy Time (min)"),
        ("power_cycles",                  "Power Cycles"),
        ("power_on_hours",                "Power-On Hours"),
        ("unsafe_shutdowns",              "Unsafe Shutdowns"),
        ("media_errors",                  "Media & Data Integrity Errors"),
        ("num_err_log_entries",           "Number of Error Log Entries"),
        ("warning_temp_time",             "Warning Composite Temp Time (min)"),
        ("critical_comp_time",            "Critical Composite Temp Time (min)"),
    ]
    result: list[NvmeAttribute] = []
    for key, label in mapping:
        val = nvme_health.get(key)
        if val is not None:
            result.append(NvmeAttribute(name=label, value=str(val)))
    return result


def get_device_info(device: str, all_attrs: bool = False,
                    usb_workaround: bool = True) -> DeviceInfo:
    """Query smartctl for a single device and return a DeviceInfo object."""
    info = DeviceInfo(path=device)

    # Build smartctl command
    cmd = ["smartctl", "-a", "--json=c", device]
    if usb_workaround:
        # Attempt USB passthrough first; fall back to plain if needed
        cmd_usb = ["smartctl", "-a", "--json=c", "-d", "sat", device]
    else:
        cmd_usb = cmd

    rc, out, err = _run(cmd)

    # If device is USB and ATA passthrough needed
    if rc != 0 and "USB" in err.upper():
        rc, out, err = _run(cmd_usb)

    if not out.strip():
        info.errors.append(f"No output from smartctl: {err.strip()}")
        return info

    try:
        data = json.loads(out)
    except json.JSONDecodeError as e:
        info.errors.append(f"JSON parse error: {e}")
        return info

    info.raw_json = data

    # ── Basic info ──────────────────────────
    dev_info = data.get("device", {})
    info.interface = dev_info.get("type", "Unknown")
    info.protocol  = dev_info.get("protocol", info.interface)

    model_info = data.get("model_family", "") or data.get("model_name", "Unknown")
    info.model    = data.get("model_name", model_info) or "Unknown"
    info.serial   = data.get("serial_number", "Unknown")
    info.firmware = data.get("firmware_version", "Unknown")
    info.capacity_bytes = (data.get("user_capacity") or {}).get("bytes", 0)
    info.form_factor = (data.get("form_factor") or {}).get("name", "Unknown")

    rotation = data.get("rotation_rate", 0)
    if isinstance(rotation, int):
        info.rpm = rotation  # 0 = SSD

    # ── SMART support / enabled ─────────────
    smart_status = data.get("smart_support", {})
    info.smart_supported = smart_status.get("available", False)
    info.smart_enabled   = smart_status.get("enabled", False)

    overall = data.get("smart_status", {})
    passed = overall.get("passed")
    if passed is not None:
        info.smart_passed = bool(passed)

    # ── Temperature ─────────────────────────
    temp = data.get("temperature", {})
    if isinstance(temp, dict):
        info.temperature = temp.get("current", 0)

    # ── ATA attributes ───────────────────────
    ata_attrs = data.get("ata_smart_attributes", {}).get("table", [])
    info.attributes = _parse_attributes(ata_attrs)

    # Derive power-on hours / cycles from attributes if not in top-level
    for attr in info.attributes:
        if attr.attr_id == 9 and not info.power_on_hours:
            info.power_on_hours = attr.raw_value
        if attr.attr_id == 12 and not info.power_cycles:
            info.power_cycles = attr.raw_value

    # Also check top-level fields (NVMe)
    nvme_health = data.get("nvme_smart_health_information_log", {})
    if nvme_health:
        info.nvme_attributes = _parse_nvme_attrs(nvme_health)
        info.power_on_hours  = nvme_health.get("power_on_hours",  info.power_on_hours)
        info.power_cycles    = nvme_health.get("power_cycles",    info.power_cycles)
        info.temperature     = nvme_health.get("temperature",     info.temperature)

    # ── Self-test log ────────────────────────
    test_log = data.get("ata_smart_self_test_log", {}).get("standard", {}).get("table", [])
    info.test_results = test_log[:5]  # most recent 5

    return info


# ─────────────────────────────────────────────
# Output formatters
# ─────────────────────────────────────────────

def _health_bar(score: int, width: int = 20, no_color: bool = False) -> str:
    if score < 0:
        return colorize("[N/A]", "grey", no_color=no_color)
    filled = round(score / 100 * width)
    bar = "#" * filled + "-" * (width - filled)
    style = "green" if score >= 70 else ("yellow" if score >= 40 else "red")
    return colorize(f"[{bar}] {score:3d}%", style, "bold", no_color=no_color)


def _status_badge(status: str, no_color: bool = False) -> str:
    color_map = {"OK": "green", "WARNING": "yellow", "CRITICAL": "red",
                 "PASSED": "green", "FAILED": "red", "UNKNOWN": "grey"}
    color = color_map.get(status, "grey")
    return colorize(f"[{status}]", color, "bold", no_color=no_color)


def _divider(char: str = "─", width: int = 78, no_color: bool = False) -> str:
    return colorize(char * width, "grey", no_color=no_color)


def format_text(devices: list[DeviceInfo], show_all_attrs: bool = False,
                show_raw_json: bool = False, no_color: bool = False) -> str:
    lines: list[str] = []
    bold = lambda t: colorize(t, "bold", no_color=no_color)
    cyan = lambda t: colorize(t, "cyan", "bold", no_color=no_color)

    lines.append(bold("=" * 78))
    lines.append(cyan("  SMART STORAGE DEVICE DIAGNOSTIC REPORT"))
    lines.append(bold(f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"))
    lines.append(bold("=" * 78))
    lines.append("")

    for idx, dev in enumerate(devices, 1):
        lines.append(_divider("─", no_color=no_color))
        lines.append(cyan(f"  Device {idx}: {dev.path}"))
        lines.append(_divider("─", no_color=no_color))

        # Identity
        dev_type = "NVMe SSD" if dev.is_nvme else ("SSD" if dev.is_ssd else f"HDD ({dev.rpm} RPM)")
        lines.append(f"  Model      : {bold(dev.model)}")
        lines.append(f"  Serial     : {dev.serial}")
        lines.append(f"  Firmware   : {dev.firmware}")
        lines.append(f"  Interface  : {dev.interface}  Protocol: {dev.protocol}  Type: {dev_type}")
        lines.append(f"  Capacity   : {dev.capacity_gb} GB  Form Factor: {dev.form_factor}")
        lines.append(f"  Temperature: {dev.temperature}°C")
        lines.append(f"  Power On   : {dev.power_on_duration}  ({dev.power_on_hours} hours)")
        lines.append(f"  Power Cycles: {dev.power_cycles}")
        lines.append("")

        # SMART status
        smart_avail = "Yes" if dev.smart_supported else "No"
        smart_enbl  = "Yes" if dev.smart_enabled   else "No"
        lines.append(f"  SMART Supported: {smart_avail}   Enabled: {smart_enbl}")

        if dev.smart_passed is None:
            overall_str = _status_badge("UNKNOWN", no_color)
        elif dev.smart_passed:
            overall_str = _status_badge("PASSED", no_color)
        else:
            overall_str = _status_badge("FAILED", no_color)
        lines.append(f"  SMART Overall Health: {overall_str}")

        hs = dev.health_score
        lines.append(f"  Health Score: {_health_bar(hs, no_color=no_color)}")
        lines.append("")

        # NVMe attributes
        if dev.nvme_attributes:
            lines.append(bold("  NVMe Health Information Log:"))
            for nv in dev.nvme_attributes:
                lines.append(f"    {nv.name:<40} {nv.value}")
            lines.append("")

        # ATA SMART attributes
        if dev.attributes:
            lines.append(bold("  SMART Attributes:"))
            header = f"  {'ID':>3}  {'Attribute':<38} {'Val':>5} {'Wst':>5} {'Thr':>5}  {'Raw Value':<18}  Status"
            lines.append(colorize(header, "grey", no_color=no_color))
            lines.append(colorize("  " + "-" * 96, "grey", no_color=no_color))

            for attr in dev.attributes:
                if not show_all_attrs and attr.status == "OK" and not attr.is_critical:
                    continue
                status_str = _status_badge(attr.status, no_color)
                flag_str = colorize(attr.flags[:6], "grey", no_color=no_color)
                line = (f"  {attr.attr_id:>3}  {attr.name:<38} {attr.value:>5} "
                        f"{attr.worst:>5} {attr.threshold:>5}  {attr.raw_string:<18}  {status_str}")
                lines.append(line)

            if show_all_attrs:
                pass  # already printed all
            else:
                hidden = sum(1 for a in dev.attributes
                             if a.status == "OK" and not a.is_critical)
                if hidden:
                    lines.append(colorize(
                        f"  … {hidden} healthy non-critical attributes hidden (use --all-attrs to show)",
                        "grey", no_color=no_color))
            lines.append("")

        # Self-test history
        if dev.test_results:
            lines.append(bold("  Recent Self-Test Results (latest 5):"))
            header2 = f"  {'#':>3}  {'Type':<20} {'Status':<25} {'Remaining':>9}  {'LBA':>12}"
            lines.append(colorize(header2, "grey", no_color=no_color))
            lines.append(colorize("  " + "-" * 74, "grey", no_color=no_color))
            for i, t in enumerate(dev.test_results, 1):
                st = t.get("status", {})
                sname = st.get("string", "Unknown")
                spass = st.get("passed", None)
                badge = _status_badge("OK" if spass else ("WARNING" if spass is None else "CRITICAL"), no_color)
                rem   = t.get("remaining_percent", 0)
                lba   = t.get("failing_lba", 0)
                ttype = t.get("type", {}).get("string", "?")
                lines.append(f"  {i:>3}  {ttype:<20} {sname:<25} {rem:>8}%  {lba:>12}")
            lines.append("")

        # Errors / warnings
        if dev.errors:
            lines.append(colorize("  Errors encountered:", "yellow", "bold", no_color=no_color))
            for e in dev.errors:
                lines.append(colorize(f"    ! {e}", "yellow", no_color=no_color))
            lines.append("")

        # Critical flags summary
        crit = dev.critical_attributes
        if crit:
            lines.append(colorize("  ⚠  Attributes requiring attention:", "red", "bold", no_color=no_color))
            for attr in crit:
                lines.append(colorize(
                    f"     • [{attr.status}] ID {attr.attr_id:>3} – {attr.name}  (raw={attr.raw_string})",
                    "red" if attr.status == "CRITICAL" else "yellow", no_color=no_color))
            lines.append("")

        if show_raw_json and dev.raw_json:
            lines.append(bold("  Raw JSON (truncated top-level keys):"))
            for k, v in dev.raw_json.items():
                if k in ("ata_smart_attributes", "nvme_smart_health_information_log"):
                    continue
                lines.append(f"    {k}: {json.dumps(v)[:120]}")
            lines.append("")

    lines.append(_divider("=", no_color=no_color))
    lines.append(bold(f"  Scanned {len(devices)} device(s)"))
    lines.append(_divider("=", no_color=no_color))
    return "\n".join(lines)


def format_json(devices: list[DeviceInfo]) -> str:
    def _to_dict(dev: DeviceInfo) -> dict:
        return {
            "path": dev.path,
            "model": dev.model,
            "serial": dev.serial,
            "firmware": dev.firmware,
            "interface": dev.interface,
            "protocol": dev.protocol,
            "capacity_gb": dev.capacity_gb,
            "form_factor": dev.form_factor,
            "rpm": dev.rpm,
            "type": "nvme" if dev.is_nvme else ("ssd" if dev.is_ssd else "hdd"),
            "temperature_c": dev.temperature,
            "power_on_hours": dev.power_on_hours,
            "power_cycles": dev.power_cycles,
            "smart_supported": dev.smart_supported,
            "smart_enabled": dev.smart_enabled,
            "smart_passed": dev.smart_passed,
            "health_score": dev.health_score,
            "attributes": [
                {
                    "id": a.attr_id,
                    "name": a.name,
                    "value": a.value,
                    "worst": a.worst,
                    "threshold": a.threshold,
                    "raw_value": a.raw_value,
                    "raw_string": a.raw_string,
                    "status": a.status,
                    "critical": a.is_critical,
                }
                for a in dev.attributes
            ],
            "nvme_attributes": [
                {"name": n.name, "value": n.value} for n in dev.nvme_attributes
            ],
            "critical_attributes": [
                {
                    "id": a.attr_id,
                    "name": a.name,
                    "status": a.status,
                    "raw_value": a.raw_value,
                }
                for a in dev.critical_attributes
            ],
            "errors": dev.errors,
        }
    return json.dumps(
        {"generated": datetime.now().isoformat(), "devices": [_to_dict(d) for d in devices]},
        indent=2
    )


def format_csv(devices: list[DeviceInfo]) -> str:
    import csv, io
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["path", "model", "serial", "protocol", "type", "capacity_gb",
                "temperature_c", "power_on_hours", "power_cycles", "health_score",
                "smart_passed", "critical_attrs"])
    for dev in devices:
        w.writerow([
            dev.path, dev.model, dev.serial, dev.protocol,
            "nvme" if dev.is_nvme else ("ssd" if dev.is_ssd else "hdd"),
            dev.capacity_gb, dev.temperature, dev.power_on_hours, dev.power_cycles,
            dev.health_score, dev.smart_passed,
            ";".join(f"ID{a.attr_id}:{a.name}={a.raw_string}" for a in dev.critical_attributes),
        ])
    return buf.getvalue()


def format_html(devices: list[DeviceInfo]) -> str:
    status_color = {"OK": "#4caf50", "WARNING": "#ff9800", "CRITICAL": "#f44336",
                    "PASSED": "#4caf50", "FAILED": "#f44336", "UNKNOWN": "#9e9e9e"}

    def badge(s: str) -> str:
        c = status_color.get(s, "#9e9e9e")
        return f'<span style="background:{c};color:#fff;padding:2px 6px;border-radius:3px;font-size:0.85em">{s}</span>'

    def score_color(s: int) -> str:
        if s < 0: return "#9e9e9e"
        if s >= 70: return "#4caf50"
        if s >= 40: return "#ff9800"
        return "#f44336"

    rows = ""
    for dev in devices:
        smart_badge = badge("PASSED" if dev.smart_passed else ("FAILED" if dev.smart_passed is False else "UNKNOWN"))
        hs = dev.health_score
        hs_style = f"color:{score_color(hs)};font-weight:bold"
        hs_str = f'<span style="{hs_style}">{hs}%</span>' if hs >= 0 else "N/A"

        crit_html = ""
        if dev.critical_attributes:
            crit_html = "<ul style='margin:0;padding-left:1em'>"
            for a in dev.critical_attributes:
                crit_html += f"<li>{badge(a.status)} ID {a.attr_id} – {a.name} (raw={a.raw_string})</li>"
            crit_html += "</ul>"
        else:
            crit_html = '<span style="color:#4caf50">None</span>'

        rows += f"""
        <tr>
          <td><code>{dev.path}</code></td>
          <td>{dev.model}</td>
          <td>{dev.serial}</td>
          <td>{dev.protocol}</td>
          <td>{"NVMe" if dev.is_nvme else ("SSD" if dev.is_ssd else f"HDD {dev.rpm}RPM")}</td>
          <td>{dev.capacity_gb} GB</td>
          <td>{dev.temperature}°C</td>
          <td>{dev.power_on_duration}</td>
          <td>{smart_badge}</td>
          <td>{hs_str}</td>
          <td>{crit_html}</td>
        </tr>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>SMART Diagnostic Report</title>
<style>
  body {{ font-family: 'Segoe UI', Arial, sans-serif; background:#1a1a2e; color:#e0e0e0; margin:0; padding:20px }}
  h1 {{ color:#90caf9; border-bottom:2px solid #1565c0; padding-bottom:8px }}
  .meta {{ color:#90a4ae; font-size:0.9em; margin-bottom:20px }}
  table {{ border-collapse:collapse; width:100%; font-size:0.9em }}
  th {{ background:#1565c0; color:#fff; padding:8px 12px; text-align:left }}
  tr:nth-child(even) {{ background:#0d0d1a }}
  tr:nth-child(odd)  {{ background:#12122a }}
  tr:hover {{ background:#1c2340 }}
  td {{ padding:7px 12px; border-bottom:1px solid #263238; vertical-align:top }}
  code {{ background:#263238; padding:1px 4px; border-radius:3px }}
</style>
</head>
<body>
<h1>SMART Storage Device Diagnostic Report</h1>
<p class="meta">Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} &nbsp;|&nbsp; Devices scanned: {len(devices)}</p>
<table>
  <thead>
    <tr>
      <th>Device</th><th>Model</th><th>Serial</th><th>Protocol</th><th>Type</th>
      <th>Capacity</th><th>Temp</th><th>Power-On</th><th>SMART</th>
      <th>Health</th><th>Issues</th>
    </tr>
  </thead>
  <tbody>{rows}</tbody>
</table>
</body>
</html>"""


# ─────────────────────────────────────────────
# Self-test runner
# ─────────────────────────────────────────────

def run_selftest(device: str, test_type: str = "short") -> bool:
    """Start a SMART self-test on the device."""
    valid = {"short", "long", "conveyance", "offline", "select"}
    if test_type not in valid:
        print(f"Invalid test type '{test_type}'. Valid: {', '.join(sorted(valid))}", file=sys.stderr)
        return False
    cmd = ["smartctl", "-t", test_type, device]
    rc, out, err = _run(cmd, timeout=10)
    print(out)
    if err:
        print(err, file=sys.stderr)
    return rc == 0


def poll_selftest(device: str, interval: int = 10, timeout: int = 600) -> bool:
    """Poll until the running self-test finishes."""
    deadline = time.time() + timeout
    print(f"Polling self-test on {device} (interval={interval}s, timeout={timeout}s)…")
    while time.time() < deadline:
        rc, out, _ = _run(["smartctl", "-a", "--json=c", device])
        try:
            data = json.loads(out)
        except json.JSONDecodeError:
            time.sleep(interval)
            continue
        status = (data.get("ata_smart_data", {})
                      .get("self_test", {})
                      .get("status", {})
                      .get("string", ""))
        pct = (data.get("ata_smart_data", {})
                   .get("self_test", {})
                   .get("status", {})
                   .get("remaining_percent", 0))
        print(f"  Self-test status: {status} (remaining {pct}%)")
        if "progress" not in status.lower() and "in progress" not in status.lower():
            return True
        time.sleep(interval)
    print("Timed out waiting for self-test to complete.", file=sys.stderr)
    return False


# ─────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="smart_diagnostic",
        description=(
            "SMART Storage Device Diagnostic Tool\n"
            "Supports SATA, USB (ATA passthrough), NVMe, SAS and other interfaces.\n"
            "Requires smartmontools (smartctl) to be installed."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                            Scan all devices, text report
  %(prog)s -d /dev/sda /dev/nvme0     Scan specific devices only
  %(prog)s --all-attrs                Show every SMART attribute (not just issues)
  %(prog)s -o json > report.json      Output as JSON
  %(prog)s -o html > report.html      Generate HTML report
  %(prog)s -o csv  > report.csv       Generate CSV summary
  %(prog)s --selftest short /dev/sda  Start a short self-test
  %(prog)s --selftest long  /dev/sda --poll  Run long test and wait
  %(prog)s --no-usb                   Skip USB devices
  %(prog)s --list                     Just list discovered devices
  %(prog)s --attr-id 5 187 197        Show only specific attribute IDs
  %(prog)s --score-threshold 70       Exit non-zero if any device scores below 70
""",
    )

    # Device selection
    sel = p.add_argument_group("Device selection")
    sel.add_argument("-d", "--device", dest="devices", metavar="DEV", nargs="+",
                     help="Specify device path(s) to scan instead of auto-discovery")
    sel.add_argument("--no-usb", action="store_true",
                     help="Exclude USB devices from scan")
    sel.add_argument("--list", action="store_true",
                     help="List discovered devices and exit (no SMART query)")

    # Output
    out = p.add_argument_group("Output control")
    out.add_argument("-o", "--output", choices=["text", "json", "csv", "html"],
                     default="text", help="Output format (default: text)")
    out.add_argument("--all-attrs", action="store_true",
                     help="Display every SMART attribute, not just flagged ones")
    out.add_argument("--attr-id", dest="attr_ids", metavar="ID", type=int, nargs="+",
                     help="Filter output to specific SMART attribute IDs")
    out.add_argument("--raw-json", action="store_true",
                     help="Append raw smartctl JSON keys to text report")
    out.add_argument("--no-color", action="store_true",
                     help="Disable ANSI color output")
    out.add_argument("--save", metavar="FILE",
                     help="Save report to FILE instead of stdout")

    # Self-test
    st = p.add_argument_group("Self-test")
    st.add_argument("--selftest", metavar="TYPE",
                    choices=["short", "long", "conveyance", "offline"],
                    help="Run a self-test on the specified device(s)")
    st.add_argument("--poll", action="store_true",
                    help="After starting a self-test, poll until completion")
    st.add_argument("--poll-interval", type=int, default=15, metavar="SECS",
                    help="Polling interval in seconds (default: 15)")
    st.add_argument("--poll-timeout", type=int, default=14400, metavar="SECS",
                    help="Max wait time for self-test completion in seconds (default: 14400 / 4 h)")

    # Thresholds / alerts
    thr = p.add_argument_group("Thresholds and alerting")
    thr.add_argument("--score-threshold", type=int, default=0, metavar="N",
                     help="Exit code 2 if any device health score falls below N (0-100)")
    thr.add_argument("--fail-on-warning", action="store_true",
                     help="Exit code 2 if any attribute has WARNING or CRITICAL status")

    # Misc
    misc = p.add_argument_group("Miscellaneous")
    misc.add_argument("--no-usb-workaround", action="store_true",
                      help="Disable SAT USB passthrough fallback")
    misc.add_argument("--info-only", action="store_true",
                      help="Print device identity only, skip SMART attributes")
    misc.add_argument("-v", "--verbose", action="store_true",
                      help="Show extra diagnostic output")

    return p


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    # ── Check smartctl ──────────────────────
    if not check_smartctl():
        print("ERROR: smartctl not found. Install smartmontools:\n"
              "  Ubuntu/Debian : sudo apt install smartmontools\n"
              "  Fedora/RHEL   : sudo dnf install smartmontools\n"
              "  Arch          : sudo pacman -S smartmontools\n"
              "  macOS         : brew install smartmontools",
              file=sys.stderr)
        return 1

    # ── Device discovery ────────────────────
    if args.devices:
        device_paths = args.devices
    else:
        device_paths = discover_devices(include_usb=not args.no_usb)
        if args.verbose:
            print(f"Discovered {len(device_paths)} device(s): {', '.join(device_paths)}",
                  file=sys.stderr)

    if not device_paths:
        print("No storage devices found.", file=sys.stderr)
        return 1

    if args.list:
        for d in device_paths:
            print(d)
        return 0

    # ── Self-test mode ──────────────────────
    if args.selftest:
        for dev in device_paths:
            print(f"\nStarting '{args.selftest}' self-test on {dev} …")
            ok = run_selftest(dev, args.selftest)
            if ok and args.poll:
                poll_selftest(dev, interval=args.poll_interval, timeout=args.poll_timeout)
        return 0

    # ── Scan devices ────────────────────────
    results: list[DeviceInfo] = []
    for dev_path in device_paths:
        if args.verbose:
            print(f"Scanning {dev_path} …", file=sys.stderr)
        dev_info = get_device_info(
            dev_path,
            all_attrs=args.all_attrs,
            usb_workaround=not args.no_usb_workaround,
        )
        # Filter by attribute IDs if requested
        if args.attr_ids:
            dev_info.attributes = [a for a in dev_info.attributes
                                   if a.attr_id in args.attr_ids]
        if args.info_only:
            dev_info.attributes = []
            dev_info.nvme_attributes = []
        results.append(dev_info)

    # ── Format output ───────────────────────
    fmt = args.output
    if fmt == "json":
        report = format_json(results)
    elif fmt == "csv":
        report = format_csv(results)
    elif fmt == "html":
        report = format_html(results)
    else:
        report = format_text(
            results,
            show_all_attrs=args.all_attrs,
            show_raw_json=args.raw_json,
            no_color=args.no_color,
        )

    if args.save:
        Path(args.save).write_text(report, encoding="utf-8")
        print(f"Report saved to {args.save}", file=sys.stderr)
    else:
        print(report)

    # ── Exit code logic ──────────────────────
    exit_code = 0
    for dev in results:
        if args.score_threshold > 0 and 0 <= dev.health_score < args.score_threshold:
            exit_code = 2
            break
        if args.fail_on_warning:
            if any(a.status in ("WARNING", "CRITICAL") for a in dev.attributes):
                exit_code = 2
                break
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
