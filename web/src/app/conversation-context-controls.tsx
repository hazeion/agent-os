"use client";

import { useEffect, useRef, useState } from "react";

import type { PublicConversationAgent } from "@/lib/bridge-conversations";
import { enableAgentAttachments, readAgentAttachmentsEnableStatus } from "@/lib/public-agent-attachments";
import {
  applyContextPack,
  attachWorkspaceFile,
  clearContextPack,
  listContextPacks,
  readConversationUploadReceipt,
  readStagedConversationContext,
  releaseConversationAttachment,
  searchWorkspaceFiles,
  uploadConversationAttachment,
  type ContextPackSummary,
  type StagedConversationContext,
  type WorkspaceFile,
} from "@/lib/public-conversation-media";


type Props = Readonly<{
  agent: PublicConversationAgent | null;
  conversationId: string;
  disabledReason: string | null;
  onAgentEnabled: (agent: PublicConversationAgent) => void;
  onContext: (context: StagedConversationContext) => void;
  onContextState: (state: "loading" | "ready" | "error") => void;
  onNotice: (message: string) => void;
  onRefresh: () => void;
  staged: StagedConversationContext | null;
  stagingState: "loading" | "ready" | "error";
}>;


function publicError(error: unknown): string {
  return error && typeof error === "object" && "code" in error
    ? String((error as { code: string }).code)
    : "unavailable";
}


export function ConversationContextControls({
  agent,
  conversationId,
  disabledReason,
  onAgentEnabled,
  onContext,
  onContextState,
  onNotice,
  onRefresh,
  staged,
  stagingState,
}: Props) {
  const [busy, setBusy] = useState(false);
  const [confirmEnable, setConfirmEnable] = useState(false);
  const [enableState, setEnableState] = useState<"loading" | "available" | "active_run" | "enabled" | "unsupported" | "error">("loading");
  const [uploadName, setUploadName] = useState("");
  const [uploadFailures, setUploadFailures] = useState<Array<{ key: string; name: string; state: "failed" | "not_attempted" }>>([]);
  const [workspaceQuery, setWorkspaceQuery] = useState("");
  const [workspaceFiles, setWorkspaceFiles] = useState<WorkspaceFile[]>([]);
  const [workspaceState, setWorkspaceState] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [packs, setPacks] = useState<ContextPackSummary[]>([]);
  const [packState, setPackState] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const abort = useRef<AbortController | null>(null);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; abort.current?.abort(); };
  }, []);
  const capable = agent?.capabilities.includes("run.attachments") === true;
  useEffect(() => {
    if (!agent || capable || agent.runtime_type !== "hermes") return;
    let cancelled = false;
    void Promise.resolve().then(async () => {
      setEnableState("loading");
      try {
        const state = await readAgentAttachmentsEnableStatus(agent.id);
        if (!cancelled) setEnableState(state);
      } catch {
        if (!cancelled) setEnableState("error");
      }
    });
    return () => { cancelled = true; };
  }, [agent, capable]);
  const canEnable = !capable && disabledReason === null && enableState === "available";
  const disabled = busy || disabledReason !== null || !capable || stagingState !== "ready";
  const directCount = staged?.attachments.filter((item) => item.source !== "context_pack").length ?? 0;

  async function enableFiles() {
    if (!agent || !canEnable || busy) return;
    if (!confirmEnable) { setConfirmEnable(true); return; }
    setBusy(true);
    try {
      const enabled = await enableAgentAttachments(agent.id, [...agent.capabilities].sort());
      if (!mounted.current) return;
      onAgentEnabled(enabled);
      setEnableState("enabled");
      setConfirmEnable(false);
      onNotice("Files are enabled for this local Hermes Agent.");
    } catch (error) {
      if (!mounted.current) return;
      setConfirmEnable(false);
      onNotice(publicError(error) === "conflict" ? "The Agent changed. Refresh before enabling files." : "Mentat could not enable files for this Agent.");
    } finally {
      if (mounted.current) setBusy(false);
    }
  }

  async function upload(files: FileList | null) {
    if (!files || disabled) return;
    const remaining = Math.max(
      0,
      Math.min(5 - directCount, 8 - (staged?.attachments.length ?? 0)),
    );
    const selected = Array.from(files).slice(0, remaining);
    if (!selected.length) { onNotice("This Conversation already has five direct files."); return; }
    setBusy(true);
    onContextState("loading");
    const failed: Array<{ key: string; name: string; state: "failed" | "not_attempted"; uploadId: string | null }> = [];
    let successful = 0;
    try {
      for (const [index, file] of selected.entries()) {
        const controller = new AbortController();
        const uploadId = `upload_${crypto.randomUUID().replaceAll("-", "")}`;
        abort.current = controller;
        setUploadName(file.name);
        try {
          const context = await uploadConversationAttachment(conversationId, file, uploadId, controller.signal);
          if (!mounted.current) return;
          onContext(context);
          successful += 1;
        } catch (error) {
          failed.push({ key: uploadId, name: file.name, state: "failed", uploadId });
          if (publicError(error) === "cancelled") {
            failed.push(...selected.slice(index + 1).map((remaining) => ({ key: `not_attempted_${crypto.randomUUID()}`, name: remaining.name, state: "not_attempted" as const, uploadId: null })));
            break;
          }
        }
      }
      if (!mounted.current) return;
      if (failed.length) {
        const receiptAttachments = new Map<string, string[]>();
        for (const item of failed) {
          if (!item.uploadId) continue;
          try {
            const receipt = await readConversationUploadReceipt(conversationId, item.uploadId);
            if (receipt.state === "staged") receiptAttachments.set(item.uploadId, receipt.attachmentIds);
          } catch {
            // Exact staging read below remains required; an absent receipt stays failed.
          }
        }
        const context = await readStagedConversationContext(conversationId);
        if (!mounted.current) return;
        onContext(context);
        const authoritativeIds = new Set(context.attachments.map((item) => item.id));
        const stagedUploadIds = new Set(
          [...receiptAttachments]
            .filter(([, attachmentIds]) => attachmentIds.length > 0 && attachmentIds.every((id) => authoritativeIds.has(id)))
            .map(([uploadId]) => uploadId),
        );
        const unresolved = failed.filter((item) => !item.uploadId || !stagedUploadIds.has(item.uploadId));
        setUploadFailures((current) => {
          const merged = new Map(current.map((item) => [item.key, item]));
          for (const item of unresolved) merged.set(item.key, item);
          for (const item of failed) if (item.uploadId && stagedUploadIds.has(item.uploadId)) merged.delete(item.key);
          return [...merged.values()].slice(-8);
        });
        successful += stagedUploadIds.size;
        failed.splice(0, failed.length, ...unresolved);
      }
      onContextState("ready");
      onNotice(failed.length
        ? `${successful} staged; ${failed.length} failed. Exact staged files were refreshed.`
        : `${successful} file${successful === 1 ? "" : "s"} staged for this Conversation.`);
    } catch {
      if (!mounted.current) return;
      setUploadFailures((current) => {
        const merged = new Map(current.map((item) => [item.key, item]));
        for (const item of failed) merged.set(item.key, item);
        return [...merged.values()].slice(-8);
      });
      onContextState("error");
      onNotice("Upload state could not be reconciled. Refresh files before sending.");
    } finally {
      abort.current = null;
      if (mounted.current) { setUploadName(""); setBusy(false); }
    }
  }

  async function remove(attachmentId: string) {
    if (disabled) return;
    setBusy(true);
    onContextState("loading");
    try {
      const context = await releaseConversationAttachment(conversationId, attachmentId);
      if (mounted.current) { onContext(context); onContextState("ready"); onNotice("Staged file released."); }
    } catch {
      if (mounted.current) { onContextState("error"); onNotice("Mentat could not verify that file release. Refresh files before sending."); }
    } finally { if (mounted.current) setBusy(false); }
  }

  async function searchWorkspace() {
    if (disabled || busy) return;
    setWorkspaceState("loading");
    try {
      const result = await searchWorkspaceFiles(workspaceQuery);
      if (mounted.current) { setWorkspaceFiles(result.files); setWorkspaceState("ready"); }
    } catch {
      if (mounted.current) { setWorkspaceFiles([]); setWorkspaceState("error"); }
    }
  }

  async function chooseWorkspace(file: WorkspaceFile) {
    if (disabled) return;
    setBusy(true);
    onContextState("loading");
    try {
      const context = await attachWorkspaceFile(conversationId, file.rootId, file.path);
      if (mounted.current) { onContext(context); onContextState("ready"); onNotice(`${file.name} staged from the workspace.`); }
    } catch { if (mounted.current) { onContextState("error"); onNotice("That workspace file was not verified. Refresh files before sending."); } }
    finally { if (mounted.current) setBusy(false); }
  }

  async function loadPacks() {
    if (disabled || busy || packState === "loading") return;
    setPackState("loading");
    try {
      const result = await listContextPacks();
      if (mounted.current) { setPacks(result.contextPacks); setPackState("ready"); }
    } catch { if (mounted.current) { setPacks([]); setPackState("error"); } }
  }

  async function choosePack(pack: ContextPackSummary) {
    if (disabled) return;
    setBusy(true);
    onContextState("loading");
    try {
      const context = await applyContextPack(conversationId, pack.id, pack.revision);
      if (mounted.current) { onContext(context); onContextState("ready"); onNotice(`${pack.name} applied to this Conversation.`); }
    } catch { if (mounted.current) { setPackState("idle"); onContextState("error"); onNotice("That Context Pack changed. Refresh files, then reopen the picker."); } }
    finally { if (mounted.current) setBusy(false); }
  }

  async function removePack() {
    if (disabled || !staged?.contextPack) return;
    setBusy(true);
    onContextState("loading");
    try {
      const context = await clearContextPack(conversationId);
      if (mounted.current) { onContext(context); onContextState("ready"); onNotice("Context Pack released."); }
    } catch { if (mounted.current) { onContextState("error"); onNotice("Mentat could not verify that Context Pack release. Refresh files before sending."); } }
    finally { if (mounted.current) setBusy(false); }
  }

  if (!capable) {
    const enableCopy = agent?.runtime_type !== "hermes" || enableState === "unsupported"
      ? "This Agent does not support Conversation files."
      : enableState === "active_run"
        ? "Finish this Agent's active work before enabling files."
        : enableState === "error"
          ? "File permission availability could not be verified."
          : enableState === "loading"
            ? "Checking file permission availability…"
            : "Files require explicit permission for this Agent.";
    return (
      <div className="conversation-context-enable">
        {canEnable ? <button disabled={busy} onClick={() => void enableFiles()} type="button">{confirmEnable ? "Confirm enable files" : "Enable files"}</button> : null}
        {confirmEnable ? <button disabled={busy} onClick={() => setConfirmEnable(false)} type="button">Cancel</button> : null}
        <span>{enableCopy}</span>
      </div>
    );
  }

  return (
    <div className="conversation-context-controls">
      {stagingState === "loading" ? <p className="conversation-context-boundary" role="status">Refreshing exact staged files…</p> : null}
      {stagingState === "error" ? <div className="conversation-context-recovery" role="status"><span>Staged files could not be verified. Send is paused.</span><button onClick={onRefresh} type="button">Refresh files</button></div> : null}
      <div className="conversation-context-actions">
        <label aria-disabled={disabled} className="conversation-upload-action">
          <span>{uploadName ? `Uploading ${uploadName}…` : "Upload files"}</span>
          <input disabled={disabled} multiple onChange={(event) => { void upload(event.target.files); event.currentTarget.value = ""; }} type="file" />
        </label>
        {uploadName ? <button onClick={() => abort.current?.abort()} type="button">Cancel upload</button> : null}
        <details className="conversation-context-picker"><summary>Workspace</summary><div><label>Find a workspace file<input onChange={(event) => setWorkspaceQuery(event.target.value)} value={workspaceQuery} /></label><button disabled={disabled} onClick={() => void searchWorkspace()} type="button">Search</button>{workspaceState === "loading" ? <p>Searching…</p> : null}{workspaceState === "error" ? <p role="status">Workspace search unavailable.</p> : null}<ul>{workspaceFiles.map((file) => <li key={`${file.rootId}:${file.path}`}><button disabled={disabled} onClick={() => void chooseWorkspace(file)} type="button"><span>{file.name}</span><small>{file.path}</small></button></li>)}</ul></div></details>
        <details className="conversation-context-picker" onToggle={(event) => { if (event.currentTarget.open && packState === "idle") void loadPacks(); }}><summary>Context Pack</summary><div>{packState === "loading" ? <p>Loading Context Packs…</p> : null}{packState === "error" ? <p role="status">Context Packs unavailable.</p> : null}<ul>{packs.map((pack) => <li key={pack.id}><button disabled={disabled} onClick={() => void choosePack(pack)} type="button"><span>{pack.name}</span><small>{pack.description || `${pack.itemCount} context items`}</small></button></li>)}</ul>{packState === "ready" && !packs.length ? <p>No Context Packs yet.</p> : null}</div></details>
      </div>
      {disabledReason ? <p className="conversation-context-boundary" role="note">{disabledReason}</p> : null}
      {staged?.contextPack ? <div className="conversation-context-pack"><strong>{staged.contextPack.name}</strong><span>Context Pack applied</span><button aria-label={`Remove ${staged.contextPack.name} Context Pack`} disabled={busy || disabledReason !== null} onClick={() => void removePack()} type="button">Remove</button></div> : null}
      {staged?.attachments.length ? <ul aria-label="Staged Conversation files" className="conversation-context-chips">{staged.attachments.map((item) => <li key={item.id}><span>{item.name}</span><small>{item.available ? item.source.replace("_", " ") : "unavailable"}</small><button aria-label={`Remove ${item.name}`} disabled={busy || disabledReason !== null} onClick={() => void remove(item.id)} type="button">×</button></li>)}</ul> : null}
      {uploadFailures.length ? <ul aria-label="Failed Conversation file uploads" className="conversation-context-chips conversation-context-failures">{uploadFailures.map((item, index) => <li key={item.key}><span>{item.name}</span><small>{item.state === "failed" ? "failed" : "not uploaded"} · choose again</small><button aria-label={`Dismiss failed upload ${item.name} ${index + 1}`} onClick={() => setUploadFailures((current) => current.filter((candidate) => candidate.key !== item.key))} type="button">×</button></li>)}</ul> : null}
    </div>
  );
}
