import { zoStructuredOutputSchema, type ZoStructuredOutput } from "./types.js";

export type ZoAskResponse = {
  output: ZoStructuredOutput;
  conversationId: string | null;
};

export class ZoHttpError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

function normalizeRelayAction(raw: unknown): Record<string, unknown> {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    return {
      type: "no_op",
      issue_id: "",
      body_markdown: "",
      next_status: "",
    };
  }
  const record = raw as Record<string, unknown>;
  const type =
    typeof record.type === "string"
      ? record.type
      : typeof record.action === "string"
        ? record.action
        : "no_op";
  return {
    type,
    issue_id: typeof record.issue_id === "string" ? record.issue_id : "",
    body_markdown: typeof record.body_markdown === "string" ? record.body_markdown : "",
    next_status: typeof record.next_status === "string" ? record.next_status : "",
  };
}

function normalizeZoOutput(raw: unknown): unknown {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return raw;
  const record = raw as Record<string, unknown>;
  const rawOutcome = typeof record.outcome === "string" ? record.outcome : "";
  const outcome =
    rawOutcome === "success"
      ? "completed"
      : rawOutcome;
  const continuityRecord =
    record.continuity && typeof record.continuity === "object" && !Array.isArray(record.continuity)
      ? (record.continuity as Record<string, unknown>)
      : null;

  return {
    outcome,
    summary_markdown: typeof record.summary_markdown === "string" ? record.summary_markdown : "",
    paperclip_actions: Array.isArray(record.paperclip_actions)
      ? record.paperclip_actions.map(normalizeRelayAction)
      : [],
    continuity: {
      should_continue:
        continuityRecord && typeof continuityRecord.should_continue === "boolean"
          ? continuityRecord.should_continue
          : false,
      continuation_hint:
        continuityRecord && typeof continuityRecord.continuation_hint === "string"
          ? continuityRecord.continuation_hint
          : typeof record.continuation_hint === "string"
            ? record.continuation_hint
            : "",
    },
  };
}

export async function callZoAsk(input: {
  apiBaseUrl: string;
  token: string;
  prompt: string;
  outputFormat: object;
  timeoutMs: number;
  modelName: string;
  personaId?: string | null;
  conversationId?: string | null;
}): Promise<ZoAskResponse> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), input.timeoutMs);

  try {
    const response = await fetch(new URL("/zo/ask", input.apiBaseUrl), {
      method: "POST",
      signal: controller.signal,
      headers: {
        authorization: input.token,
        "content-type": "application/json",
        accept: "application/json",
      },
      body: JSON.stringify({
        input: input.prompt,
        model_name: input.modelName,
        output_format: input.outputFormat,
        ...(input.personaId ? { persona_id: input.personaId } : {}),
        ...(input.conversationId ? { conversation_id: input.conversationId } : {}),
      }),
    });

    const raw = await response.text();
    if (!response.ok) {
      throw new ZoHttpError(`Zo /zo/ask failed with ${response.status}: ${raw}`, response.status);
    }

    const parsed = raw ? JSON.parse(raw) as { output?: unknown; conversation_id?: unknown } : {};
    const output = zoStructuredOutputSchema.parse(normalizeZoOutput(parsed.output));
    const conversationId =
      typeof parsed.conversation_id === "string" && parsed.conversation_id.trim().length > 0
        ? parsed.conversation_id
        : null;

    return {
      output,
      conversationId,
    };
  } finally {
    clearTimeout(timeout);
  }
}
