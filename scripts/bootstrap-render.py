#!/usr/bin/env python3.12
"""Bootstrap the Render-hosted Paperclip in authenticated mode.

Usage:
  python3.12 scripts/bootstrap-render.py
  python3.12 scripts/bootstrap-render.py --render-url=https://paperclip-server.onrender.com
  python3.12 scripts/bootstrap-render.py --admin-email=ops@example.com --admin-password=...

Flow:
  1. Resolve the Render service URL + relay metadata from scripts/.render-state.json.
  2. Create or sign in a board user over Better Auth.
  3. Claim bootstrap admin if the instance is still pending first admin bootstrap.
  4. If the instance is already bootstrapped but this session cannot see the seeded company,
     recover instance-admin access over HTTP using the bootstrap secret.
  5. Seed or reconcile the company, agents, relay keys, heartbeat adapters, and goal.
"""
import json
import os
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar

RENDER_API = "https://api.render.com/v1"
STATE_FILE = os.path.join(os.path.dirname(__file__), ".render-state.json")
BOOTSTRAP_STATE_FILE = os.path.join(os.path.dirname(__file__), ".render-bootstrap.json")


def parse_args():
    args = {
        "render_url": None,
        "admin_email": None,
        "admin_password": None,
        "admin_name": "Paperclip Render Admin",
    }
    for arg in sys.argv[1:]:
        if arg.startswith("--render-url="):
            args["render_url"] = arg.split("=", 1)[1].rstrip("/")
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


def read_bootstrap_state():
    if not os.path.exists(BOOTSTRAP_STATE_FILE):
        return {}
    with open(BOOTSTRAP_STATE_FILE) as f:
        return json.load(f)


def write_bootstrap_state(payload):
    with open(BOOTSTRAP_STATE_FILE, "w") as f:
        json.dump(payload, f, indent=2)
        f.write("\n")


def render_api(method, path, body=None):
    key = os.environ.get("RENDER_API_KEY")
    if not key:
        probe = subprocess.run(
            ["zsh", "-lc", "printf %s \"$RENDER_API_KEY\""],
            text=True,
            capture_output=True,
            check=False,
        )
        key = probe.stdout.strip()
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


def restart_render_service(service_id):
    return render_api("POST", f"/services/{service_id}/restart", {})


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


def api(method, base_url, path, body=None, opener=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{base_url}{path}", data=data, method=method)
    req.add_header("Accept", "application/json")
    if body is not None:
        req.add_header("Content-Type", "application/json")
    if method.upper() not in ("GET", "HEAD", "OPTIONS"):
        req.add_header("Origin", base_url)
        req.add_header("Referer", f"{base_url}/")
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
        return None
    session_code, session_payload = api("GET", render_url, "/api/auth/get-session", opener=opener)
    if session_code != 200:
        print(f"Session verification failed ({session_code}): {session_payload}", file=sys.stderr)
        sys.exit(1)
    return session_payload


def sign_in_admin(render_url, opener, creds):
    status_code, payload = api(
        "POST",
        render_url,
        "/api/auth/sign-in/email",
        {"email": creds["email"], "password": creds["password"]},
        opener=opener,
    )
    if status_code not in (200, 201):
        return None
    session_code, session_payload = api("GET", render_url, "/api/auth/get-session", opener=opener)
    if session_code != 200:
        print(f"Session verification failed ({session_code}): {session_payload}", file=sys.stderr)
        sys.exit(1)
    return session_payload


def sign_up_or_sign_in_admin(render_url, opener, creds):
    session_payload = sign_up_admin(render_url, opener, creds)
    if session_payload:
        return session_payload, "signed_up"
    session_payload = sign_in_admin(render_url, opener, creds)
    if session_payload:
        return session_payload, "signed_in"
    print(f"Could not sign up or sign in admin user: {creds['email']}", file=sys.stderr)
    sys.exit(1)


def claim_bootstrap_admin(render_url, opener, bootstrap_secret):
    req = urllib.request.Request(
        f"{render_url}/api/bootstrap/claim-admin",
        data=b"{}",
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-Bootstrap-Secret": bootstrap_secret,
            "Origin": render_url,
            "Referer": f"{render_url}/",
        },
    )
    try:
        with opener.open(req, timeout=30) as resp:
            return json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        payload = e.read().decode() if e.fp else ""
        print(f"Bootstrap admin claim failed ({e.code}): {payload}", file=sys.stderr)
        sys.exit(1)


def recover_bootstrap_admin(render_url, opener, bootstrap_secret):
    req = urllib.request.Request(
        f"{render_url}/api/bootstrap/recover-admin",
        data=b"{}",
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-Bootstrap-Secret": bootstrap_secret,
            "Origin": render_url,
            "Referer": f"{render_url}/",
        },
    )
    try:
        with opener.open(req, timeout=30) as resp:
            return json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        payload = e.read().decode() if e.fp else ""
        print(f"Bootstrap admin recovery failed ({e.code}): {payload}", file=sys.stderr)
        sys.exit(1)


def authed_api(method, render_url, path, body, opener):
    status_code, payload = api(method, render_url, path, body, opener=opener)
    if status_code >= 400:
        print(f"API error {status_code} {method} {path}: {payload}", file=sys.stderr)
        sys.exit(1)
    return payload


def persist_bootstrap_state(state_payload, **updates):
    state_payload.update(updates)
    write_bootstrap_state(state_payload)


def ensure_company(render_url, opener, bootstrap_state):
    companies = authed_api("GET", render_url, "/api/companies", None, opener)
    company = None
    if bootstrap_state.get("company_id"):
        company = next((item for item in companies if item.get("id") == bootstrap_state["company_id"]), None)
    if company is None:
        company = next(
            (
                item
                for item in companies
                if item.get("name") == "Zo Autonomous" or item.get("issuePrefix") == "ZOA"
            ),
            None,
        )
    if company is None:
        company = authed_api(
            "POST",
            render_url,
            "/api/companies",
            {
                "name": "Zo Autonomous",
                "budgetMonthlyCents": 100000,
            },
            opener,
        )
        print(f"Company created: {company['id']}")
    else:
        print(f"Company reused: {company['id']}")
    company = authed_api(
        "PATCH",
        render_url,
        f"/api/companies/{company['id']}",
        {
            "requireBoardApprovalForNewAgents": True,
            "budgetMonthlyCents": 100000,
        },
        opener,
    )
    return company


def ensure_agent(render_url, opener, company_id, existing_agents, agent_def):
    existing = next((item for item in existing_agents if item.get("name") == agent_def["name"]), None)
    payload = {
        "name": agent_def["name"],
        "role": agent_def["role"],
        "capabilities": agent_def["capabilities"],
        "budgetMonthlyCents": agent_def["budgetMonthlyCents"],
        "metadata": agent_def["metadata"],
    }
    if existing is None:
        agent = authed_api("POST", render_url, f"/api/companies/{company_id}/agents", payload, opener)
        print(f"  {agent_def['name']} created: {agent['id']}")
        return agent
    agent = authed_api("PATCH", render_url, f"/api/agents/{existing['id']}", payload, opener)
    print(f"  {agent_def['name']} reused: {agent['id']}")
    return agent


def ensure_goal(render_url, opener, company_id):
    goals = authed_api("GET", render_url, f"/api/companies/{company_id}/goals", None, opener)
    existing = next((item for item in goals if item.get("title") == "Autonomous Zo Infrastructure Operations"), None)
    payload = {
        "title": "Autonomous Zo Infrastructure Operations",
        "description": (
            "Operate and maintain the Zo Computer ecosystem autonomously. Monitor fleet health, "
            "resolve issues, enforce governance, and continuously improve system reliability."
        ),
        "status": "active",
    }
    if existing is None:
        goal = authed_api("POST", render_url, f"/api/companies/{company_id}/goals", payload, opener)
        print(f"Goal created: {goal.get('id')}")
        return goal
    goal = authed_api("PATCH", render_url, f"/api/goals/{existing['id']}", payload, opener)
    print(f"Goal reused: {goal.get('id')}")
    return goal


def update_relay_env(state, agent_key_map):
    relay = state.get("relay", {})
    relay_id = relay.get("id")
    env_vars = relay.get("env_vars", [])
    if not relay_id or not isinstance(env_vars, list):
        print("Relay metadata missing from .render-state.json", file=sys.stderr)
        sys.exit(1)

    zo_token = os.environ.get("ZO_EXECUTION_TOKEN") or os.environ.get("ZO_CLIENT_IDENTITY_TOKEN")
    eval_service_url = os.environ.get("EVAL_SERVICE_URL", "https://eval-service-abp.zocomputer.io/eval")
    updated = []
    saw_agent_map = False
    saw_zo_token = False
    saw_eval_enabled = False
    saw_eval_project = False
    saw_eval_url = False
    changed = False
    for entry in env_vars:
        if entry.get("key") == "PAPERCLIP_AGENT_KEYS_JSON":
            next_value = json.dumps(agent_key_map, separators=(",", ":"))
            updated.append({"key": "PAPERCLIP_AGENT_KEYS_JSON", "value": next_value})
            saw_agent_map = True
            changed = changed or entry.get("value") != next_value
        elif entry.get("key") == "ZO_EXECUTION_TOKEN" and zo_token:
            updated.append({"key": "ZO_EXECUTION_TOKEN", "value": zo_token})
            saw_zo_token = True
            changed = changed or entry.get("value") != zo_token
        elif entry.get("key") == "RELAY_EVAL_ENABLED":
            updated.append({"key": "RELAY_EVAL_ENABLED", "value": "true"})
            saw_eval_enabled = True
            changed = changed or entry.get("value") != "true"
        elif entry.get("key") == "RELAY_EVAL_PROJECT":
            updated.append({"key": "RELAY_EVAL_PROJECT", "value": "paperclip"})
            saw_eval_project = True
            changed = changed or entry.get("value") != "paperclip"
        elif entry.get("key") == "EVAL_SERVICE_URL":
            updated.append({"key": "EVAL_SERVICE_URL", "value": eval_service_url})
            saw_eval_url = True
            changed = changed or entry.get("value") != eval_service_url
        else:
            updated.append(entry)
    if not saw_agent_map:
        updated.append({"key": "PAPERCLIP_AGENT_KEYS_JSON", "value": json.dumps(agent_key_map, separators=(",", ":"))})
        changed = True
    if zo_token and not saw_zo_token:
        updated.append({"key": "ZO_EXECUTION_TOKEN", "value": zo_token})
        changed = True
    if not saw_eval_enabled:
        updated.append({"key": "RELAY_EVAL_ENABLED", "value": "true"})
        changed = True
    if not saw_eval_project:
        updated.append({"key": "RELAY_EVAL_PROJECT", "value": "paperclip"})
        changed = True
    if not saw_eval_url:
        updated.append({"key": "EVAL_SERVICE_URL", "value": eval_service_url})
        changed = True

    if changed:
        render_api("PUT", f"/services/{relay_id}/env-vars", updated)
        restart_render_service(relay_id)
    state["relay"]["env_vars"] = updated


def main():
    args = parse_args()
    state = read_state()
    bootstrap_state = read_bootstrap_state()
    render_url = get_render_url(state, args["render_url"])
    relay_url = get_relay_url(state)
    health = ensure_service_ready(render_url)

    if health.get("deploymentMode") != "authenticated":
        print(f"Expected authenticated deployment mode, got {health.get('deploymentMode')}.", file=sys.stderr)
        sys.exit(1)
    if health.get("bootstrapStatus") not in ("bootstrap_pending", "ready"):
        print(
            f"Instance is not awaiting first-admin bootstrap (bootstrapStatus={health.get('bootstrapStatus')}).",
            file=sys.stderr,
        )
        sys.exit(1)

    print("\n=== Creating bootstrap admin session ===")
    opener = create_authenticated_opener()
    existing_admin = bootstrap_state.get("admin", {})
    creds = {
        "name": args["admin_name"],
        "email": args["admin_email"] or existing_admin.get("email") or f"paperclip-render-admin-{int(time.time())}@paperclip.local",
        "password": args["admin_password"] or existing_admin.get("password") or secrets.token_urlsafe(24),
    }
    session_payload, auth_mode = sign_up_or_sign_in_admin(render_url, opener, creds)
    print(f"Session ready via {auth_mode}: {creds['email']}")
    bootstrap_state = {
        **bootstrap_state,
        "render_url": render_url,
        "relay_url": relay_url,
        "admin": creds,
    }
    write_bootstrap_state(bootstrap_state)

    bootstrap_secret = state.get("auth_secret")
    if not bootstrap_secret:
        print("auth_secret missing from .render-state.json", file=sys.stderr)
        sys.exit(1)
    if health.get("bootstrapStatus") == "bootstrap_pending":
        print("\n=== Claiming bootstrap admin access ===")
        bootstrap_payload = claim_bootstrap_admin(render_url, opener, bootstrap_secret)
        print(f"Bootstrap admin claimed for user: {bootstrap_payload.get('userId')}")
    else:
        visible_companies = authed_api("GET", render_url, "/api/companies", None, opener)
        if not visible_companies:
            print("\n=== Recovering bootstrap admin access ===")
            recovery_payload = recover_bootstrap_admin(render_url, opener, bootstrap_secret)
            print(f"Bootstrap admin recovered for user: {recovery_payload.get('userId')}")

    print("\n=== Ensuring company ===")
    company = ensure_company(render_url, opener, bootstrap_state)
    company_id = company["id"]
    persist_bootstrap_state(bootstrap_state, company_id=company_id)

    print("\n=== Ensuring agents ===")
    agents = [
        {
            "name": "Ender",
            "role": "ceo",
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
            "role": "cto",
            "capabilities": "Architecture review, code review, engineering boundaries, dependency decisions, verification",
            "budgetMonthlyCents": 25000,
            "metadata": {
                "persona": "ender-verifier",
                "skills": ["architecture-governance", "engineering-boundaries", "coding-workflow", "ops-runbooks"],
            },
        },
        {
            "name": "Builder",
            "role": "engineer",
            "capabilities": "Code implementation, testing, pattaya builds, data synthesis, operational fixes",
            "budgetMonthlyCents": 25000,
            "metadata": {
                "persona": "madi",
                "skills": ["coding-workflow", "pattaya", "ops-runbooks", "data-synthesis"],
            },
        },
    ]

    existing_agents = authed_api("GET", render_url, f"/api/companies/{company_id}/agents", None, opener)
    agent_ids = {}
    agent_keys = bootstrap_state.get("agent_keys", {}).copy()
    for agent_def in agents:
        agent = ensure_agent(render_url, opener, company_id, existing_agents, agent_def)
        agent_ids[agent_def["name"]] = agent["id"]
        if agent["id"] not in agent_keys:
            key = authed_api(
                "POST",
                render_url,
                f"/api/agents/{agent['id']}/keys",
                {"name": "render-relay-v1"},
                opener,
            )
            agent_keys[agent["id"]] = key["token"]
            print(f"    relay key created: {key['id']}")
        else:
            print("    relay key reused from bootstrap state")
        persist_bootstrap_state(bootstrap_state, agent_ids=agent_ids, agent_keys=agent_keys)

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
        "ceo": "general",
        "cto": "architecture-planning",
        "engineer": "code-generation",
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
            "adapterType": "http",
            "adapterConfig": {
                "url": f"{relay_url}/execute",
                "method": "POST",
                "timeoutMs": 45000,
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
            "runtimeConfig": {
                "heartbeat": {
                    "enabled": True,
                    "intervalSec": 14400,
                    "wakeOnDemand": True,
                    "maxConcurrentRuns": 1,
                },
            },
        }
        authed_api("PATCH", render_url, f"/api/agents/{agent_id}", adapter_config, opener)
        print(f"  {name}: heartbeat configured")

    print("\n=== Ensuring goal ===")
    goal = ensure_goal(render_url, opener, company_id)

    persist_bootstrap_state(
        bootstrap_state,
        render_url=render_url,
        relay_url=relay_url,
        company_id=company_id,
        agent_ids=agent_ids,
        agent_keys=agent_keys,
        goal_id=goal.get("id"),
        bootstrapped_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    )
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)
        f.write("\n")

    print(f"\n{'=' * 50}")
    print("Bootstrap complete!")
    print(f"  Dashboard: {render_url}")
    print(f"  Company: {company_id}")
    print(f"  Agents: {len(agent_ids)}")
    print(f"  State: {BOOTSTRAP_STATE_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
