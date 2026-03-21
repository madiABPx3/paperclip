import { afterEach, describe, expect, it, vi } from "vitest";
import { callZoAsk } from "../zo-client.js";

describe("callZoAsk", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("normalizes near-miss structured output shapes from Zo", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(JSON.stringify({
        output: {
          outcome: "success",
          summary_markdown: "Relay path confirmed.",
          paperclip_actions: [
            {
              action: "comment_issue",
              issue_id: "22222222-2222-2222-2222-222222222222",
              body_markdown: "Validated.",
              next_status: "",
              continuation_hint: "",
            },
          ],
        },
        conversation_id: "conv_test",
      }), {
        status: 200,
        headers: { "content-type": "application/json" },
      })),
    );

    const result = await callZoAsk({
      apiBaseUrl: "https://api.zo.computer",
      token: "Bearer test",
      prompt: "test",
      outputFormat: { type: "object", properties: {}, required: [] },
      timeoutMs: 1000,
      modelName: "byok:test",
      personaId: "persona-test",
    });

    expect(result.conversationId).toBe("conv_test");
    expect(result.output).toEqual({
      outcome: "completed",
      summary_markdown: "Relay path confirmed.",
      paperclip_actions: [
        {
          type: "comment_issue",
          issue_id: "22222222-2222-2222-2222-222222222222",
          body_markdown: "Validated.",
          next_status: "",
        },
      ],
      continuity: {
        should_continue: false,
        continuation_hint: "",
      },
    });
  });
});
