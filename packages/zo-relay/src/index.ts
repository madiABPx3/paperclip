import express from "express";
import { PaperclipClient } from "./paperclip-client.js";
import { executeRelayRequest } from "./service.js";
import { PostgresContinuityStore } from "./store.js";
import type { PaperclipWakePayload } from "./types.js";

function requireEnv(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`Missing required env var ${name}`);
  return value;
}

function resolveZoToken() {
  return requireEnv("ZO_EXECUTION_TOKEN");
}

function resolveAgentKeys() {
  const raw = requireEnv("PAPERCLIP_AGENT_KEYS_JSON");
  return JSON.parse(raw) as Record<string, string>;
}

function createPersonaResolver(token: string) {
  let cache: Record<string, string> | null = null;

  return async (payload: PaperclipWakePayload): Promise<string | null> => {
    if (payload.relay.zoPersonaId) return payload.relay.zoPersonaId;
    const personaName = payload.relay.zoPersonaName?.trim();
    if (!personaName) return null;
    if (!cache) {
      const response = await fetch("https://api.zo.computer/personas/available", {
        headers: {
          authorization: token,
          accept: "application/json",
        },
      });
      if (!response.ok) {
        throw new Error(`Failed to load Zo personas: ${response.status}`);
      }
      const json = await response.json() as { personas?: Array<{ id?: string; name?: string }> };
      cache = Object.fromEntries(
        (json.personas ?? [])
          .filter((persona) => typeof persona.id === "string" && typeof persona.name === "string")
          .map((persona) => [persona.name!, persona.id!]),
      );
    }
    return cache[personaName] ?? null;
  };
}

async function main() {
  const databaseUrl = process.env.RELAY_DATABASE_URL?.trim() || requireEnv("DATABASE_URL");
  const relaySecret = process.env.PAPERCLIP_RELAY_SECRET?.trim() || "";
  const agentKeys = resolveAgentKeys();
  const zoToken = resolveZoToken();
  const personaResolver = createPersonaResolver(zoToken);
  const store = new PostgresContinuityStore(databaseUrl);
  await store.ensureSchema();

  const app = express();
  app.use(express.json());

  app.get("/health", (_req, res) => {
    res.json({ ok: true });
  });

  app.post("/execute", async (req, res) => {
    if (relaySecret) {
      const provided = req.header("x-paperclip-relay-secret")?.trim();
      if (!provided || provided !== relaySecret) {
        res.status(401).json({ error: "Unauthorized" });
        return;
      }
    }

    const result = await executeRelayRequest(req.body, {
      store,
      resolveZoToken: () => zoToken,
      resolvePersonaId: personaResolver,
      createPaperclipClient: (payload) => {
        const keyRef = payload.relay.paperclipAgentKeyRef;
        const agentKey = agentKeys[keyRef] || agentKeys[payload.agentId];
        if (!agentKey) {
          throw new Error(`No Paperclip agent key configured for ${keyRef}`);
        }
        return new PaperclipClient(payload.relay.paperclipBaseUrl, agentKey, payload.runId);
      },
      now: () => new Date(),
      env: process.env,
      log: (entry) => console.log(JSON.stringify(entry)),
    });
    res.status(result.httpStatus).json(result.body);
  });

  const port = Number(process.env.PORT || "3200");
  const host = process.env.HOST || "0.0.0.0";
  const server = app.listen(port, host, () => {
    console.log(JSON.stringify({ event: "relay.started", host, port }));
  });

  const close = async () => {
    await store.close();
    server.close();
  };
  process.on("SIGINT", () => void close());
  process.on("SIGTERM", () => void close());
}

void main();

