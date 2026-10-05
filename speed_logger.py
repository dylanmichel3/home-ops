"""Hourly internet speed logging for Home Ops.

Uses speedtest-cli (pip) against Ookla servers. Results go into a local
SQLite database; app.py serves them at /api/speed and graphs them on the
dashboard. Failures are recorded, never raised.
"""

import os
import sqlite3
import threading
import time
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "speedtests.db")

_last_error = None
_last_run = None


def init_db():
    with sqlite3.connect(DB_PATH) as c:
        c.execute(
            """CREATE TABLE IF NOT EXISTS speedtests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                download_mbps REAL,
                upload_mbps REAL,
                ping_ms REAL,
                server_name TEXT
            )"""
        )


def run_speedtest_once():
    """Run one test and store the result. Returns True on success."""
    global _last_error, _last_run
    try:
        import speedtest

        s = speedtest.Speedtest()
        s.get_best_server()
        down_bps = s.download()
        up_bps = s.upload()
        res = s.results.dict()
        server = res.get("server", {})
        with sqlite3.connect(DB_PATH) as c:
            c.execute(
                "INSERT INTO speedtests (ts, download_mbps, upload_mbps, ping_ms, server_name)"
                " VALUES (?, ?, ?, ?, ?)",
                (
                    datetime.now().isoformat(timespec="seconds"),
                    round(down_bps / 1e6, 1),
                    round(up_bps / 1e6, 1),
                    round(res.get("ping", 0), 1),
                    "%s (%s)" % (server.get("sponsor", "?"), server.get("name", "?")),
                ),
            )
        _last_error = None
        _last_run = datetime.now().isoformat(timespec="seconds")
        return True
    except Exception as e:  # noqa: BLE001 - record and keep going
        _last_error = str(e)[:200]
        _last_run = datetime.now().isoformat(timespec="seconds")
        return False


def _worker():
    run_speedtest_once()


def speed_loop(interval_secs=3600):
    init_db()
    while True:
        t = threading.Thread(target=_worker, daemon=True)
        t.start()
        t.join(timeout=600)  # don't let a hung test block the schedule
        time.sleep(interval_secs)


def history(hours=168):
    """Recent points for graphing, plus the latest reading and any error."""
    since = datetime.now().timestamp() - hours * 3600
    with sqlite3.connect(DB_PATH) as c:
        c.row_factory = sqlite3.Row
        rows = c.execute(
            "SELECT ts, download_mbps, upload_mbps, ping_ms FROM speedtests"
            " WHERE strftime('%s', ts) >= ? ORDER BY ts",
            (since,),
        ).fetchall()
    points = [dict(r) for r in rows]
    return {
        "latest": points[-1] if points else None,
        "points": points,
        "count": len(points),
        "last_run": _last_run,
        "last_error": _last_error,
    }
