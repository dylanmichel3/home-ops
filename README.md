# Home Ops

A self-hosted monitoring and administration service for a home Windows PC. It runs as a small Flask app on the machine itself and is reachable only over [Tailscale](https://tailscale.com), so the PC can be checked and managed from anywhere without exposing it to the internet.

## Why it exists

A home PC is usually unmanaged infrastructure. Updates pile up unnoticed, disks fill slowly, and the first sign of trouble is something breaking. Remote-desktop tools solve the access problem, but they do not tell you the state of the machine before you connect.

Home Ops is the awareness layer that sits next to remote access:

- It collects the things an administrator would check by hand: patch state, event logs, disk usage, and connection quality.
- It keeps that data fresh on its own, on a schedule, instead of waiting for someone to log in and look.
- It treats alerting as a design problem. A monitor that reports constantly gets ignored, so this one stays silent unless something changes: the machine went offline, came back, or crossed a disk threshold.

It is also a deliberate practice environment for real systems administration work: Windows Update internals, event log analysis, capacity tracking, and API design, all running against a machine that has to work every day.

## What it does

- **System status**: hostname, OS, uptime, CPU, memory, and disk usage.
- **Remote power control**: sleep, restart, and shutdown, each requiring a confirmation step.
- **Wake-on-LAN relay**: wake other devices on the home LAN by name, so the PC acts as the always-reachable sender for magic packets.
- **Patch compliance**: pending Windows Update count and titles, reboot-required flag, and last installed hotfix, read through the Windows Update COM API.
- **Event log digest**: Critical, Error, and Warning events from the System and Application logs over the last 24 hours, grouped by source and event ID.
- **Disk usage**: per-drive totals plus the 15 largest top-level items, so "the disk is full" becomes a list of suspects.
- **Internet speed history**: an Ookla speed test every hour (download, upload, ping), stored locally in SQLite and viewable over 24 hours, 7 days, or 30 days.
- **Health endpoint for external monitoring**: a minimal, unauthenticated summary (uptime, disk and memory percentages, pending update count) that a separate checker can poll without holding the admin token.

## How it works

- `app.py` is a Flask service that binds only to the PC's Tailscale address (`100.x.y.z`), never `0.0.0.0`. If Tailscale is not up, the app is not reachable.
- Every route except `/api/health` and `/api/events` requires a Bearer token, including the dashboard.
- Three PowerShell collectors do the Windows-specific work and cache their results as JSON for the app to serve:
  - `patch_check.ps1` queries the Windows Update COM API (refreshes every 6 hours)
  - `event_digest.ps1` reads events with `Get-WinEvent` (refreshes every 2 hours)
  - `disk_usage.ps1` walks the drives (refreshes every 12 hours)
- `speed_logger.py` runs `speedtest-cli` hourly and appends each result to `speedtests.db`, a local SQLite database that is gitignored.
- The dashboard is a single page under `templates/` that reads the same API the monitoring uses. There is no separate admin interface to keep in sync.
- The app is designed to be watched from outside itself: a separate checker polls `/api/health` every 30 minutes and alerts only on reachability changes or disk usage crossing 90%, with a weekly patch digest and a daily event digest drawn from the same endpoints.

## API

| Route | Auth | Description |
| --- | --- | --- |
| `GET /` | Token | Dashboard: status, updates, Wake-on-LAN, power controls |
| `GET /api/health` | None | Minimal health summary (uptime, disk/memory %, pending updates) |
| `GET /api/status` | Token | Hostname, OS, uptime, CPU / memory / disk usage |
| `GET /api/patches` | Token | Pending update count and titles, reboot-required flag, last hotfix |
| `GET /api/events` | None | Event-log digest: counts by severity and source, last 24 hours |
| `GET /api/disk` | Token | Per-drive totals and largest top-level items |
| `GET /api/speed?hours=168` | Token | Speed test history (default: last 24 hours of tests) |
| `POST /api/speed/test` | Token | Run a speed test immediately |
| `POST /api/wol` | Token | Send a magic packet: `{"device": "name"}` or `{"mac": "AA:BB:..."}` |
| `POST /api/power` | Token | `{"action": "sleep" \| "restart" \| "shutdown", "confirm": true}` |

## Setup (Windows)

1. Install Python 3.11 or newer from python.org (tick **Add python.exe to PATH**) and Git.
2. Clone this repo and enter it:
   ```
   git clone https://github.com/dylanmichel3/home-ops.git
   cd home-ops
   ```
3. Install dependencies:
   ```
   pip install -r requirements.txt
   ```
   `speedtest-cli` also needs to be installed and on the PATH for the speed logger.
4. Find the PC's Tailscale address: `tailscale ip -4`, or hover the Tailscale tray icon. It looks like `100.x.y.z`.
5. Create the config from the example and edit it:
   ```
   copy config.example.json config.json
   ```
6. Start it:
   ```
   python app.py
   ```
7. On a phone with Tailscale connected, open `http://100.x.y.z:5000` and paste the token.

To start it at logon, create a Task Scheduler task triggered **at log on** that runs `pythonw.exe C:\path\to\home-ops\app.py` (`pythonw` runs without a console window).

## Configuration

`config.json` is gitignored; only `config.example.json` is committed.

| Field | Meaning |
| --- | --- |
| `token` | Long random string. This is the password for the dashboard and API; treat it like one. |
| `host` | The PC's Tailscale address. Use `127.0.0.1` only for local testing. |
| `devices` | Name/MAC pairs for LAN devices the Wake-on-LAN relay can wake. Each target needs Wake-on-LAN enabled in BIOS/UEFI and "Wake on Magic Packet" on its wired network adapter. |

## Security notes

- The app binds to the Tailscale address from `config.json` and nothing else, so it is unreachable from the LAN and the internet. Tailscale being down means the app is down, by design.
- `/api/health` and `/api/events` are unauthenticated on purpose, for pollers that should not hold the admin token. They expose only summary counts and percentages, no event message text and no controls.
- Power actions require `"confirm": true` in the API, and the dashboard makes you tap twice.
- Nothing in this repo contains a real token or address. `config.json` and `speedtests.db` are gitignored.

## Limitations

- The collectors are Windows-only. Patch state comes from the Windows Update COM API and events from `Get-WinEvent`, so the service targets a Windows PC.
- Wake-on-LAN wakes other devices, not the PC running Home Ops: the sender has to be awake to send the packet. Waking this PC itself needs a different always-on device on the LAN.
- Magic packets do not cross Tailscale, which is why the relay runs on the PC and broadcasts onto its local LAN.
- Hourly speed tests move real data (tens of MB per test). Negligible on unmetered broadband, worth knowing about on a metered link.
- It is single-user and single-machine on purpose. There are no accounts to manage; the token is the whole auth model, and SQLite holds the speed history.

## Project layout

| File | Role |
| --- | --- |
| `app.py` | Flask service, routes, auth, background refresh loops |
| `templates/` | Dashboard page |
| `patch_check.ps1` | Windows Update compliance via COM API |
| `event_digest.ps1` | System/Application event digest via Get-WinEvent |
| `disk_usage.ps1` | Per-drive usage and largest items |
| `speed_logger.py` | Hourly speed test runner and history queries |
| `config.example.json` | Example configuration |
| `requirements.txt` | Python dependencies |
