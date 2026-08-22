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
  homeDelegationRefresh: '/api/tasks/delegations/refresh-home',
  agents: '/api/agents',
  contextPacks: '/api/context-packs',
  agentActivity: '/api/agent-activity',
  attention: '/api/attention',
  calendar: '/api/calendar',
  email: '/api/email',
  agentConsole: '/api/agent-console',
  agentConsoleCommands: '/api/agent-console/commands',
  agentConsoleAttachments: '/api/agent-console/attachments',
  agentConsoleWorkspaceFiles: '/api/agent-console/workspace-files',
  agentConsoleWorkspaceAttachments: '/api/agent-console/workspace-attachments',
  crons: '/api/hermes/crons',
  sessions: '/api/hermes/sessions',
  search: '/api/hermes/search',
  config: '/api/hermes/config',
  hermesProfiles: '/api/hermes/profiles',
  hermesSkillCatalog: '/api/hermes/skills/catalog',
  hermesKanbanCapabilities: '/api/hermes/kanban/capabilities',
  hermesCapabilities: '/api/hermes/capabilities',
  hermesWebhookHealth: '/api/hermes/webhooks/health',
  hermesWebhookProbe: '/api/hermes/webhooks/probe',
  hermesEvents: '/api/hermes/events',
  notes: '/api/obsidian-notes',
  health: '/api/health',
  diagnosticsBundle: '/api/diagnostics/bundle',
  unifiedSearch: '/api/search',
};

const state = {
  sessions: [],
  tasks: [],
  overviewCards: {},
  homeCalendar: {},
  homeCrons: {},
  taskDeletionPreview: null,
  taskDeletionRequestToken: 0,
  projects: [],
  agents: [],
  latestAgentsPayload: null,
  latestSessionsPayload: null,
  contextPacks: [],
  contextPackDraft: null,
  editingContextPackId: '',
  dismissedAgentPulseIds: new Set(),
  lastAgentPulsePayload: null,
  renderCache: {},
  taskStatsCache: { key: '', byProject: new Map(), portfolio: null },
  projectsLoaded: false,
  greetingName: 'Operator',
  greetingPrefix: 'Hello',
  appName: 'Mentat',
  sessionFilter: '',
  sessionMessageMatchIds: new Set(),
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
  sessionDetailRequestGeneration: 0,
  activeView: 'today',
  messageSearchTimer: null,
  messageSearchRequestGeneration: 0,
  messageSearchInFlight: false,
  messageSearchPending: null,
  isRefreshing: false,
  needsRefresh: false,
  hermesProjectionRefreshTimer: null,
  hermesPendingProjections: new Set(),
  hermesEventSource: null,
  hermesFetchStreamActive: false,
  hermesFetchStreamCursor: '',
  hermesFetchReconnectTimer: null,
  homeDelegationRefreshInFlight: false,
  hasBootstrapped: false,
  currentTheme: 'emerald',
  agentConsoleRuns: [],
  agentConsoleAgents: [],
  agentConsoleModels: [],
  agentConsoleModelCatalog: {},
  agentConsoleProviderInventory: {},
  agentConsoleSelectedProvider: '',
  agentConsoleProviderPreview: null,
  agentConsoleProviderPreviewSource: 'console',
  agentConsoleSelectedModel: '',
  agentConsoleRuntimeLoading: false,
  agentConsoleRuntimeMutationInFlight: false,
  agentConsoleRuntimeMutationGeneration: 0,
  agentConsoleRuntimePending: null,
  agentConsoleRuntimeUnresolved: false,
  agentConsoleRuntimeRequestGeneration: 0,
  agentConsoleRuntimeNotices: [],
  agentConsoleShowActivity: false,
  agentConsoleToolActivityContext: '',
  agentConsoleToolActivityActive: false,
  agentConsoleSelectedAgentId: '',
  agentConsoleRunId: '',
  agentConsoleSteerInFlight: false,
  agentConsoleSessionId: '',
  agentConsoleStartFresh: false,
  agentConsolePollTimer: null,
  agentConsoleEventCursors: {},
  agentConsoleCommandManifest: null,
  agentConsoleAttachments: [],
  agentConsoleRemoteContext: null,
  agentConsoleTransportBinding: '',
  agentConsoleAttachmentsUploading: false,
  agentConsoleAttachmentError: '',
  agentConsoleWorkspaceSearchTimer: null,
  agentConsoleWorkspaceRequestToken: 0,
  agentCreatorProfiles: [],
  agentCreatorSkills: [],
  agentCreatorSelectedSkills: [],
  agentCreatorPreview: null,
  agentCreatorStep: 'details',
  hermesProfiles: [],
  hermesWebhookHealth: null,
  selectedHermesProfileId: '',
  hermesProfileCapabilities: {},
  activeHermesProfileId: '',
  managedAgentIdentities: {},
  managedAgentIdentityPreview: null,
  managedAgentIdentityRequestToken: 0,
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

function beginSessionMessageSearch(currentGeneration) {
  return {
    generation: currentGeneration + 1,
    matchIds: new Set(),
  };
}

function sessionMessageMatchIdsForResponse(requestGeneration, currentGeneration, payload = {}, sessions = []) {
  if (requestGeneration !== currentGeneration) return null;
  if (payload.error) return new Set();
  const availableSessionIds = new Set(sessions.map((session) => session.id));
  const results = Array.isArray(payload.results) ? payload.results : [];
  return new Set(
    results
      .map((result) => result?.session_id)
      .filter((sessionId) => availableSessionIds.has(sessionId)),
  );
}

function sessionSearchIncludes(session, query, messageMatchIds = new Set()) {
  if (messageMatchIds.has(session.id)) return true;
  if (!query) return true;
  const haystack = `${session.title || ''} ${session.source || ''} ${session.message_count || ''} ${session.tool_call_count || ''}`.toLowerCase();
  return haystack.includes(query.toLowerCase());
}

function sessionSearchMatches(sessions, query, messageMatchIds = new Set()) {
  return sessions.filter((session) => sessionSearchIncludes(session, query, messageMatchIds));
}

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

function searchQueryLength(value = '') {
  return Array.from(String(value)).length;
}

function highlightHtml(value = '', query = '') {
  const text = String(value);
  const literal = String(query).trim();
  if (literal.length >= 1) {
    const literalPattern = escapeRegExp(literal).replace(/\s+/g, '\\s+');
    const matches = Array.from(text.matchAll(new RegExp(literalPattern, 'gi')));
    if (matches.length) {
      let offset = 0;
      const parts = [];
      matches.forEach((match) => {
        const index = match.index ?? 0;
        parts.push(escapeHtml(text.slice(offset, index)));
        parts.push(`<mark>${escapeHtml(match[0])}</mark>`);
        offset = index + match[0].length;
      });
      parts.push(escapeHtml(text.slice(offset)));
      return parts.join('');
    }
  }
  const terms = queryTerms(query);
  let html = escapeHtml(text);
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
  html = html.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, (_match, label, url) => (
    `<a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${label}</a>`
  ));
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

const CODE_LANGUAGE_ALIASES = {
  cjs: 'javascript', js: 'javascript', jsx: 'javascript', mjs: 'javascript',
  ts: 'typescript', tsx: 'typescript',
  py: 'python',
  sh: 'shell', bash: 'shell', zsh: 'shell',
  ps1: 'powershell',
  c: 'c', h: 'c', cc: 'cpp', cpp: 'cpp', cxx: 'cpp', hpp: 'cpp',
  cs: 'csharp',
  rs: 'rust',
  rb: 'ruby',
  yml: 'yaml',
  html: 'markup', xml: 'markup', svg: 'markup',
  md: 'markdown',
  text: 'plain', txt: 'plain', plaintext: 'plain',
};

const CODE_LANGUAGE_RULES = {
  javascript: {
    keywords: 'async await break case catch class const continue debugger default delete do else export extends finally for from function get if import in instanceof let new of return set static super switch throw try typeof var void while with yield',
    literals: 'false null true undefined', lineComments: ['//'], blockComments: [['/*', '*/']],
  },
  typescript: {
    keywords: 'abstract any as async await boolean break case catch class const constructor continue declare default delete do else enum export extends finally for from function get if implements import in infer instanceof interface keyof let module namespace never new number object of override private protected public readonly return satisfies set static string super switch symbol this throw try type typeof unknown var void while with yield',
    literals: 'false null true undefined', lineComments: ['//'], blockComments: [['/*', '*/']],
  },
  python: {
    keywords: 'and as assert async await break class continue def del elif else except finally for from global if import in is lambda nonlocal not or pass raise return try while with yield',
    literals: 'False None True', lineComments: ['#'], blockComments: [],
  },
  shell: {
    keywords: 'case do done elif else esac fi for function if in select then time until while',
    literals: 'false true', lineComments: ['#'], blockComments: [],
  },
  powershell: {
    keywords: 'begin break catch class continue data do dynamicparam else elseif end enum exit filter finally for foreach from function hidden if in param process return static switch throw trap try until using var while workflow',
    literals: 'false null true', lineComments: ['#'], blockComments: [['<#', '#>']],
  },
  sql: {
    keywords: 'add alter and as asc begin between by case check column commit constraint create database default delete desc distinct drop else end exists foreign from full grant group having in index inner insert into is join key left like limit not null on or order outer primary references right rollback row select set table then union unique update values view when where',
    literals: 'false null true', lineComments: ['--'], blockComments: [['/*', '*/']],
  },
  c: {
    keywords: 'auto break case char const continue default do double else enum extern float for goto if inline int long register restrict return short signed sizeof static struct switch typedef union unsigned void volatile while',
    literals: 'false null true', lineComments: ['//'], blockComments: [['/*', '*/']],
  },
  cpp: {
    keywords: 'alignas alignof auto bool break case catch char class const constexpr continue default delete do double else enum explicit export extern float for friend goto if inline int long mutable namespace new noexcept operator private protected public register reinterpret_cast return short signed sizeof static struct switch template this throw try typedef typename union unsigned using virtual void volatile while',
    literals: 'false nullptr true', lineComments: ['//'], blockComments: [['/*', '*/']],
  },
  csharp: {
    keywords: 'abstract as async await base bool break byte case catch char checked class const continue decimal default delegate do double else enum event explicit extern false finally fixed float for foreach goto if implicit in int interface internal is lock long namespace new object operator out override params private protected public readonly ref return sbyte sealed short sizeof stackalloc static string struct switch this throw true try typeof uint ulong unchecked unsafe ushort using virtual void volatile while',
    literals: 'false null true', lineComments: ['//'], blockComments: [['/*', '*/']],
  },
  java: {
    keywords: 'abstract assert boolean break byte case catch char class const continue default do double else enum extends final finally float for goto if implements import instanceof int interface long native new package private protected public return short static strictfp super switch synchronized this throw throws transient try void volatile while',
    literals: 'false null true', lineComments: ['//'], blockComments: [['/*', '*/']],
  },
  go: {
    keywords: 'break case chan const continue default defer else fallthrough for func go goto if import interface map package range return select struct switch type var',
    literals: 'false nil true', lineComments: ['//'], blockComments: [['/*', '*/']],
  },
  rust: {
    keywords: 'as async await break const continue crate dyn else enum extern fn for if impl in let loop match mod move mut pub ref return self Self static struct super trait type unsafe use where while',
    literals: 'false None Some true', lineComments: ['//'], blockComments: [['/*', '*/']],
  },
  ruby: {
    keywords: 'alias and begin break case class def defined do else elsif end ensure false for if in module next nil not or redo rescue retry return self super then true undef unless until when while yield',
    literals: 'false nil true', lineComments: ['#'], blockComments: [],
  },
  php: {
    keywords: 'abstract and array as break callable case catch class clone const continue declare default do echo else elseif empty enddeclare endfor endforeach endif endswitch endwhile eval exit extends final finally fn for foreach function global goto if implements include include_once instanceof insteadof interface isset list match namespace new or print private protected public readonly require require_once return static switch throw trait try unset use var while xor yield',
    literals: 'false null true', lineComments: ['//', '#'], blockComments: [['/*', '*/']],
  },
  css: {
    keywords: 'and from important media not only or supports to var',
    literals: 'inherit initial none revert transparent unset', lineComments: [], blockComments: [['/*', '*/']],
  },
  json: { keywords: '', literals: 'false null true', lineComments: [], blockComments: [] },
  yaml: { keywords: '', literals: 'false null true yes no', lineComments: ['#'], blockComments: [] },
  toml: { keywords: '', literals: 'false true', lineComments: ['#'], blockComments: [] },
  markup: { keywords: '', literals: '', lineComments: [], blockComments: [['<!--', '-->']] },
};

function normalizeCodeLanguage(value = '') {
  const language = String(value || '').trim().toLowerCase();
  return CODE_LANGUAGE_ALIASES[language] || language;
}

function syntaxToken(kind, value) {
  return `<span class="syntax-${kind}">${escapeHtml(value)}</span>`;
}

function highlightCode(value = '', rawLanguage = '') {
  const code = String(value || '');
  const language = normalizeCodeLanguage(rawLanguage);
  const rules = CODE_LANGUAGE_RULES[language];
  if (!rules) return escapeHtml(code);
  const keywords = new Set(rules.keywords.split(/\s+/).filter(Boolean));
  const literals = new Set(rules.literals.split(/\s+/).filter(Boolean));
  let html = '';
  let index = 0;
  while (index < code.length) {
    const lineComment = rules.lineComments.find((marker) => code.startsWith(marker, index));
    if (lineComment) {
      const end = code.indexOf('\n', index);
      const stop = end < 0 ? code.length : end;
      html += syntaxToken('comment', code.slice(index, stop));
      index = stop;
      continue;
    }
    const blockComment = rules.blockComments.find(([start]) => code.startsWith(start, index));
    if (blockComment) {
      const end = code.indexOf(blockComment[1], index + blockComment[0].length);
      const stop = end < 0 ? code.length : end + blockComment[1].length;
      html += syntaxToken('comment', code.slice(index, stop));
      index = stop;
      continue;
    }
    const character = code[index];
    if (character === '"' || character === "'" || character === '`') {
      const triple = code.startsWith(character.repeat(3), index);
      const delimiter = triple ? character.repeat(3) : character;
      let stop = index + delimiter.length;
      while (stop < code.length) {
        if (code.startsWith(delimiter, stop)) {
          stop += delimiter.length;
          break;
        }
        if (!triple && code[stop] === '\\') stop += 2;
        else stop += 1;
      }
      html += syntaxToken('string', code.slice(index, stop));
      index = stop;
      continue;
    }
    const number = code.slice(index).match(/^(?:0[xob][0-9a-f]+|\d+(?:\.\d+)?(?:e[+-]?\d+)?)/i);
    if (number && (index === 0 || !/[\w$]/.test(code[index - 1]))) {
      html += syntaxToken('number', number[0]);
      index += number[0].length;
      continue;
    }
    const identifier = code.slice(index).match(/^[A-Za-z_$@][\w$@-]*/);
    if (identifier) {
      const token = identifier[0];
      const rest = code.slice(index + token.length);
      if (keywords.has(token)) html += syntaxToken('keyword', token);
      else if (literals.has(token)) html += syntaxToken('literal', token);
      else if (/^\s*\(/.test(rest)) html += syntaxToken('function', token);
      else html += escapeHtml(token);
      index += token.length;
      continue;
    }
    if (/[{}[\]();,.<>:=+*/%!&|?~-]/.test(character)) {
      html += syntaxToken('operator', character);
      index += 1;
      continue;
    }
    html += escapeHtml(character);
    index += 1;
  }
  return html;
}

function renderMarkdown(value = '', query = '') {
  const parts = String(value || '').split('```');
  return parts.map((part, index) => {
    if (index % 2 === 0) return renderMarkdownBlocks(part, query);
    const normalized = part.replace(/\r/g, '');
    const firstLineBreak = normalized.indexOf('\n');
    const rawLanguage = firstLineBreak >= 0 ? normalized.slice(0, firstLineBreak).trim() : '';
    const language = /^[A-Za-z0-9_+#.-]{1,32}$/.test(rawLanguage) ? rawLanguage : '';
    const code = language ? normalized.slice(firstLineBreak + 1) : normalized.replace(/^\n/, '');
    const normalizedLanguage = normalizeCodeLanguage(language);
    return `<figure class="markdown-code-block"><figcaption><span class="mono">${escapeHtml(language || 'plain text')}</span><button type="button" class="markdown-code-copy" data-copy-code aria-label="Copy ${escapeHtml(language || 'plain text')} code">Copy</button></figcaption><pre><code class="language-${escapeHtml(normalizedLanguage || 'plain')}">${highlightCode(code.trimEnd(), normalizedLanguage)}</code></pre></figure>`;
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

async function refreshHomeDelegations() {
  return sendJson(endpoints.homeDelegationRefresh, {}, { method: 'POST' });
}

async function fetchHermesWebhookHealth() {
  return api(endpoints.hermesWebhookHealth);
}

async function verifyHermesWebhookProbe() {
  return sendJson(endpoints.hermesWebhookProbe, {}, { method: 'POST' });
}

async function previewDelegationRebind(id) {
  return sendJson(`${endpoints.tasks}/${encodeURIComponent(id)}/delegation/rebind/preview`, {}, { method: 'POST' });
}

async function confirmDelegationRebind(id, confirmationId) {
  return sendJson(`${endpoints.tasks}/${encodeURIComponent(id)}/delegation/rebind`, {
    confirmed: true,
    confirmation_id: confirmationId,
  }, { method: 'POST' });
}

async function reorderTodayTask(id, direction) {
  return sendJson(`${endpoints.tasks}/${encodeURIComponent(id)}/today-order`, { direction }, { method: 'POST' });
}

async function createTaskFromCalendarEvent(eventId, project, context = {}) {
  const payload = { project };
  if (context.week_start && context.timezone) {
    payload.week_start = context.week_start;
    payload.timezone = context.timezone;
  }
  return sendJson(`/api/calendar/events/${encodeURIComponent(eventId)}/task`, payload, { method: 'POST' });
}

async function linkTaskToCalendarEvent(taskId, eventId, context = {}) {
  const payload = { event_id: eventId };
  if (context.week_start && context.timezone) {
    payload.week_start = context.week_start;
    payload.timezone = context.timezone;
  }
  return sendJson(`${endpoints.tasks}/${encodeURIComponent(taskId)}/calendar-link`, payload, { method: 'POST' });
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

async function fetchContextPacks() {
  return api(endpoints.contextPacks);
}

async function createContextPack(payload) {
  return sendJson(endpoints.contextPacks, payload, { method: 'POST' });
}

async function saveContextPack(id, payload) {
  return sendJson(`${endpoints.contextPacks}/${encodeURIComponent(id)}`, payload, { method: 'POST' });
}

async function removeContextPack(id, revision, updatedAt = '') {
  const payload = { confirmed: true };
  const expectedRevision = String(revision || '').trim();
  if (expectedRevision) payload.expected_revision = expectedRevision;
  else if (updatedAt) payload.expected_updated_at = updatedAt;
  return sendJson(`${endpoints.contextPacks}/${encodeURIComponent(id)}/delete`, payload, { method: 'POST' });
}

async function stageContextPack(id) {
  return sendJson(`${endpoints.contextPacks}/${encodeURIComponent(id)}/stage`, {}, { method: 'POST' });
}

async function startAgentConsoleRun(payload) {
  return sendJson(`${endpoints.agentConsole}/runs`, payload, { method: 'POST' });
}

async function respondToAgentConsoleRequest(id, payload) {
  return sendJson(`${endpoints.agentConsole}/runs/${encodeURIComponent(id)}/response`, payload, { method: 'POST' });
}

async function steerAgentConsoleRun(id, text, controlRevision, agentId) {
  return sendJson(`${endpoints.agentConsole}/runs/${encodeURIComponent(id)}/steer`, {
    text,
    control_revision: controlRevision,
    agent_id: agentId,
  }, { method: 'POST' });
}

async function uploadAgentConsoleAttachment(file) {
  if (!(file instanceof File)) throw new Error('Choose a file to attach.');
  return api(endpoints.agentConsoleAttachments, {
    method: 'POST',
    headers: {
      'Content-Type': file.type || 'application/octet-stream',
      'X-Mentat-Filename': encodeURIComponent(file.name || 'attachment'),
    },
    body: file,
  });
}

async function uploadAgentConsoleAttachments(files = [], onUploaded = null) {
  const attachments = [];
  for (const file of Array.from(files)) {
    const payload = await uploadAgentConsoleAttachment(file);
    const attachment = payload.attachment || payload;
    attachments.push(attachment);
    if (typeof onUploaded === 'function') onUploaded(attachment);
  }
  return attachments;
}

async function fetchAgentConsoleWorkspaceFiles(query = '') {
  return api(`${endpoints.agentConsoleWorkspaceFiles}?q=${encodeURIComponent(String(query || '').slice(0, 200))}`);
}

async function createAgentConsoleWorkspaceAttachment(rootId, relativePath) {
  return sendJson(endpoints.agentConsoleWorkspaceAttachments, {
    root_id: rootId,
    relative_path: relativePath,
  }, { method: 'POST' });
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

async function fetchHermesProfileIdentity(profileId) {
  return api(`${endpoints.hermesProfiles}/${encodeURIComponent(profileId)}/identity`);
}

async function previewHermesProfileIdentity(profileId, role) {
  return sendJson(`${endpoints.hermesProfiles}/${encodeURIComponent(profileId)}/identity/preview`, {
    role,
  }, { method: 'POST' });
}

async function updateHermesProfileIdentity(profileId, role, confirmationId) {
  return sendJson(`${endpoints.hermesProfiles}/${encodeURIComponent(profileId)}/identity`, {
    role,
    confirmed: true,
    confirmation_id: confirmationId,
  }, { method: 'POST' });
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
