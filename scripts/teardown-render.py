#!/usr/bin/env python3.12
"""Teardown Paperclip from Render. Agent-executable, zero-human.

Usage: python3.12 scripts/teardown-render.py

Reads scripts/.render-state.json and destroys all resources.
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
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        if e.code == 404:
            print(f"  Already deleted (404)")
            return None
        body_text = e.read().decode() if e.fp else ""
        print(f"API error {e.code} {method} {path}: {body_text}", file=sys.stderr)
        return None

def main():
    if not KEY:
        print("RENDER_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    if not os.path.exists(STATE_FILE):
        print(f"No state file found at {STATE_FILE}. Nothing to tear down.")
        sys.exit(0)

    with open(STATE_FILE) as f:
        state = json.load(f)

    svc_id = state.get("service", {}).get("id")
    worker_id = state.get("worker", {}).get("id")
    relay_id = state.get("relay", {}).get("id")
    db_id = state.get("database", {}).get("id")

    if relay_id:
        print(f"Deleting relay service {relay_id}...")
        api("DELETE", f"/services/{relay_id}")
        print("  Done")

    if svc_id:
        print(f"Deleting web service {svc_id}...")
        api("DELETE", f"/services/{svc_id}")
        print("  Done")

    if worker_id:
        print(f"Deleting worker service {worker_id}...")
        api("DELETE", f"/services/{worker_id}")
        print("  Done")

    if db_id:
        print(f"Deleting database {db_id}...")
        api("DELETE", f"/postgres/{db_id}")
        print("  Done")

    os.remove(STATE_FILE)
    print(f"\n✓ Teardown complete. State file removed.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
