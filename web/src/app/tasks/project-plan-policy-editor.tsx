"use client";

import type { PlanDraftNode, PlanOperation, PlanPolicy } from "@/lib/project-plan-contract";
import { editOutput, policyTotals, reconcilePolicy } from "./project-plan-policy-draft";

const OPERATIONS: Array<{ id: PlanOperation; label: string }> = [
  { id: "read_selected_inputs", label: "Read selected Project inputs" },
  { id: "read_public_web", label: "Research the public web" },
  { id: "write_registered_artifacts", label: "Produce registered outputs" },
  { id: "ask_owner", label: "Ask the owner in Mentat" },
];
const TYPES = ["diagram", "document", "checklist", "research"] as const;
const FINAL_TYPES = { layout: "diagram", products: "document", steps: "checklist" } as const;

export function ProjectPlanPolicyEditor({ nodes, policy, prepared, disabled, onChange }: {
  nodes: PlanDraftNode[];
  policy: PlanPolicy;
  prepared: Record<string, { fileCount: number; hasBrief: boolean } | null>;
  disabled: boolean;
  onChange: (next: PlanPolicy) => void;
}) {
  const update = (next: PlanPolicy) => onChange(reconcilePolicy(next, nodes, nodes));
  const sums = policyTotals(nodes);
  const slotNames = new Set(policy.outputs.map((output) => output.slot));
  const producerSlots = (index: number) => policy.outputs.filter((output) => output.producer === index);
  const pairs = nodes.flatMap((consumer, consumerIndex) => nodes.slice(0, consumerIndex).flatMap((producer, producerIndex) =>
    consumer.after.includes(producer.task_id) && producerSlots(producerIndex).length
      && (!policy.operations[producerIndex]?.includes("read_public_web") || producer.segment < consumer.segment)
      && policy.operations[consumerIndex]?.includes("read_selected_inputs")
      && !policy.operations[consumerIndex]?.includes("read_public_web")
      ? [{ producer: producerIndex, consumer: consumerIndex }] : []));

  function operation(index: number, id: PlanOperation, checked: boolean) {
    const current = policy.operations[index];
    let next = checked ? [...current, id] : current.filter((item) => item !== id);
    if (checked && id === "read_public_web") next = next.filter((item) => item !== "read_selected_inputs" && item !== "ask_owner");
    if (checked && id === "read_selected_inputs") next = next.filter((item) => item !== "read_public_web");
    if (checked && id === "ask_owner") next = next.filter((item) => item !== "read_public_web");
    update({ ...policy, operations: policy.operations.map((item, position) => position === index ? [...new Set(next)].sort() as PlanOperation[] : item) });
  }
  function addOutput() {
    if (policy.outputs.length >= 11 || !nodes.length) return;
    const final = (Object.keys(FINAL_TYPES) as Array<keyof typeof FINAL_TYPES>).find((name) => !slotNames.has(name));
    const intermediate = Array.from({ length: 8 }, (_, index) => `research_${index + 1}`).find((name) => !slotNames.has(name));
    const slot = final ?? intermediate;
    const producer = policy.operations.findIndex((item) => item.includes("write_registered_artifacts"));
    if (!slot || producer < 0) return;
    update({ ...policy, outputs: [...policy.outputs, {
      slot, kind: final ? "final" : "intermediate", type: final ? FINAL_TYPES[final] : "research",
      producer, max_bytes: 100_000, owner_review: true,
    }] });
  }
  function addTransfer() {
    if (policy.transfers.length >= 64 || !pairs.length) return;
    const pair = pairs[0], output = producerSlots(pair.producer)[0];
    update({ ...policy, transfers: [...policy.transfers, {
      ...pair, slots: [output.slot], use: "read_registered_input", max_files: 1,
      max_bytes: output.max_bytes, segment: nodes[pair.consumer].segment,
    }] });
  }

  return <section aria-label="Plan policy" className="project-context-panel project-plan-policy">
    <h4>Requested Agent access and handoffs</h4>
    <p>These choices are saved with the plan for owner review. They do not approve work or make a runtime capable of carrying it out.</p>
    <ol>{nodes.map((node, index) => {
      const ready = prepared[node.task_id];
      const web = policy.operations[index]?.includes("read_public_web");
      const handoffProtected = policy.transfers.some((transfer) => transfer.producer === index || transfer.consumer === index);
      return <li key={node.task_id}><strong>{node.task_id}</strong><fieldset><legend>Requested operations</legend>
        {OPERATIONS.map((option) => <label key={option.id}><input checked={policy.operations[index]?.includes(option.id) ?? false} disabled={disabled || option.id === "write_registered_artifacts" && producerSlots(index).length > 0 || handoffProtected && (option.id === "read_public_web" || option.id === "read_selected_inputs" || option.id === "ask_owner" && web) || (option.id === "read_public_web" && ready !== undefined && (!!ready && (ready.fileCount !== 0 || !ready.hasBrief)))} onChange={(event) => operation(index, option.id, event.target.checked)} type="checkbox" />{option.label}</label>)}
      </fieldset>{handoffProtected ? <p>Remove this Task’s planned handoffs before changing its web or selected-input access.</p> : null}{web ? <p>{ready?.fileCount === 0 && ready.hasBrief ? "The saved Task input has a fileless public brief." : "Prepare a fileless Task input whose instructions are the public brief, then recheck it before saving."} This policy keeps private Project files and context out of the web Task.</p> : null}</li>;
    })}</ol>

    <div className="project-context-actions"><button disabled={disabled || policy.outputs.length >= 11 || !policy.operations.some((item) => item.includes("write_registered_artifacts"))} onClick={addOutput} type="button">Add output slot</button></div>
    {policy.outputs.length ? <ul>{policy.outputs.map((output, index) => <li key={index}>
      <label>Output kind<select disabled={disabled} onChange={(event) => {
        const kind = event.target.value as PlanPolicy["outputs"][number]["kind"];
        const slot = kind === "final" ? (Object.keys(FINAL_TYPES) as Array<keyof typeof FINAL_TYPES>).find((name) => name === output.slot || !slotNames.has(name)) : output.kind === "intermediate" ? output.slot : `research_${index + 1}`;
        if (!slot) return;
        update(editOutput(policy, index, {
          kind, slot, type: kind === "final" ? FINAL_TYPES[slot as keyof typeof FINAL_TYPES] : "research",
        }));
      }} value={output.kind}><option value="final">Final deliverable</option><option value="intermediate">Intermediate handoff</option></select></label>
      {output.kind === "final" ? <label>Final result<select disabled={disabled} onChange={(event) => {
        const slot = event.target.value as keyof typeof FINAL_TYPES;
        update(editOutput(policy, index, { slot, type: FINAL_TYPES[slot] }));
      }} value={output.slot}>{(Object.keys(FINAL_TYPES) as Array<keyof typeof FINAL_TYPES>).map((name) => <option disabled={name !== output.slot && slotNames.has(name)} key={name} value={name}>{name}</option>)}</select></label>
        : <><label>Handoff name<input disabled={disabled} maxLength={48} onChange={(event) => update(editOutput(policy, index, { slot: event.target.value }))} value={output.slot} /></label><label>Type<select disabled={disabled} onChange={(event) => update({ ...policy, outputs: policy.outputs.map((item, position) => position === index ? { ...item, type: event.target.value as typeof TYPES[number] } : item) })} value={output.type}>{TYPES.map((type) => <option key={type} value={type}>{type}</option>)}</select></label></>}
      <label>Producing Task<select disabled={disabled || policy.transfers.some((transfer) => transfer.slots.includes(output.slot))} onChange={(event) => update({ ...policy, outputs: policy.outputs.map((item, position) => position === index ? { ...item, producer: Number(event.target.value) } : item) })} value={output.producer}>{nodes.map((node, position) => <option disabled={!policy.operations[position]?.includes("write_registered_artifacts")} key={node.task_id} value={position}>{node.task_id}</option>)}</select></label>
      <label>Maximum bytes<input disabled={disabled} min={1} max={2 * 1024 * 1024} onChange={(event) => update({ ...policy, outputs: policy.outputs.map((item, position) => position === index ? { ...item, max_bytes: Number(event.target.value) } : item) })} type="number" value={output.max_bytes} /></label>
      <label><input checked={output.owner_review} disabled={disabled || policy.operations[output.producer]?.includes("read_public_web")} onChange={(event) => update({ ...policy, outputs: policy.outputs.map((item, position) => position === index ? { ...item, owner_review: event.target.checked } : item) })} type="checkbox" />Owner review before handoff</label>
      <button disabled={disabled} onClick={() => update({ ...policy, outputs: policy.outputs.filter((_, position) => position !== index), transfers: policy.transfers.filter((transfer) => !transfer.slots.includes(output.slot)) })} type="button">Remove output{policy.transfers.some((transfer) => transfer.slots.includes(output.slot)) ? " and its handoffs" : ""}</button>
    </li>)}</ul> : <p>No outputs selected yet.</p>}

    <div className="project-context-actions"><button disabled={disabled || !pairs.length || policy.transfers.length >= 64} onClick={addTransfer} type="button">Add planned handoff</button></div>
    {policy.transfers.length ? <ul className="project-plan-transfers">{policy.transfers.map((transfer, index) => <li key={index}>
      <label>Producer and consumer<select disabled={disabled} onChange={(event) => {
        const pair = pairs[Number(event.target.value)], output = producerSlots(pair.producer)[0];
        update({ ...policy, transfers: policy.transfers.map((item, position) => position === index ? {
          ...item, ...pair, slots: [output.slot], max_files: 1, max_bytes: output.max_bytes,
          segment: nodes[pair.consumer].segment,
        } : item) });
      }} value={Math.max(0, pairs.findIndex((pair) => pair.producer === transfer.producer && pair.consumer === transfer.consumer))}>{pairs.map((pair, pairIndex) => <option key={`${pair.producer}:${pair.consumer}`} value={pairIndex}>{nodes[pair.producer].task_id} → {nodes[pair.consumer].task_id}</option>)}</select></label>
      <p>{nodes[transfer.producer]?.task_id} → {nodes[transfer.consumer]?.task_id}</p>
      <fieldset><legend>Registered output versions to hand off</legend>{producerSlots(transfer.producer).map((output) => <label key={output.slot}><input checked={transfer.slots.includes(output.slot)} disabled={disabled} onChange={(event) => update({ ...policy, transfers: policy.transfers.map((item, position) => position === index ? { ...item, slots: event.target.checked ? [...item.slots, output.slot].sort() : item.slots.filter((slot) => slot !== output.slot) } : item) })} type="checkbox" />{output.slot}</label>)}</fieldset>
      <label>Allowed use<select disabled={disabled} onChange={(event) => update({ ...policy, transfers: policy.transfers.map((item, position) => position === index ? { ...item, use: event.target.value as PlanPolicy["transfers"][number]["use"] } : item) })} value={transfer.use}><option value="read_registered_input">Read as selected input</option><option value="cite_public_source">Carry public citation</option></select></label>
      <label>Maximum files<input disabled={disabled} min={1} max={8} onChange={(event) => update({ ...policy, transfers: policy.transfers.map((item, position) => position === index ? { ...item, max_files: Number(event.target.value) } : item) })} type="number" value={transfer.max_files} /></label>
      <label>Maximum bytes<input disabled={disabled} min={1} max={8 * 1024 * 1024} onChange={(event) => update({ ...policy, transfers: policy.transfers.map((item, position) => position === index ? { ...item, max_bytes: Number(event.target.value) } : item) })} type="number" value={transfer.max_bytes} /></label>
      <p>Requires exact finished producer output and checkpoint {transfer.segment} approval. No latest-result substitution.</p>
      <button disabled={disabled} onClick={() => update({ ...policy, transfers: policy.transfers.filter((_, position) => position !== index) })} type="button">Remove handoff</button>
    </li>)}</ul> : <p>No handoffs selected.</p>}

    <fieldset><legend>Whole-plan requested limits, including retries</legend>
      {(["max_attempts", "max_wall_seconds", "max_work_units"] as const).map((field) => <label key={field}>{field.replaceAll("_", " ")} (minimum {sums[field]})<input disabled={disabled} min={field === "max_wall_seconds" ? 60 : 1} max={field === "max_attempts" ? 96 : field === "max_wall_seconds" ? 604800 : 32000} onChange={(event) => update({ ...policy, ceilings: { ...policy.ceilings, [field]: Number(event.target.value) } })} type="number" value={policy.ceilings[field]} /></label>)}
    </fieldset>
  </section>;
}
