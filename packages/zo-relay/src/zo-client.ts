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
    const output = zoStructuredOutputSchema.parse(parsed.output);
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

