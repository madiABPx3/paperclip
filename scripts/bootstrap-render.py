#!/usr/bin/env python3.12
"""Bootstrap the Render-hosted Paperclip with company, agents, and goal.

Usage: python3.12 scripts/bootstrap-render.py [--render-url URL]

Reads the Render service URL from scripts/.render-state.json (or --render-url).
Creates the same company/agents/goal structure as the local Zo instance.
"""
import json
import os
import sys
import urllib.request
import urllib.error

STATE_FILE = os.path.join(os.path.dirname(__file__), ".render-state.json")
WEBHOOK_SECRET_PATH = "/home/workspace/config/.paperclip-webhook-secret"

def get_render_url():
    for arg in sys.argv[1:]:
        if arg.startswith("--render-url="):
            return arg.split("=", 1)[1].rstrip("/")
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            state = json.load(f)
        return state.get("service", {}).get("url", "").rstrip("/")
    print("No Render URL found. Pass --render-url=URL or ensure .render-state.json exists.", file=sys.stderr)
    sys.exit(1)

def api(base_url, method, path, body=None):
    url = f"{base_url}{path}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        body_text = e.read().decode() if e.fp else ""
        print(f"API error {e.code} {method} {path}: {body_text[:300]}", file=sys.stderr)
        return None

def get_webhook_secret():
    try:
        return open(WEBHOOK_SECRET_PATH).read().strip()
    except:
        return None

def main():
    render_url = get_render_url()
    base = f"{render_url}/api"
    print(f"Bootstrapping Paperclip at: {render_url}")

    # Check health
    health = api(render_url, "GET", "/api/health")
    if not health:
        print("Server not healthy yet. Is it deployed and running?", file=sys.stderr)
        sys.exit(1)
    print(f"Server healthy: {health}")

    webhook_secret = get_webhook_secret()

    # Create company
    print("\n=== Creating Company ===")
    company = api(render_url, "POST", "/api/companies", {
        "name": "Zo Autonomous",
        "prefix": "ZOA",
        "monthlyBudgetCents": 100000,
        "requireBoardApproval": True,
    })
    if not company:
        print("Failed to create company", file=sys.stderr)
        sys.exit(1)
    company_id = company["id"]
    print(f"Company created: {company_id}")

    # Create agents
    print("\n=== Creating Agents ===")
    agents = [
        {
            "name": "Ender",
            "role": "CEO",
            "capabilities": "Strategic planning, architecture governance, fleet monitoring, issue triage, goal tracking",
            "monthlyBudgetCents": 50000,
            "metadata": {
                "persona": "ender",
                "skills": ["architecture-governance", "coding-workflow", "orchestrator", "pattaya", "ops-runbooks", "mission-control"],
            },
        },
        {
            "name": "Architect",
            "role": "CTO",
            "capabilities": "Architecture review, code review, engineering boundaries, dependency decisions, verification",
            "monthlyBudgetCents": 25000,
            "metadata": {
                "persona": "ender-verifier",
                "skills": ["architecture-governance", "engineering-boundaries", "coding-workflow", "ops-runbooks"],
            },
        },
        {
            "name": "Builder",
            "role": "Engineer",
            "capabilities": "Code implementation, testing, pattaya builds, data synthesis, operational fixes",
            "monthlyBudgetCents": 25000,
            "metadata": {
                "persona": "madi",
                "skills": ["coding-workflow", "pattaya", "ops-runbooks", "data-synthesis"],
            },
        },
    ]

    agent_ids = {}
    for agent_def in agents:
        agent = api(render_url, "POST", f"/api/companies/{company_id}/agents", agent_def)
        if agent:
            agent_ids[agent_def["name"]] = agent["id"]
            print(f"  {agent_def['name']} ({agent_def['role']}): {agent['id']}")
        else:
            print(f"  Failed to create {agent_def['name']}", file=sys.stderr)

    # Set reporting structure
    if "Architect" in agent_ids and "Ender" in agent_ids:
        api(render_url, "PATCH", f"/api/agents/{agent_ids['Architect']}", {"reportsTo": agent_ids["Ender"]})
    if "Builder" in agent_ids and "Ender" in agent_ids:
        api(render_url, "PATCH", f"/api/agents/{agent_ids['Builder']}", {"reportsTo": agent_ids["Ender"]})

    # Configure heartbeat adapters — point to zo.space webhook
    print("\n=== Configuring Heartbeat Adapters ===")
    adapter_config = {
        "heartbeatEnabled": True,
        "heartbeatIntervalSeconds": 14400,  # 4 hours
        "maxConcurrentHeartbeatRuns": 1,
        "heartbeatAdapter": {
            "type": "http",
            "url": "https://abp.zo.space/api/paperclip-heartbeat",
            "method": "POST",
            "headers": {},
        },
    }
    if webhook_secret:
        adapter_config["heartbeatAdapter"]["headers"]["X-Webhook-Secret"] = webhook_secret

    for name, aid in agent_ids.items():
        result = api(render_url, "PATCH", f"/api/agents/{aid}", adapter_config)
        if result:
            print(f"  {name}: heartbeat configured → zo.space webhook")
        else:
            print(f"  {name}: failed to configure heartbeat", file=sys.stderr)

    # Create goal
    print("\n=== Creating Goal ===")
    goal = api(render_url, "POST", f"/api/companies/{company_id}/goals", {
        "title": "Autonomous Zo Infrastructure Operations",
        "description": "Operate and maintain the Zo Computer ecosystem autonomously. Monitor fleet health, resolve issues, enforce governance, and continuously improve system reliability — all without human intervention.",
        "status": "active",
    })
    if goal:
        print(f"Goal created: {goal.get('id')}")

    # Summary
    print(f"\n{'='*50}")
    print(f"Bootstrap complete!")
    print(f"  Company: {company_id}")
    print(f"  Agents: {len(agent_ids)}")
    print(f"  Dashboard: {render_url}")
    print(f"  API: {render_url}/api")

    # Save bootstrap state
    bootstrap_state = {
        "render_url": render_url,
        "company_id": company_id,
        "agent_ids": agent_ids,
        "bootstrapped_at": __import__("time").strftime("%Y-%m-%dT%H:%M:%SZ", __import__("time").gmtime()),
    }
    bootstrap_path = os.path.join(os.path.dirname(__file__), ".render-bootstrap.json")
    with open(bootstrap_path, "w") as f:
        json.dump(bootstrap_state, f, indent=2)
    print(f"  State: {bootstrap_path}")

    return 0

if __name__ == "__main__":
    sys.exit(main())
