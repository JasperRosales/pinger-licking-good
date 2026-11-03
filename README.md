# pinger-licking-good

A GitHub Actions setup that pings several services on a schedule. Use it to keep free-tier apps awake (Render, Railway, Supabase, etc.) or as a basic uptime check.

## How it works

- `.github/workflows/ping.yml` runs every 10 minutes. You can also start it by hand from the Actions tab, and it runs when the config changes.
- `scripts/ping.sh` reads the service list, sends a request to each URL with `curl` (with retries), and writes a results table to the job summary.
- If any service returns an unexpected status, the run fails. GitHub then emails you, depending on your notification settings.

## Adding services

Edit `services.json`:

```json
[
  {
    "name": "My API",
    "url": "https://my-api.onrender.com/health",
    "method": "GET",
    "expected_status": 200,
    "timeout": 30
  }
]
```

Only `url` is required. The defaults are: `method` = `GET`, `expected_status` = `200`, `timeout` = `30` seconds.

### Keeping URLs private

This repo is public, so `services.json` is visible to everyone. For private endpoints, add a repository secret named **`SERVICES_JSON`** that holds the same JSON array (Settings → Secrets and variables → Actions). When that secret is set, the script uses it instead of the file, and it masks the URLs in the logs.

## Running locally

```bash
bash scripts/ping.sh services.json
```

You need `curl` and `jq`.

## Notes

- GitHub turns off scheduled workflows in public repos after **60 days without repository activity**. Push a commit now and then, or re-enable the workflow from the Actions tab.
- Cron runs are best-effort and can be several minutes late when GitHub is busy.
- To change how often it runs, edit the `cron` line in `ping.yml`. The minimum interval is 5 minutes.
