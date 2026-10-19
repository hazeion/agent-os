import assert from "node:assert/strict";
import test from "node:test";
import { ProjectPlanBridgeError, projectPlanCapability } from "../src/lib/bridge-project-plans.ts";

const environment = { MENTAT_BRIDGE_ORIGIN: "http://127.0.0.1:43210", MENTAT_BRIDGE_TOKEN: "a".repeat(43) };
const envelope = { schema_version: 1, service: "mentat-local-bridge", runtime: "python", status: "ready" };
const inputId = `task_input_${"b".repeat(32)}`, versionId = `plan_version_${"c".repeat(32)}`;
const body = { project_id: "project_garage", expected_project_revision: 1, expected_plan_revision: 0,
  title: "Garage organization", nodes: [{ task_id: "task_research", expected_task_revision: 1, agent_id: "agent_research", input_version_id: inputId,
    after: [], segment: 0, max_attempts: 1, max_wall_seconds: 900, max_work_units: 100 }] };

test("plan bridge uses one fixed private mutation and exact safe response", async () => {
  let calls = 0;
  const fetcher = async (input: string | URL | Request, init?: RequestInit) => {
    calls++;
    assert.equal(String(input), "http://127.0.0.1:43210/bridge/v1/project-plans/publish");
    assert.equal(init?.method, "POST");
    assert.deepEqual(JSON.parse(String(init?.body)), body);
    return Response.json({ ...envelope, data: { id: versionId, revision: 1, project_id: body.project_id, status: "unapproved" } });
  };
  assert.equal((await projectPlanCapability("publish", body, fetcher, environment)).id, versionId);
  assert.equal(calls, 1);
  await assert.rejects(() => projectPlanCapability("publish", { ...body, runtime_method: "exec" }, fetcher, environment),
    (error: unknown) => error instanceof ProjectPlanBridgeError && error.status === 400);
  assert.equal(calls, 1);
  await assert.rejects(() => projectPlanCapability("publish", body, async () => Response.json({ ...envelope, data: { id: versionId, revision: 1, project_id: body.project_id, status: "unapproved", binding: "private" } }), environment),
    (error: unknown) => error instanceof ProjectPlanBridgeError && error.status === 502);
});
