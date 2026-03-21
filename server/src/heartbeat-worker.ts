import { createDb, inspectMigrations, applyPendingMigrations, reconcilePendingMigrationHistory } from "@paperclipai/db";
import { loadConfig } from "./config.js";
import { logger } from "./middleware/logger.js";
import { heartbeatService } from "./services/index.js";

type MigrationSummary =
  | "already applied"
  | "applied (pending migrations)";

function formatPendingMigrationSummary(migrations: string[]): string {
  if (migrations.length === 0) return "none";
  return migrations.length > 3
    ? `${migrations.slice(0, 3).join(", ")} (+${migrations.length - 3} more)`
    : migrations.join(", ");
}

async function ensureMigrations(connectionString: string): Promise<MigrationSummary> {
  let state = await inspectMigrations(connectionString);
  if (state.status === "needsMigrations" && state.reason === "pending-migrations") {
    const repair = await reconcilePendingMigrationHistory(connectionString);
    if (repair.repairedMigrations.length > 0) {
      logger.warn(
        { repairedMigrations: repair.repairedMigrations },
        "Heartbeat worker repaired drifted migration journal entries from existing schema state",
      );
      state = await inspectMigrations(connectionString);
      if (state.status === "upToDate") return "already applied";
    }
  }

  if (state.status === "upToDate") return "already applied";

  if (process.env.PAPERCLIP_MIGRATION_AUTO_APPLY !== "true") {
    throw new Error(
      `Heartbeat worker found pending migrations (${formatPendingMigrationSummary(state.pendingMigrations)}). ` +
        "Set PAPERCLIP_MIGRATION_AUTO_APPLY=true or migrate before starting the worker.",
    );
  }

  logger.info(
    { pendingMigrations: state.pendingMigrations },
    "Heartbeat worker applying pending migrations",
  );
  await applyPendingMigrations(connectionString);
  return "applied (pending migrations)";
}

async function runHeartbeatTick(heartbeat: ReturnType<typeof heartbeatService>, reason: string) {
  const now = new Date();
  const result = await heartbeat.tickTimers(now);
  if (result.enqueued > 0 || result.skipped > 0) {
    logger.info({ reason, now: now.toISOString(), ...result }, "heartbeat worker tick completed");
  }
  await heartbeat.reapOrphanedRuns({ staleThresholdMs: 5 * 60 * 1000 });
  await heartbeat.resumeQueuedRuns();
}

async function main() {
  const config = loadConfig();
  if (!config.databaseUrl) {
    throw new Error("Heartbeat worker requires DATABASE_URL");
  }
  if (!config.heartbeatSchedulerEnabled) {
    logger.warn("Heartbeat worker exiting because HEARTBEAT_SCHEDULER_ENABLED=false");
    return;
  }

  const migrationSummary = await ensureMigrations(config.databaseUrl);
  const db = createDb(config.databaseUrl);
  const heartbeat = heartbeatService(db as any);

  logger.info(
    {
      intervalMs: config.heartbeatSchedulerIntervalMs,
      migrationSummary,
    },
    "Heartbeat worker started",
  );

  await heartbeat.reapOrphanedRuns();
  await heartbeat.resumeQueuedRuns();
  await runHeartbeatTick(heartbeat, "startup");

  const timer = setInterval(() => {
    void runHeartbeatTick(heartbeat, "interval").catch((err) => {
      logger.error({ err }, "Heartbeat worker interval failed");
    });
  }, config.heartbeatSchedulerIntervalMs);

  const shutdown = async (signal: string) => {
    clearInterval(timer);
    logger.info({ signal }, "Heartbeat worker stopping");
    process.exit(0);
  };

  process.on("SIGINT", () => {
    void shutdown("SIGINT");
  });
  process.on("SIGTERM", () => {
    void shutdown("SIGTERM");
  });
}

void main().catch((err) => {
  logger.error({ err }, "Heartbeat worker crashed");
  process.exit(1);
});
