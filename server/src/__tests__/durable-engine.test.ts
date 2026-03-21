import { describe, expect, it } from "vitest";
import {
  APPROVAL_WORKFLOW_METADATA_KEY,
  readApprovalWorkflowMetadata,
  withApprovalWorkflowMetadata,
} from "../services/durable-engine.js";
import {
  buildApprovalResolvedEventId,
  buildApprovalResumeKey,
  buildHeartbeatRequestedEventId,
} from "@paperclipai/shared";

describe("durable engine helpers", () => {
  it("attaches and reads approval workflow metadata without disturbing the payload", () => {
    const payload = withApprovalWorkflowMetadata(
      { type: "hire_agent", nested: { ok: true } },
      { runId: "run-123" },
    );

    expect(payload).toMatchObject({
      type: "hire_agent",
      nested: { ok: true },
      [APPROVAL_WORKFLOW_METADATA_KEY]: { runId: "run-123" },
    });
    expect(readApprovalWorkflowMetadata(payload)).toEqual({ runId: "run-123" });
  });

  it("builds deterministic event and resume identifiers", () => {
    expect(buildHeartbeatRequestedEventId("run-123")).toBe("heartbeat-requested:run-123");
    expect(buildApprovalResolvedEventId("approval-1", "2026-03-21T12:00:00.000Z")).toBe(
      "approval-resolved:approval-1:2026-03-21T12:00:00.000Z",
    );
    expect(
      buildApprovalResumeKey({
        companyId: "company-1",
        runId: "run-123",
        approvalId: "approval-1",
      }),
    ).toBe("company-1:run-123:approval-1");
  });
});
