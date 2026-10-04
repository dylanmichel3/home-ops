# Home Ops

A small Flask service that runs on your home PC and lets you manage it from
anywhere on your Tailscale network: check system status, send Wake-on-LAN
packets to other devices on your home LAN, and sleep / restart / shut down
the PC itself.

It listens **only** on the PC's Tailscale address, and every route requires a
bearer token, so nothing else on the tailnet can use it without the secret.

## What it does

- `GET /` — dashboard: status, updates, Wake-on-LAN buttons, power controls
- `GET /api/health` — public minimal health (uptime, disk/memory %, cached
  patch summary) for automated monitoring; no token needed
- `GET /api/status` — hostname, OS, uptime, CPU / memory / disk usage
- `GET /api/patches` — Windows Update compliance: pending count and titles,
  reboot-required flag, last installed hotfix (refreshed in the background
  every 6 hours by `patch_check.ps1`)
- `GET /api/events` — public event-log digest: Critical/Error/Warning counts
  from the System and Application logs over the last 24 hours, grouped by
  source (refreshed in the background every 2 hours by `event_digest.ps1`).
  Each group also carries a plain-language `friendly` explanation next to
  the technical details.
- `GET /api/disk` — disk usage breakdown: per-drive totals and the largest
  top-level folders (refreshed in the background every 12 hours by
  `disk_usage.ps1`; the first scan can take a while on a full drive)
- `POST /api/wol` — send a magic packet: `{"device": "name"}` or `{"mac": "AA:BB:CC:DD:EE:FF"}`
- `POST /api/power` — `{"action": "sleep" | "restart" | "shutdown", "confirm": true}`

## Monitoring

The `/api/health` endpoint is intentionally public (minimal data only) so a
monitor can poll it without the token. A scheduled check every 30 minutes
watches reachability and disk usage and alerts on state changes; a weekly
report covers pending updates and reboot status.

## Setup (Windows)

1. Install Python 3.11+ from python.org (tick **"Add python.exe to PATH"**)
   and install Git if you don't have it.
2. Clone and enter the repo:
   ```
   git clone https://github.com/dylanmichel3/home-ops.git
   cd home-ops
   ```
3. Install dependencies:
   ```
   pip install -r requirements.txt
   ```
4. Find this PC's Tailscale address. In Command Prompt run `tailscale ip -4`,
   or hover the Tailscale icon in the system tray. It looks like `100.x.y.z`.
5. Copy the example config and edit it:
   ```
   copy config.example.json config.json
   ```
   - `token`: a long random string (this is the password for the dashboard
     and the API; keep it secret).
   - `host`: the Tailscale address from step 4. Leave `127.0.0.1` only for
     local testing.
   - `devices`: name/MAC pairs for anything on your home LAN you want to
     wake. The target device needs Wake-on-LAN enabled (BIOS/UEFI setting
     plus "Wake on Magic Packet" on its network adapter).
6. Start it:
   ```
   python app.py
   ```
7. On your phone (Tailscale connected), open `http://100.x.y.z:5000` and
   paste the token.

## Run at startup (optional)

To have it start with Windows, open Task Scheduler, create a basic task
triggered "at log on" that runs `pythonw.exe C:\path\to\home-ops\app.py`
(`pythonw` runs without a console window).

## Security notes

- The app binds to the Tailscale IP from `config.json`, never `0.0.0.0`,
  so it is not reachable from your LAN or the internet.
- `config.json` holds the token and is gitignored; only
  `config.example.json` is committed.
- Power actions require `"confirm": true` in the API, and the dashboard
  makes you tap twice.
- `/api/health` is public by design but exposes only uptime, disk/memory
  percentages, and patch counts, enough for monitoring and nothing more.
  Everything else needs the token.
