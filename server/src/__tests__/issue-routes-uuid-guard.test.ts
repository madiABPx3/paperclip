import express from "express";
import request from "supertest";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { errorHandler } from "../middleware/index.js";
import { issueRoutes } from "../routes/issues.js";

const mockIssueService = vi.hoisted(() => ({
  getById: vi.fn(),
  getByIdentifier: vi.fn(),
  list: vi.fn(),
  create: vi.fn(),
  update: vi.fn(),
  addComment: vi.fn(),
  listComments: vi.fn(),
}));

vi.mock("../services/index.js", () => ({
  issueService: () => mockIssueService,
  accessService: () => ({ hasPermission: vi.fn().mockResolvedValue(true) }),
  agentService: () => ({ getById: vi.fn() }),
  heartbeatService: () => ({ wakeup: vi.fn(), getRun: vi.fn(), getActiveRunForAgent: vi.fn(), cancelRun: vi.fn() }),
  goalService: () => ({ getById: vi.fn() }),
  projectService: () => ({ getById: vi.fn() }),
  issueApprovalService: () => ({ getById: vi.fn() }),
  documentService: () => ({ getIssueDocumentByKey: vi.fn(), upsertIssueDocument: vi.fn() }),
  logActivity: vi.fn(),
}));

function createApp() {
  const app = express();
  app.use(express.json());
  app.use((req, _res, next) => {
    (req as any).actor = {
      type: "board",
      userId: "user-1",
      companyIds: ["company-1"],
      source: "session",
      isInstanceAdmin: false,
    };
    next();
  });
  app.use("/api", issueRoutes({} as any, {} as any));
  app.use(errorHandler);
  return app;
}

describe("issue routes — UUID guard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("returns 404 (not 500) when issue id is not a UUID or identifier format", async () => {
    const res = await request(createApp()).get("/api/issues/not-a-uuid");
    expect(res.status).toBe(404);
    expect(res.body).toEqual({ error: "Issue not found" });
    expect(mockIssueService.getById).not.toHaveBeenCalled();
  });

  it("returns 404 when identifier format ZOA-99 is not found in DB", async () => {
    mockIssueService.getByIdentifier.mockResolvedValue(null);
    const res = await request(createApp()).get("/api/issues/ZOA-99");
    expect(res.status).toBe(404);
    expect(res.body).toEqual({ error: "Issue not found" });
    expect(mockIssueService.getById).not.toHaveBeenCalled();
  });

  it("passes through a valid UUID without calling getByIdentifier", async () => {
    const validUuid = "550e8400-e29b-41d4-a716-446655440000";
    mockIssueService.getById.mockResolvedValue({
      id: validUuid,
      companyId: "company-1",
      labels: [],
    });
    const res = await request(createApp()).get(`/api/issues/${validUuid}`);
    expect(mockIssueService.getByIdentifier).not.toHaveBeenCalled();
    expect(mockIssueService.getById).toHaveBeenCalledWith(validUuid);
  });

  it("resolves a valid identifier ZOA-13 to UUID before calling getById", async () => {
    const resolvedUuid = "9f91bd4a-5cb4-45cc-9bdd-231211d9f307";
    mockIssueService.getByIdentifier.mockResolvedValue({
      id: resolvedUuid,
      companyId: "company-1",
      labels: [],
    });
    mockIssueService.getById.mockResolvedValue({
      id: resolvedUuid,
      companyId: "company-1",
      labels: [],
    });
    const res = await request(createApp()).get("/api/issues/ZOA-13");
    expect(mockIssueService.getByIdentifier).toHaveBeenCalledWith("ZOA-13");
    expect(mockIssueService.getById).toHaveBeenCalledWith(resolvedUuid);
  });
});
