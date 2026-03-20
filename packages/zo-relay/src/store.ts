import postgres, { type Sql } from "postgres";
import type { ContinuityRecord } from "./types.js";

export class PostgresContinuityStore {
  private readonly sql: Sql;

  constructor(databaseUrl: string) {
    this.sql = postgres(databaseUrl, { prepare: false, max: 1 });
  }

  async ensureSchema() {
    await this.sql`
      create table if not exists zo_relay_continuity (
        continuity_key text primary key,
        agent_id uuid not null,
        issue_id uuid null,
        task_key text null,
        latest_run_id uuid not null,
        zo_conversation_id text not null,
        last_zo_outcome text not null,
        last_summary_sha256 text not null,
        last_touched_at timestamptz not null,
        expires_at timestamptz null
      )
    `;
  }

  async get(continuityKey: string): Promise<ContinuityRecord | null> {
    const rows = await this.sql<ContinuityRecord[]>`
      select
        continuity_key as "continuityKey",
        agent_id as "agentId",
        issue_id as "issueId",
        task_key as "taskKey",
        latest_run_id as "latestRunId",
        zo_conversation_id as "zoConversationId",
        last_zo_outcome as "lastZoOutcome",
        last_summary_sha256 as "lastSummarySha256",
        to_char(last_touched_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') as "lastTouchedAt",
        case
          when expires_at is null then null
          else to_char(expires_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"')
        end as "expiresAt"
      from zo_relay_continuity
      where continuity_key = ${continuityKey}
    `;
    const row = rows[0] ?? null;
    if (!row) return null;
    if (row.expiresAt && new Date(row.expiresAt).getTime() <= Date.now()) {
      await this.delete(continuityKey);
      return null;
    }
    return row;
  }

  async upsert(record: ContinuityRecord) {
    await this.sql`
      insert into zo_relay_continuity (
        continuity_key,
        agent_id,
        issue_id,
        task_key,
        latest_run_id,
        zo_conversation_id,
        last_zo_outcome,
        last_summary_sha256,
        last_touched_at,
        expires_at
      )
      values (
        ${record.continuityKey},
        ${record.agentId},
        ${record.issueId},
        ${record.taskKey},
        ${record.latestRunId},
        ${record.zoConversationId},
        ${record.lastZoOutcome},
        ${record.lastSummarySha256},
        ${record.lastTouchedAt},
        ${record.expiresAt}
      )
      on conflict (continuity_key) do update set
        agent_id = excluded.agent_id,
        issue_id = excluded.issue_id,
        task_key = excluded.task_key,
        latest_run_id = excluded.latest_run_id,
        zo_conversation_id = excluded.zo_conversation_id,
        last_zo_outcome = excluded.last_zo_outcome,
        last_summary_sha256 = excluded.last_summary_sha256,
        last_touched_at = excluded.last_touched_at,
        expires_at = excluded.expires_at
    `;
  }

  async delete(continuityKey: string) {
    await this.sql`delete from zo_relay_continuity where continuity_key = ${continuityKey}`;
  }

  async close() {
    await this.sql.end({ timeout: 5 });
  }
}

