"""Home Ops: a small Flask service for managing a home PC over Tailscale.

Runs on the home PC and listens only on its Tailscale address. Every route
requires the bearer token from config.json, so nothing else on the tailnet
can use it without the secret.
"""

import json
import os
import platform
import subprocess
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
@require_token
def index():
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


if __name__ == "__main__":
    if not TOKEN or TOKEN == "CHANGE-ME":
        raise SystemExit("Set a real token in config.json first (see config.example.json).")
    app.run(host=config.get("host", "127.0.0.1"), port=config.get("port", 5000))
