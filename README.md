# pinger-licking-good

A GitHub Actions setup that pings several services, **each on its own schedule**. Use it to keep free-tier apps awake (Render, Railway, Supabase, etc.) or as a basic uptime check.

## How it works

- `.github/workflows/ping.yml` runs every 10 minutes (GitHub allows down to 5) to keep the number of Actions runs low.
- On each run, `scripts/ping.py` checks every service in `services.json` and pings only the ones that are due by their own `every` or `at` setting.
- The time of each service's last ping is saved between runs in the Actions cache, so the schedules hold up even when GitHub starts runs late.
- The results table appears on each run's summary page. If a ping fails, the run fails, which triggers GitHub's failure email.

## Configuring services

Edit `services.json`. Each entry needs a `url` and **one** schedule type:

```json
[
  { "name": "My API",   "url": "https://my-api.onrender.com/health", "every": "10m" },
  { "name": "Backend",  "url": "https://backend.example.com",        "every": "2h" },
  { "name": "Reports",  "url": "https://reports.example.com/run",    "at": ["08:00", "20:00"], "timezone": "Asia/Manila" }
]
```

### Schedule

| Field | Example | Meaning |
|---|---|---|
| `every` | `"10m"`, `"30m"`, `"2h"`, `"1d"` | Repeating interval. The minimum is `10m` (the workflow tick). The default is `10m`. |
| `at` | `"09:00"` or `["08:00","20:00"]` | Fixed time(s) each day (24-hour clock) |
| `timezone` | `"Asia/Manila"` | Time zone for `at`. The default is `UTC`. |

If a scheduled `at` time is missed by more than an hour (for example, because GitHub was down), that ping is skipped and the service waits for its next time.

### Request options (all optional)

| Field | Default | Notes |
|---|---|---|
| `name` | the URL | Shown in logs and the summary. Also used with `only` (see below). |
| `method` | `GET` | `GET`, `POST`, `HEAD`, … |
| `headers` | `{}` | e.g. `{"Authorization": "Bearer ..."}` (put anything sensitive in the secret, see below) |
| `body` | none | A string or a JSON object |
| `expected_status` | `200` | A number, or a list such as `[200, 204]` |
| `timeout` | `30` | Seconds per attempt |
| `retries` | `2` | Extra attempts before marking the service down |
| `enabled` | `true` | Set to `false` to pause a service without deleting it |

## Running it by hand

Go to **Actions → Ping services → Run workflow**:
- **force**: ping every service now, ignoring schedules. On by default.
- **only**: ping just one service, by its `name`.

A push that changes `services.json` also starts a run. That run follows the normal schedules.

## Keeping URLs private

This repo is public, so `services.json` is visible to everyone. For private endpoints or auth headers, add a repository secret named **`SERVICES_JSON`** that holds the same JSON array (Settings → Secrets and variables → Actions). When that secret is set, the script uses it instead of the file, and it masks the URLs in the logs.

## Running locally

```bash
python3 scripts/ping.py services.json            # follows schedules (saves state to .ping-state/)
python3 scripts/ping.py services.json --force    # ping everything now
python3 scripts/ping.py services.json --only "My API"
```

Requires Python 3.9 or newer. It has no other dependencies.

## Notes

- GitHub turns off scheduled workflows in public repos after **60 days without repository activity**. Push a commit now and then, or re-enable the workflow from the Actions tab.
- Cron runs are best-effort and can be several minutes late when GitHub is busy, so exact timing isn't guaranteed.
