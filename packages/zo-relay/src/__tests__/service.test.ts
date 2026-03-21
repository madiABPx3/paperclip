import { describe, expect, it, vi } from "vitest";
import { executeRelayRequest, deriveContinuityKey } from "../service.js";
import type { ContinuityRecord, PaperclipWakePayload } from "../types.js";
import { callEvalService } from "../eval-client.js";

function basePayload(): PaperclipWakePayload {
  return {
    agentId: "8670781a-1443-49cc-98a1-3f507502b997",
    runId: "11111111-1111-1111-1111-111111111111",
    context: {
      issueId: "22222222-2222-2222-2222-222222222222",
      taskKey: "ZOA-29",
    },
    relay: {
      schemaVersion: "v1",
      executionMode: "heartbeat",
      paperclipBaseUrl: "https://paperclip.example.com",
      paperclipAgentKeyRef: "8670781a-1443-49cc-98a1-3f507502b997",
      zoPersonaName: "ender",
      zoModelScenario: "general",
      timeoutMs: 45000,
      maxAttempts: 2,
      taskIdentityPreference: ["issueId", "taskKey", "runId"],
    },
  };
}

describe("deriveContinuityKey", () => {
  it("prefers issueId over taskKey and runId", () => {
    expect(deriveContinuityKey(basePayload())).toBe(
      "8670781a-1443-49cc-98a1-3f507502b997:22222222-2222-2222-2222-222222222222",
    );
  });
});

describe("executeRelayRequest", () => {
  it("reuses prior continuity and applies comment actions", async () => {
    const payload = basePayload();
    const upserts: ContinuityRecord[] = [];
    const postIssueComment = vi.fn(async () => ({}));
    const updateIssueStatus = vi.fn(async () => ({}));

    const result = await executeRelayRequest(payload, {
      store: {
        get: async () => ({
          continuityKey: deriveContinuityKey(payload),
          agentId: payload.agentId,
          issueId: "22222222-2222-2222-2222-222222222222",
          taskKey: "ZOA-29",
          latestRunId: "33333333-3333-3333-3333-333333333333",
          zoConversationId: "conv_existing",
          lastZoOutcome: "completed",
          lastSummarySha256: "abc",
          lastTouchedAt: new Date().toISOString(),
          expiresAt: null,
        }),
        upsert: async (record) => {
          upserts.push(record);
        },
      },
      createPaperclipClient: () => ({
        getAgent: async () => ({
          id: payload.agentId,
          companyId: "44444444-4444-4444-4444-444444444444",
          name: "Ender",
          role: "ceo",
          capabilities: null,
          metadata: { skills: ["architecture-governance"] },
        }),
        getIssueHeartbeatContext: async () => ({
          issue: {
            id: "22222222-2222-2222-2222-222222222222",
            identifier: "ZOA-29",
            title: "Example",
            description: null,
            status: "todo",
            priority: "medium",
            projectId: null,
            goalId: null,
            parentId: null,
            assigneeAgentId: payload.agentId,
            assigneeUserId: null,
            updatedAt: new Date().toISOString(),
          },
          ancestors: [],
          project: null,
          goal: null,
          commentCursor: null,
          wakeComment: null,
        }),
        postIssueComment,
        updateIssueStatus,
      }),
      resolvePersonaId: async () => "persona_ender",
      resolveZoToken: () => "Bearer token",
      now: () => new Date("2026-03-20T18:30:00.000Z"),
      env: {
        ZO_MODEL_SCENARIO_MAP_JSON: JSON.stringify({
          general: { modelName: "byok:test-general", label: "test-general" },
        }),
        ZO_API_BASE_URL: "https://api.zo.computer",
      },
      log: () => undefined,
    });

    expect(result.httpStatus).toBe(200);
    expect(result.body.status).toBe("success");
    expect(postIssueComment).toHaveBeenCalledOnce();
    expect(updateIssueStatus).not.toHaveBeenCalled();
    expect(upserts[0]?.zoConversationId).toBe("conv_new");
  });

  it("fails closed before Paperclip mutations when eval does not pass", async () => {
    vi.mocked(callEvalService).mockResolvedValueOnce({
      passed: false,
      correlationId: "11111111-1111-1111-1111-111111111111",
      results: [
        {
          metric_name: "safety",
          score: 0.6,
          threshold: 0.95,
          passed: false,
          metric_type: "g_eval",
          reason: "Unsafe mutation",
        },
      ],
    });

    const payload = basePayload();
    const postIssueComment = vi.fn(async () => ({}));
    const updateIssueStatus = vi.fn(async () => ({}));

    const result = await executeRelayRequest(payload, {
      store: {
        get: async () => null,
        upsert: async () => undefined,
      },
      createPaperclipClient: () => ({
        getAgent: async () => ({
          id: payload.agentId,
          companyId: "44444444-4444-4444-4444-444444444444",
          name: "Ender",
          role: "ceo",
          capabilities: null,
          metadata: { skills: ["architecture-governance"] },
        }),
        getIssueHeartbeatContext: async () => ({
          issue: {
            id: "22222222-2222-2222-2222-222222222222",
            identifier: "ZOA-29",
            title: "Example",
            description: null,
            status: "todo",
            priority: "medium",
            projectId: null,
            goalId: null,
            parentId: null,
            assigneeAgentId: payload.agentId,
            assigneeUserId: null,
            updatedAt: new Date().toISOString(),
          },
          ancestors: [],
          project: null,
          goal: null,
          commentCursor: null,
          wakeComment: null,
        }),
        postIssueComment,
        updateIssueStatus,
      }),
      resolvePersonaId: async () => "persona_ender",
      resolveZoToken: () => "Bearer token",
      now: () => new Date("2026-03-20T18:30:00.000Z"),
      env: {
        RELAY_EVAL_ENABLED: "true",
        EVAL_SERVICE_URL: "https://eval.example.com/eval",
        ZO_MODEL_SCENARIO_MAP_JSON: JSON.stringify({
          general: { modelName: "byok:test-general", label: "test-general" },
        }),
      },
      log: () => undefined,
    });

    expect(result.httpStatus).toBe(500);
    expect(result.body.failureCode).toBe("eval_gate_failed");
    expect(postIssueComment).not.toHaveBeenCalled();
    expect(updateIssueStatus).not.toHaveBeenCalled();
  });
});

vi.mock("../zo-client.js", () => ({
  callZoAsk: vi.fn(async () => ({
    conversationId: "conv_new",
    output: {
      outcome: "completed",
      summary_markdown: "completed summary",
      paperclip_actions: [
        {
          type: "comment_issue",
          issue_id: "22222222-2222-2222-2222-222222222222",
          body_markdown: "Relay comment",
          next_status: "",
        },
      ],
      continuity: {
        should_continue: true,
        continuation_hint: "",
      },
    },
  })),
  ZoHttpError: class ZoHttpError extends Error {
    constructor(message: string, readonly status: number) {
      super(message);
    }
  },
}));

vi.mock("../eval-client.js", () => ({
  callEvalService: vi.fn(async () => ({
    passed: true,
    correlationId: "11111111-1111-1111-1111-111111111111",
    results: [],
  })),
  EvalHttpError: class EvalHttpError extends Error {
    constructor(message: string, readonly status: number) {
      super(message);
    }
  },
}));
