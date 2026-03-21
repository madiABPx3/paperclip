#!/usr/bin/env python3.12
"""Deploy Paperclip, the heartbeat worker, and the Zo relay to Render via API. Agent-executable, zero-human.

Usage: python3.12 scripts/deploy-render.py [--teardown-first]

Creates:
  1. Managed Postgres
  2. Paperclip web service from Dockerfile.render
  3. Heartbeat worker from Dockerfile.heartbeat-worker
  4. Zo relay web service from Dockerfile.relay
  5. Links shared DATABASE_URL and relay secrets/env

Outputs a JSON state file at scripts/.render-state.json for teardown/status.
"""
import json
import secrets
import os
import sys
import time
import urllib.parse
import urllib.request
import urllib.error
import importlib.util

API = "https://api.render.com/v1"
KEY = os.environ.get("RENDER_API_KEY")
STATE_FILE = os.path.join(os.path.dirname(__file__), ".render-state.json")
REPO = os.environ.get("RENDER_DEPLOY_REPO", "https://github.com/paperclipai/paperclip")
BRANCH = os.environ.get("RENDER_DEPLOY_BRANCH", "master")
OWNER_ID = None  # will be resolved
ZO_API = "https://api.zo.computer"

_zo_models_spec = importlib.util.spec_from_file_location(
    "zo_models",
    "/home/workspace/lib/zo_models.py",
)
_zo_models = importlib.util.module_from_spec(_zo_models_spec)
assert _zo_models_spec and _zo_models_spec.loader
_zo_models_spec.loader.exec_module(_zo_models)

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


def http_json(method, url, token, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", token)
    req.add_header("Accept", "application/json")
    if body is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=60) as resp:
        raw = resp.read().decode()
        return json.loads(raw) if raw else {}

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


def get_zo_token():
    token = os.environ.get("ZO_EXECUTION_TOKEN") or os.environ.get("ZO_CLIENT_IDENTITY_TOKEN")
    if not token:
        print("Set ZO_EXECUTION_TOKEN or ZO_CLIENT_IDENTITY_TOKEN before deploying the relay.", file=sys.stderr)
        sys.exit(1)
    return token


def build_model_scenario_map():
    scenarios = _zo_models.get_scenarios()
    mapping = {}
    for scenario in scenarios:
        model_name, label = _zo_models.get_model_for_scenario(scenario)
        mapping[scenario] = {
            "modelName": model_name,
            "label": label,
        }
    return mapping


def fetch_persona_map(token):
    payload = http_json("GET", f"{ZO_API}/personas/available", token)
    personas = payload.get("personas", [])
    mapping = {}
    for persona in personas:
        name = persona.get("name")
        persona_id = persona.get("id")
        if isinstance(name, str) and isinstance(persona_id, str):
            mapping[name] = persona_id
    return mapping


SENSITIVE_ENV_SUBSTRINGS = ("SECRET", "TOKEN", "PASSWORD", "KEY", "DATABASE_URL")


def maybe_env_var(key):
    value = os.environ.get(key)
    if value:
        return {"key": key, "value": value}
    return None


def sanitize_env_vars(env_vars):
    sanitized = []
    for env_var in env_vars:
        key = env_var.get("key", "")
        value = env_var.get("value")
        if any(part in key for part in SENSITIVE_ENV_SUBSTRINGS) and value is not None:
            sanitized.append({"key": key, "value": "[redacted]"})
            continue
        sanitized.append(env_var)
    return sanitized


def sanitize_service_state(service):
    sanitized = dict(service)
    env_vars = service.get("env_vars")
    if isinstance(env_vars, list):
        sanitized["env_vars"] = sanitize_env_vars(env_vars)
    return sanitized


def create_service(owner_id, name, service_type, dockerfile_path, env_vars, default_slug, port=None, health_check_path=None):
    service_details = {
        "runtime": "docker",
        "plan": "starter",
        "envSpecificDetails": {
            "dockerfilePath": dockerfile_path,
            "dockerContext": ".",
        },
        "numInstances": 1,
    }
    if health_check_path:
        service_details["healthCheckPath"] = health_check_path

    svc = api("POST", "/services", {
        "name": name,
        "ownerId": owner_id,
        "type": service_type,
        "repo": REPO,
        "branch": BRANCH,
        "autoDeploy": "yes",
        "envVars": env_vars,
        "serviceDetails": service_details,
    })
    svc_info = svc.get("service", svc)
    svc_id = svc_info["id"]
    svc_url = svc_info.get("serviceDetails", {}).get("url") or f"https://{svc_info.get('slug', default_slug)}.onrender.com"
    print(f"{name} created: {svc_id}")
    print(f"URL: {svc_url}")
    return {
        "id": svc_id,
        "name": name,
        "url": svc_url,
        "port": port,
        "type": service_type,
        "env_vars": env_vars,
    }

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
    zo_token = get_zo_token()
    persona_map = fetch_persona_map(zo_token)
    model_scenario_map = build_model_scenario_map()
    relay_secret = secrets.token_urlsafe(32)
    auth_secret = secrets.token_urlsafe(48)

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

    # 2. Create Paperclip Web Service
    print("\n=== Creating Paperclip Web Service ===")
    paperclip_public_base_url = "https://paperclip-server.onrender.com"
    paperclip_env_vars = [
        {"key": "NODE_ENV", "value": "production"},
        {"key": "HOST", "value": "0.0.0.0"},
        {"key": "PORT", "value": "3100"},
        {"key": "SERVE_UI", "value": "true"},
        {"key": "BETTER_AUTH_SECRET", "value": auth_secret},
        {"key": "PAPERCLIP_AUTH_PUBLIC_BASE_URL", "value": paperclip_public_base_url},
        {"key": "PAPERCLIP_DEPLOYMENT_MODE", "value": "authenticated"},
        {"key": "PAPERCLIP_DEPLOYMENT_EXPOSURE", "value": "private"},
        {"key": "PAPERCLIP_MIGRATION_AUTO_APPLY", "value": "true"},
        {"key": "HEARTBEAT_SCHEDULER_ENABLED", "value": "false"},
        {"key": "DURABLE_ENGINE", "value": "legacy"},
        {"key": "INNGEST_APP_ID", "value": "paperclip"},
    ]
    for optional_env in ("INNGEST_EVENT_KEY", "INNGEST_SIGNING_KEY"):
        env_var = maybe_env_var(optional_env)
        if env_var:
            paperclip_env_vars.append(env_var)

    if database_url:
        paperclip_env_vars.append({"key": "DATABASE_URL", "value": database_url})

    paperclip_service = create_service(
        owner_id=owner_id,
        name="paperclip-server",
        service_type="web_service",
        dockerfile_path="./Dockerfile.render",
        env_vars=paperclip_env_vars,
        default_slug="paperclip-server",
        port="3100",
        health_check_path="/api/health",
    )

    worker_env_vars = [
        {"key": "NODE_ENV", "value": "production"},
        {"key": "PAPERCLIP_MIGRATION_AUTO_APPLY", "value": "true"},
        {"key": "HEARTBEAT_SCHEDULER_ENABLED", "value": "true"},
        {"key": "HEARTBEAT_SCHEDULER_INTERVAL_MS", "value": "30000"},
        {"key": "DURABLE_ENGINE", "value": "legacy"},
        {"key": "INNGEST_APP_ID", "value": "paperclip"},
    ]
    env_var = maybe_env_var("INNGEST_EVENT_KEY")
    if env_var:
        worker_env_vars.append(env_var)
    if database_url:
        worker_env_vars.append({"key": "DATABASE_URL", "value": database_url})

    print("\n=== Creating Heartbeat Worker ===")
    worker_service = create_service(
        owner_id=owner_id,
        name="paperclip-heartbeat-worker",
        service_type="worker",
        dockerfile_path="./Dockerfile.heartbeat-worker",
        env_vars=worker_env_vars,
        default_slug="paperclip-heartbeat-worker",
    )

    relay_env_vars = [
        {"key": "NODE_ENV", "value": "production"},
        {"key": "HOST", "value": "0.0.0.0"},
        {"key": "PORT", "value": "3200"},
        {"key": "ZO_EXECUTION_TOKEN", "value": zo_token},
        {"key": "RELAY_EVAL_ENABLED", "value": "true"},
        {"key": "RELAY_EVAL_PROJECT", "value": "paperclip"},
        {"key": "EVAL_SERVICE_URL", "value": os.environ.get("EVAL_SERVICE_URL", "https://eval-service-abp.zocomputer.io/eval")},
        {"key": "PAPERCLIP_RELAY_SECRET", "value": relay_secret},
        {"key": "ZO_MODEL_SCENARIO_MAP_JSON", "value": json.dumps(model_scenario_map, separators=(",", ":"))},
        {"key": "ZO_PERSONA_MAP_JSON", "value": json.dumps(persona_map, separators=(",", ":"))},
        {"key": "PAPERCLIP_AGENT_KEYS_JSON", "value": "{}"},
    ]
    if database_url:
        relay_env_vars.extend([
            {"key": "DATABASE_URL", "value": database_url},
            {"key": "RELAY_DATABASE_URL", "value": database_url},
        ])

    print("\n=== Creating Zo Relay Web Service ===")
    relay_service = create_service(
        owner_id=owner_id,
        name="paperclip-zo-relay",
        service_type="web_service",
        dockerfile_path="./Dockerfile.relay",
        env_vars=relay_env_vars,
        default_slug="paperclip-zo-relay",
        port="3200",
        health_check_path="/health",
    )

    # If we didn't have the DB URL yet, update both services
    if not database_url:
        print("Fetching database connection string...")
        db_detail = api("GET", f"/postgres/{db_id}")
        db_d = db_detail.get("postgres", db_detail)
        ci = db_d.get("connectionInfo", {})
        database_url = ci.get("internalConnectionString") or ci.get("externalConnectionString", "")
        if database_url:
            paperclip_env_vars = [
                *paperclip_env_vars,
                {"key": "DATABASE_URL", "value": database_url},
            ]
            worker_env_vars = [
                *worker_env_vars,
                {"key": "DATABASE_URL", "value": database_url},
            ]
            relay_env_vars = [
                *relay_env_vars,
                {"key": "DATABASE_URL", "value": database_url},
                {"key": "RELAY_DATABASE_URL", "value": database_url},
            ]
            api("PUT", f"/services/{paperclip_service['id']}/env-vars", paperclip_env_vars)
            api("PUT", f"/services/{worker_service['id']}/env-vars", worker_env_vars)
            api("PUT", f"/services/{relay_service['id']}/env-vars", relay_env_vars)
            paperclip_service["env_vars"] = paperclip_env_vars
            worker_service["env_vars"] = worker_env_vars
            relay_service["env_vars"] = relay_env_vars
            print("DATABASE_URL set on all services")

    # Save state
    state = {
        "owner_id": owner_id,
        "database": {
            "id": db_id,
            "name": "paperclip-db",
            "internal_url": "[redacted]" if internal_url else "",
            "external_url": "[redacted]" if external_url else "",
        },
        "service": sanitize_service_state(paperclip_service),
        "worker": sanitize_service_state(worker_service),
        "relay": sanitize_service_state(relay_service),
        "relay_secret": "[redacted]",
        "auth_secret": "[redacted]",
        "zo_persona_map": persona_map,
        "zo_model_scenario_map": model_scenario_map,
        "deployed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    save_state(state)

    # Wait for deploys
    print("\n=== Waiting for initial deploys ===")
    paperclip_ok = wait_for_service(paperclip_service["id"])
    worker_ok = wait_for_service(worker_service["id"])
    relay_ok = wait_for_service(relay_service["id"])
    success = paperclip_ok and worker_ok and relay_ok

    if success:
        print("\n✓ Paperclip stack deployed successfully!")
        print(f"  Paperclip: {paperclip_service['url']}")
        print(f"  Relay: {relay_service['url']}")
    else:
        print(f"\n⚠ Deploy may still be in progress. Check: {paperclip_service['url']} and {relay_service['url']}")
        print("  Run: python3.12 scripts/render-status.py")

    return 0 if success else 1

if __name__ == "__main__":
    sys.exit(main())
