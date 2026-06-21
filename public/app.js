const REFRESH_MS = 30_000;
const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));
const fmt = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' });

const endpoints = {
  overview: '/api/overview',
  projects: '/api/projects',
  tasks: '/api/tasks',
  attention: '/api/attention',
  calendar: '/api/calendar',
  crons: '/api/hermes/crons',
  sessions: '/api/hermes/sessions',
  search: '/api/hermes/search',
  config: '/api/hermes/config',
  notes: '/api/obsidian-notes',
  health: '/api/health',
};

const state = {
  sessions: [],
  tasks: [],
  sessionFilter: '',
  taskFilter: '',
  selectedSessionId: '',
  activeView: 'today',
  messageSearchTimer: null,
  isRefreshing: false,
  needsRefresh: false,
  hasBootstrapped: false,
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

async function api(path, options = {}) {
  const res = await fetch(path, { cache: 'no-store', ...options });
  if (!res.ok) throw new Error(`${path} returned ${res.status}`);
  return res.json();
}

async function resolveAttentionItem(id) {
  return api(`/api/attention/${encodeURIComponent(id)}/resolve`, { method: 'POST' });
}

async function fetchSessionDetail(id, messageId = '') {
  const suffix = messageId ? `?message_id=${encodeURIComponent(messageId)}` : '';
  return api(`${endpoints.sessions}/${encodeURIComponent(id)}${suffix}`);
}

async function searchMessages(query) {
  return api(`${endpoints.search}?q=${encodeURIComponent(query)}`);
}

function humanDate(value) {
  if (!value) return '—';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return String(value);
  return fmt.format(d);
}

function setView(view) {
  const viewChanged = state.activeView !== view;
  state.activeView = view;
  $$('.nav-item').forEach((item) => item.classList.toggle('active', item.dataset.view === view));
  $$('[data-view-panel]').forEach((panel) => panel.classList.toggle('active', panel.dataset.viewPanel === view));
  const titles = {
    today: 'Mission Control / Today',
    agents: 'Agents / Sessions',
    calendar: 'Calendar',
    projects: 'Projects / Tasks',
    notes: 'Knowledge Base',
    settings: 'Settings',
  };
  const eyebrow = $('.command-header .eyebrow');
  if (eyebrow) eyebrow.textContent = titles[view] || 'Mission Control';
  if (state.hasBootstrapped && viewChanged) return refresh();
  return Promise.resolve();
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function flashTarget(target) {
  if (!target) return;
  target.classList.remove('jump-highlight');
  void target.offsetWidth;
  target.classList.add('jump-highlight');
  window.setTimeout(() => target.classList.remove('jump-highlight'), 1600);
}

async function jumpToDashboardSection(view, targetSelector) {
  if (!view) return;
  await setView(view);
  await sleep(60);
  const target = targetSelector ? document.querySelector(targetSelector) : document.querySelector(`[data-view-panel="${view}"]`);
  if (!target) return;
  target.scrollIntoView({ behavior: 'smooth', block: 'start' });
  flashTarget(target);
}

function renderCards(cards = {}) {
  const defs = [
    ['needs_attention', 'Attention', 'open items', 'danger', 'today', '#attention-panel'],
    ['active_tasks', 'Active Tasks', 'today focus', 'accent', 'projects', '#tasks-panel'],
    ['completed_this_week', 'Completed', 'this week', 'success', 'projects', '#completed-work-panel'],
    ['recent_sessions', 'Sessions', 'recent Hermes work', 'purple', 'agents', '#conversation-library-panel'],
    ['scheduled_crons', 'Crons', 'scheduled jobs', 'warn', 'agents', '#cron-monitor-panel'],
    ['active_projects', 'Projects', 'active portfolio', 'accent', 'projects', '#projects-panel'],
  ];
  $('#overview-cards').innerHTML = defs.map(([key, label, sub, tone, jumpView, jumpTarget]) => `
    <button class="metric-card metric-card-button ${tone}" type="button" data-jump-view="${escapeHtml(jumpView)}" data-jump-target="${escapeHtml(jumpTarget)}" aria-label="Open ${escapeHtml(label)} details">
      <div class="metric-icon" aria-hidden="true">${metricIcons[key]}</div>
      <div>
        <div class="metric-value">${cards[key] ?? 0}</div>
        <div class="metric-label">${escapeHtml(label)}</div>
        <div class="metric-sub">${escapeHtml(sub)}</div>
      </div>
      <span class="metric-arrow" aria-hidden="true">↗</span>
    </button>
  `).join('');
}

function renderAttention(items = []) {
  const open = items.filter((item) => item.status !== 'resolved');
  const panel = $('.priority-panel');
  const count = $('#attention-count');
  panel?.classList.toggle('has-attention', open.length > 0);
  panel?.classList.toggle('clear', open.length === 0);
  count.textContent = open.length ? `${open.length} open` : 'clear skies';
  count.className = `pill ${open.length ? 'danger' : 'success'}`;
  $('#attention-list').innerHTML = open.length ? open.map((item) => `
    <article class="item">
      <div class="item-title">
        <span>${escapeHtml(item.title)}</span>
        <span class="pill ${item.severity === 'high' ? 'danger' : 'warn'}">${escapeHtml(item.severity || 'medium')}</span>
      </div>
      <div class="item-desc">${escapeHtml(item.description || '')}</div>
      <div class="item-meta mono">${escapeHtml(item.type || 'manual')} · ${escapeHtml(item.project || 'General')} · ${humanDate(item.created_at)}</div>
      <div class="item-actions">
        <button class="action-button resolve-attention" type="button" data-attention-id="${escapeHtml(item.id)}">Resolve</button>
      </div>
    </article>
  `).join('') : `<div class="empty clear-skies">No open attention items. Clear skies.</div>`;
}

function taskArea(task = {}) {
  if (task.status === 'completed') return 'completed';
  if (task.status === 'in_progress') return 'in progress';
  if (task.status === 'waiting') return 'waiting';
  if (task.status === 'needs_attention' || task.needs_attention || task.review_required) return 'needs attention';
  return 'todo';
}

function taskTone(area) {
  if (area === 'completed') return 'success';
  if (area === 'needs attention') return 'danger';
  if (area === 'waiting') return 'warn';
  return '';
}

function taskMatches(task, query) {
  if (!query) return true;
  const haystack = [
    task.title,
    task.description,
    task.project,
    task.status,
    taskArea(task),
  ].join(' ').toLowerCase();
  return haystack.includes(query.toLowerCase());
}

function renderFocusTasks(tasks = []) {
  const focus = tasks.filter((task) => taskArea(task) !== 'completed').slice(0, 5);
  $('#focus-task-list').innerHTML = focus.length ? focus.map((task) => `
    <article class="item">
      <div class="item-title"><span>${escapeHtml(task.title)}</span><span class="pill ${taskTone(taskArea(task))}">${escapeHtml(taskArea(task))}</span></div>
      <div class="item-desc">${escapeHtml(task.description || '')}</div>
      <div class="item-meta mono">${escapeHtml(task.project || 'General')} · due ${escapeHtml(task.due_date || 'none')}</div>
    </article>
  `).join('') : `<div class="empty">No active focus tasks yet.</div>`;
}

function renderTaskList(tasks = []) {
  state.tasks = tasks;
  const query = state.taskFilter;
  const filtered = tasks.filter((task) => taskMatches(task, query));
  const count = $('#task-count');
  if (count) count.textContent = query ? `${filtered.length} shown` : `${tasks.length} tasks`;
  $('#task-list').innerHTML = filtered.length ? filtered.map((task) => {
    const area = taskArea(task);
    return `
      <article class="task-list-item">
        <div class="task-list-main">
          <div class="item-title"><span>${escapeHtml(task.title)}</span><span class="pill ${taskTone(area)}">${escapeHtml(area)}</span></div>
          <div class="item-desc">${escapeHtml(task.description || '')}</div>
        </div>
        <span class="pill project-pill">${escapeHtml(task.project || 'General')}</span>
      </article>
    `;
  }).join('') : `<div class="empty">No tasks match this search.</div>`;

  const completed = tasks.filter((t) => taskArea(t) === 'completed');
  const completedMarkup = `
    <article class="item">
      <div class="item-title"><span>Completed tasks</span><span class="pill success">${completed.length}</span></div>
      <div class="item-meta">${completed.length ? completed.map((t) => escapeHtml(t.title)).join(' · ') : 'No completed tasks yet.'}</div>
    </article>
    <article class="item">
      <div class="item-title"><span>Agent/session outputs</span><span class="pill">read-only</span></div>
      <div class="item-meta">Use Agents / Sessions for the searchable conversation space.</div>
    </article>
  `;
  $('#completed-list').innerHTML = completedMarkup;
  const projectCompleted = $('#project-completed-list');
  if (projectCompleted) projectCompleted.innerHTML = completedMarkup;
}

function projectTone(status = '') {
  const normalized = String(status).toLowerCase();
  if (normalized === 'active') return 'success';
  if (['waiting', 'paused', 'blocked'].includes(normalized)) return 'warn';
  if (['archived', 'inactive'].includes(normalized)) return '';
  return '';
}

function renderProjects(projects = []) {
  $('#project-list').innerHTML = projects.length ? projects.map((project) => `
    <article class="project-card">
      <div class="item-title"><span>${escapeHtml(project.name)}</span><span class="pill ${projectTone(project.status)}">${escapeHtml(project.status)}</span></div>
      <div class="item-desc">${escapeHtml(project.description || '')}</div>
      <div class="item-meta mono">${escapeHtml(project.type)} · [[${escapeHtml(project.obsidian_note || 'No note')}]]</div>
    </article>
  `).join('') : `<div class="empty">No projects found.</div>`;
}

function renderCalendar(payload = {}) {
  const items = Array.isArray(payload) ? payload : (payload.items || []);
  const source = Array.isArray(payload) ? 'local' : (payload.source || 'local');
  const auth = Array.isArray(payload) ? 'legacy' : (payload.auth || 'unknown');
  const sourceLabel = source === 'google' ? 'Google live' : source === 'local' && auth === 'error' ? 'Google error' : 'local json';
  const pillClass = source === 'google' ? 'pill success' : auth === 'error' ? 'pill warn' : 'pill';
  ['#calendar-source-pill', '#calendar-full-source-pill'].forEach((selector) => {
    const pill = $(selector);
    if (!pill) return;
    pill.textContent = sourceLabel;
    pill.className = pillClass;
  });
  const markup = items.length ? items.map((item) => `
    <article class="item">
      <div class="item-title"><span>${escapeHtml(item.title)}</span><span class="pill">${escapeHtml(item.type || 'event')}</span></div>
      <div class="item-desc">${escapeHtml(item.description || item.location || '')}</div>
      <div class="item-meta mono">${humanDate(item.start)} → ${humanDate(item.end)}</div>
    </article>
  `).join('') : `<div class="empty">${source === 'google' ? 'No upcoming Google Calendar events in the selected window.' : 'No local calendar items yet. Google Calendar integration is planned later.'}</div>`;
  $('#calendar-list').innerHTML = markup;
  $('#calendar-full-list').innerHTML = markup;
}

function renderCrons(payload = {}) {
  const jobs = payload.jobs || [];
  $('#cron-count').textContent = `${jobs.length} jobs`;
  $('#cron-list').innerHTML = jobs.length ? jobs.map((job) => `
    <article class="item">
      <div class="item-title"><span>${escapeHtml(job.name)}</span><span class="pill ${job.enabled ? 'success' : 'warn'}">${job.enabled ? 'enabled' : 'disabled'}</span></div>
      <div class="item-meta mono">${escapeHtml(job.schedule)} · last ${escapeHtml(job.last_status || 'unknown')}</div>
    </article>
  `).join('') : `<div class="empty">No scheduled Hermes cron jobs found yet.</div>`;
}

function sessionMatches(session, query) {
  if (!query) return true;
  const haystack = `${session.title || ''} ${session.source || ''} ${session.message_count || ''} ${session.tool_call_count || ''}`.toLowerCase();
  return haystack.includes(query.toLowerCase());
}

function renderSessions(payload = {}) {
  state.sessions = payload.sessions || state.sessions || [];
  const filtered = state.sessions.filter((session) => sessionMatches(session, state.sessionFilter));
  $('#session-list').innerHTML = filtered.length ? filtered.map((session) => `
    <button class="session-card ${state.selectedSessionId === session.id ? 'active' : ''}" type="button" data-session-id="${escapeHtml(session.id)}">
      <div class="session-avatar">H</div>
      <div class="session-body">
        <div class="item-title"><span>${escapeHtml(session.title || 'Untitled session')}</span><span class="pill">${escapeHtml(session.source || 'session')}</span></div>
        <div class="item-meta mono">${humanDate(session.ended_at || session.started_at)} · ${session.message_count ?? 0} msgs · ${session.tool_call_count ?? 0} tools</div>
      </div>
    </button>
  `).join('') : `<div class="empty">${state.sessionFilter ? 'No session titles match. Message matches can still be opened above.' : 'No sessions match this search.'}</div>`;
}

function topEntry(counts = {}) {
  return Object.entries(counts).sort((a, b) => b[1] - a[1])[0] || ['none', 0];
}

function renderSessionStats(payload = {}) {
  const container = $('#session-stats');
  if (!container) return;
  const sessions = payload.sessions || [];
  if (!sessions.length) {
    container.innerHTML = `<div class="empty">No recent Hermes sessions available yet.</div>`;
    return;
  }
  const sourceCounts = {};
  const modelCounts = {};
  let totalMessages = 0;
  let totalTools = 0;
  sessions.forEach((session) => {
    const source = session.source || 'unknown';
    const model = session.model || 'unknown';
    sourceCounts[source] = (sourceCounts[source] || 0) + 1;
    modelCounts[model] = (modelCounts[model] || 0) + 1;
    totalMessages += Number(session.message_count || 0);
    totalTools += Number(session.tool_call_count || 0);
  });
  const [topSource, topSourceCount] = topEntry(sourceCounts);
  const [topModel] = topEntry(modelCounts);
  container.innerHTML = `
    <article class="stat-mini"><span>${sessions.length}</span><small>recent sessions</small></article>
    <article class="stat-mini"><span>${escapeHtml(topSource)}</span><small>${topSourceCount} by source</small></article>
    <article class="stat-mini"><span>${totalTools}</span><small>tool calls</small></article>
    <article class="stat-mini"><span>${totalMessages}</span><small>messages observed</small></article>
    <article class="stat-mini wide"><span>${escapeHtml(topModel)}</span><small>dominant model</small></article>
  `;
}

function renderMessageSearchResults(payload = {}, query = '') {
  const container = $('#message-search-results');
  if (!container) return;
  const term = (query || payload.query || '').trim();
  if (term.length < 2) {
    container.innerHTML = `<div class="empty">Type at least two characters to search Hermes message contents with read-only FTS.</div>`;
    return;
  }
  if (payload.error) {
    container.innerHTML = `<div class="empty">Message search unavailable: ${escapeHtml(payload.error)}</div>`;
    return;
  }
  const results = payload.results || [];
  container.innerHTML = results.length ? `
    <div class="message-search-head mono">${results.length} message matches for “${escapeHtml(term)}”</div>
    <div class="message-result-grid">
      ${results.map((result) => `
        <button class="message-result" type="button" data-session-id="${escapeHtml(result.session_id)}" data-message-id="${escapeHtml(result.message_id)}" data-query="${escapeHtml(term)}">
          <div class="item-title"><span>${escapeHtml(result.title || 'Untitled session')}</span><span class="pill">${escapeHtml(result.role || 'message')}</span></div>
          <div class="item-desc">${highlightHtml(result.snippet || '', term)}</div>
          <div class="item-meta mono">${humanDate(result.timestamp)} · ${escapeHtml(result.source || 'session')} · msg ${escapeHtml(result.message_id)}</div>
        </button>
      `).join('')}
    </div>
  ` : `<div class="empty">No message matches for “${escapeHtml(term)}”.</div>`;
}

function renderConfig(payload = {}) {
  const summary = $('#config-summary');
  const text = $('#config-text');
  if (!summary || !text) return;
  if (!payload.exists) {
    summary.innerHTML = `<div class="empty">Hermes config not found at ${escapeHtml(payload.path || 'unknown path')}.</div>`;
    text.textContent = '';
    return;
  }
  if (payload.error) {
    summary.innerHTML = `<div class="empty">Could not load Hermes config: ${escapeHtml(payload.error)}</div>`;
    text.textContent = '';
    return;
  }
  const rows = Object.entries(payload.summary || {});
  summary.innerHTML = `
    <article class="item"><div class="item-title"><span>Config file</span><span class="pill">${escapeHtml(payload.size || 'n/a')}</span></div><div class="item-desc mono">${escapeHtml(payload.path || '')}</div><div class="item-meta mono">Modified ${humanDate(payload.modified_at)}</div></article>
    ${rows.length ? rows.map(([key, value]) => `
      <article class="item"><div class="item-title"><span>${escapeHtml(key.replaceAll('_', ' '))}</span><span class="pill">config</span></div><div class="item-desc mono">${escapeHtml(value)}</div></article>
    `).join('') : `<div class="empty">No simple model/provider summary fields found. Use the masked config below.</div>`}
  `;
  text.textContent = payload.masked_config || '# Empty masked config';
}

function renderSessionDetail(payload = null, context = {}) {
  const detail = $('#session-detail');
  if (!detail) return;
  if (!payload) {
    detail.innerHTML = `<div class="empty">Select a session to read the conversation.</div>`;
    return;
  }

  const session = payload.session || {};
  const messages = payload.messages || [];
  const windowInfo = payload.message_window || {};
  const targetId = Number(context.messageId || windowInfo.target_message_id || 0);
  const query = context.query || '';
  const totalVisible = windowInfo.total_visible ?? messages.length;
  const visibleLabel = windowInfo.truncated ? `${messages.length} of ${totalVisible} visible messages` : `${messages.length} visible messages`;
  detail.innerHTML = `
    <div class="session-detail-head">
      <div>
        <div class="eyebrow">Session Detail</div>
        <h3>${escapeHtml(session.title || 'Untitled session')}</h3>
        <div class="item-meta mono">${humanDate(session.ended_at || session.started_at)} · ${escapeHtml(visibleLabel)} · ${session.model ? escapeHtml(session.model) : 'model n/a'}</div>
      </div>
      <span class="pill">read-only</span>
    </div>
    ${windowInfo.truncated ? `<div class="conversation-window-note mono">${windowInfo.mode === 'around_target' ? 'Showing a focused window around the selected search match.' : 'Showing the first conversation window.'} ${escapeHtml(visibleLabel)}.</div>` : ''}
    <div class="message-list">
      ${messages.length ? messages.map((message) => {
        const isTarget = targetId && Number(message.id) === targetId;
        return `
          <article id="message-${escapeHtml(message.id)}" class="message-card ${escapeHtml(message.role)} ${isTarget ? 'target-message' : ''}" data-message-id="${escapeHtml(message.id)}">
            <div class="message-meta mono">${escapeHtml(message.role)} · msg ${escapeHtml(message.id)} · ${humanDate(message.timestamp)}</div>
            <div class="message-content">${query ? highlightHtml(message.content || '', query) : escapeHtml(message.content || '')}</div>
          </article>
        `;
      }).join('') : `<div class="empty">No user/assistant messages found for this session.</div>`}
    </div>
  `;
}

function scrollDetailToMessage(messageId) {
  const scroller = $('#session-detail');
  const target = document.getElementById(`message-${String(messageId)}`);
  if (!scroller || !target) return;
  const scrollerRect = scroller.getBoundingClientRect();
  const targetRect = target.getBoundingClientRect();
  const offset = targetRect.top - scrollerRect.top - scroller.clientHeight * 0.28;
  scroller.scrollTo({ top: scroller.scrollTop + offset, behavior: 'smooth' });
}

async function loadSessionDetail(sessionId, options = {}) {
  state.selectedSessionId = sessionId;
  renderSessions({ sessions: state.sessions });
  const detail = $('#session-detail');
  if (detail) detail.innerHTML = `<div class="empty">Loading session conversation…</div>`;
  try {
    renderSessionDetail(await fetchSessionDetail(sessionId, options.messageId), options);
    if (options.messageId) {
      requestAnimationFrame(() => scrollDetailToMessage(options.messageId));
    }
  } catch (err) {
    console.error(err);
    if (detail) detail.innerHTML = `<div class="empty">Could not load session: ${escapeHtml(err.message)}</div>`;
  }
}

function renderAgentPulse(payload = {}) {
  const sessions = payload.sessions || [];
  const recentCount = sessions.length;
  const latest = sessions[0];
  $('#agent-pulse-pill').textContent = `${recentCount} sessions`;
  $('#agent-pulse').innerHTML = `
    <div class="agent-orb"><span>${recentCount}</span><small>recent</small></div>
    <div>
      <div class="item-title"><span>Hermes session pulse</span></div>
      <div class="item-desc">Recent read-only Hermes activity from state.db. Live agent heartbeat tracking can be added later when there is real roster data.</div>
      <div class="item-meta mono">Latest: ${latest ? `${escapeHtml(latest.title || 'Untitled')} · ${humanDate(latest.ended_at || latest.started_at)}` : 'No session data yet'}</div>
    </div>
  `;
}

function renderNotes(payload = {}) {
  const notes = payload.notes || [];
  $('#notes-list').innerHTML = notes.length ? notes.map((note) => `
    <article class="note-card">
      <div class="item-title"><span>${escapeHtml(note.title || note.name)}</span></div>
      <div class="item-desc">${escapeHtml(note.excerpt || '')}</div>
      <div class="item-meta mono">${note.exists ? `${escapeHtml(note.size || '')} · ${humanDate(note.modified_at)}` : 'Missing from vault'}</div>
    </article>
  `).join('') : `<div class="empty">No Obsidian project notes found.</div>`;
}

function renderHealth(payload = {}) {
  const dot = $('#health-dot');
  const label = $('#health-label');
  dot.className = 'dot healthy';
  label.textContent = `Healthy · DB ${payload.state_db_size || 'n/a'} · E: ${payload.disk?.['E:/']?.free || 'n/a'} free`;
}

async function refresh() {
  if (state.isRefreshing) {
    state.needsRefresh = true;
    return;
  }
  state.isRefreshing = true;

  const activeView = state.activeView || 'today';
  const requests = {
    overview: api(endpoints.overview),
    tasks: api(endpoints.tasks),
    attention: api(endpoints.attention),
    calendar: api(endpoints.calendar),
    sessions: api(endpoints.sessions),
    health: api(endpoints.health),
  };

  if (activeView === 'projects') requests.projects = api(endpoints.projects);
  if (activeView === 'agents') requests.crons = api(endpoints.crons);
  if (activeView === 'notes') requests.notes = api(endpoints.notes);
  if (activeView === 'settings') requests.config = api(endpoints.config);

  try {
    const entries = await Promise.all(Object.entries(requests).map(async ([key, promise]) => [key, await promise]));
    const data = Object.fromEntries(entries);

    renderCards(data.overview.cards);
    if (data.projects) renderProjects(data.projects.projects);
    renderTaskList(data.tasks.tasks);
    renderFocusTasks(data.tasks.tasks);
    renderAttention(data.attention.attention);
    renderCalendar(data.calendar);
    if (data.crons) renderCrons(data.crons);
    renderSessions(data.sessions);
    renderSessionStats(data.sessions);
    renderAgentPulse(data.sessions);
    if (data.notes) renderNotes(data.notes);
    if (data.config) renderConfig(data.config);
    renderHealth(data.health);
    state.hasBootstrapped = true;
    $('#last-updated').textContent = fmt.format(new Date());
  } catch (err) {
    console.error(err);
    $('#health-dot').className = 'dot degraded';
    $('#health-label').textContent = `Error: ${err.message}`;
  } finally {
    state.isRefreshing = false;
    if (state.needsRefresh) {
      state.needsRefresh = false;
      refresh();
    }
  }
}

function queueMessageSearch(query) {
  const term = (query || '').trim();
  clearTimeout(state.messageSearchTimer);
  if (term.length < 2) {
    renderMessageSearchResults({}, term);
    return;
  }
  const container = $('#message-search-results');
  if (container) container.innerHTML = `<div class="empty">Searching Hermes messages for “${escapeHtml(term)}”…</div>`;
  state.messageSearchTimer = setTimeout(async () => {
    try {
      renderMessageSearchResults(await searchMessages(term), term);
    } catch (err) {
      console.error(err);
      renderMessageSearchResults({ error: err.message }, term);
    }
  }, 250);
}

$('#refresh-rate').textContent = `${REFRESH_MS / 1000}s`;

$$('.nav-item').forEach((button) => {
  button.addEventListener('click', () => {
    void setView(button.dataset.view);
  });
});

$('#overview-cards').addEventListener('click', (event) => {
  const card = event.target.closest('.metric-card-button');
  if (!card) return;
  void jumpToDashboardSection(card.dataset.jumpView, card.dataset.jumpTarget);
});

const globalSearch = $('#global-search');
if (globalSearch) {
  globalSearch.addEventListener('input', (event) => {
    const query = event.target.value.trim();
    state.sessionFilter = query;
    state.taskFilter = query;
    const sessionSearch = $('#session-search');
    if (sessionSearch && sessionSearch.value !== event.target.value) sessionSearch.value = event.target.value;
    renderSessions({ sessions: state.sessions });
    renderTaskList(state.tasks);
    if (query) {
      const taskHits = state.tasks.filter((task) => taskMatches(task, query));
      setView(taskHits.length ? 'projects' : 'agents');
      if (!taskHits.length) queueMessageSearch(query);
    } else {
      renderMessageSearchResults({}, '');
    }
  });
}

const sessionSearch = $('#session-search');
if (sessionSearch) {
  sessionSearch.addEventListener('input', (event) => {
    state.sessionFilter = event.target.value.trim();
    renderSessions({ sessions: state.sessions });
    queueMessageSearch(state.sessionFilter);
  });
}

$('#session-list').addEventListener('click', (event) => {
  const card = event.target.closest('.session-card');
  if (!card) return;
  const sessionId = card.dataset.sessionId;
  if (sessionId) loadSessionDetail(sessionId);
});

$('#message-search-results').addEventListener('click', (event) => {
  const result = event.target.closest('.message-result');
  if (!result) return;
  const sessionId = result.dataset.sessionId;
  if (sessionId) loadSessionDetail(sessionId, { messageId: result.dataset.messageId, query: result.dataset.query || state.sessionFilter });
});

$('#attention-list').addEventListener('click', async (event) => {
  const button = event.target.closest('.resolve-attention');
  if (!button) return;

  const id = button.dataset.attentionId;
  if (!id) return;

  button.disabled = true;
  button.textContent = 'Resolving…';
  try {
    await resolveAttentionItem(id);
    await refresh();
  } catch (err) {
    console.error(err);
    button.disabled = false;
    button.textContent = 'Resolve';
    $('#health-dot').className = 'dot degraded';
    $('#health-label').textContent = `Resolve failed: ${err.message}`;
  }
});

setView('today');
refresh();
setInterval(refresh, REFRESH_MS);
