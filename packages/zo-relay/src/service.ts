import type { PaperclipAgentRecord, IssueHeartbeatContext } from "./paperclip-client.js";
import { callEvalService, EvalHttpError, type RelayEvalResult } from "./eval-client.js";
import { buildHeartbeatPrompt } from "./prompt.js";
import { getScenarioModelConfig } from "./model-registry.js";
import {
  paperclipWakePayloadSchema,
  relayResultSchema,
  sha256,
  type ContinuityRecord,
  type PaperclipWakePayload,
  type RelayAction,
  type RelayResult,
} from "./types.js";
import { zoAskOutputFormat, type ZoStructuredOutput } from "./types.js";
import { callZoAsk, ZoHttpError } from "./zo-client.js";

type Store = {
  get(key: string): Promise<ContinuityRecord | null>;
  upsert(record: ContinuityRecord): Promise<void>;
};

type PaperclipApi = {
  getAgent(agentId: string): Promise<PaperclipAgentRecord>;
  getIssueHeartbeatContext(issueId: string): Promise<IssueHeartbeatContext>;
  postIssueComment(issueId: string, body: string): Promise<unknown>;
  updateIssueStatus(issueId: string, status: RelayAction["next_status"], comment?: string | null): Promise<unknown>;
};

type ServiceDeps = {
  store: Store;
  createPaperclipClient(payload: PaperclipWakePayload): PaperclipApi;
  resolvePersonaId(payload: PaperclipWakePayload): Promise<string | null>;
  resolveZoToken(): string;
  now(): Date;
  env: NodeJS.ProcessEnv;
  log(entry: Record<string, unknown>): void;
};

function shouldRunEval(env: NodeJS.ProcessEnv): boolean {
  const raw = env.RELAY_EVAL_ENABLED?.trim().toLowerCase();
  return raw === "1" || raw === "true" || raw === "yes" || raw === "on";
}

function getEvalServiceUrl(env: NodeJS.ProcessEnv): string {
  const raw = env.EVAL_SERVICE_URL?.trim();
  if (!raw) {
    throw new Error("RELAY_EVAL_ENABLED is true but EVAL_SERVICE_URL is missing");
  }
  return raw;
}

function normalizeOptionalString(value: string): string | null {
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
}

export function deriveContinuityKey(payload: PaperclipWakePayload): string {
  const context = payload.context;
  const preference = payload.relay.taskIdentityPreference;

  for (const key of preference) {
    const raw = context[key];
    if (typeof raw === "string" && raw.trim().length > 0) {
      return `${payload.agentId}:${raw.trim()}`;
    }
  }

  return `${payload.agentId}:${payload.runId}`;
}

function relayResult(input: RelayResult): RelayResult {
  return relayResultSchema.parse(input);
}

function isRetryableZoFailure(error: unknown): boolean {
  if (error instanceof ZoHttpError) {
    return error.status >= 500;
  }
  if (error instanceof EvalHttpError) {
    return error.status >= 500;
  }
  if (error instanceof Error) {
    return error.name === "AbortError" || /fetch failed/i.test(error.message);
  }
  return false;
}

function formatEvalOutput(result: ZoStructuredOutput): string {
  return JSON.stringify(
    {
      outcome: result.outcome,
      summary_markdown: result.summary_markdown,
      paperclip_actions: result.paperclip_actions,
      continuity: result.continuity,
    },
    null,
    2,
  );
}

function summarizeEvalFailure(result: RelayEvalResult): string {
  const failedMetrics = result.results
    .filter((metric) => !metric.passed)
    .map((metric) => `${metric.metric_name} (${metric.score.toFixed(2)} < ${metric.threshold.toFixed(2)})`);

  if (failedMetrics.length > 0) {
    return `Eval gate failed: ${failedMetrics.join(", ")}`;
  }

  return result.error?.trim() || "Eval gate failed";
}

async function applyPaperclipActions(input: {
  actions: RelayAction[];
  payload: PaperclipWakePayload;
  issueContext: IssueHeartbeatContext | null;
  paperclip: PaperclipApi;
}) {
  const defaultIssueId =
    typeof input.payload.context.issueId === "string" && input.payload.context.issueId.trim().length > 0
      ? input.payload.context.issueId.trim()
      : input.issueContext?.issue.id ?? null;

  for (const action of input.actions) {
    const issueId = normalizeOptionalString(action.issue_id) ?? defaultIssueId;
    if (action.type === "no_op") continue;
    if (!issueId) {
      throw new Error(`Relay action ${action.type} required an issue id`);
    }
    if (action.type === "comment_issue") {
      const body = normalizeOptionalString(action.body_markdown);
      if (!body) {
        throw new Error("comment_issue action missing body_markdown");
      }
      await input.paperclip.postIssueComment(issueId, body);
      continue;
    }
    const nextStatus = normalizeOptionalString(action.next_status) as RelayAction["next_status"] | null;
    const body = normalizeOptionalString(action.body_markdown);
    if (!nextStatus) {
      throw new Error("update_issue_status action missing next_status");
    }
    await input.paperclip.updateIssueStatus(issueId, nextStatus, body);
  }
}

export async function executeRelayRequest(
  rawPayload: unknown,
  deps: ServiceDeps,
): Promise<{ httpStatus: number; body: RelayResult }> {
  let parsedPayload: PaperclipWakePayload;
  try {
    parsedPayload = paperclipWakePayloadSchema.parse(rawPayload);
  } catch (error) {
    return {
      httpStatus: 400,
      body: relayResult({
        status: "terminal_failure",
        runId: typeof rawPayload === "object" && rawPayload && "runId" in rawPayload ? String((rawPayload as { runId: unknown }).runId ?? "") : "00000000-0000-0000-0000-000000000000",
        agentId: typeof rawPayload === "object" && rawPayload && "agentId" in rawPayload ? String((rawPayload as { agentId: unknown }).agentId ?? "") : "00000000-0000-0000-0000-000000000000",
        continuityKey: "invalid",
        zoConversationId: null,
        zoOutcome: null,
        summaryMarkdown: "",
        paperclipActions: [],
        attemptCount: 1,
        failureCode: "invalid_payload",
        failureDetail: error instanceof Error ? error.message : "invalid payload",
      }),
    };
  }

  const continuityKey = deriveContinuityKey(parsedPayload);
  const paperclip = deps.createPaperclipClient(parsedPayload);
  const prior = await deps.store.get(continuityKey);
  const agent = await paperclip.getAgent(parsedPayload.agentId);
  const issueId =
    typeof parsedPayload.context.issueId === "string" && parsedPayload.context.issueId.trim().length > 0
      ? parsedPayload.context.issueId.trim()
      : null;
  const issueContext = issueId ? await paperclip.getIssueHeartbeatContext(issueId) : null;
  const prompt = buildHeartbeatPrompt({
    payload: parsedPayload,
    agent,
    issueContext,
  });
  const evalEnabled = shouldRunEval(deps.env);
  const evalServiceUrl = evalEnabled ? getEvalServiceUrl(deps.env) : null;
  const personaId = await deps.resolvePersonaId(parsedPayload);
  const zoToken = deps.resolveZoToken();
  const model = getScenarioModelConfig(parsedPayload.relay.zoModelScenario, deps.env);

  let lastError: unknown = null;
  let attempts = 0;

  while (attempts < parsedPayload.relay.maxAttempts) {
    attempts += 1;
    try {
      const result = await callZoAsk({
        apiBaseUrl: deps.env.ZO_API_BASE_URL || "https://api.zo.computer",
        token: zoToken,
        prompt,
        outputFormat: zoAskOutputFormat,
        timeoutMs: Math.min(parsedPayload.relay.timeoutMs, 35000),
        modelName: model.modelName,
        personaId,
        conversationId: prior?.zoConversationId ?? null,
      });

      if (!result.conversationId) {
        throw new Error("Zo did not return a conversation_id");
      }

      let evalResult: RelayEvalResult | null = null;
      if (evalEnabled && evalServiceUrl) {
        evalResult = await callEvalService({
          url: evalServiceUrl,
          prompt,
          output: formatEvalOutput(result.output),
          correlationId: parsedPayload.runId,
          project: deps.env.RELAY_EVAL_PROJECT?.trim() || "paperclip",
          timeoutMs: Math.min(parsedPayload.relay.timeoutMs, 45000),
        });

        deps.log({
          event: "relay.eval.complete",
          runId: parsedPayload.runId,
          agentId: parsedPayload.agentId,
          continuityKey,
          attempt: attempts,
          passed: evalResult.passed,
          metrics: evalResult.results.map((metric) => ({
            metric: metric.metric_name,
            score: metric.score,
            threshold: metric.threshold,
            passed: metric.passed,
          })),
        });

        if (!evalResult.passed) {
          throw new Error(summarizeEvalFailure(evalResult));
        }
      }

      await applyPaperclipActions({
        actions: result.output.paperclip_actions,
        payload: parsedPayload,
        issueContext,
        paperclip,
      });

      const nowIso = deps.now().toISOString();
      await deps.store.upsert({
        continuityKey,
        agentId: parsedPayload.agentId,
        issueId,
        taskKey: typeof parsedPayload.context.taskKey === "string" ? parsedPayload.context.taskKey : null,
        latestRunId: parsedPayload.runId,
        zoConversationId: result.conversationId,
        lastZoOutcome: result.output.outcome,
        lastSummarySha256: sha256(result.output.summary_markdown),
        lastTouchedAt: nowIso,
        expiresAt: new Date(deps.now().getTime() + 14 * 24 * 60 * 60 * 1000).toISOString(),
      });

      deps.log({
        event: "relay.execution.success",
        runId: parsedPayload.runId,
        agentId: parsedPayload.agentId,
        continuityKey,
        attempt: attempts,
        zoOutcome: result.output.outcome,
        modelName: model.modelName,
        evalPassed: evalResult?.passed ?? null,
      });

      return {
        httpStatus: 200,
        body: relayResult({
          status: "success",
          runId: parsedPayload.runId,
          agentId: parsedPayload.agentId,
          continuityKey,
          zoConversationId: result.conversationId,
          zoOutcome: result.output.outcome,
          summaryMarkdown: result.output.summary_markdown,
          paperclipActions: result.output.paperclip_actions,
          attemptCount: attempts,
          failureCode: null,
          failureDetail: null,
        }),
      };
    } catch (error) {
      lastError = error;
      deps.log({
        event: "relay.execution.error",
        runId: parsedPayload.runId,
        agentId: parsedPayload.agentId,
        continuityKey,
        attempt: attempts,
        error: error instanceof Error ? error.message : String(error),
      });
      if (!isRetryableZoFailure(error) || attempts >= parsedPayload.relay.maxAttempts) break;
      await new Promise((resolve) => setTimeout(resolve, 1500 * attempts));
    }
  }

  const retryable = isRetryableZoFailure(lastError);
  const failureDetail = lastError instanceof Error ? lastError.message : String(lastError);
  const evalFailure = !retryable && /eval gate failed/i.test(failureDetail);
  return {
    httpStatus: retryable ? 502 : 500,
    body: relayResult({
      status: retryable ? "retryable_failure" : "terminal_failure",
      runId: parsedPayload.runId,
      agentId: parsedPayload.agentId,
      continuityKey,
      zoConversationId: prior?.zoConversationId ?? null,
      zoOutcome: null,
      summaryMarkdown: "",
      paperclipActions: [],
      attemptCount: attempts,
      failureCode: retryable ? "zo_retryable_failure" : evalFailure ? "eval_gate_failed" : "relay_terminal_failure",
      failureDetail,
    }),
  };
}
