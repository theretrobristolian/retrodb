"""Read-only Linux host snapshot for the RetroDB Settings dashboard.

All data comes from bounded local system files or fixed, read-only commands.
No privileged helper, shell input, remote calls or background polling.
"""
from __future__ import annotations

import os
import platform
import re
import shutil
import socket
import subprocess
import time
from pathlib import Path


def read_text(path: str, limit: int = 16384) -> str:
    try:
        with open(path, "rb") as stream:
            return stream.read(limit).replace(b"\x00", b"\n").decode("utf-8", "replace").strip()
    except OSError:
        return ""


def os_name() -> str:
    raw = read_text("/etc/os-release")
    for line in raw.splitlines():
        if line.startswith("PRETTY_NAME="):
            return line.split("=", 1)[1].strip().strip('"')
    return platform.system() + " " + platform.release()


def hardware() -> tuple[str, str]:
    pi_model = read_text("/proc/device-tree/model", 256).splitlines()[0:1]
    if pi_model and "raspberry pi" in pi_model[0].lower():
        return "Raspberry Pi", pi_model[0]
    manufacturer = read_text("/sys/class/dmi/id/sys_vendor", 256)
    model = read_text("/sys/class/dmi/id/product_name", 256)
    if not model:
        return "Physical / unknown", platform.machine()
    descriptor = (manufacturer + " " + model).lower()
    virtual = ("vmware", "virtualbox", "qemu", "kvm", "hyper-v", "hyperv",
               "virtual machine", "bhyve", "xen", "parallels", "bochs", "proxmox")
    kind = "Virtual machine" if any(token in descriptor for token in virtual) else "Physical / unknown"
    return kind, " ".join(part for part in (manufacturer, model) if part)


def ipv4_addresses() -> str:
    # Fixed binary and arguments. No user input is used in the command.
    try:
        binary = shutil.which("ip")
        if not binary:
            return "Unavailable"
        completed = subprocess.run(
            [binary, "-o", "-4", "addr", "show", "scope", "global"],
            capture_output=True, text=True, timeout=2, check=False,
        )
        if completed.returncode != 0:
            return "Unavailable"
        addresses = []
        for line in completed.stdout.splitlines()[:48]:
            match = re.search(r"\binet\s+(\d{1,3}(?:\.\d{1,3}){3})/", line)
            if match and match.group(1) not in addresses:
                addresses.append(match.group(1))
        return ", ".join(addresses[:8]) or "Unavailable"
    except (OSError, subprocess.TimeoutExpired):
        return "Unavailable"


def cpu_sample() -> tuple[int, int]:
    line = read_text("/proc/stat", 1024).splitlines()[0]
    values = [int(value) for value in line.split()[1:]]
    idle = values[3] + (values[4] if len(values) > 4 else 0)
    return sum(values), idle


def cpu_percent() -> float | None:
    try:
        start_total, start_idle = cpu_sample()
        time.sleep(0.15)
        end_total, end_idle = cpu_sample()
        delta = end_total - start_total
        if delta <= 0:
            return None
        return round(max(0.0, min(100.0, 100 * (1 - (end_idle - start_idle) / delta))), 1)
    except (ValueError, IndexError, OSError):
        return None


def memory_usage() -> tuple[int, int, float] | None:
    values: dict[str, int] = {}
    for line in read_text("/proc/meminfo", 8192).splitlines():
        match = re.match(r"^(MemTotal|MemAvailable):\s+(\d+)\s+kB", line)
        if match:
            values[match.group(1)] = int(match.group(2)) * 1024
    total = values.get("MemTotal", 0)
    available = values.get("MemAvailable")
    if not total or available is None:
        return None
    used = max(0, total - available)
    return used, total, round(100 * used / total, 1)


def drive_usage(path: str) -> tuple[int, int, float] | None:
    try:
        usage = shutil.disk_usage(path)
        if not usage.total:
            return None
        return usage.used, usage.total, round(100 * usage.used / usage.total, 1)
    except OSError:
        return None


def uptime_seconds() -> int | None:
    try:
        return max(0, int(float(read_text("/proc/uptime", 128).split()[0])))
    except (ValueError, IndexError):
        return None


def service_state(unit: str = "xerabora.service") -> str:
    # Intentionally fixed service; never accepts arbitrary caller units.
    if unit != "xerabora.service":
        return "unknown"
    try:
        completed = subprocess.run(
            ["/usr/bin/systemctl", "is-active", unit],
            capture_output=True, text=True, timeout=2, check=False,
        )
        state = completed.stdout.strip().lower()
        return state if state in {"active", "inactive", "failed", "activating", "deactivating"} else "unknown"
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"


def snapshot() -> dict[str, object]:
    kind, model = hardware()
    disk = drive_usage("/")
    network = "/mnt/retrodb-retronas"
    # Never automatically trigger an automount just to calculate disk size.
    mounts = read_text("/proc/mounts", 256 * 1024)
    mounted = any(line.split()[1:2] == [network] and line.split()[2:3] == ["cifs"]
                  for line in mounts.splitlines())
    return {
        "hostname": socket.gethostname(),
        "ip": ipv4_addresses(),
        "os": os_name(),
        "architecture": platform.machine(),
        "hardware_type": kind,
        "model": model,
        "uptime": uptime_seconds(),
        "cpu_cores": os.cpu_count(),
        "cpu_percent": cpu_percent(),
        "memory": memory_usage(),
        "disk": disk,
        "retronas_disk": drive_usage(network) if mounted else None,
        "xerabora": service_state(),
        "captured": time.strftime("%Y-%m-%d %H:%M:%S %Z", time.localtime()),
    }
