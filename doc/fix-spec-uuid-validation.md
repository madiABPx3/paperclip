# Fix Spec: UUID Validation in Issue Routes

**Issue**: Paperclip PostgresError: invalid UUID input syntax
**Issue ID**: 84581d90-f2ef-408f-99de-6243e399f813
**Author**: Architect agent (e640a574)
**Date**: 2026-03-17
**Principle**: ARCH-13 (fail fast, recover gracefully), CORE-03 (simplicity first)

---

## Root Cause

`POST /api/issues/6292c6e4/comments` was sent with a truncated UUID (`6292c6e4` — only the first 8 hex chars of `6292c6e4-384c-4b6f-919c-fa3843f93436`).

`normalizeIssueIdentifier` only transforms short identifiers like `PAP-39`. For everything else, it passes `rawId` through unchanged. When `svc.getById("6292c6e4")` executes, Postgres throws:

```
PostgresError: invalid input syntax for type uuid: "6292c6e4"
```

This yields a 500 Internal Server Error instead of the correct 400 Bad Request.

**Source of truncation**: The CEO agent constructed the comment URL using only the first hyphen-delimited segment of the UUID rather than the full UUID string. This is a client-side data extraction error (likely a string split + first-element selection).

---

## Fix: Two-Layer Defense

### Layer 1 — Server-Side (primary fix): UUID validation in `normalizeIssueIdentifier`

File: `paperclip/server/src/routes/issues.ts`

```typescript
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

async function normalizeIssueIdentifier(rawId: string): Promise<string> {
  // Short identifier like PAP-39
  if (/^[A-Z]+-\d+$/i.test(rawId)) {
    const issue = await svc.getByIdentifier(rawId);
    if (issue) return issue.id;
  }
  // Reject malformed UUIDs before they reach Postgres
  if (!UUID_RE.test(rawId)) {
    const err: any = new Error(`Invalid issue identifier format: "${rawId}"`);
    err.statusCode = 400;
    throw err;
  }
  return rawId;
}
```

This converts the 500 to a 400 Bad Request. No behavior change for valid UUIDs or valid short identifiers.

**Note**: Verify that the error middleware in `app.ts` reads `err.statusCode` and returns it to the client. If not, use a custom error class that the error handler already recognizes.

### Layer 2 — Client-Side (secondary hardening): Ensure agents use full UUIDs

The Paperclip heartbeat system prompt instructs agents to call:
```
POST http://localhost:3102/api/issues/{id}/comments
```

The `{id}` must be the **full UUID**. The CEO agent incorrectly used `6292c6e4` (first segment only) instead of `6292c6e4-384c-4b6f-919c-fa3843f93436`.

**Where to check**: The CEO agent config or heartbeat adapter context that constructs the comment URL. Verify that issue IDs passed to agents in context are full UUIDs, not truncated strings.

---

## Acceptance Criteria

1. `POST /api/issues/6292c6e4/comments` returns HTTP 400 with `{"error": "Invalid issue identifier format: \"6292c6e4\""}` instead of 500
2. `POST /api/issues/6292c6e4-384c-4b6f-919c-fa3843f93436/comments` continues to work normally
3. `POST /api/issues/PAP-39/comments` continues to work normally (short identifier)
4. No new unit test failures
5. Add one test case: `normalizeIssueIdentifier("6292c6e4")` throws a 400-level error

---

## Effort Estimate

Server fix: ~15 min (3 lines of code + 1 test case)
Client investigation: ~30 min (find where agent truncates UUID in heartbeat context)
