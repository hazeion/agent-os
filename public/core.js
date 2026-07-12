const REFRESH_MS = 30_000;
const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));
const fmt = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' });
const dayFmt = new Intl.DateTimeFormat(undefined, { weekday: 'short', month: 'short', day: 'numeric' });
const timeFmt = new Intl.DateTimeFormat(undefined, { hour: 'numeric', minute: '2-digit' });

const endpoints = {
  overview: '/api/overview',
  projects: '/api/projects',
  tasks: '/api/tasks',
  agents: '/api/agents',
  agentMessages: '/api/agent-messages',
  agentActivity: '/api/agent-activity',
  attention: '/api/attention',
  calendar: '/api/calendar',
  email: '/api/email',
  agentConsole: '/api/agent-console',
  agentConsoleCommands: '/api/agent-console/commands',
  crons: '/api/hermes/crons',
  sessions: '/api/hermes/sessions',
  search: '/api/hermes/search',
  config: '/api/hermes/config',
  hermesProfiles: '/api/hermes/profiles',
  hermesSkillCatalog: '/api/hermes/skills/catalog',
  hermesKanbanCapabilities: '/api/hermes/kanban/capabilities',
  notes: '/api/obsidian-notes',
  health: '/api/health',
  unifiedSearch: '/api/search',
};

const state = {
  sessions: [],
  tasks: [],
  taskDeletionPreview: null,
  taskDeletionRequestToken: 0,
  projects: [],
  agents: [],
  agentMessages: [],
  dismissedAgentPulseIds: new Set(),
  lastAgentPulsePayload: null,
  renderCache: {},
  taskStatsCache: { key: '', byProject: new Map(), portfolio: null },
  projectsLoaded: false,
  greetingName: 'Operator',
  greetingPrefix: 'Hello',
  appName: 'Mentat',
  sessionFilter: '',
  taskFilter: '',
  taskStatusFilter: 'open',
  projectFilter: '',
  selectedTaskId: '',
  taskEditorMode: 'view',
  taskEditorTaskId: '',
  taskEditorDraft: null,
  projectEditorMode: 'view',
  projectEditorProjectId: '',
  projectEditorDraft: null,
  selectedSessionId: '',
  selectedSessionDetailTab: 'replay',
  selectedSessionDetailPayload: null,
  selectedSessionDetailContext: null,
  activeView: 'today',
  messageSearchTimer: null,
  isRefreshing: false,
  needsRefresh: false,
  hasBootstrapped: false,
  currentTheme: 'compact-dark',
  agentConsoleRuns: [],
  agentConsoleAgents: [],
  agentConsoleModels: [],
  agentConsoleModelCatalog: {},
  agentConsoleProviderInventory: {},
  agentConsoleSelectedProvider: '',
  agentConsoleProviderPreview: null,
  agentConsoleProviderPreviewSource: 'console',
  agentConsoleSelectedModel: '',
  agentConsoleSelectedAgentId: '',
  agentConsoleRunId: '',
  agentConsoleSessionId: '',
  agentConsoleStartFresh: false,
  agentConsolePollTimer: null,
  agentConsoleEventCursors: {},
  agentConsoleCommandManifest: null,
  agentCreatorProfiles: [],
  agentCreatorSkills: [],
  agentCreatorSelectedSkills: [],
  agentCreatorPreview: null,
  agentCreatorStep: 'details',
  hermesProfiles: [],
  selectedHermesProfileId: '',
  hermesProfileCapabilities: {},
  activeHermesProfileId: '',
  agentDeletionPreview: null,
  agentDeletionRequestToken: 0,
  cronTriggerPreview: null,
  cronTriggerRequestToken: 0,
  cronTriggerFeedback: null,
  managedAgentProviderInventory: {},
  managedAgentSelectedProvider: '',
  managedAgentSelectedModel: '',
  hermesKanbanCapabilities: null,
  agentActivity: { groups: {}, counts: {} },
  taskDelegationPreview: null,
  taskDelegationTaskId: '',
  taskDelegationRequestToken: 0,
  delegationActionPreview: null,
  delegationActionRequestToken: 0,
  globalSearchResults: [],
  globalSearchSelectedIndex: -1,
  globalSearchRequestToken: 0,
  globalSearchTimer: null,
  notesPayload: { notes: [], vault_name: '' },
  notesFilter: '',
  notesSearchTimer: null,
};

const taskStatusLabels = {
  open: 'Open',
  todo: 'Todo',
  'in progress': 'In Progress',
  waiting: 'Waiting',
  'needs attention': 'Needs Attention',
  completed: 'Completed',
  today: 'Today',
  review: 'Review',
  someday: 'Someday',
  blocked: 'Blocked',
  all: 'All',
};

const metricIcons = {

  needs_attention: `
    <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path d="M12 3.4 21 19H3L12 3.4Z" />
      <path d="M12 8.5v5" />
      <path d="M12 17.2h.01" />
    </svg>`,
  active_tasks: `
    <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path d="M8 6h11" />
      <path d="M8 12h11" />
      <path d="M8 18h11" />
      <path d="m3.8 6 1.1 1.1L7 4.8" />
      <path d="m3.8 12 1.1 1.1L7 10.8" />
      <path d="m3.8 18 1.1 1.1L7 16.8" />
    </svg>`,
  completed_this_week: `
    <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <circle cx="12" cy="12" r="8.5" />
      <path d="m8.2 12.3 2.4 2.4 5.3-5.4" />
    </svg>`,
  recent_sessions: `
    <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path d="M6 7.5h10.5a3 3 0 0 1 3 3v2.8a3 3 0 0 1-3 3H12l-4.2 3v-3H6a3 3 0 0 1-3-3v-2.8a3 3 0 0 1 3-3Z" />
      <path d="M8 11h7" />
      <path d="M8 13.7h4.7" />
    </svg>`,
  scheduled_crons: `
    <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <circle cx="12" cy="12" r="8.5" />
      <path d="M12 7.5V12l3.2 2" />
      <path d="M17.7 5.7 19 4.4" />
      <path d="M5 4.4l1.3 1.3" />
    </svg>`,
  active_projects: `
    <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path d="M3.5 7.5a2 2 0 0 1 2-2h4l2 2h7a2 2 0 0 1 2 2v7.8a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2V7.5Z" />
      <path d="M3.8 10h16.4" />
    </svg>`,
};

function escapeHtml(value = '') {
  return String(value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function safeExternalUrl(value = '') {
  try {
    const url = new URL(String(value));
    return ['http:', 'https:'].includes(url.protocol) ? url.href : '';
  } catch {
    return '';
  }
}

function escapeRegExp(value = '') {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function queryTerms(query = '') {
  return Array.from(new Set(String(query).match(/[A-Za-z0-9_]+/g) || []))
    .filter((term) => term.length >= 2)
    .slice(0, 8);
}

function highlightHtml(value = '', query = '') {
  const terms = queryTerms(query);
  let html = escapeHtml(value);
  terms.forEach((term) => {
    const safeTerm = escapeHtml(term);
    html = html.replace(new RegExp(`(${escapeRegExp(safeTerm)})`, 'gi'), '<mark>$1</mark>');
  });
  return html;
}

function isMarkdownSpecialLine(line = '') {
  return /^(#{1,4}\s+|[-*]\s+|\d+\.\s+|>\s*)/.test(line.trim());
}

function inlineMarkdown(value = '', query = '') {
  let html = highlightHtml(value, query);
  html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
  html = html.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noreferrer">$1</a>');
  html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  html = html.replace(/(^|\s)\*([^*]+)\*(?=\s|$)/g, '$1<em>$2</em>');
  html = html.replace(/(^|\s)_([^_]+)_(?=\s|$)/g, '$1<em>$2</em>');
  return html;
}

function renderMarkdownBlocks(value = '', query = '') {
  const lines = String(value).replace(/\r/g, '').split('\n');
  const html = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    const trimmed = line.trim();
    if (!trimmed) {
      i += 1;
      continue;
    }
    const heading = trimmed.match(/^(#{1,4})\s+(.+)$/);
    if (heading) {
      const level = Math.min(4, heading[1].length + 3);
      html.push(`<h${level}>${inlineMarkdown(heading[2], query)}</h${level}>`);
      i += 1;
      continue;
    }
    if (/^[-*]\s+/.test(trimmed)) {
      const items = [];
      while (i < lines.length && /^[-*]\s+/.test(lines[i].trim())) {
        items.push(`<li>${inlineMarkdown(lines[i].trim().replace(/^[-*]\s+/, ''), query)}</li>`);
        i += 1;
      }
      html.push(`<ul>${items.join('')}</ul>`);
      continue;
    }
    if (/^\d+\.\s+/.test(trimmed)) {
      const items = [];
      while (i < lines.length && /^\d+\.\s+/.test(lines[i].trim())) {
        items.push(`<li>${inlineMarkdown(lines[i].trim().replace(/^\d+\.\s+/, ''), query)}</li>`);
        i += 1;
      }
      html.push(`<ol>${items.join('')}</ol>`);
      continue;
    }
    if (/^>\s*/.test(trimmed)) {
      const quotes = [];
      while (i < lines.length && /^>\s*/.test(lines[i].trim())) {
        quotes.push(inlineMarkdown(lines[i].trim().replace(/^>\s*/, ''), query));
        i += 1;
      }
      html.push(`<blockquote>${quotes.join('<br>')}</blockquote>`);
      continue;
    }
    const paragraph = [];
    while (i < lines.length && lines[i].trim() && !isMarkdownSpecialLine(lines[i])) {
      paragraph.push(lines[i].trim());
      i += 1;
    }
    html.push(`<p>${inlineMarkdown(paragraph.join(' '), query)}</p>`);
  }
  return html.join('');
}

function renderMarkdown(value = '', query = '') {
  const parts = String(value || '').split('```');
  return parts.map((part, index) => {
    if (index % 2 === 0) return renderMarkdownBlocks(part, query);
    let code = part.replace(/^\s*([A-Za-z0-9_-]+)\n/, '');
    return `<pre><code>${escapeHtml(code.trimEnd())}</code></pre>`;
  }).join('');
}

async function api(path, options = {}) {
  const res = await fetch(path, { cache: 'no-store', ...options });
  const text = await res.text();
  const payload = text ? JSON.parse(text) : {};
  if (!res.ok) {
    const error = typeof payload?.error === 'string' ? payload.error : payload?.error?.message;
    throw new Error(error || `${path} returned ${res.status}`);
  }
  return payload;
}

async function sendJson(path, payload, { method = 'POST' } = {}) {
  return api(path, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload ?? {}),
  });
}

async function resolveAttentionItem(id) {
  return api(`/api/attention/${encodeURIComponent(id)}/resolve`, { method: 'POST' });
}

async function createTask(payload) {
  return sendJson(endpoints.tasks, payload, { method: 'POST' });
}

async function saveTaskEdits(id, payload) {
  return sendJson(`${endpoints.tasks}/${encodeURIComponent(id)}`, payload, { method: 'POST' });
}

async function previewTaskDeletion(id) {
  return sendJson(`${endpoints.tasks}/${encodeURIComponent(id)}/delete/preview`, {}, { method: 'POST' });
}

async function deleteTask(id, confirmationId) {
  return sendJson(`${endpoints.tasks}/${encodeURIComponent(id)}/delete`, {
    confirmed: true,
    confirmation_id: confirmationId,
  }, { method: 'POST' });
}

async function fetchHermesKanbanCapabilities() {
  return api(endpoints.hermesKanbanCapabilities);
}

async function previewTaskDelegation(id, payload) {
  return sendJson(`${endpoints.tasks}/${encodeURIComponent(id)}/delegation/preview`, payload, { method: 'POST' });
}

async function delegateTask(id, payload, confirmationId) {
  return sendJson(`${endpoints.tasks}/${encodeURIComponent(id)}/delegation`, {
    ...payload,
    confirmed: true,
    confirmation_id: confirmationId,
  }, { method: 'POST' });
}

async function refreshTaskDelegation(id) {
  return sendJson(`${endpoints.tasks}/${encodeURIComponent(id)}/delegation/refresh`, {}, { method: 'POST' });
}

async function reorderTodayTask(id, direction) {
  return sendJson(`${endpoints.tasks}/${encodeURIComponent(id)}/today-order`, { direction }, { method: 'POST' });
}

async function createTaskFromCalendarEvent(eventId, project) {
  return sendJson(`/api/calendar/events/${encodeURIComponent(eventId)}/task`, { project }, { method: 'POST' });
}

async function linkTaskToCalendarEvent(taskId, eventId) {
  return sendJson(`${endpoints.tasks}/${encodeURIComponent(taskId)}/calendar-link`, { event_id: eventId }, { method: 'POST' });
}

async function unlinkTaskFromCalendarEvent(taskId, eventId) {
  return sendJson(`${endpoints.tasks}/${encodeURIComponent(taskId)}/calendar-unlink`, { event_id: eventId }, { method: 'POST' });
}

async function fetchObsidianNotes(query = '') {
  const suffix = query ? `?q=${encodeURIComponent(query)}` : '';
  return api(`${endpoints.notes}${suffix}`);
}

async function attachNoteToTask(taskId, relativePath) {
  return sendJson(`${endpoints.tasks}/${encodeURIComponent(taskId)}/notes`, { relative_path: relativePath }, { method: 'POST' });
}

async function detachNoteFromTask(taskId, relativePath) {
  return sendJson(`${endpoints.tasks}/${encodeURIComponent(taskId)}/notes/remove`, { relative_path: relativePath }, { method: 'POST' });
}

async function previewTaskDelegationAction(id, action, note = '') {
  return sendJson(`${endpoints.tasks}/${encodeURIComponent(id)}/delegation/action/preview`, { action, note }, { method: 'POST' });
}

async function runTaskDelegationAction(id, action, note, confirmationId) {
  return sendJson(`${endpoints.tasks}/${encodeURIComponent(id)}/delegation/action`, {
    action,
    note,
    confirmed: true,
    confirmation_id: confirmationId,
  }, { method: 'POST' });
}

async function previewCronTrigger(id) {
  return sendJson(`${endpoints.crons}/${encodeURIComponent(id)}/trigger/preview`, {}, { method: 'POST' });
}

async function triggerCron(id, confirmationId) {
  return sendJson(`${endpoints.crons}/${encodeURIComponent(id)}/trigger`, {
    confirmed: true,
    confirmation_id: confirmationId,
  }, { method: 'POST' });
}

async function createProject(payload) {
  return sendJson(endpoints.projects, payload, { method: 'POST' });
}

async function saveProjectEdits(id, payload) {
  return sendJson(`${endpoints.projects}/${encodeURIComponent(id)}`, payload, { method: 'POST' });
}

async function sendAgentMessage(payload) {
  return sendJson(endpoints.agentMessages, payload, { method: 'POST' });
}

async function setAgentMessageState(id, payload) {
  return sendJson(`${endpoints.agentMessages}/${encodeURIComponent(id)}/state`, payload, { method: 'POST' });
}

async function startAgentConsoleRun(payload) {
  return sendJson(`${endpoints.agentConsole}/runs`, payload, { method: 'POST' });
}

async function fetchAgentConsoleRun(runId, afterCursor = null) {
  const suffix = afterCursor === null ? '' : `?after=${encodeURIComponent(afterCursor)}`;
  return api(`${endpoints.agentConsole}/runs/${encodeURIComponent(runId)}${suffix}`);
}

async function refreshAgentConsoleModels(agentId = '') {
  return sendJson(`${endpoints.agentConsole}/models/refresh`, { agent_id: agentId }, { method: 'POST' });
}

async function previewAgentConsoleProvider(provider, model, agentId = '') {
  return sendJson(`${endpoints.agentConsole}/provider/preview`, { provider, model, agent_id: agentId }, { method: 'POST' });
}

async function switchAgentConsoleProvider(provider, model, agentId, confirmationId) {
  return sendJson(`${endpoints.agentConsole}/provider`, {
    provider,
    model,
    agent_id: agentId,
    confirmed: true,
    confirmation_id: confirmationId,
  }, { method: 'POST' });
}

async function fetchAgentConsoleCommandManifest() {
  return api(endpoints.agentConsoleCommands);
}

async function fetchHermesProfiles() {
  return api(endpoints.hermesProfiles);
}

async function fetchHermesSkillCatalog() {
  return api(endpoints.hermesSkillCatalog);
}

async function previewHermesProfile(payload) {
  return sendJson(`${endpoints.hermesProfiles}/preview`, payload, { method: 'POST' });
}

async function createHermesProfile(payload) {
  return sendJson(endpoints.hermesProfiles, payload, { method: 'POST' });
}

async function previewHermesProfileDeletion(profileId) {
  return sendJson(`${endpoints.hermesProfiles}/${encodeURIComponent(profileId)}/delete/preview`, {}, { method: 'POST' });
}

async function deleteHermesProfile(profileId, confirmationId) {
  return sendJson(`${endpoints.hermesProfiles}/${encodeURIComponent(profileId)}/delete`, {
    confirmed: true,
    confirmation_id: confirmationId,
  }, { method: 'POST' });
}

async function stopAgentConsoleRun(id) {
  return sendJson(`${endpoints.agentConsole}/runs/${encodeURIComponent(id)}/cancel`, {}, { method: 'POST' });
}

async function fetchSessionDetail(id, messageId = '') {
  const suffix = messageId ? `?message_id=${encodeURIComponent(messageId)}` : '';
  return api(`${endpoints.sessions}/${encodeURIComponent(id)}${suffix}`);
}

async function fetchSessionReplay(id) {
  return api(`${endpoints.sessions}/${encodeURIComponent(id)}/replay`);
}

async function searchMessages(query) {
  return api(`${endpoints.search}?q=${encodeURIComponent(query)}`);
}

async function searchDashboard(query) {
  return api(`${endpoints.unifiedSearch}?q=${encodeURIComponent(query)}`);
}
