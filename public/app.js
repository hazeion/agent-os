const REFRESH_MS = 30_000;
const $ = (selector) => document.querySelector(selector);
const fmt = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' });

const endpoints = {
  overview: '/api/overview',
  projects: '/api/projects',
  tasks: '/api/tasks',
  attention: '/api/attention',
  calendar: '/api/calendar',
  crons: '/api/hermes/crons',
  sessions: '/api/hermes/sessions',
  notes: '/api/obsidian-notes',
  health: '/api/health',
};

function escapeHtml(value = '') {
  return String(value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

async function api(path, options = {}) {
  const res = await fetch(path, { cache: 'no-store', ...options });
  if (!res.ok) throw new Error(`${path} returned ${res.status}`);
  return res.json();
}

async function resolveAttentionItem(id) {
  return api(`/api/attention/${encodeURIComponent(id)}/resolve`, { method: 'POST' });
}

function humanDate(value) {
  if (!value) return '—';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return String(value);
  return fmt.format(d);
}

function renderCards(cards = {}) {
  const defs = [
    ['needs_attention', 'Needs Attention', 'open review / blocker items'],
    ['active_tasks', 'Active Tasks', 'todo, working, waiting'],
    ['completed_this_week', 'Completed', 'tasks completed this week'],
    ['scheduled_crons', 'Crons', 'scheduled Hermes jobs'],
    ['recent_sessions', 'Sessions', 'latest Hermes sessions'],
    ['active_projects', 'Projects', 'active portfolio items'],
  ];
  $('#overview-cards').innerHTML = defs.map(([key, label, sub]) => `
    <article class="card">
      <div class="eyebrow">${escapeHtml(label)}</div>
      <div class="value">${cards[key] ?? 0}</div>
      <div class="label">${escapeHtml(sub)}</div>
    </article>
  `).join('');
}

function renderAttention(items = []) {
  const open = items.filter((item) => item.status !== 'resolved');
  $('#attention-count').textContent = `${open.length} open`;
  $('#attention-list').innerHTML = open.length ? open.map((item) => `
    <article class="item attention-item">
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
  `).join('') : `<div class="empty">No open attention items. Clear skies.</div>`;
}

function groupTasks(tasks = []) {
  return {
    'Backlog / To Do': tasks.filter((t) => t.status === 'todo'),
    'In Progress': tasks.filter((t) => t.status === 'in_progress'),
    'Waiting / Needs Attention': tasks.filter((t) => ['waiting', 'needs_attention'].includes(t.status) || t.needs_attention || t.review_required),
    'Completed This Week': tasks.filter((t) => t.status === 'completed'),
  };
}

function renderTaskGroups(tasks = []) {
  const grouped = groupTasks(tasks);
  $('#task-groups').innerHTML = Object.entries(grouped).map(([group, groupTasks]) => `
    <section class="task-group">
      <h3>${escapeHtml(group)} · ${groupTasks.length}</h3>
      ${groupTasks.length ? groupTasks.map((task) => `
        <article class="task-card">
          <div class="item-title"><span>${escapeHtml(task.title)}</span><span class="pill">${escapeHtml(task.priority || 'normal')}</span></div>
          <div class="item-desc">${escapeHtml(task.description || '')}</div>
          <div class="item-meta mono">${escapeHtml(task.assignee || 'unassigned')} · ${escapeHtml(task.source || 'manual')} · due ${escapeHtml(task.due_date || 'none')}</div>
          <div class="tag-row">${(task.tags || []).map((tag) => `<span class="tag">#${escapeHtml(tag)}</span>`).join('')}</div>
        </article>
      `).join('') : `<div class="empty">No tasks here yet.</div>`}
    </section>
  `).join('');

  const completed = tasks.filter((t) => t.status === 'completed');
  $('#completed-list').innerHTML = completed.length ? `
    <article class="item">
      <div class="item-title"><span>Completed tasks</span><span class="pill success">${completed.length}</span></div>
      <div class="item-meta">${completed.map((t) => escapeHtml(t.title)).join(' · ')}</div>
    </article>
    <article class="item">
      <div class="item-title"><span>Completed cron runs</span><span class="pill">0</span></div>
      <div class="item-meta">No cron jobs are configured yet.</div>
    </article>
    <article class="item">
      <div class="item-title"><span>Agent/session outputs</span><span class="pill">read-only</span></div>
      <div class="item-meta">See Recent Sessions for latest Hermes work.</div>
    </article>
  ` : `<div class="empty">No completed task data yet.</div>`;
}

function renderProjects(projects = []) {
  $('#project-list').innerHTML = projects.length ? projects.map((project) => `
    <article class="project-card">
      <div class="item-title"><span>${escapeHtml(project.name)}</span><span class="pill success">${escapeHtml(project.status)}</span></div>
      <div class="item-desc">${escapeHtml(project.description || '')}</div>
      <div class="item-meta mono">${escapeHtml(project.type)} · [[${escapeHtml(project.obsidian_note || 'No note')}]]</div>
    </article>
  `).join('') : `<div class="empty">No projects found.</div>`;
}

function renderCalendar(items = []) {
  $('#calendar-list').innerHTML = items.length ? items.map((item) => `
    <article class="item">
      <div class="item-title"><span>${escapeHtml(item.title)}</span><span class="pill">${escapeHtml(item.type || 'event')}</span></div>
      <div class="item-desc">${escapeHtml(item.description || '')}</div>
      <div class="item-meta mono">${humanDate(item.start)} → ${humanDate(item.end)}</div>
    </article>
  `).join('') : `<div class="empty">No local calendar items yet.</div>`;
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

function renderSessions(payload = {}) {
  const sessions = payload.sessions || [];
  $('#session-list').innerHTML = sessions.length ? sessions.map((session) => `
    <article class="item">
      <div class="item-title"><span>${escapeHtml(session.title)}</span><span class="pill">${escapeHtml(session.source || 'session')}</span></div>
      <div class="item-meta mono">${humanDate(session.ended_at || session.started_at)} · ${session.message_count ?? 0} msgs · ${session.tool_call_count ?? 0} tools</div>
    </article>
  `).join('') : `<div class="empty">No recent Hermes sessions available.</div>`;
}

function renderNotes(payload = {}) {
  const notes = payload.notes || [];
  $('#notes-list').innerHTML = notes.length ? notes.map((note) => `
    <article class="item">
      <div class="item-title"><span>${escapeHtml(note.title || note.name)}</span><span class="pill ${note.exists ? '' : 'warn'}">${note.exists ? 'found' : 'missing'}</span></div>
      <div class="item-desc">${escapeHtml(note.excerpt || '')}</div>
      <div class="item-meta mono">${escapeHtml(note.size || '')} · ${humanDate(note.modified_at)}</div>
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
  try {
    const [overview, projects, tasks, attention, calendar, crons, sessions, notes, health] = await Promise.all([
      api(endpoints.overview),
      api(endpoints.projects),
      api(endpoints.tasks),
      api(endpoints.attention),
      api(endpoints.calendar),
      api(endpoints.crons),
      api(endpoints.sessions),
      api(endpoints.notes),
      api(endpoints.health),
    ]);

    renderCards(overview.cards);
    renderProjects(projects.projects);
    renderTaskGroups(tasks.tasks);
    renderAttention(attention.attention);
    renderCalendar(calendar.items);
    renderCrons(crons);
    renderSessions(sessions);
    renderNotes(notes);
    renderHealth(health);
    $('#last-updated').textContent = fmt.format(new Date());
  } catch (err) {
    console.error(err);
    $('#health-dot').className = 'dot degraded';
    $('#health-label').textContent = `Error: ${err.message}`;
  }
}

$('#refresh-rate').textContent = `${REFRESH_MS / 1000}s`;
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
refresh();
setInterval(refresh, REFRESH_MS);
