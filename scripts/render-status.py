#!/usr/bin/env python3.12
"""Check Paperclip Render deployment status. Agent-executable.

Usage: python3.12 scripts/render-status.py
"""
import json
import os
import sys
import urllib.request
import urllib.error

API = "https://api.render.com/v1"
KEY = os.environ.get("RENDER_API_KEY")
STATE_FILE = os.path.join(os.path.dirname(__file__), ".render-state.json")

def api(method, path):
    url = f"{API}{path}"
    req = urllib.request.Request(url, method=method)
    req.add_header("Authorization", f"Bearer {KEY}")
    req.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return {"error": e.code, "body": e.read().decode()[:200] if e.fp else ""}

def main():
    if not KEY:
        print("RENDER_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    if not os.path.exists(STATE_FILE):
        print("No deployment found (no state file).")
        sys.exit(0)

    with open(STATE_FILE) as f:
        state = json.load(f)

    print(f"Deployed at: {state.get('deployed_at', 'unknown')}\n")

    db_id = state.get("database", {}).get("id")
    if db_id:
        db = api("GET", f"/postgres/{db_id}")
        db_info = db.get("postgres", db)
        print(f"Database: {db_info.get('name', 'unknown')}")
        print(f"  ID: {db_id}")
        print(f"  Status: {db_info.get('status', 'unknown')}")
        print(f"  Plan: {db_info.get('plan', 'unknown')}")

    for key in ("service", "worker", "relay"):
        svc_state = state.get(key, {})
        svc_id = svc_state.get("id")
        if not svc_id:
            continue
        svc = api("GET", f"/services/{svc_id}")
        svc_info = svc.get("service", svc)
        print(f"\nService: {svc_info.get('name', 'unknown')}")
        print(f"  ID: {svc_id}")
        print(f"  URL: {svc_state.get('url', 'unknown')}")
        suspended = svc_info.get("suspended", "unknown")
        status = "active" if suspended == "not_suspended" else suspended
        print(f"  Status: {status}")

        deploys = api("GET", f"/services/{svc_id}/deploys?limit=1")
        if isinstance(deploys, list) and deploys:
            d = deploys[0].get("deploy", deploys[0])
            print(f"  Latest deploy: {d.get('status', 'unknown')} ({d.get('finishedAt', d.get('createdAt', '?'))})")

    return 0

if __name__ == "__main__":
    sys.exit(main())
