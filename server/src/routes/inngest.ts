import { Router } from "express";
import type { Db } from "@paperclipai/db";
import { serve } from "inngest/express";
import {
  paperclipApprovalResolvedEventName,
  paperclipHeartbeatRequestedEventName,
} from "@paperclipai/shared";
import { logger } from "../middleware/logger.js";
import { heartbeatService, issueApprovalService } from "../services/index.js";
import {
  attachHeartbeatDispatchMarker,
  findPendingApprovalForRun,
  inngest,
} from "../services/durable-engine.js";

export function inngestRoutes(db: Db) {
  const router = Router();
  const heartbeat = heartbeatService(db);
  const issueApprovals = issueApprovalService(db);

  const functions = [
    inngest.createFunction(
      {
        id: "paperclip-heartbeat-durable-pilot",
        triggers: [{ event: paperclipHeartbeatRequestedEventName }],
      },
      async ({ event, step }) => {
        await step.run("load-paperclip-context", async () => {
          await attachHeartbeatDispatchMarker(db, event.data.runId, event.id);
          return { runId: event.data.runId };
        });

        const initialRun = await step.run("invoke-zo-heartbeat", async () => {
          const run = await heartbeat.executeDurableRun(event.data.runId);
          return run
            ? {
                id: run.id,
                agentId: run.agentId,
                status: run.status,
              }
            : null;
        });

        if (!initialRun) {
          return { status: "run_missing", runId: event.data.runId };
        }

        const approval = await step.run("create-approval-if-needed", async () => {
          const pending = await findPendingApprovalForRun(db, event.data.runId);
          if (!pending) return null;
          const linkedIssues = await issueApprovals.listIssuesForApproval(pending.id);
          return {
            id: pending.id,
            status: pending.status,
            issueIds: linkedIssues.map((issue) => issue.id),
          };
        });

        if (!approval) {
          return {
            status: initialRun.status,
            initialRunId: initialRun.id,
          };
        }

        const resolved = await step.waitForEvent("wait-for-approval-resolution", {
          event: paperclipApprovalResolvedEventName,
          timeout: "7d",
          if: "async.data.runId == event.data.runId",
        });

        if (!resolved) {
          logger.warn({ runId: event.data.runId, approvalId: approval.id }, "durable approval wait timed out");
          return {
            status: "approval_timeout",
            initialRunId: initialRun.id,
            approvalId: approval.id,
          };
        }

        const resumedRun = await step.run("apply-approval-outcome", async () => {
          const run = await heartbeat.continueAfterApproval({
            agentId: initialRun.agentId,
            sourceRunId: event.data.runId,
            approvalId: resolved.data.approvalId as string,
            approvalStatus: resolved.data.status as "approved" | "rejected" | "revision_requested",
            issueIds: Array.isArray(resolved.data.issueIds)
              ? resolved.data.issueIds.filter((value): value is string => typeof value === "string")
              : [],
            decisionNote: typeof resolved.data.decisionNote === "string" ? resolved.data.decisionNote : null,
            decidedByUserId:
              typeof resolved.data.decidedByUserId === "string" ? resolved.data.decidedByUserId : null,
          });

          if (!run) return null;

          const followUpApproval = await findPendingApprovalForRun(db, run.id);
          if (followUpApproval) {
            throw new Error(
              `Inngest pilot only supports one approval checkpoint per workflow run (runId=${run.id})`,
            );
          }

          return {
            id: run.id,
            status: run.status,
          };
        });

        return {
          status: resumedRun?.status ?? "resume_skipped",
          initialRunId: initialRun.id,
          resumedRunId: resumedRun?.id ?? null,
          approvalId: resolved.data.approvalId as string,
        };
      },
    ),
  ];

  router.use(serve({ client: inngest, functions }));
  return router;
}
