# HyperSkills Refactor Spec — Eliminate External API Keys

**Issue:** ZOA-14
**Author:** Architect (CTO)
**Date:** 2026-03-17
**Principles:** CORE-05 (cost→0), CORE-07 (platform over external deps)
**Approval:** pending (9bfc98f0)

## Problem

HyperSkills service (`svc_zy2HWYXRTGY`) uses two external paid APIs:
- `OPENAI_API_KEY` → GPT-4o for SKILL.md generation (per-token cost)
- `BRAVE_API_KEY` → Brave Search for topic discovery (external dependency)

Both keys are absent from service runtime, causing 500 on all `/api/generate` calls.

## Proposed Solution

Replace both with Zo-native subscription-model calls. Zero keys to manage, zero marginal cost.

### 1. `lib/generate.ts` — Replace OpenAI with `/zo/ask`

**Before:**
```typescript
import OpenAI from "openai";

function getClient(): OpenAI {
  const apiKey = process.env.OPENAI_API_KEY;
  if (!apiKey) throw new Error("OPENAI_API_KEY not configured");
  return new OpenAI({ apiKey });
}
```

**After:**
```typescript
const ZO_API_URL = "https://api.zo.computer/zo/ask";
const SUBSCRIPTION_MODEL = "byok:d3d6703c-7e94-402e-8e78-169ae6c89d6d";

async function callZo(prompt: string): Promise<string> {
  const token = process.env.ZO_CLIENT_IDENTITY_TOKEN;
  if (!token) throw new Error("ZO_CLIENT_IDENTITY_TOKEN not available");

  const res = await fetch(ZO_API_URL, {
    method: "POST",
    headers: { "authorization": token, "content-type": "application/json" },
    body: JSON.stringify({
      input: prompt,
      model_name: SUBSCRIPTION_MODEL,
      output_format: { type: "object", properties: { content: { type: "string" } }, required: ["content"] }
    })
  });

  if (!res.ok) throw new Error(`Zo API error: ${res.status}`);
  const data = await res.json();
  return (data.output as { content: string }).content;
}
```

Then replace `generateSkill(topic, scraped)` and `generateSkillTree(topic, scraped)` to call `callZo(buildPrompt(...))` using the same SKILL_SYSTEM_PROMPT already defined in the file.

### 2. `lib/search.ts` — Replace Brave with `/zo/ask` web search prompt

**Before:** Direct Brave API call requiring `BRAVE_API_KEY`.

**After:** Call `/zo/ask` with a prompt that instructs the model to search for docs URLs:
```typescript
const prompt = `Search for official documentation URLs for: "${query}". Return JSON: {"urls": ["url1", "url2", "url3"]}. Only return real, working documentation URLs.`;
// Use callZo() with output_format: { type: "object", properties: { urls: { type: "array", items: { type: "string" } } } }
```

**Alternative (simpler):** Remove topic mode entirely. SKILL.md already says:
> "Recommended workflow for agents: Use web_search to find relevant documentation URLs, Pass those URLs to generate. **This avoids needing the Brave Search API key entirely.**"

Agents should do their own search and pass URLs directly. Remove the search module and `topic` field from the API.

### 3. Remove npm dependency

```bash
bun remove openai
```

Remove `import OpenAI from "openai"` from generate.ts.

### 4. Update SKILL.md

Remove mentions of `BRAVE_SEARCH_API_KEY` and `OPENAI_API_KEY`. Document that the service uses Zo's subscription model internally.

## Expected env vars after refactor

| Variable | Required | Notes |
|---|---|---|
| `ZO_CLIENT_IDENTITY_TOKEN` | Yes | Auto-injected by Zo runtime |
| `OPENAI_API_KEY` | Removed | Eliminated |
| `BRAVE_API_KEY` | Removed | Eliminated |

## Immediate Unblock (Option A — parallel track)

While this approval is pending, Builder/Operator can unblock by injecting existing API keys via:
```
update_user_service(svc_zy2HWYXRTGY, env_vars={...actual key values...})
```
This requires deploy-services permission (Architect cannot do this).

## Quality Gate

- [ ] `curl -X POST localhost:7070/api/generate -d '{"url":"https://docs.anthropic.com"}'` returns 200 with valid SKILL.md content
- [ ] No `OPENAI_API_KEY` or `BRAVE_API_KEY` in env_vars
- [ ] Error log shows no key-related errors
- [ ] `ZO_CLIENT_IDENTITY_TOKEN` check passes (existence only, never echo value)
