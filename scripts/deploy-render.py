#!/usr/bin/env python3.12
"""Deploy Paperclip to Render via API. Agent-executable, zero-human.

Usage: python3.12 scripts/deploy-render.py [--teardown-first]

Creates:
  1. Managed Postgres (starter plan)
  2. Web Service from Dockerfile (starter plan, connected to GitHub repo)
  3. Links DATABASE_URL from Postgres to Web Service

Outputs a JSON state file at scripts/.render-state.json for teardown/status.
"""
import json
import os
import sys
import time
import urllib.request
import urllib.error

API = "https://api.render.com/v1"
KEY = os.environ.get("RENDER_API_KEY")
STATE_FILE = os.path.join(os.path.dirname(__file__), ".render-state.json")
REPO = "https://github.com/paperclipai/paperclip"
BRANCH = "master"
OWNER_ID = None  # will be resolved

def api(method, path, body=None):
    url = f"{API}{path}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {KEY}")
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        body_text = e.read().decode() if e.fp else ""
        print(f"API error {e.code} {method} {path}: {body_text}", file=sys.stderr)
        sys.exit(1)

def get_owner_id():
    result = api("GET", "/owners?limit=1")
    if isinstance(result, list) and result:
        return result[0].get("owner", {}).get("id") or result[0].get("id")
    if isinstance(result, dict) and "id" in result:
        return result["id"]
    print(f"Could not resolve owner. Response: {json.dumps(result)[:500]}", file=sys.stderr)
    sys.exit(1)

def wait_for_db(db_id, max_wait=300):
    print(f"Waiting for database {db_id} to become available...")
    start = time.time()
    while time.time() - start < max_wait:
        db = api("GET", f"/postgres/{db_id}")
        status = db.get("status") or db.get("postgres", {}).get("status", "unknown")
        print(f"  DB status: {status}")
        if status == "available":
            return db
        time.sleep(10)
    print("Database did not become available in time.", file=sys.stderr)
    sys.exit(1)

def wait_for_service(svc_id, max_wait=600):
    print(f"Waiting for service {svc_id} to deploy...")
    start = time.time()
    while time.time() - start < max_wait:
        deploys = api("GET", f"/services/{svc_id}/deploys?limit=1")
        if deploys:
            deploy = deploys[0] if isinstance(deploys, list) else deploys
            d = deploy.get("deploy", deploy)
            status = d.get("status", "unknown")
            print(f"  Deploy status: {status}")
            if status == "live":
                return True
            if status in ("build_failed", "update_failed", "deactivated", "canceled"):
                print(f"Deploy failed with status: {status}", file=sys.stderr)
                return False
        time.sleep(15)
    print("Service did not deploy in time.", file=sys.stderr)
    return False

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)
    print(f"State saved to {STATE_FILE}")

def main():
    if not KEY:
        print("RENDER_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    if "--teardown-first" in sys.argv:
        if os.path.exists(STATE_FILE):
            print("Tearing down existing deployment first...")
            os.system(f"python3.12 {os.path.join(os.path.dirname(__file__), 'teardown-render.py')}")

    owner_id = get_owner_id()
    print(f"Owner ID: {owner_id}")

    # 1. Create Postgres
    print("\n=== Creating Managed Postgres ===")
    db = api("POST", "/postgres", {
        "databaseName": "paperclip",
        "databaseUser": "paperclip",
        "name": "paperclip-db",
        "plan": "free",
        "version": "16",
        "ownerId": owner_id,
    })
    db_info = db.get("postgres", db)
    db_id = db_info["id"]
    print(f"Postgres created: {db_id}")

    # Wait for DB
    wait_for_db(db_id)
    conn_info = api("GET", f"/postgres/{db_id}/connection-info")
    internal_url = conn_info.get("internalConnectionString", "")
    external_url = conn_info.get("externalConnectionString", "")
    database_url = internal_url or external_url
    print(f"Database URL available: {'yes' if database_url else 'no'}")

    # 2. Create Web Service
    print("\n=== Creating Web Service ===")
    env_vars = [
        {"key": "NODE_ENV", "value": "production"},
        {"key": "HOST", "value": "0.0.0.0"},
        {"key": "PORT", "value": "3100"},
        {"key": "SERVE_UI", "value": "true"},
        {"key": "PAPERCLIP_DEPLOYMENT_MODE", "value": "local_trusted"},
        {"key": "PAPERCLIP_MIGRATION_AUTO_APPLY", "value": "true"},
        {"key": "HEARTBEAT_SCHEDULER_ENABLED", "value": "true"},
    ]

    if database_url:
        env_vars.append({"key": "DATABASE_URL", "value": database_url})

    svc = api("POST", "/services", {
        "name": "paperclip-server",
        "ownerId": owner_id,
        "type": "web_service",
        "plan": "starter",
        "repo": REPO,
        "branch": BRANCH,
        "autoDeploy": "yes",
        "serviceDetails": {
            "runtime": "docker",
            "dockerfilePath": "./Dockerfile",
            "dockerContext": ".",
            "healthCheckPath": "/api/health",
            "numInstances": 1,
            "envVars": env_vars,
        },
    })
    svc_info = svc.get("service", svc)
    svc_id = svc_info["id"]
    svc_url = svc_info.get("serviceDetails", {}).get("url") or f"https://{svc_info.get('slug', 'paperclip-server')}.onrender.com"
    print(f"Web Service created: {svc_id}")
    print(f"URL: {svc_url}")

    # If we didn't have the DB URL yet, update the service env var
    if not database_url:
        print("Fetching database connection string...")
        db_detail = api("GET", f"/postgres/{db_id}")
        db_d = db_detail.get("postgres", db_detail)
        ci = db_d.get("connectionInfo", {})
        database_url = ci.get("internalConnectionString") or ci.get("externalConnectionString", "")
        if database_url:
            api("PUT", f"/services/{svc_id}/env-vars", [
                *env_vars,
                {"key": "DATABASE_URL", "value": database_url},
            ])
            print("DATABASE_URL set on service")

    # Save state
    state = {
        "owner_id": owner_id,
        "database": {
            "id": db_id,
            "name": "paperclip-db",
            "internal_url": internal_url,
            "external_url": external_url,
        },
        "service": {
            "id": svc_id,
            "name": "paperclip-server",
            "url": svc_url,
        },
        "deployed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    save_state(state)

    # Wait for deploy
    print("\n=== Waiting for initial deploy ===")
    success = wait_for_service(svc_id)

    if success:
        print(f"\n✓ Paperclip deployed successfully!")
        print(f"  Server: {svc_url}")
        print(f"  API: {svc_url}/api/health")
        print(f"  Dashboard: {svc_url}")
    else:
        print(f"\n⚠ Deploy may still be in progress. Check: {svc_url}")
        print("  Run: python3.12 scripts/render-status.py")

    return 0 if success else 1

if __name__ == "__main__":
    sys.exit(main())
