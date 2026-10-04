"""Home Ops: a small Flask service for managing a home PC over Tailscale.

Runs on the home PC and listens only on its Tailscale address. Every route
requires the bearer token from config.json, so nothing else on the tailnet
can use it without the secret.
"""

import json
import os
import platform
import subprocess
import threading
import time
from datetime import datetime
from functools import wraps

from flask import Flask, jsonify, render_template, request

import psutil

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


config = load_config()
TOKEN = config.get("token", "")
DEVICES = {d["name"]: d["mac"] for d in config.get("devices", [])}

app = Flask(__name__)


def require_token(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        auth = request.headers.get("Authorization", "")
        if not TOKEN or auth != "Bearer " + TOKEN:
            return jsonify({"error": "unauthorized"}), 401
        return view(*args, **kwargs)

    return wrapper


@app.get("/")
def index():
    # The page itself is public; every API route it calls still needs the token.
    return render_template("index.html", devices=sorted(DEVICES))


@app.get("/api/status")
@require_token
def api_status():
    boot = datetime.fromtimestamp(psutil.boot_time())
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage(os.path.abspath(os.sep))
    return jsonify(
        {
            "hostname": platform.node(),
            "os": platform.system() + " " + platform.release(),
            "uptime_seconds": int((datetime.now() - boot).total_seconds()),
            "cpu_percent": psutil.cpu_percent(interval=1),
            "memory_percent": mem.percent,
            "memory_used_gb": round(mem.used / 1e9, 1),
            "memory_total_gb": round(mem.total / 1e9, 1),
            "disk_percent": disk.percent,
            "disk_free_gb": round(disk.free / 1e9, 1),
        }
    )


@app.post("/api/wol")
@require_token
def api_wol():
    from wakeonlan import send_magic_packet

    data = request.get_json(force=True, silent=True) or {}
    mac = data.get("mac") or DEVICES.get(data.get("device", ""), "")
    if not mac:
        return (
            jsonify({"error": "unknown device; send a known device name or a mac address"}),
            400,
        )
    send_magic_packet(mac)
    return jsonify({"ok": True, "mac": mac})


@app.post("/api/power")
@require_token
def api_power():
    data = request.get_json(force=True, silent=True) or {}
    action = data.get("action")
    if data.get("confirm") is not True:
        return jsonify({"error": 'power actions need {"confirm": true}'}), 400
    commands = {
        "sleep": ["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"],
        "shutdown": ["shutdown", "/s", "/t", "15"],
        "restart": ["shutdown", "/r", "/t", "15"],
    }
    if action not in commands:
        return jsonify({"error": "action must be sleep, shutdown, or restart"}), 400
    subprocess.Popen(commands[action])
    return jsonify({"ok": True, "action": action})


PATCH_CACHE = {
    "fetched_at": None,
    "data": {
        "pending_count": None,
        "pending_titles": [],
        "reboot_required": None,
        "last_hotfix": None,
        "last_hotfix_id": None,
    },
}
PATCH_SCRIPT = os.path.join(BASE_DIR, "patch_check.ps1")


def run_patch_check():
    """Run the PowerShell patch check and return its parsed JSON."""
    proc = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            PATCH_SCRIPT,
        ],
        capture_output=True,
        text=True,
        timeout=300,
    )
    if not proc.stdout.strip():
        raise RuntimeError("patch script produced no output: " + proc.stderr.strip()[:200])
    return json.loads(proc.stdout)


def refresh_patch_cache_loop():
    while True:
        try:
            data = run_patch_check()
            PATCH_CACHE["data"] = {
                "pending_count": data.get("pending_count"),
                "pending_titles": data.get("pending_titles", [])[:25],
                "reboot_required": data.get("reboot_required"),
                "last_hotfix": data.get("last_hotfix"),
                "last_hotfix_id": data.get("last_hotfix_id"),
            }
            PATCH_CACHE["fetched_at"] = datetime.now().isoformat(timespec="seconds")
        except Exception:
            pass  # keep the previous cache; the next cycle retries
        time.sleep(6 * 3600)


threading.Thread(target=refresh_patch_cache_loop, daemon=True).start()


@app.get("/api/health")
def api_health():
    """Minimal public health for the monitoring cron. The service is
    tailnet-only, and the token still guards full status and every action."""
    disk = psutil.disk_usage(os.path.abspath(os.sep))
    mem = psutil.virtual_memory()
    boot = datetime.fromtimestamp(psutil.boot_time())
    return jsonify(
        {
            "ok": True,
            "uptime_seconds": int((datetime.now() - boot).total_seconds()),
            "disk_percent": disk.percent,
            "memory_percent": mem.percent,
            "patch": PATCH_CACHE["data"],
            "patch_fetched_at": PATCH_CACHE["fetched_at"],
        }
    )


@app.get("/api/patches")
@require_token
def api_patches():
    return jsonify(
        {
            "fetched_at": PATCH_CACHE["fetched_at"],
            **PATCH_CACHE["data"],
        }
    )


EVENT_CACHE = {"fetched_at": None, "data": {"total": None, "errors": None, "warnings": None, "groups": []}}
DISK_CACHE = {"fetched_at": None, "data": {"drives": []}}

def run_ps_script(name):
    script = os.path.join(BASE_DIR, name)
    proc = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            script,
        ],
        capture_output=True,
        text=True,
        timeout=1800,
    )
    if not proc.stdout.strip():
        raise RuntimeError(name + " produced no output: " + proc.stderr.strip()[:200])
    return json.loads(proc.stdout)


def refresh_loop(script, cache, interval):
    while True:
        try:
            cache["data"] = run_ps_script(script)
            cache["fetched_at"] = datetime.now().isoformat(timespec="seconds")
        except Exception:
            pass  # keep the previous cache; the next cycle retries
        time.sleep(interval)


threading.Thread(target=refresh_loop, args=("event_digest.ps1", EVENT_CACHE, 2 * 3600), daemon=True).start()
threading.Thread(target=refresh_loop, args=("disk_usage.ps1", DISK_CACHE, 12 * 3600), daemon=True).start()


@app.get("/api/events")
def api_events():
    """Public event-log digest for the daily monitor. Tailnet-only service;
    the token still guards power, WoL, and full status."""
    return jsonify({"fetched_at": EVENT_CACHE["fetched_at"], **EVENT_CACHE["data"]})


@app.get("/api/disk")
@require_token
def api_disk():
    return jsonify({"fetched_at": DISK_CACHE["fetched_at"], **DISK_CACHE["data"]})


if __name__ == "__main__":
    if not TOKEN or TOKEN == "CHANGE-ME":
        raise SystemExit("Set a real token in config.json first (see config.example.json).")
    app.run(host=config.get("host", "127.0.0.1"), port=config.get("port", 5000))
