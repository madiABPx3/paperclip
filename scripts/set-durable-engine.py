#!/usr/bin/env python3.12
"""Flip Paperclip Render durable-engine mode without dashboard edits.

Usage:
  python3.12 scripts/set-durable-engine.py legacy
  INNGEST_EVENT_KEY=... INNGEST_SIGNING_KEY=... python3.12 scripts/set-durable-engine.py inngest-pilot
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

API = "https://api.render.com/v1"
KEY = os.environ.get("RENDER_API_KEY")
DEFAULT_APP_ID = os.environ.get("INNGEST_APP_ID", "paperclip").strip() or "paperclip"
TARGETS = {
    "paperclip-server": {
        "required_keys": ("DURABLE_ENGINE", "INNGEST_APP_ID"),
        "inngest_keys": ("INNGEST_EVENT_KEY", "INNGEST_SIGNING_KEY"),
    },
    "paperclip-heartbeat-worker": {
        "required_keys": ("DURABLE_ENGINE", "INNGEST_APP_ID"),
        "inngest_keys": ("INNGEST_EVENT_KEY",),
    },
}


def api(method: str, path: str, body=None):
    req = urllib.request.Request(
        f"{API}{path}",
        data=json.dumps(body).encode() if body is not None else None,
        method=method,
    )
    req.add_header("Authorization", f"Bearer {KEY}")
    req.add_header("Accept", "application/json")
    if body is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as err:
        message = err.read().decode() if err.fp else ""
        raise SystemExit(f"Render API {method} {path} failed with {err.code}: {message}") from err


def list_services():
    services = {}
    cursor = None
    while True:
        path = "/services?limit=100"
        if cursor:
            path = f"{path}&cursor={cursor}"
        payload = api("GET", path)
        if not isinstance(payload, list):
            raise SystemExit(f"Unexpected Render services payload: {type(payload).__name__}")
        next_cursor = None
        for entry in payload:
            service = entry.get("service", entry)
            name = service.get("name")
            if isinstance(name, str):
                services[name] = service
            next_cursor = entry.get("cursor") or next_cursor
        if not payload or not next_cursor:
            return services
        cursor = next_cursor


def get_env_vars(service_id: str):
    payload = api("GET", f"/services/{service_id}/env-vars")
    env_vars = []
    for entry in payload:
        env_var = entry.get("envVar", entry)
        key = env_var.get("key")
        value = env_var.get("value")
        if isinstance(key, str) and value is not None:
            env_vars.append({"key": key, "value": value})
    return env_vars


def upsert_env(env_vars, key: str, value: str):
    for env_var in env_vars:
        if env_var["key"] == key:
            env_var["value"] = value
            return
    env_vars.append({"key": key, "value": value})


def wait_for_deploy(service_id: str, service_name: str, max_wait: int = 900):
    start = time.time()
    while time.time() - start < max_wait:
        deploys = api("GET", f"/services/{service_id}/deploys?limit=1")
        if isinstance(deploys, list) and deploys:
            deploy = deploys[0].get("deploy", deploys[0])
            status = deploy.get("status", "unknown")
            if status == "live":
                print(f"{service_name}: deploy live")
                return
            if status in {"build_failed", "update_failed", "canceled", "deactivated"}:
                raise SystemExit(f"{service_name}: deploy failed with status={status}")
            print(f"{service_name}: deploy status={status}")
        else:
            print(f"{service_name}: waiting for deploy record")
        time.sleep(15)
    raise SystemExit(f"{service_name}: deploy did not reach live within {max_wait}s")


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["legacy", "inngest-pilot"])
    parser.add_argument("--app-id", default=DEFAULT_APP_ID)
    parser.add_argument("--event-key", default=os.environ.get("INNGEST_EVENT_KEY"))
    parser.add_argument("--signing-key", default=os.environ.get("INNGEST_SIGNING_KEY"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-wait", action="store_true")
    return parser.parse_args()


def main():
    if not KEY:
        raise SystemExit("RENDER_API_KEY not set")

    args = parse_args()
    if args.mode == "inngest-pilot":
        if not args.event_key:
            raise SystemExit("INNGEST_EVENT_KEY is required for inngest-pilot mode")
        if not args.signing_key:
            raise SystemExit("INNGEST_SIGNING_KEY is required for inngest-pilot mode")

    services = list_services()
    missing = [name for name in TARGETS if name not in services]
    if missing:
        raise SystemExit(f"Render services not found: {', '.join(missing)}")

    for service_name, config in TARGETS.items():
        service = services[service_name]
        env_vars = get_env_vars(service["id"])
        upsert_env(env_vars, "DURABLE_ENGINE", args.mode)
        upsert_env(env_vars, "INNGEST_APP_ID", args.app_id)
        if args.mode == "inngest-pilot":
            if "INNGEST_EVENT_KEY" in config["inngest_keys"]:
                upsert_env(env_vars, "INNGEST_EVENT_KEY", args.event_key)
            if "INNGEST_SIGNING_KEY" in config["inngest_keys"]:
                upsert_env(env_vars, "INNGEST_SIGNING_KEY", args.signing_key)

        print(f"{service_name}: setting DURABLE_ENGINE={args.mode}")
        if args.dry_run:
            continue

        api("PUT", f"/services/{service['id']}/env-vars", env_vars)
        if not args.skip_wait:
            wait_for_deploy(service["id"], service_name)

    print("Durable engine update complete.")


if __name__ == "__main__":
    sys.exit(main())
