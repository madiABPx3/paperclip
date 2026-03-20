import type { IssueStatus } from "./types.js";

export type PaperclipAgentRecord = {
  id: string;
  companyId: string;
  name: string;
  role: string;
  capabilities: string | null;
  metadata: Record<string, unknown> | null;
};

export type IssueHeartbeatContext = {
  issue: {
    id: string;
    identifier: string;
    title: string;
    description: string | null;
    status: string;
    priority: string;
    projectId: string | null;
    goalId: string | null;
    parentId: string | null;
    assigneeAgentId: string | null;
    assigneeUserId: string | null;
    updatedAt: string;
  };
  ancestors: Array<Record<string, unknown>>;
  project: Record<string, unknown> | null;
  goal: Record<string, unknown> | null;
  commentCursor: Record<string, unknown> | null;
  wakeComment: Record<string, unknown> | null;
};

export class PaperclipClient {
  constructor(
    private readonly baseUrl: string,
    private readonly agentKey: string,
    private readonly runId: string,
  ) {}

  private async request<T>(path: string, init?: RequestInit): Promise<T> {
    const response = await fetch(new URL(path, this.baseUrl), {
      ...init,
      headers: {
        Accept: "application/json",
        Authorization: `Bearer ${this.agentKey}`,
        "Content-Type": "application/json",
        "X-Paperclip-Run-Id": this.runId,
        ...(init?.headers ?? {}),
      },
    });
    if (!response.ok) {
      const body = await response.text();
      throw new Error(`Paperclip ${response.status} ${path}: ${body}`);
    }
    return (await response.json()) as T;
  }

  getAgent(agentId: string) {
    return this.request<PaperclipAgentRecord>(`/api/agents/${agentId}`);
  }

  getIssueHeartbeatContext(issueId: string) {
    return this.request<IssueHeartbeatContext>(`/api/issues/${issueId}/heartbeat-context`);
  }

  postIssueComment(issueId: string, body: string) {
    return this.request(`/api/issues/${issueId}/comments`, {
      method: "POST",
      body: JSON.stringify({ body }),
    });
  }

  updateIssueStatus(issueId: string, status: IssueStatus, comment?: string | null) {
    return this.request(`/api/issues/${issueId}`, {
      method: "PATCH",
      body: JSON.stringify({
        status,
        ...(comment ? { comment } : {}),
      }),
    });
  }
}

