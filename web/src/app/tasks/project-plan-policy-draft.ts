import type { PlanDraftNode, PlanPolicy } from "@/lib/project-plan-contract";

const DEFAULT_OPERATIONS: PlanPolicy["operations"][number] = ["read_selected_inputs", "write_registered_artifacts"];

function totals(nodes: PlanDraftNode[]) {
  return {
    max_attempts: nodes.reduce((sum, node) => sum + node.max_attempts, 0),
    max_wall_seconds: nodes.reduce((sum, node) => sum + node.max_attempts * node.max_wall_seconds, 0),
    max_work_units: nodes.reduce((sum, node) => sum + node.max_attempts * node.max_work_units, 0),
  };
}

export function initialPolicy(nodes: PlanDraftNode[]): PlanPolicy {
  return { operations: nodes.map(() => [...DEFAULT_OPERATIONS]), outputs: [], transfers: [], ceilings: totals(nodes) };
}

export function editOutput(policy: PlanPolicy, index: number, changes: Partial<PlanPolicy["outputs"][number]>): PlanPolicy {
  const before = policy.outputs[index];
  const after = { ...before, ...changes };
  return {
    ...policy,
    outputs: policy.outputs.map((output, position) => position === index ? after : output),
    transfers: before.slot === after.slot ? policy.transfers : policy.transfers.map((transfer) => ({
      ...transfer,
      slots: transfer.slots.map((slot) => slot === before.slot ? after.slot : slot).sort(),
    })),
  };
}

export function reconcilePolicy(policy: PlanPolicy, oldNodes: PlanDraftNode[], newNodes: PlanDraftNode[]): PlanPolicy {
  const oldIndex = new Map(oldNodes.map((node, index) => [node.task_id, index]));
  const newIndex = new Map(newNodes.map((node, index) => [node.task_id, index]));
  const operations = newNodes.map((node) => {
    const prior = oldIndex.get(node.task_id);
    return prior === undefined ? [...DEFAULT_OPERATIONS] : [...policy.operations[prior]];
  });
  const outputs = policy.outputs.flatMap((output) => {
    const task = oldNodes[output.producer]?.task_id, producer = task === undefined ? undefined : newIndex.get(task);
    return producer === undefined || !operations[producer].includes("write_registered_artifacts") ? [] : [{
      ...output, producer, owner_review: operations[producer].includes("read_public_web") ? true : output.owner_review,
    }];
  });
  const slots = new Map(outputs.map((output) => [output.slot, output.producer]));
  const transfers = policy.transfers.flatMap((transfer) => {
    const source = oldNodes[transfer.producer]?.task_id, target = oldNodes[transfer.consumer]?.task_id;
    const producer = source === undefined ? undefined : newIndex.get(source);
    const consumer = target === undefined ? undefined : newIndex.get(target);
    if (producer === undefined || consumer === undefined || producer >= consumer
      || !newNodes[consumer].after.includes(newNodes[producer].task_id)
      || operations[producer].includes("read_public_web") && newNodes[producer].segment >= newNodes[consumer].segment
      || !operations[consumer].includes("read_selected_inputs")
      || transfer.slots.some((slot) => slots.get(slot) !== producer)) return [];
    return [{ ...transfer, producer, consumer, segment: newNodes[consumer].segment }];
  });
  const required = totals(newNodes);
  return { operations, outputs, transfers, ceilings: {
    max_attempts: Math.min(96, Math.max(policy.ceilings.max_attempts, required.max_attempts)),
    max_wall_seconds: Math.min(604800, Math.max(policy.ceilings.max_wall_seconds, required.max_wall_seconds)),
    max_work_units: Math.min(32000, Math.max(policy.ceilings.max_work_units, required.max_work_units)),
  } };
}

export function policyTotals(nodes: PlanDraftNode[]) { return totals(nodes); }
