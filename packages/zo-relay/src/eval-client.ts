import { z } from "zod";

const evalMetricSchema = z.object({
  metric_name: z.string(),
  score: z.number(),
  threshold: z.number(),
  passed: z.boolean(),
  metric_type: z.string(),
  reason: z.string().optional().default(""),
});

const evalResponseSchema = z.object({
  passed: z.boolean(),
  results: z.array(evalMetricSchema).default([]),
  correlationId: z.string().optional().default(""),
  error: z.string().optional(),
});

export type RelayEvalResult = z.infer<typeof evalResponseSchema>;

export class EvalHttpError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

export async function callEvalService(input: {
  url: string;
  prompt: string;
  output: string;
  correlationId: string;
  project?: string;
  timeoutMs: number;
}): Promise<RelayEvalResult> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), input.timeoutMs);

  try {
    const response = await fetch(input.url, {
      method: "POST",
      signal: controller.signal,
      headers: {
        "content-type": "application/json",
        accept: "application/json",
      },
      body: JSON.stringify({
        input: input.prompt,
        output: input.output,
        project: input.project ?? "paperclip",
        correlationId: input.correlationId,
      }),
    });

    const raw = await response.text();
    if (!response.ok) {
      throw new EvalHttpError(`Eval service failed with ${response.status}: ${raw}`, response.status);
    }

    const parsed = raw ? JSON.parse(raw) as unknown : {};
    return evalResponseSchema.parse(parsed);
  } finally {
    clearTimeout(timeout);
  }
}
