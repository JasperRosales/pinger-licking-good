#!/usr/bin/env python3
"""Ping services from a JSON config, each on its own schedule.

The workflow runs this every 10 minutes. On each run, a service is pinged only
if it is due according to its own `every` or `at` setting. The last ping time
of each service is kept in a state file, which the workflow saves between runs
with actions/cache.

Usage: ping.py [config.json] [--state FILE] [--force] [--only NAME]
Config source: $SERVICES_JSON (repo secret) if set, otherwise the file.
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

TICK = timedelta(minutes=10)      # how often the workflow cron fires
GRACE = timedelta(minutes=2)      # slack for cron jitter on interval schedules
AT_WINDOW = timedelta(minutes=60) # "at" slots missed by more than this are skipped
UNITS = {"m": "minutes", "h": "hours", "d": "days"}
IN_ACTIONS = bool(os.environ.get("GITHUB_ACTIONS"))


def parse_interval(text):
    m = re.fullmatch(r"\s*(\d+)\s*([mhd])\s*", str(text))
    if not m:
        raise ValueError(f"bad interval {text!r} (use e.g. '5m', '2h', '1d')")
    delta = timedelta(**{UNITS[m.group(2)]: int(m.group(1))})
    if delta < TICK:
        raise ValueError(f"interval {text!r} is shorter than the 10m minimum")
    return delta


def last_scheduled_time(times, tz, now):
    """Most recent 'HH:MM' time (in tz) that is <= now."""
    local_now = now.astimezone(tz)
    candidates = []
    for t in times:
        hh, mm = map(int, t.split(":"))
        for days_back in (0, 1):
            day = local_now - timedelta(days=days_back)
            dt = day.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if dt <= local_now:
                candidates.append(dt)
    return max(candidates).astimezone(timezone.utc)


def is_due(svc, last, now):
    """Return (due, reason)."""
    if "at" in svc:
        times = svc["at"] if isinstance(svc["at"], list) else [svc["at"]]
        tz = ZoneInfo(svc.get("timezone", "UTC"))
        slot = last_scheduled_time(times, tz, now)
        label = f"{slot.astimezone(tz):%H:%M %Z}"
        if last is not None and last >= slot:
            return False, f"already pinged for {label}"
        if now - slot > AT_WINDOW:
            return False, f"waiting for next slot (last was {label})"
        return True, f"scheduled at {label}"

    interval = parse_interval(svc.get("every", "10m"))
    if last is None:
        return True, "first ping"
    elapsed = now - last
    if elapsed + GRACE >= interval:
        return True, f"every {svc.get('every', '10m')}"
    left = interval - elapsed
    return False, f"next in ~{int(left.total_seconds() // 60)}m"


def ping(svc):
    url = svc["url"]
    method = svc.get("method", "GET").upper()
    expected = svc.get("expected_status", 200)
    expected = expected if isinstance(expected, list) else [expected]
    timeout = svc.get("timeout", 30)
    retries = svc.get("retries", 2)
    headers = {"User-Agent": "pinger-licking-good/2.0", **svc.get("headers", {})}
    body = svc.get("body")
    data = (json.dumps(body) if isinstance(body, (dict, list)) else body)
    data = data.encode() if data is not None else None

    status, elapsed, error = 0, 0.0, ""
    for attempt in range(retries + 1):
        start = time.monotonic()
        try:
            req = urllib.request.Request(url, data=data, method=method, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                status = resp.status
        except urllib.error.HTTPError as e:
            status = e.code
        except Exception as e:  # timeout, DNS, connection refused, ...
            status, error = 0, type(e).__name__
        elapsed = time.monotonic() - start
        if status in expected:
            break
        if attempt < retries:
            time.sleep(5)
    return status in expected, status, expected, elapsed, error


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("config", nargs="?", default="services.json")
    ap.add_argument("--state", default=".ping-state/state.json")
    ap.add_argument("--force", action="store_true", help="ping everything now")
    ap.add_argument("--only", help="ping only the service with this name")
    args = ap.parse_args()

    secret = os.environ.get("SERVICES_JSON", "").strip()
    if secret:
        services = json.loads(secret)
        print("Using services from SERVICES_JSON secret")
    else:
        with open(args.config) as f:
            services = json.load(f)
        print(f"Using services from {args.config}")

    state = {}
    if os.path.exists(args.state):
        with open(args.state) as f:
            state = json.load(f)

    now = datetime.now(timezone.utc)
    rows, failures = [], 0

    for svc in services:
        name = svc.get("name") or svc["url"]
        if secret and IN_ACTIONS:
            print(f"::add-mask::{svc['url']}")
        if svc.get("enabled", True) is False:
            rows.append((name, "-", "-", "-", "⏸️ disabled"))
            continue
        if args.only and name != args.only:
            continue

        last = state.get(name, {}).get("last_ping")
        last = datetime.fromisoformat(last) if last else None
        try:
            due, reason = (True, "forced") if args.force or args.only else is_due(svc, last, now)
        except Exception as e:
            failures += 1
            print(f"::error title={name} config error::{e}" if IN_ACTIONS else f"❗ {name}: {e}")
            rows.append((name, "-", "-", "-", f"❗ config error: {e}"))
            continue

        if not due:
            print(f"⏭️  {name}: skipped ({reason})")
            rows.append((name, "-", "-", "-", f"⏭️ {reason}"))
            continue

        ok, status, expected, elapsed, error = ping(svc)
        state[name] = {"last_ping": now.isoformat(), "last_status": status, "ok": ok}
        exp = ",".join(map(str, expected))
        if ok:
            print(f"✅ {name} -> {status} ({elapsed:.2f}s) [{reason}]")
            rows.append((name, status, exp, f"{elapsed:.2f}", "✅ up"))
        else:
            failures += 1
            detail = error or f"HTTP {status}"
            msg = f"Got {detail}, expected {exp}"
            print(f"::error title={name} is down::{msg}" if IN_ACTIONS else f"❌ {name}: {msg}")
            rows.append((name, status or error, exp, f"{elapsed:.2f}", "❌ down"))

    os.makedirs(os.path.dirname(args.state) or ".", exist_ok=True)
    with open(args.state, "w") as f:
        json.dump(state, f, indent=2)

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a") as f:
            f.write(f"## Ping results ({now:%Y-%m-%d %H:%M} UTC)\n\n")
            f.write("| Service | Status | Expected | Time (s) | Result |\n|---|---|---|---|---|\n")
            for r in rows:
                f.write("| " + " | ".join(map(str, r)) + " |\n")

    if failures:
        print(f"{failures} service(s) failed")
        sys.exit(1)
    print("Done")


if __name__ == "__main__":
    main()
