#!/usr/bin/env python3.12
"""Bootstrap the Render-hosted Paperclip in authenticated mode.

Usage:
  python3.12 scripts/bootstrap-render.py
  python3.12 scripts/bootstrap-render.py --render-url=https://paperclip-server.onrender.com
  python3.12 scripts/bootstrap-render.py --admin-email=ops@example.com --admin-password=...

Flow:
  1. Resolve the Render service URL + external Postgres URL from scripts/.render-state.json
     and the Render API.
  2. Mint a bootstrap CEO invite directly against the Render database using the local CLI.
  3. Create a board user over Better Auth, accept the bootstrap invite, and keep the session.
  4. Seed the company, agents, heartbeat adapter, and goal using authenticated API calls.
"""
import json
import os
import re
import secrets
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar

RENDER_API = "https://api.render.com/v1"
STATE_FILE = os.path.join(os.path.dirname(__file__), ".render-state.json")
BOOTSTRAP_STATE_FILE = os.path.join(os.path.dirname(__file__), ".render-bootstrap.json")
WEBHOOK_SECRET_PATH = "/home/workspace/config/.paperclip-webhook-secret"
PAPERCLIP_DIR = "/home/workspace/paperclip"


def parse_args():
    args = {
        "render_url": None,
        "db_url": None,
        "admin_email": None,
        "admin_password": None,
        "admin_name": "Paperclip Render Admin",
        "force": False,
    }
    for arg in sys.argv[1:]:
        if arg == "--force":
            args["force"] = True
        elif arg.startswith("--render-url="):
            args["render_url"] = arg.split("=", 1)[1].rstrip("/")
        elif arg.startswith("--db-url="):
            args["db_url"] = arg.split("=", 1)[1]
        elif arg.startswith("--admin-email="):
            args["admin_email"] = arg.split("=", 1)[1]
        elif arg.startswith("--admin-password="):
            args["admin_password"] = arg.split("=", 1)[1]
        elif arg.startswith("--admin-name="):
            args["admin_name"] = arg.split("=", 1)[1]
    return args


def read_state():
    if not os.path.exists(STATE_FILE):
        print(f"State file missing: {STATE_FILE}", file=sys.stderr)
        sys.exit(1)
    with open(STATE_FILE) as f:
        return json.load(f)


def render_api(method, path, body=None):
    key = os.environ.get("RENDER_API_KEY")
    if not key:
        print("RENDER_API_KEY not set; required to resolve the Render Postgres connection string.", file=sys.stderr)
        sys.exit(1)
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{RENDER_API}{path}", data=data, method=method)
    req.add_header("Authorization", f"Bearer {key}")
    req.add_header("Accept", "application/json")
    if body is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=60) as resp:
        raw = resp.read().decode()
        return json.loads(raw) if raw else {}


def get_render_url(state, explicit_url=None):
    url = explicit_url or state.get("service", {}).get("url", "")
    if not url:
        print("No Render URL found. Pass --render-url=URL or ensure .render-state.json exists.", file=sys.stderr)
        sys.exit(1)
    return url.rstrip("/")


def get_relay_url(state):
    url = state.get("relay", {}).get("url", "")
    if not url:
        print("No relay URL found in state file. Run deploy-render.py first.", file=sys.stderr)
        sys.exit(1)
    return url.rstrip("/")


def get_db_url(state, explicit_db_url=None):
    if explicit_db_url:
        return ensure_ssl_db_url(explicit_db_url)
    db_state = state.get("database", {})
    if db_state.get("external_url"):
        return ensure_ssl_db_url(db_state["external_url"])
    db_id = db_state.get("id")
    if not db_id:
        print("No Render Postgres ID found in state file.", file=sys.stderr)
        sys.exit(1)
    conn_info = render_api("GET", f"/postgres/{db_id}/connection-info")
    external = conn_info.get("externalConnectionString", "")
    if external:
        return ensure_ssl_db_url(external)
    print("Render API did not return an external Postgres connection string.", file=sys.stderr)
    sys.exit(1)


def ensure_ssl_db_url(db_url):
    parsed = urllib.parse.urlparse(db_url)
    if not parsed.scheme.startswith("postgres"):
        return db_url
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    keys = {key for key, _ in query}
    if "sslmode" not in keys:
        query.append(("sslmode", "require"))
    return urllib.parse.urlunparse(parsed._replace(query=urllib.parse.urlencode(query)))


def get_webhook_secret():
    try:
        with open(WEBHOOK_SECRET_PATH) as f:
            return f.read().strip()
    except OSError:
        return None


def api(method, base_url, path, body=None, opener=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{base_url}{path}", data=data, method=method)
    req.add_header("Accept", "application/json")
    if body is not None:
        req.add_header("Content-Type", "application/json")
    try:
        if opener is None:
            resp = urllib.request.urlopen(req, timeout=30)
        else:
            resp = opener.open(req, timeout=30)
        with resp:
            raw = resp.read().decode()
            return resp.getcode(), json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raw = e.read().decode() if e.fp else ""
        try:
            payload = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            payload = {"raw": raw}
        return e.code, payload


def ensure_service_ready(render_url):
    status_code, health = api("GET", render_url, "/api/health")
    if status_code != 200:
        print(f"Health check failed ({status_code}): {health}", file=sys.stderr)
        sys.exit(1)
    print(f"Server healthy: {health}")
    return health


def write_remote_bootstrap_config(db_url, render_url):
    tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
    config = {
        "$meta": {
            "version": 1,
            "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "source": "configure",
        },
        "database": {
            "mode": "postgres",
            "connectionString": db_url,
            "backup": {
                "enabled": True,
                "intervalMinutes": 60,
                "retentionDays": 30,
                "dir": "~/.paperclip/instances/default/data/backups",
            },
        },
        "logging": {
            "mode": "file",
            "logDir": "~/.paperclip/instances/default/logs",
        },
        "server": {
            "deploymentMode": "authenticated",
            "exposure": "private",
            "host": "0.0.0.0",
            "port": 3100,
            "allowedHostnames": [urllib.parse.urlparse(render_url).hostname],
            "serveUi": True,
        },
        "auth": {
            "baseUrlMode": "explicit",
            "publicBaseUrl": render_url,
            "disableSignUp": False,
        },
        "storage": {
            "provider": "local_disk",
            "localDisk": {
                "baseDir": "~/.paperclip/instances/default/data/storage",
            },
            "s3": {
                "bucket": "paperclip",
                "region": "us-east-1",
                "prefix": "",
                "forcePathStyle": False,
            },
        },
        "secrets": {
            "provider": "local_encrypted",
            "strictMode": False,
            "localEncrypted": {
                "keyFilePath": "~/.paperclip/instances/default/secrets/master.key",
            },
        },
    }
    json.dump(config, tmp)
    tmp.write("\n")
    tmp.close()
    return tmp.name


def run_bootstrap_invite(db_url, render_url, force=False):
    config_path = write_remote_bootstrap_config(db_url, render_url)
    cmd = [
        "pnpm",
        "paperclipai",
        "auth",
        "bootstrap-ceo",
        "--config",
        config_path,
        "--db-url",
        db_url,
        "--base-url",
        render_url,
    ]
    if force:
        cmd.append("--force")
    result = subprocess.run(
        cmd,
        cwd=PAPERCLIP_DIR,
        text=True,
        capture_output=True,
        check=False,
    )
    output = "\n".join(part for part in (result.stdout.strip(), result.stderr.strip()) if part)
    try:
        os.unlink(config_path)
    except OSError:
        pass
    if result.returncode != 0:
        print(output, file=sys.stderr)
        sys.exit(result.returncode)
    match = re.search(r"Invite URL:\s+(https?://\S+)", output)
    if not match:
        print(output, file=sys.stderr)
        print("Could not parse bootstrap invite URL from CLI output.", file=sys.stderr)
        sys.exit(1)
    invite_url = match.group(1)
    token = invite_url.rstrip("/").rsplit("/", 1)[-1]
    return invite_url, token, output


def create_authenticated_opener():
    jar = CookieJar()
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))


def ensure_admin_credentials(args):
    return {
        "name": args["admin_name"],
        "email": args["admin_email"] or f"paperclip-render-admin-{int(time.time())}@paperclip.local",
        "password": args["admin_password"] or secrets.token_urlsafe(24),
    }


def sign_up_admin(render_url, opener, creds):
    status_code, payload = api("POST", render_url, "/api/auth/sign-up/email", creds, opener=opener)
    if status_code not in (200, 201):
        print(f"Admin sign-up failed ({status_code}): {payload}", file=sys.stderr)
        sys.exit(1)
    session_code, session_payload = api("GET", render_url, "/api/auth/get-session", opener=opener)
    if session_code != 200:
        print(f"Session verification failed ({session_code}): {session_payload}", file=sys.stderr)
        sys.exit(1)
    return session_payload


def claim_bootstrap_admin(render_url, opener, bootstrap_secret):
    status_code, payload = api(
        "POST",
        render_url,
        "/api/bootstrap/claim-admin",
        {},
        opener=opener,
    )
    if status_code == 401:
        req = urllib.request.Request(
            f"{render_url}/api/bootstrap/claim-admin",
            data=b"{}",
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "X-Bootstrap-Secret": bootstrap_secret,
            },
        )
        with opener.open(req, timeout=30) as resp:
            return json.loads(resp.read().decode() or "{}")
    if status_code >= 400:
        print(f"Bootstrap admin claim failed ({status_code}): {payload}", file=sys.stderr)
        sys.exit(1)
    return payload


def accept_bootstrap_invite(render_url, opener, token):
    status_code, payload = api(
        "POST",
        render_url,
        f"/api/invites/{token}/accept",
        {"requestType": "human"},
        opener=opener,
    )
    if status_code != 202:
        print(f"Bootstrap invite acceptance failed ({status_code}): {payload}", file=sys.stderr)
        sys.exit(1)
    return payload


def authed_api(method, render_url, path, body, opener):
    status_code, payload = api(method, render_url, path, body, opener=opener)
    if status_code >= 400:
        print(f"API error {status_code} {method} {path}: {payload}", file=sys.stderr)
        sys.exit(1)
    return payload


def update_relay_env(state, agent_key_map):
    relay = state.get("relay", {})
    relay_id = relay.get("id")
    env_vars = relay.get("env_vars", [])
    if not relay_id or not isinstance(env_vars, list):
        print("Relay metadata missing from .render-state.json", file=sys.stderr)
        sys.exit(1)

    updated = []
    saw_agent_map = False
    for entry in env_vars:
        if entry.get("key") == "PAPERCLIP_AGENT_KEYS_JSON":
            updated.append({"key": "PAPERCLIP_AGENT_KEYS_JSON", "value": json.dumps(agent_key_map, separators=(",", ":"))})
            saw_agent_map = True
        else:
            updated.append(entry)
    if not saw_agent_map:
        updated.append({"key": "PAPERCLIP_AGENT_KEYS_JSON", "value": json.dumps(agent_key_map, separators=(",", ":"))})

    render_api("PUT", f"/services/{relay_id}/env-vars", updated)
    state["relay"]["env_vars"] = updated


def main():
    args = parse_args()
    state = read_state()
    render_url = get_render_url(state, args["render_url"])
    relay_url = get_relay_url(state)
    db_url = get_db_url(state, args["db_url"])
    health = ensure_service_ready(render_url)

    if health.get("deploymentMode") != "authenticated":
        print(f"Expected authenticated deployment mode, got {health.get('deploymentMode')}.", file=sys.stderr)
        sys.exit(1)
    if health.get("bootstrapStatus") != "bootstrap_pending":
        print(
            f"Instance is not awaiting first-admin bootstrap (bootstrapStatus={health.get('bootstrapStatus')}).",
            file=sys.stderr,
        )
        sys.exit(1)

    print("\n=== Creating bootstrap admin session ===")
    opener = create_authenticated_opener()
    creds = ensure_admin_credentials(args)
    session_payload = sign_up_admin(render_url, opener, creds)
    print(f"Signed in as: {session_payload.get('user', {}).get('email')}")

    print("\n=== Claiming bootstrap admin access ===")
    bootstrap_secret = state.get("auth_secret")
    if not bootstrap_secret:
        print("auth_secret missing from .render-state.json", file=sys.stderr)
        sys.exit(1)
    bootstrap_payload = claim_bootstrap_admin(render_url, opener, bootstrap_secret)
    print(f"Bootstrap admin claimed for user: {bootstrap_payload.get('userId')}")

    print("\n=== Creating company ===")
    company = authed_api(
        "POST",
        render_url,
        "/api/companies",
        {
            "name": "Zo Autonomous",
            "prefix": "ZOA",
            "budgetMonthlyCents": 100000,
            "requireBoardApprovalForNewAgents": True,
        },
        opener,
    )
    company_id = company["id"]
    print(f"Company created: {company_id}")

    print("\n=== Creating agents ===")
    agents = [
        {
            "name": "Ender",
            "role": "CEO",
            "capabilities": "Strategic planning, architecture governance, fleet monitoring, issue triage, goal tracking",
            "budgetMonthlyCents": 50000,
            "metadata": {
                "persona": "ender",
                "skills": [
                    "architecture-governance",
                    "coding-workflow",
                    "orchestrator",
                    "pattaya",
                    "ops-runbooks",
                    "mission-control",
                ],
            },
        },
        {
            "name": "Architect",
            "role": "CTO",
            "capabilities": "Architecture review, code review, engineering boundaries, dependency decisions, verification",
            "budgetMonthlyCents": 25000,
            "metadata": {
                "persona": "ender-verifier",
                "skills": ["architecture-governance", "engineering-boundaries", "coding-workflow", "ops-runbooks"],
            },
        },
        {
            "name": "Builder",
            "role": "Engineer",
            "capabilities": "Code implementation, testing, pattaya builds, data synthesis, operational fixes",
            "budgetMonthlyCents": 25000,
            "metadata": {
                "persona": "madi",
                "skills": ["coding-workflow", "pattaya", "ops-runbooks", "data-synthesis"],
            },
        },
    ]

    agent_ids = {}
    agent_keys = {}
    for agent_def in agents:
        agent = authed_api("POST", render_url, f"/api/companies/{company_id}/agents", agent_def, opener)
        agent_ids[agent_def["name"]] = agent["id"]
        print(f"  {agent_def['name']} ({agent_def['role']}): {agent['id']}")
        key = authed_api(
            "POST",
            render_url,
            f"/api/agents/{agent['id']}/keys",
            {"name": "render-relay-v1"},
            opener,
        )
        agent_keys[agent["id"]] = key["token"]
        print(f"    relay key: {key['id']}")

    if "Architect" in agent_ids and "Ender" in agent_ids:
        authed_api(
            "PATCH",
            render_url,
            f"/api/agents/{agent_ids['Architect']}",
            {"reportsTo": agent_ids["Ender"]},
            opener,
        )
    if "Builder" in agent_ids and "Ender" in agent_ids:
        authed_api(
            "PATCH",
            render_url,
            f"/api/agents/{agent_ids['Builder']}",
            {"reportsTo": agent_ids["Ender"]},
            opener,
        )

    update_relay_env(state, agent_keys)

    print("\n=== Configuring heartbeat adapters ===")
    relay_secret = state.get("relay_secret")
    persona_map = state.get("zo_persona_map", {})

    scenario_by_role = {
        "CEO": "general",
        "CTO": "architecture-planning",
        "Engineer": "code-generation",
    }
    persona_by_name = {
        "Ender": persona_map.get("ender"),
        "Architect": persona_map.get("ender-verifier"),
        "Builder": persona_map.get("madi"),
    }

    for agent_def in agents:
        name = agent_def["name"]
        agent_id = agent_ids[name]
        persona_id = persona_by_name.get(name)
        adapter_config = {
            "heartbeatEnabled": True,
            "heartbeatIntervalSeconds": 14400,
            "maxConcurrentHeartbeatRuns": 1,
            "heartbeatAdapter": {
                "type": "http",
                "url": f"{relay_url}/execute",
                "method": "POST",
                "headers": {
                    "X-Paperclip-Relay-Secret": relay_secret,
                },
                "payloadTemplate": {
                    "relay": {
                        "schemaVersion": "v1",
                        "executionMode": "heartbeat",
                        "paperclipBaseUrl": render_url,
                        "paperclipCompanyId": company_id,
                        "paperclipAgentKeyRef": agent_id,
                        "zoPersonaId": persona_id,
                        "zoModelScenario": scenario_by_role.get(agent_def["role"], "general"),
                        "timeoutMs": 45000,
                        "maxAttempts": 2,
                        "taskIdentityPreference": ["issueId", "taskKey", "runId"],
                    },
                },
            },
        }
        authed_api("PATCH", render_url, f"/api/agents/{agent_id}", adapter_config, opener)
        print(f"  {name}: heartbeat configured")

    print("\n=== Creating goal ===")
    goal = authed_api(
        "POST",
        render_url,
        f"/api/companies/{company_id}/goals",
        {
            "title": "Autonomous Zo Infrastructure Operations",
            "description": (
                "Operate and maintain the Zo Computer ecosystem autonomously. Monitor fleet health, "
                "resolve issues, enforce governance, and continuously improve system reliability."
            ),
            "status": "active",
        },
        opener,
    )
    print(f"Goal created: {goal.get('id')}")

    state_payload = {
        "render_url": render_url,
        "relay_url": relay_url,
        "company_id": company_id,
        "agent_ids": agent_ids,
        "agent_keys": agent_keys,
        "bootstrap_invite_url": invite_url,
        "admin": {
            "name": creds["name"],
            "email": creds["email"],
            "password": creds["password"],
        },
        "bootstrapped_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    with open(BOOTSTRAP_STATE_FILE, "w") as f:
        json.dump(state_payload, f, indent=2)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

    print(f"\n{'=' * 50}")
    print("Bootstrap complete!")
    print(f"  Dashboard: {render_url}")
    print(f"  Company: {company_id}")
    print(f"  Agents: {len(agent_ids)}")
    print(f"  State: {BOOTSTRAP_STATE_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
