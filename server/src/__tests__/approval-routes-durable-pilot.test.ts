import express from "express";
import request from "supertest";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { approvalRoutes } from "../routes/approvals.js";
import { errorHandler } from "../middleware/index.js";

const mockApprovalService = vi.hoisted(() => ({
  list: vi.fn(),
  getById: vi.fn(),
  create: vi.fn(),
  approve: vi.fn(),
  reject: vi.fn(),
  requestRevision: vi.fn(),
  resubmit: vi.fn(),
  listComments: vi.fn(),
  addComment: vi.fn(),
}));

const mockHeartbeatService = vi.hoisted(() => ({
  wakeup: vi.fn(),
}));

const mockIssueApprovalService = vi.hoisted(() => ({
  listIssuesForApproval: vi.fn(),
  linkManyForApproval: vi.fn(),
}));

const mockSecretService = vi.hoisted(() => ({
  normalizeHireApprovalPayloadForPersistence: vi.fn(),
}));

const mockLogActivity = vi.hoisted(() => vi.fn());

const mockDurableEngine = vi.hoisted(() => ({
  isInngestPilotEnabled: vi.fn(() => true),
  readApprovalWorkflowMetadata: vi.fn(() => ({ runId: "run-1" })),
  withApprovalWorkflowMetadata: vi.fn((payload: Record<string, unknown>) => payload),
  buildApprovalResolvedPayload: vi.fn((input: Record<string, unknown>) => input),
  publishApprovalResolvedEvent: vi.fn(),
  logDurableEngineFallback: vi.fn(),
}));

vi.mock("../services/index.js", () => ({
  approvalService: () => mockApprovalService,
  heartbeatService: () => mockHeartbeatService,
  issueApprovalService: () => mockIssueApprovalService,
  logActivity: mockLogActivity,
  secretService: () => mockSecretService,
}));

vi.mock("../services/durable-engine.js", () => mockDurableEngine);

function createApp() {
  const app = express();
  app.use(express.json());
  app.use((req, _res, next) => {
    (req as any).actor = {
      type: "board",
      userId: "user-1",
      companyIds: ["company-1"],
      source: "session",
      isInstanceAdmin: false,
    };
    next();
  });
  app.use("/api", approvalRoutes({} as any));
  app.use(errorHandler);
  return app;
}

describe("approval routes durable pilot integration", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockIssueApprovalService.listIssuesForApproval.mockResolvedValue([{ id: "issue-1" }]);
    mockLogActivity.mockResolvedValue(undefined);
  });

  it("emits approval resolved events instead of waking the requester when the pilot owns resume", async () => {
    mockApprovalService.approve.mockResolvedValue({
      approval: {
        id: "approval-1",
        companyId: "company-1",
        type: "hire_agent",
        status: "approved",
        payload: { __paperclipWorkflow: { runId: "run-1" } },
        decisionNote: "ship it",
        decidedAt: new Date("2026-03-21T12:00:00.000Z"),
        decidedByUserId: "user-1",
        requestedByAgentId: "agent-1",
      },
      applied: true,
    });
    mockDurableEngine.publishApprovalResolvedEvent.mockResolvedValue("evt-1");

    const res = await request(createApp())
      .post("/api/approvals/approval-1/approve")
      .send({});

    expect(res.status).toBe(200);
    expect(mockDurableEngine.publishApprovalResolvedEvent).toHaveBeenCalledTimes(1);
    expect(mockHeartbeatService.wakeup).not.toHaveBeenCalled();
  });

  it("falls back to the legacy wakeup path if durable event emission fails", async () => {
    mockApprovalService.approve.mockResolvedValue({
      approval: {
        id: "approval-1",
        companyId: "company-1",
        type: "hire_agent",
        status: "approved",
        payload: { __paperclipWorkflow: { runId: "run-1" } },
        decisionNote: null,
        decidedAt: new Date("2026-03-21T12:00:00.000Z"),
        decidedByUserId: "user-1",
        requestedByAgentId: "agent-1",
      },
      applied: true,
    });
    mockDurableEngine.publishApprovalResolvedEvent.mockRejectedValue(new Error("network"));
    mockHeartbeatService.wakeup.mockResolvedValue({ id: "wake-1" });

    const res = await request(createApp())
      .post("/api/approvals/approval-1/approve")
      .send({});

    expect(res.status).toBe(200);
    expect(mockDurableEngine.logDurableEngineFallback).toHaveBeenCalledTimes(1);
    expect(mockHeartbeatService.wakeup).toHaveBeenCalledTimes(1);
  });
});
