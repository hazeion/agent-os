function humanDate(value) {
  if (!value) return '—';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return String(value);
  return fmt.format(d);
}

function humanDurationApprox(totalSeconds) {
  const seconds = Number(totalSeconds);
  if (!Number.isFinite(seconds) || seconds < 0) return 'unknown';
  if (seconds < 60) return `${Math.max(1, Math.round(seconds))}s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
  return `${Math.round(seconds / 3600)}h`;
}

function humanNumber(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return '0';
  return Math.round(number).toLocaleString();
}

function humanCost(value) {
  if (value === null || value === undefined || value === '') return '';
  const number = Number(value);
  if (!Number.isFinite(number)) return '';
  return `$${number.toFixed(number > 0 && number < 0.01 ? 4 : 2)} est.`;
}

const THEME_STORAGE_KEY = 'mentat-theme';
const THEMES = [
  { id: 'compact-dark', label: 'Compact Dark', pill: 'compact dark' },
  { id: 'light', label: 'Light', pill: 'light' },
  { id: 'catppuccin', label: 'Catppuccin', pill: 'catppuccin' },
  { id: 'nord', label: 'Nord', pill: 'nord' },
  { id: 'aurora', label: 'Aurora', pill: 'aurora' },
];

function themeById(themeId = '') {
  return THEMES.find((theme) => theme.id === themeId) || THEMES[0];
}

function applyTheme(themeId = state.currentTheme || THEMES[0].id) {
  const theme = themeById(themeId);
  state.currentTheme = theme.id;
  document.documentElement.dataset.theme = theme.id;
  const activePill = $('#theme-active-pill');
  if (activePill) activePill.textContent = theme.pill;
  const select = $('#theme-select');
  if (select && select.value !== theme.id) select.value = theme.id;
  const preview = $('#theme-preview-grid');
  if (preview) {
    preview.innerHTML = THEMES.map((item) => `
      <button class="theme-swatch ${item.id === theme.id ? 'active' : ''}" type="button" data-theme-choice="${escapeHtml(item.id)}" aria-pressed="${item.id === theme.id ? 'true' : 'false'}">
        <span class="theme-swatch-chip theme-${escapeHtml(item.id)}" aria-hidden="true"></span>
        <span>${escapeHtml(item.label)}</span>
      </button>
    `).join('');
  }
  if (typeof localStorage !== 'undefined') {
    try {
      localStorage.setItem(THEME_STORAGE_KEY, theme.id);
    } catch {}
  }
}

function initializeTheme() {
  let saved = '';
  if (typeof localStorage !== 'undefined') {
    try {
      saved = localStorage.getItem(THEME_STORAGE_KEY) || '';
    } catch {}
  }
  applyTheme(saved || document.documentElement.dataset.theme || THEMES[0].id);
}

function renderGreeting(identity = {}) {
  state.appName = (identity.app_name || state.appName || 'Mentat').trim();
  state.greetingName = (identity.display_name || state.greetingName || 'Operator').trim();
  state.greetingPrefix = (identity.greeting_prefix || state.greetingPrefix || 'Hello').trim();
  const title = `${state.greetingPrefix} ${state.greetingName}`.trim();
  const brand = document.querySelector('#brand-name');
  const hero = document.querySelector('.hero-title');
  if (brand) brand.textContent = state.appName;
  document.title = `${state.appName} · Mission Control`;
  if (!hero) return;
  hero.textContent = title;
  hero.dataset.text = title;
  hero.setAttribute('aria-label', title);
}

function setView(view, { refreshOnChange = true } = {}) {
  const viewChanged = state.activeView !== view;
  state.activeView = view;
  $$('.nav-item').forEach((item) => item.classList.toggle('active', item.dataset.view === view));
  $$('[data-view-panel]').forEach((panel) => panel.classList.toggle('active', panel.dataset.viewPanel === view));
  if (view !== 'today') scheduleAgentConsolePoll(false);
  if (state.hasBootstrapped && viewChanged && refreshOnChange) return refresh();
  return Promise.resolve();
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function stablePayloadHash(value) {
  const normalize = (item) => {
    if (Array.isArray(item)) return item.map(normalize);
    if (item && typeof item === 'object') {
      return Object.keys(item).sort().reduce((acc, key) => {
        acc[key] = normalize(item[key]);
        return acc;
      }, {});
    }
    return item;
  };
  return JSON.stringify(normalize(value));
}

function renderIfChanged(key, payload, renderFn) {
  const hash = stablePayloadHash(payload);
  if (state.renderCache[key] === hash) return false;
  state.renderCache[key] = hash;
  renderFn(payload);
  return true;
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

function renderProjectScopedViews() {
  renderTaskList(state.tasks);
  renderFocusTasks(state.tasks);
  renderProjects(state.projects);
}

function renderCards(cards = {}) {
  const defs = [
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

function hasAttentionTag(task = {}) {
  const tags = Array.isArray(task.tags) ? task.tags : [];
  return tags.some((tag) => normalizeFilterValue(tag).replaceAll('_', ' ') === 'needs attention');
}

function taskArea(task = {}) {
  const status = normalizeFilterValue(task.status).replaceAll('_', ' ');
  if (status === 'completed') return 'completed';
  if (status === 'in progress') return 'in progress';
  if (status === 'waiting') return 'waiting';
  if (status === 'needs attention' || task.needs_attention || task.review_required || hasAttentionTag(task)) return 'needs attention';
  return 'todo';
}

function taskTone(area) {
  if (area === 'completed') return 'success';
  if (area === 'needs attention') return 'danger';
  if (area === 'waiting' || area === 'todo') return 'warn';
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

function taskProject(task = {}) {
  return task.project || 'General';
}

function normalizeFilterValue(value = '') {
  return String(value).trim().toLowerCase();
}

function taskMatchesProject(task = {}) {
  if (!state.projectFilter) return true;
  const selected = normalizeFilterValue(state.projectFilter);
  const project = normalizeFilterValue(taskProject(task));
  const tags = Array.isArray(task.tags) ? task.tags.map(normalizeFilterValue) : [];
  return project === selected || tags.includes(selected);
}

function isOpenTask(task = {}) {
  return taskArea(task) !== 'completed';
}

function taskMatchesStatus(task = {}) {
  if (state.taskStatusFilter === 'all') return true;
  if (state.taskStatusFilter === 'open') return isOpenTask(task);
  return taskArea(task) === state.taskStatusFilter;
}

function visibleTasks(tasks = []) {
  return tasks
    .filter(taskMatchesProject)
    .filter(taskMatchesStatus)
    .filter((task) => taskMatches(task, state.taskFilter));
}

function projectFilteredTasks(tasks = []) {
  return tasks.filter(taskMatchesProject);
}

function completedTimeLabel(task = {}) {
  return task.completed_at ? `Completed ${humanDate(task.completed_at)}` : 'Completed time unknown';
}

function taskId(task = {}, index = 0) {
  return String(task.id || `${normalizeFilterValue(task.title || 'task').replaceAll(' ', '-')}-${index}`);
}

function taskNextMoveLabel(task = {}, area = taskArea(task)) {
  if (area === 'completed') return 'Review completion history or reopen only if needed.';
  if (area === 'needs attention') return 'Resolve the blocker or review-required item first.';
  if (area === 'in progress') return 'Continue the active work and update status when done.';
  if (area === 'waiting') return 'Identify the dependency or decision needed to unblock it.';
  return 'Ready to start or schedule as the next focused work item.';
}

function taskDueDate(task = {}) {
  if (!task.due_date) return null;
  const raw = String(task.due_date);
  const date = new Date(/^\d{4}-\d{2}-\d{2}$/.test(raw) ? `${raw}T00:00:00` : raw);
  return Number.isNaN(date.getTime()) ? null : date;
}

function isDueTask(task = {}) {
  return taskArea(task) !== 'completed' && Boolean(taskDueDate(task));
}

function focusTaskIndicator(task = {}) {
  const area = taskArea(task);
  if (area === 'completed') return { key: 'completed', label: 'Completed' };
  if (area === 'needs attention') return { key: 'attention', label: 'Needs attention' };
  if (isDueTask(task)) return { key: 'due', label: 'Due' };
  if (area === 'in progress') return { key: 'progress', label: 'In progress' };
  return { key: 'open', label: 'Open' };
}

function projectOptionsFromTasks(tasks = []) {
  const names = new Set(state.projects.map((project) => project.name).filter(Boolean));
  tasks.forEach((task) => names.add(taskProject(task)));
  return Array.from(names).sort((a, b) => a.localeCompare(b));
}

function selectedTaskFrom(tasks = []) {
  if (!tasks.length) return null;
  let selected = tasks.find((task, index) => taskId(task, index) === state.selectedTaskId);
  if (!selected) {
    selected = tasks[0];
    state.selectedTaskId = taskId(selected, 0);
  }
  return selected;
}

function taskEditorSeedTask(tasks = visibleTasks(state.tasks)) {
  const draft = state.taskEditorDraft;
  if (state.taskEditorMode === 'edit') {
    const selected = state.tasks.find((task) => String(task.id || '') === state.taskEditorTaskId) || selectedTaskFrom(tasks) || {};
    return draft ? { ...selected, ...draft } : selected;
  }
  const base = {
    project: state.projectFilter || state.projects[0]?.name || '',
    status: 'todo',
    priority: 'medium',
    assignee: '',
    due_date: '',
    tags: [],
    title: '',
    description: '',
    review_required: false,
    needs_attention: false,
  };
  return draft ? { ...base, ...draft } : base;
}

function parseTaskTagsInput(value = '') {
  return String(value)
    .split(',')
    .map((part) => part.trim())
    .filter(Boolean);
}

function openTaskEditor(mode = 'create', task = selectedTaskFrom(visibleTasks(state.tasks))) {
  state.taskEditorMode = mode;
  state.taskEditorTaskId = mode === 'edit' && task?.id ? String(task.id) : '';
  state.taskEditorDraft = null;
  renderTaskList(state.tasks);

  const detailPanel = $('#selected-task-panel');
  if (state.activeView !== 'projects') {
    void setView('projects', { refreshOnChange: false });
  }
  if (window.matchMedia('(max-width: 1120px)').matches) {
    detailPanel?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  } else {
    flashTarget(detailPanel);
  }
}

function closeTaskEditor() {
  state.taskEditorMode = 'view';
  state.taskEditorTaskId = '';
  state.taskEditorDraft = null;
  renderTaskList(state.tasks);
}

function syncTaskEditorControls(tasks = visibleTasks(state.tasks)) {
  const editButton = $('#selected-task-edit');
  const cancelButton = $('#selected-task-cancel');
  const editorActive = state.taskEditorMode === 'create' || state.taskEditorMode === 'edit';
  const selected = selectedTaskFrom(tasks);
  if (editButton) {
    editButton.hidden = editorActive;
    editButton.disabled = !selected;
  }
  if (cancelButton) cancelButton.hidden = !editorActive;
}

function taskPayloadFromForm(form) {
  const formData = new FormData(form);
  return {
    title: String(formData.get('title') || '').trim(),
    description: String(formData.get('description') || '').trim(),
    project: String(formData.get('project') || '').trim(),
    status: String(formData.get('status') || 'todo').trim(),
    priority: String(formData.get('priority') || 'medium').trim(),
    assignee: String(formData.get('assignee') || '').trim(),
    due_date: String(formData.get('due_date') || '').trim(),
    tags: parseTaskTagsInput(formData.get('tags') || ''),
    review_required: formData.get('review_required') === 'on',
    needs_attention: formData.get('needs_attention') === 'on',
  };
}

async function submitTaskEditorForm(form) {
  const mode = form.dataset.mode || 'create';
  const payload = taskPayloadFromForm(form);
  const submitButton = form.querySelector('[type="submit"]');
  const status = $('#task-editor-status');
  if (submitButton) submitButton.disabled = true;
  if (status) status.textContent = mode === 'edit' ? 'Saving task…' : 'Creating task…';
  try {
    const response = mode === 'edit'
      ? await saveTaskEdits(form.dataset.taskId || '', payload)
      : await createTask(payload);
    state.projectFilter = response.task?.project || state.projectFilter;
    state.selectedTaskId = response.task?.id || state.selectedTaskId;
    state.taskEditorMode = 'view';
    state.taskEditorTaskId = '';
    await refresh();
    renderProjectScopedViews();
    flashTarget($('#selected-task-panel'));
  } catch (err) {
    console.error(err);
    if (submitButton) submitButton.disabled = false;
    if (status) status.textContent = err.message;
    $('#health-dot').className = 'dot degraded';
    $('#health-label').textContent = `Task save failed: ${err.message}`;
  }
}

function renderSelectedTaskInspector(tasks = visibleTasks(state.tasks)) {
  const container = $('#selected-task-detail');
  if (!container) return;

  const editorActive = state.taskEditorMode === 'create' || state.taskEditorMode === 'edit';
  if (editorActive) {
    const draft = taskEditorSeedTask(tasks);
    const mode = state.taskEditorMode;
    const projects = state.projects.length ? state.projects : [{ name: draft?.project || state.projectFilter || 'General' }];
    const projectOptions = projects.map((project) => {
      const name = project.name || 'General';
      const selectedProject = name === (draft?.project || '');
      return `<option value="${escapeHtml(name)}" ${selectedProject ? 'selected' : ''}>${escapeHtml(name)}</option>`;
    }).join('');
    const statusOptions = ['todo', 'in progress', 'waiting', 'needs attention', 'completed']
      .map((value) => `<option value="${escapeHtml(value)}" ${value === (draft?.status || 'todo') ? 'selected' : ''}>${escapeHtml(taskStatusLabels[value] || value)}</option>`)
      .join('');
    const priorityOptions = ['high', 'medium', 'low']
      .map((value) => `<option value="${escapeHtml(value)}" ${value === (draft?.priority || 'medium') ? 'selected' : ''}>${escapeHtml(value)}</option>`)
      .join('');
    container.innerHTML = `
      <form id="task-editor-form" class="task-detail-card task-editor-form" data-mode="${escapeHtml(mode)}" data-task-id="${escapeHtml(String(draft?.id || ''))}">
        <div class="task-detail-kicker mono">${mode === 'edit' ? 'task edit' : 'new task'} · project-owned write-back</div>
        <h3>${mode === 'edit' ? 'Edit task details' : 'Create a new task'}</h3>
        <div class="task-editor-grid">
          <label class="task-editor-field field-span-2">
            <span class="task-editor-label mono">Title</span>
            <input name="title" type="text" maxlength="160" required value="${escapeHtml(draft?.title || '')}" placeholder="What needs to happen?" />
          </label>
          <label class="task-editor-field field-span-2">
            <span class="task-editor-label mono">Description</span>
            <textarea name="description" rows="5" placeholder="Add the task context, outcome, or next move.">${escapeHtml(draft?.description || '')}</textarea>
          </label>
          <label class="task-editor-field">
            <span class="task-editor-label mono">Project</span>
            <select name="project" required>${projectOptions}</select>
          </label>
          <label class="task-editor-field">
            <span class="task-editor-label mono">Status</span>
            <select name="status">${statusOptions}</select>
          </label>
          <label class="task-editor-field">
            <span class="task-editor-label mono">Priority</span>
            <select name="priority">${priorityOptions}</select>
          </label>
          <label class="task-editor-field">
            <span class="task-editor-label mono">Due date</span>
            <input name="due_date" type="date" value="${escapeHtml(draft?.due_date || '')}" />
          </label>
          <label class="task-editor-field field-span-2">
            <span class="task-editor-label mono">Assignee</span>
            <input name="assignee" type="text" maxlength="120" value="${escapeHtml(draft?.assignee || '')}" placeholder="Operator, Hermes, or another owner" />
          </label>
          <label class="task-editor-field field-span-2">
            <span class="task-editor-label mono">Tags</span>
            <input name="tags" type="text" value="${escapeHtml(Array.isArray(draft?.tags) ? draft.tags.join(', ') : '')}" placeholder="phase-3, write-back" />
          </label>
          <label class="task-editor-toggle">
            <input name="review_required" type="checkbox" ${draft?.review_required ? 'checked' : ''} />
            <span>Review required</span>
          </label>
          <label class="task-editor-toggle">
            <input name="needs_attention" type="checkbox" ${draft?.needs_attention ? 'checked' : ''} />
            <span>Needs attention</span>
          </label>
        </div>
        <div class="task-editor-actions">
          <button class="action-button" type="submit">${mode === 'edit' ? 'Save Changes' : 'Create Task'}</button>
          <button class="mini-button" type="button" data-task-editor-cancel>Cancel</button>
        </div>
        <div class="task-editor-status mono" id="task-editor-status">Mentat writes only to project-owned task data and never mutates Hermes core files.</div>
      </form>
    `;
    syncTaskEditorControls(tasks);
    return;
  }

  const selected = selectedTaskFrom(tasks);
  if (!selected) {
    container.innerHTML = `<div class="empty">No tasks match ${escapeHtml(filterSummary())}. Adjust the project, status, or search filter to inspect a task.</div>`;
    syncTaskEditorControls(tasks);
    return;
  }

  const area = taskArea(selected);
  const statusLabel = taskStatusLabels[area] || area;
  const tags = Array.isArray(selected.tags) ? selected.tags : [];
  const updated = selected.updated_at || selected.created_at || selected.completed_at;
  const updatedLabel = updated ? `updated ${humanDate(updated)}` : 'no update timestamp';
  container.innerHTML = `
    <article class="task-detail-card">
      <div class="task-detail-kicker mono">${escapeHtml(selected.project || 'General')} · ${escapeHtml(selected.priority || 'priority n/a')}</div>
      <h3>${escapeHtml(selected.title || 'Untitled task')}</h3>
      <div class="task-detail-text">${escapeHtml(selected.description || 'No description yet.')}</div>
      <div class="task-detail-meta-row mono">
        <span>${escapeHtml(statusLabel)}</span>
        <span>due ${escapeHtml(selected.due_date || 'none')}</span>
        <span>${escapeHtml(selected.assignee || 'unassigned')}</span>
      </div>
      <div class="task-next-inline">
        <span class="mono">Next</span>
        <strong>${escapeHtml(taskNextMoveLabel(selected, area))}</strong>
      </div>
      <div class="task-detail-footer mono">${escapeHtml(updatedLabel)}${selected.source ? ` · ${escapeHtml(selected.source)}` : ''}${tags.length ? ` · tags: ${escapeHtml(tags.join(' · '))}` : ''}</div>
    </article>
  `;
  syncTaskEditorControls(tasks);
}

function filterSummary() {
  const parts = [];
  if (state.projectFilter) parts.push(state.projectFilter);
  if (state.taskStatusFilter === 'open') parts.push('open tasks');
  else if (state.taskStatusFilter !== 'all') parts.push(state.taskStatusFilter);
  if (state.taskFilter) parts.push(`search: ${state.taskFilter}`);
  return parts.length ? parts.join(' · ') : 'all tasks';
}

function syncTaskStatusControl() {
  const value = state.taskStatusFilter || 'open';
  const select = $('#task-status-filter');

  if (select && select.value !== value) select.value = value;
}

function applyTaskStatusFilter(value = 'open') {
  state.taskStatusFilter = taskStatusLabels[value] ? value : 'open';
  syncTaskStatusControl();
  renderTaskList(state.tasks);
}

function scrollProjectRail(direction = 1) {
  const rail = $('#project-list');
  if (!rail) return;
  const distance = Math.max(280, Math.round(rail.clientWidth * 0.72));
  rail.scrollBy({ left: direction * distance, behavior: 'smooth' });
  window.setTimeout(updateProjectRailButtons, 260);
}

function updateProjectRailButtons() {
  const rail = $('#project-list');
  const left = $('#project-scroll-left');
  const right = $('#project-scroll-right');
  if (!rail || !left || !right) return;

  const items = Array.from(rail.children);
  const style = window.getComputedStyle(rail);
  const paddingLeft = parseFloat(style.paddingLeft) || 0;
  const paddingRight = parseFloat(style.paddingRight) || 0;
  const contentWidth = items.length
    ? Math.max(...items.map((item) => item.offsetLeft + item.offsetWidth)) - Math.min(...items.map((item) => item.offsetLeft))
    : 0;
  const availableWidth = Math.max(0, rail.clientWidth - paddingLeft - paddingRight);
  const canScroll = contentWidth > availableWidth + 4;
  const atStart = rail.scrollLeft <= 4;
  const atEnd = rail.scrollLeft + rail.clientWidth >= rail.scrollWidth - 4;
  left.hidden = !canScroll;
  right.hidden = !canScroll;
  left.disabled = !canScroll || atStart;
  right.disabled = !canScroll || atEnd;
}

function renderFocusTasks(tasks = []) {
  const scoped = projectFilteredTasks(tasks);
  const open = scoped.filter(isOpenTask).sort((a, b) => taskSortScore(a) - taskSortScore(b));
  const focus = open.slice(0, 8);

  const projectOptions = projectOptionsFromTasks(tasks);
  const scopeLabel = state.projectFilter || (projectOptions.length === 1 ? projectOptions[0] : 'All Projects');
  const inProgress = open.filter((task) => taskArea(task) === 'in progress').length;
  const needsAttention = open.filter((task) => taskArea(task) === 'needs attention').length;
  const due = open.filter(isDueTask).length;
  const nextTask = open[0];
  const statusLine = nextTask
    ? `Next: ${escapeHtml(nextTask.title)} · ${escapeHtml(taskArea(nextTask))}`
    : 'Queue clear — no open next moves in this scope.';
  const queueMeta = `${open.length} open`;
  const projectSelect = `
    <label class="today-project-select-label" for="today-project-select">
      <span class="detail-context-label mono">Project</span>
      <select id="today-project-select" class="today-project-select" aria-label="Filter next moves by project">
        <option value="" ${state.projectFilter ? '' : 'selected'}>All projects</option>
        ${projectOptions.map((name) => `<option value="${escapeHtml(name)}" ${state.projectFilter === name ? 'selected' : ''}>${escapeHtml(name)}</option>`).join('')}
      </select>
    </label>
  `;

  const header = `
    <section class="focus-queue-shell ${open.length ? '' : 'clear'}">
      <header class="focus-queue-header">
        <div class="focus-queue-copy">
          <div class="focus-kicker mono">Current queue</div>
          <h3>${escapeHtml(scopeLabel)} queue</h3>
          <p>${statusLine}</p>
        </div>
        ${projectSelect}
        <div class="focus-queue-head-meta detail-context-label mono">${escapeHtml(queueMeta)}</div>
        <div class="focus-stat-row" aria-label="Queue status summary">
          <span><strong>${inProgress}</strong> in progress</span>
          <span><strong>${needsAttention}</strong> attention</span>
          <span><strong>${due}</strong> due</span>
        </div>
      </header>
      <div class="focus-task-rail">
  `;


  const taskCards = focus.length ? focus.map((task, index) => {
    const area = taskArea(task);
    const indicator = focusTaskIndicator(task);
    return `
      <button class="item focus-task-item focus-task-button focus-task-${escapeHtml(indicator.key)}" type="button" data-focus-task-id="${escapeHtml(String(task.id || ''))}" data-focus-task-title="${escapeHtml(task.title || '')}" data-focus-project-name="${escapeHtml(task.project || '')}" data-focus-task-area="${escapeHtml(area)}" aria-label="Open task ${escapeHtml(task.title || 'Untitled task')} in Projects / Tasks">
        <span class="focus-task-indicator" aria-label="${escapeHtml(indicator.label)}"></span>
        <span class="focus-task-rank mono">${String(index + 1).padStart(2, '0')}</span>
        <div class="focus-task-body">
          <div class="item-title"><span>${escapeHtml(task.title)}</span><span class="task-state-text ${taskTone(area)}">${escapeHtml(indicator.label)}</span></div>
          <div class="item-desc">${escapeHtml(task.description || '')}</div>
          <div class="item-meta mono">${escapeHtml(task.project || 'General')} · due ${escapeHtml(task.due_date || 'none')} · ${escapeHtml(taskArea(task))}</div>
        </div>
      </button>
    `;
  }).join('') : `
      <div class="empty clear-skies">No tasks found in this project scope.</div>
  `;

  $('#focus-task-list').innerHTML = `${header}${taskCards}</div></section>`;
}

function renderTaskList(tasks = []) {
  state.tasks = tasks;
  const filterSelect = $('#task-status-filter');
  if (filterSelect && filterSelect.value !== state.taskStatusFilter) filterSelect.value = state.taskStatusFilter;
  syncTaskStatusControl();

  const filtered = visibleTasks(tasks);
  selectedTaskFrom(filtered);
  const count = $('#task-count');
  if (count) count.textContent = `${filtered.length} tasks`;
  const clearProject = $('#clear-project-filter');
  const projectLabel = $('#project-filter-label');
  if (clearProject) clearProject.hidden = !state.projectFilter;
  if (projectLabel) {
    projectLabel.hidden = !state.projectFilter;
    projectLabel.textContent = state.projectFilter || '';
  }

  $('#task-list').innerHTML = filtered.length ? filtered.map((task, index) => {
    const area = taskArea(task);
    const id = taskId(task, index);
    const selected = id === state.selectedTaskId;
    const meta = area === 'completed'
      ? escapeHtml(completedTimeLabel(task))
      : `${escapeHtml(task.project || 'General')} · due ${escapeHtml(task.due_date || 'none')} · ${escapeHtml(task.priority || 'priority n/a')}`;
    return `
      <button class="task-list-item task-list-item-button ${selected ? 'active' : ''}" type="button" data-task-id="${escapeHtml(id)}" aria-pressed="${selected ? 'true' : 'false'}">
        <div class="task-list-main">
          <div class="task-list-title-row"><span>${escapeHtml(task.title)}</span><span class="task-state-text ${taskTone(area)}">${escapeHtml(area)}</span></div>
          <div class="item-desc">${escapeHtml(task.description || '')}</div>
          <div class="item-meta mono">${meta}</div>
        </div>
      </button>
    `;
  }).join('') : `<div class="empty">No tasks match ${escapeHtml(filterSummary())}.</div>`;

  renderSelectedTaskInspector(filtered);
  renderCompletedWork(tasks);
  renderProjectStatus(state.projects, tasks);
}

function completedWorkMarkup(completed = [], emptyText = 'No completed tasks yet.', limit = 8) {
  const visible = completed.slice(0, limit);
  return visible.length ? `
    <div class="completed-list-scroll">
      ${visible.map((task) => `
        <article class="completed-line">
          <div class="completed-line-main">
            <span class="completed-title">${escapeHtml(task.title)}</span>
            <span class="completed-project">${escapeHtml(task.project || 'General')}</span>
            <span class="item-meta mono">${escapeHtml(completedTimeLabel(task))}</span>
          </div>
        </article>
      `).join('')}
      ${completed.length > visible.length ? `<div class="item-meta mono completed-overflow">+${completed.length - visible.length} older completed items hidden in this compact view.</div>` : ''}
    </div>
  ` : `<div class="empty">${emptyText}</div>`;
}

function renderCompletedWork(tasks = []) {
  const allCompleted = tasks
    .filter((t) => taskArea(t) === 'completed')
    .sort((a, b) => (parse_iso_sort(b.completed_at) - parse_iso_sort(a.completed_at)));
  const scopedCompleted = projectFilteredTasks(tasks)
    .filter((t) => taskArea(t) === 'completed')
    .sort((a, b) => (parse_iso_sort(b.completed_at) - parse_iso_sort(a.completed_at)));

  const todayCompleted = $('#completed-list');
  if (todayCompleted) todayCompleted.innerHTML = completedWorkMarkup(allCompleted, 'No completed tasks yet.', 6);

  const projectCompleted = $('#project-completed-list');
  if (projectCompleted) {
    const scope = state.projectFilter ? ` for ${escapeHtml(state.projectFilter)}` : '';
    projectCompleted.innerHTML = completedWorkMarkup(scopedCompleted, `No completed work${scope} yet.`, 10);
  }

  const completedCount = $('#completed-count');
  if (completedCount) completedCount.textContent = `${scopedCompleted.length} done`;
}

function parse_iso_sort(value) {
  const time = value ? new Date(value).getTime() : 0;
  return Number.isNaN(time) ? 0 : time;
}

function projectTone(status = '') {
  const normalized = String(status).toLowerCase();
  if (normalized === 'active') return 'success';
  if (['waiting', 'paused', 'blocked'].includes(normalized)) return 'warn';
  if (['archived', 'inactive'].includes(normalized)) return '';
  return '';
}

function tasksStatsKey(tasks = []) {
  return JSON.stringify(tasks.map((task) => [task.id, task.project, task.status, task.priority, task.needs_attention, task.review_required, task.completed_at, task.updated_at]));
}

function computeProjectStats(projectName = '', tasks = state.tasks) {
  const scoped = projectName
    ? tasks.filter((task) => normalizeFilterValue(taskProject(task)) === normalizeFilterValue(projectName))
    : tasks;
  const stats = {
    total: scoped.length,
    open: scoped.filter(isOpenTask).length,
    completed: scoped.filter((task) => taskArea(task) === 'completed').length,
    todo: scoped.filter((task) => taskArea(task) === 'todo').length,
    inProgress: scoped.filter((task) => taskArea(task) === 'in progress').length,
    waiting: scoped.filter((task) => taskArea(task) === 'waiting').length,
    needsAttention: scoped.filter((task) => taskArea(task) === 'needs attention').length,
  };
  stats.progress = stats.total ? Math.round((stats.completed / stats.total) * 100) : 0;
  return { stats, scoped };
}

function projectStats(projectName = '', tasks = state.tasks) {
  const key = tasksStatsKey(tasks);
  if (state.taskStatsCache.key !== key) {
    state.taskStatsCache = { key, byProject: new Map(), portfolio: null };
  }
  const normalizedProject = normalizeFilterValue(projectName);
  if (!normalizedProject) {
    if (!state.taskStatsCache.portfolio) state.taskStatsCache.portfolio = computeProjectStats('', tasks);
    return state.taskStatsCache.portfolio;
  }
  if (!state.taskStatsCache.byProject.has(normalizedProject)) {
    state.taskStatsCache.byProject.set(normalizedProject, computeProjectStats(projectName, tasks));
  }
  return state.taskStatsCache.byProject.get(normalizedProject);
}

function taskSortScore(task = {}) {
  const area = taskArea(task);
  const areaScore = {
    'needs attention': 0,
    'in progress': 1,
    todo: 2,
    waiting: 3,
    completed: 9,
  }[area] ?? 5;
  const priorityScore = { high: 0, medium: 1, low: 2 }[String(task.priority || '').toLowerCase()] ?? 3;
  return areaScore * 10 + priorityScore;
}

function renderProjectStatus(projects = state.projects, tasks = state.tasks) {
  const container = $('#project-portfolio-summary');
  if (!container) return;

  const selectedProject = state.projectFilter
    ? projects.find((project) => normalizeFilterValue(project.name) === normalizeFilterValue(state.projectFilter))
    : null;
  const { stats, scoped } = projectStats(selectedProject?.name || '', tasks);
  const nextTask = scoped.filter(isOpenTask).sort((a, b) => taskSortScore(a) - taskSortScore(b))[0];
  const title = selectedProject?.name || 'All Projects';
  const scopeLabel = selectedProject ? 'selected scope' : 'portfolio summary';
  const scopeMeta = selectedProject
    ? `${stats.open} open · ${stats.completed} done · ${stats.inProgress} in progress · ${stats.waiting + stats.needsAttention} blocked / waiting`
    : `${projects.length} project${projects.length === 1 ? '' : 's'} · ${tasks.length} total tasks · ${stats.open} open · ${stats.completed} done`;
  const noteMeta = selectedProject?.obsidian_note ? ` · [[${escapeHtml(selectedProject.obsidian_note)}]]` : '';
  const nextMeta = nextTask
    ? `${escapeHtml(taskStatusLabels[taskArea(nextTask)] || taskArea(nextTask))} · due ${escapeHtml(nextTask.due_date || 'none')}`
    : 'Nothing pending right now.';

  container.innerHTML = `
    <article class="project-scope-strip">
      <div class="project-scope-main">
        <div class="detail-context-label mono">${escapeHtml(scopeLabel)}</div>
        <div class="item-title"><span>${escapeHtml(title)}</span><span class="project-progress-text mono">${stats.progress}% complete</span></div>
        <div class="item-meta mono">${escapeHtml(scopeMeta)}${selectedProject ? ` · ${escapeHtml(selectedProject.type || 'project')}` : ''}${noteMeta}</div>
        <div class="progress-track mini" aria-hidden="true"><span style="width: ${stats.progress}%"></span></div>
      </div>
      <div class="project-scope-next">
        <small>Next move</small>
        <strong>${nextTask ? escapeHtml(nextTask.title) : 'No open tasks in this scope.'}</strong>
        <span class="item-meta mono">${nextMeta}</span>
      </div>
    </article>
  `;
}

function selectedProject() {
  if (!state.projectFilter) return null;
  return state.projects.find((project) => normalizeFilterValue(project.name) === normalizeFilterValue(state.projectFilter)) || null;
}

function projectPayloadFromForm(form) {
  return {
    name: form.elements.name?.value || '',
    type: form.elements.type?.value || 'project',
    status: form.elements.status?.value || 'active',
    description: form.elements.description?.value || '',
    obsidian_note: form.elements.obsidian_note?.value || '',
    aliases: (form.elements.aliases?.value || '').split(',').map((value) => value.trim()).filter(Boolean),
  };
}

function renderProjectEditor() {
  const container = $('#project-editor');
  if (!container) return;
  if (state.projectEditorMode === 'view') {
    container.innerHTML = '';
    return;
  }
  const mode = state.projectEditorMode;
  const existing = mode === 'edit'
    ? state.projects.find((project) => String(project.id || '') === state.projectEditorProjectId) || selectedProject() || {}
    : {};
  const draft = state.projectEditorDraft ? { ...existing, ...state.projectEditorDraft } : existing;
  container.innerHTML = `
    <form id="project-editor-form" class="task-editor-form" data-mode="${escapeHtml(mode)}" data-project-id="${escapeHtml(existing.id || '')}">
      <div class="detail-context-label mono">${mode === 'edit' ? 'Edit project' : 'Create project'} · local JSON write-back</div>
      <div class="task-editor-grid">
        <label class="task-editor-field"><span class="task-editor-label">Name</span><input name="name" required maxlength="120" value="${escapeHtml(draft.name || '')}" /></label>
        <label class="task-editor-field"><span class="task-editor-label">Type</span><input name="type" maxlength="80" value="${escapeHtml(draft.type || 'project')}" /></label>
        <label class="task-editor-field"><span class="task-editor-label">Status</span><select name="status"><option value="active" ${draft.status === 'active' ? 'selected' : ''}>Active</option><option value="paused" ${draft.status === 'paused' ? 'selected' : ''}>Paused</option><option value="archived" ${draft.status === 'archived' ? 'selected' : ''}>Archived</option></select></label>
        <label class="task-editor-field"><span class="task-editor-label">Obsidian note</span><input name="obsidian_note" maxlength="160" value="${escapeHtml(draft.obsidian_note || '')}" /></label>
        <label class="task-editor-field field-span-2"><span class="task-editor-label">Description</span><textarea name="description">${escapeHtml(draft.description || '')}</textarea></label>
        <label class="task-editor-field field-span-2"><span class="task-editor-label">Aliases (comma separated)</span><input name="aliases" value="${escapeHtml((draft.aliases || draft.legacy_names || []).join(', '))}" /></label>
      </div>
      <div class="task-editor-actions">
        <button class="action-button" type="submit">${mode === 'edit' ? 'Save Project' : 'Create Project'}</button>
        <button class="mini-button" type="button" data-project-editor-cancel>Cancel</button>
        <span class="task-editor-status" id="project-editor-status">Project-owned write only; no Hermes core mutation.</span>
      </div>
    </form>
  `;
}

function openProjectEditor(mode = 'create', project = null) {
  state.projectEditorMode = mode;
  state.projectEditorProjectId = project?.id || '';
  state.projectEditorDraft = null;
  renderProjectEditor();
  $('#project-editor')?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

function closeProjectEditor() {
  state.projectEditorMode = 'view';
  state.projectEditorProjectId = '';
  state.projectEditorDraft = null;
  renderProjectEditor();
}

async function submitProjectEditorForm(form) {
  const status = $('#project-editor-status');
  const payload = projectPayloadFromForm(form);
  if (status) status.textContent = 'Saving project…';
  try {
    const mode = form.dataset.mode || 'create';
    const result = mode === 'edit'
      ? await saveProjectEdits(form.dataset.projectId || state.projectEditorProjectId, payload)
      : await createProject(payload);
    state.projects = result.projects || state.projects;
    state.projectsLoaded = true;
    state.projectFilter = result.project?.name || state.projectFilter;
    closeProjectEditor();
    renderProjectScopedViews();
  } catch (err) {
    console.error(err);
    if (status) status.textContent = `Project save failed: ${err.message}`;
  }
}

function renderProjects(projects = []) {
  state.projects = projects;
  const projectCount = $('#project-count');
  if (projectCount) projectCount.textContent = `${projects.length} project${projects.length === 1 ? '' : 's'}`;
  const editProjectButton = $('#edit-project-button');
  if (editProjectButton) editProjectButton.disabled = !selectedProject();

  $('#project-list').innerHTML = projects.length ? projects.map((project) => {
    const name = project.name || 'Untitled project';
    const active = state.projectFilter === name;
    const { stats } = projectStats(name, state.tasks);
    const statusMeta = project.status ? `${project.status} · ` : '';
    return `
      <button class="project-card project-card-button ${active ? 'active' : ''}" type="button" data-project-name="${escapeHtml(name)}" aria-pressed="${active ? 'true' : 'false'}">
        <div class="item-title"><span>${escapeHtml(name)}</span></div>
        <div class="item-desc">${escapeHtml(project.description || '')}</div>
        <div class="project-card-footer">
          <span class="item-meta mono">${escapeHtml(statusMeta)}${stats.open} open · ${stats.completed} done</span>
          <span class="project-progress-text mono">${stats.progress}% complete</span>
        </div>
      </button>
    `;
  }).join('') : `<div class="empty">No projects found. For now, ask Hermes to add one to <code>data/projects.json</code>.</div>`;
  requestAnimationFrame(updateProjectRailButtons);
  renderProjectStatus(projects, state.tasks);
  renderProjectEditor();
}

function isDateOnly(value = '') {
  return /^\d{4}-\d{2}-\d{2}$/.test(String(value));
}

function calendarDate(value) {
  if (!value) return null;
  const raw = String(value);
  const d = new Date(isDateOnly(raw) ? `${raw}T00:00:00` : raw);
  return Number.isNaN(d.getTime()) ? null : d;
}

function sameCalendarDay(a, b) {
  return a && b && a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
}

function calendarDayLabel(date) {
  if (!date) return 'Unscheduled';
  const today = new Date();
  const tomorrow = new Date();
  tomorrow.setDate(today.getDate() + 1);
  if (sameCalendarDay(date, today)) return 'Today';
  if (sameCalendarDay(date, tomorrow)) return 'Tomorrow';
  return dayFmt.format(date);
}

function calendarTimeLabel(item = {}) {
  const start = calendarDate(item.start);
  const end = calendarDate(item.end);
  if (!start) return 'No scheduled time';
  if (isDateOnly(item.start)) return 'All day';
  if (end && !sameCalendarDay(start, end)) return `${timeFmt.format(start)} → ${dayFmt.format(end)} ${timeFmt.format(end)}`;
  return end ? `${timeFmt.format(start)} → ${timeFmt.format(end)}` : timeFmt.format(start);
}

function sortedCalendarItems(items = []) {
  return [...items].sort((a, b) => {
    const aDate = calendarDate(a.start);
    const bDate = calendarDate(b.start);
    if (!aDate && !bDate) return 0;
    if (!aDate) return 1;
    if (!bDate) return -1;
    return aDate - bDate;
  });
}

function calendarGroups(items = []) {
  return sortedCalendarItems(items).reduce((groups, item) => {
    const date = calendarDate(item.start);
    const label = calendarDayLabel(date);
    if (!groups.has(label)) groups.set(label, []);
    groups.get(label).push(item);
    return groups;
  }, new Map());
}

function calendarStatusDateLabel(value) {
  const date = calendarDate(value);
  if (!date) return 'unscheduled';
  return isDateOnly(value) ? `${calendarDayLabel(date)} all day` : `${calendarDayLabel(date)} ${timeFmt.format(date)}`;
}

function calendarStatusText(payload = {}, items = []) {
  const summary = payload.summary || {};
  const next = summary.next_event;
  const range = payload.window?.label || `Today + next ${(payload.range_days || 7) - 1} days`;
  if (payload.source === 'google') {
    return next ? `${items.length} live · ${range} · next ${calendarStatusDateLabel(next.start)}` : `${items.length} live events · ${range} · read-only`;
  }
  const stale = summary.stale ? 'stale ' : '';
  if (payload.auth === 'error') return `Google error · ${stale}local fallback${payload.data_updated_at ? ` · ${humanDate(payload.data_updated_at)}` : ''}`;
  if (payload.auth === 'not_connected') return `Google not connected · ${stale}local fallback`;
  return `${stale}local calendar fallback`;
}

function calendarEventLink(item = {}) {
  const href = safeExternalUrl(item.htmlLink || '');
  return href ? ` · <a href="${escapeHtml(href)}" target="_blank" rel="noreferrer">Open in Google</a>` : '';
}

function renderCalendarInto(selector, payload = {}, { limit = Infinity } = {}) {
  const container = $(selector);
  if (!container) return;
  const items = Array.isArray(payload) ? payload : (payload.items || []);
  const visible = sortedCalendarItems(items).slice(0, limit);
  const source = Array.isArray(payload) ? 'local' : (payload.source || 'local');
  const auth = Array.isArray(payload) ? 'legacy' : (payload.auth || 'unknown');
  const summary = payload.summary || {};
  const statusLine = calendarStatusText(payload, items);
  const groups = calendarGroups(visible);

  const summaryMarkup = `
    <section class="calendar-agenda-summary ${source === 'google' ? 'live' : auth === 'error' ? 'fallback-error' : 'fallback'} ${summary.stale ? 'stale' : ''}">
      <div>
        <div class="calendar-summary-kicker mono">${source === 'google' ? 'Google Calendar · read-only' : 'Local fallback'}</div>
        <strong>${escapeHtml(statusLine)}</strong>
        <p>${escapeHtml(payload.read_only ? 'Read-only agenda; Mentat never writes calendar events.' : 'Calendar feed')}</p>
      </div>
      <div class="calendar-summary-stats mono">
        <span><b>${summary.today_count ?? 0}</b> today</span>
        <span><b>${items.length}</b> ${payload.range_days || 7}d</span>
      </div>
    </section>
  `;

  if (!visible.length) {
    const emptyText = source === 'google'
      ? 'No upcoming Google Calendar events in the next 7 days.'
      : 'No usable local calendar items available. Google Calendar read-only sync will appear here when connected; otherwise Mentat falls back to local calendar data.';
    container.innerHTML = `${summaryMarkup}<div class="empty">${emptyText}</div>`;
    return;
  }

  const groupMarkup = Array.from(groups.entries()).map(([label, groupItems]) => `
    <section class="calendar-day-group">
      <div class="calendar-day-heading mono"><span>${escapeHtml(label)}</span><small>${groupItems.length} item${groupItems.length === 1 ? '' : 's'}</small></div>
      <div class="calendar-day-list">
        ${groupItems.map((item) => `
          <article class="item calendar-event ${source === 'google' ? 'google-event' : 'local-event'}">
            <div class="calendar-event-time mono">${escapeHtml(calendarTimeLabel(item))}</div>
            <div class="calendar-event-body">
              <div class="item-title"><span>${escapeHtml(item.title || 'Untitled event')}</span><span class="pill">${escapeHtml(item.type || 'event')}</span></div>
              <div class="item-desc">${escapeHtml(item.description || item.location || '')}</div>
              <div class="item-meta mono">${escapeHtml(item.location || source)}${calendarEventLink(item)}</div>
            </div>
          </article>
        `).join('')}
      </div>
    </section>
  `).join('');

  const overflow = items.length > visible.length
    ? `<div class="item-meta mono calendar-overflow">+${items.length - visible.length} later events hidden in this compact view.</div>`
    : '';
  container.innerHTML = `${summaryMarkup}${groupMarkup}${overflow}`;
}

function renderCalendar(payload = {}) {
  const source = Array.isArray(payload) ? 'local' : (payload.source || 'local');
  const auth = Array.isArray(payload) ? 'legacy' : (payload.auth || 'unknown');
  const sourceLabel = source === 'google' ? 'Google live' : source === 'local' && auth === 'error' ? 'Google error' : source === 'local' && auth === 'not_connected' ? 'local fallback' : 'local json';
  const pillClass = source === 'google' ? 'pill success' : auth === 'error' ? 'pill warn' : 'pill';
  ['#calendar-source-pill', '#calendar-full-source-pill'].forEach((selector) => {
    const pill = $(selector);
    if (!pill) return;
    pill.textContent = sourceLabel;
    pill.className = pillClass;
    if (payload.error) pill.title = payload.error;
  });
  renderCalendarInto('#calendar-list', payload, { limit: 5 });
  renderCalendarInto('#calendar-full-list', payload, { limit: Infinity });
}

function renderEmail(payload = {}) {
  const container = $('#email-list');
  const pill = $('#email-source-pill');
  if (!container) return;
  const items = payload.items || [];
  if (pill) {
    pill.textContent = payload.configured ? 'connected read-only' : 'local placeholder';
    pill.className = payload.configured ? 'pill success' : 'pill warn';
  }
  container.innerHTML = items.length ? items.slice(0, 5).map((item) => `
    <article class="item">
      <div class="item-title"><span>${escapeHtml(item.subject || item.title || 'Untitled email')}</span><span class="pill">${escapeHtml(item.priority || 'read-only')}</span></div>
      <div class="item-desc">${escapeHtml(item.snippet || item.from || '')}</div>
      <div class="item-meta mono">${escapeHtml(item.from || 'unknown sender')} · ${humanDate(item.received_at || item.date)}</div>
    </article>
  `).join('') : `<div class="empty">${escapeHtml(payload.guidance || 'Read-only email pane is ready; connect a source later to surface priority messages.')}</div>`;
}

const agentConsoleCommands = [
  { command: '/model', detail: 'Refresh current provider models' },
  { command: '/new', detail: 'Start a new Hermes session' },
  { command: '/help', detail: 'Show dashboard commands' },
];

function agentConsoleRunIsActive(run = {}) {
  return ['queued', 'running', 'cancelling'].includes(run.status);
}

function agentConsoleCommandSuggestions(value = '') {
  const query = String(value || '').trim().toLowerCase();
  if (!query.startsWith('/')) return [];
  return agentConsoleCommands.filter((item) => item.command.startsWith(query) || query === '/help');
}

function renderAgentConsoleCommandMenu() {
  const prompt = $('#agent-console-prompt');
  const menu = $('#agent-console-command-menu');
  if (!prompt || !menu) return;
  const suggestions = agentConsoleCommandSuggestions(prompt.value);
  menu.hidden = !suggestions.length;
  menu.innerHTML = suggestions.map((item) => `
    <button type="button" class="agent-console-command-option" data-agent-console-command="${escapeHtml(item.command)}">
      <code>${escapeHtml(item.command)}</code><span>${escapeHtml(item.detail)}</span>
    </button>
  `).join('');
}

function renderAgentConsole(payload = {}) {
  const chat = $('#agent-console-chat');
  const agentSelect = $('#agent-console-agent');
  const modelSelect = $('#agent-console-model-select');
  const applyModel = $('#agent-console-apply-model');
  const prompt = $('#agent-console-prompt');
  const send = $('#agent-console-form .agent-console-send');
  const stop = $('#agent-console-stop');
  const newSession = $('#agent-console-new-session');
  const stateLabel = $('#agent-console-state');
  const presence = $('#agent-console-presence');
  if (!chat || !agentSelect) return;

  const agents = Array.isArray(payload.agents) ? payload.agents : state.agentConsoleAgents;
  const catalog = payload.model_catalog || state.agentConsoleModelCatalog || {};
  const models = Array.isArray(catalog.models) ? catalog.models : [];
  const runs = Array.isArray(payload.runs) ? payload.runs : state.agentConsoleRuns;
  state.agentConsoleAgents = agents;
  state.agentConsoleModels = models;
  state.agentConsoleModelCatalog = catalog;
  state.agentConsoleRuns = runs;

  const requestedAgentId = state.agentConsoleSelectedAgentId || agentSelect.value || payload.selected_agent_id || 'default';
  const selectedAgentId = agents.some((agent) => agent.id === requestedAgentId)
    ? requestedAgentId
    : agents[0]?.id || 'default';
  agentSelect.innerHTML = agents.length
    ? agents.map((agent) => `<option value="${escapeHtml(agent.id)}" ${agent.id === selectedAgentId ? 'selected' : ''}>${escapeHtml(agent.name)}</option>`).join('')
    : '<option value="default">Hermes · default</option>';
  state.agentConsoleSelectedAgentId = agentSelect.value || selectedAgentId;
  const selectedAgent = agents.find((agent) => agent.id === agentSelect.value) || agents[0] || { available: false, model: '' };
  const catalogMatchesAgent = !catalog.profile_id || catalog.profile_id === selectedAgent.id;
  const scopedModels = catalogMatchesAgent ? models : [];
  const defaultModel = [state.agentConsoleSelectedModel, selectedAgent.model, catalog.current_model].find((item) => scopedModels.includes(item)) || scopedModels[0] || '';
  if (modelSelect) {
    modelSelect.innerHTML = scopedModels.length
      ? scopedModels.map((model) => `<option value="${escapeHtml(model)}" ${model === defaultModel ? 'selected' : ''}>${escapeHtml(model)}</option>`).join('')
      : `<option value="">${escapeHtml(catalogMatchesAgent ? catalog.error || 'No active models available' : 'Refresh models for this profile')}</option>`;
    state.agentConsoleSelectedModel = modelSelect.value;
  }

  const activeRun = runs.find(agentConsoleRunIsActive);
  const selectedRuns = runs.filter((run) => (run.agent_id || 'default') === selectedAgent.id);
  const latestRun = selectedRuns[0];
  if (latestRun?.session_id && !state.agentConsoleStartFresh) state.agentConsoleSessionId = latestRun.session_id;
  state.agentConsoleRunId = activeRun?.id || '';
  const available = Boolean(selectedAgent.available);
  const modelLabel = modelSelect?.value || selectedAgent.model || 'configured model';
  const providerLabel = catalog.provider_label || catalog.provider || 'Hermes';
  if (stateLabel) stateLabel.textContent = !available ? 'Hermes CLI unavailable' : activeRun ? `${providerLabel} · ${modelLabel} · working` : `${providerLabel} · ${modelLabel} · ready`;
  if (presence) presence.className = `agent-console-presence ${activeRun ? 'working' : available ? 'ready' : 'offline'}`;
  if (prompt) prompt.disabled = !available || Boolean(activeRun);
  if (send) send.disabled = !available || Boolean(activeRun);
  if (modelSelect) modelSelect.disabled = !available || Boolean(activeRun) || !scopedModels.length;
  if (applyModel) applyModel.disabled = !available || Boolean(activeRun) || !modelSelect?.value;
  if (newSession) newSession.disabled = Boolean(activeRun);
  if (stop) {
    stop.hidden = !activeRun;
    stop.disabled = activeRun?.status === 'cancelling';
  }

  const wasNearBottom = chat.scrollHeight - chat.scrollTop - chat.clientHeight < 80;
  const visibleRuns = [...selectedRuns].slice(0, 10).reverse();
  chat.innerHTML = visibleRuns.length ? visibleRuns.map((run) => {
    const runAgentName = run.agent_name || selectedAgent.name || 'Hermes';
    const events = (run.events || []).map((event) => `
      <div class="agent-console-log-row agent-console-log-status ${escapeHtml(event.kind || 'status')}">
        <time class="mono">${escapeHtml(timeFmt.format(new Date(event.timestamp || Date.now())))}</time><span>${escapeHtml(runAgentName)}</span><span>${escapeHtml(event.message || 'Working')}</span>
      </div>`).join('');
    const working = agentConsoleRunIsActive(run) ? `
      <div class="agent-console-log-row agent-console-working" role="status"><span class="agent-console-working-mark" aria-hidden="true"><i></i><i></i><i></i></span><span>${escapeHtml(runAgentName)}</span><span>${run.status === 'cancelling' ? 'Stopping' : 'Working'}</span></div>` : '';
    const response = run.response ? `<div class="agent-console-log-row agent-console-log-response"><span class="mono">${escapeHtml(runAgentName)}</span><div class="message-content markdown-body">${renderMarkdown(run.response)}</div></div>` : '';
    const error = run.error ? `<div class="agent-console-log-row agent-console-log-error"><span class="mono">${run.status === 'cancelled' ? 'Stopped' : 'Error'}</span><div class="message-content">${escapeHtml(run.error)}</div></div>` : '';
    return `<section class="agent-console-turn"><div class="agent-console-log-row agent-console-log-prompt"><time class="mono">${escapeHtml(timeFmt.format(new Date(run.created_at || Date.now())))}</time><span>You</span><div class="message-content">${escapeHtml(run.prompt || '')}</div></div><div class="agent-console-events">${events}</div>${working}${response}${error}</section>`;
  }).join('') : `<div class="agent-console-empty mono">${escapeHtml(payload.error || (available ? 'Hermes ready.' : 'Hermes CLI unavailable.'))}</div>`;
  if (wasNearBottom || activeRun) chat.scrollTop = chat.scrollHeight;
  scheduleAgentConsolePoll(Boolean(activeRun));
}

function scheduleAgentConsolePoll(shouldPoll = true) {
  clearTimeout(state.agentConsolePollTimer);
  state.agentConsolePollTimer = null;
  if (!shouldPoll || state.activeView !== 'today') return;
  state.agentConsolePollTimer = setTimeout(async () => {
    try { renderAgentConsole(await api(endpoints.agentConsole)); } catch (err) { $('#agent-console-form-status').textContent = err.message; }
  }, 1000);
}

function resizeAgentConsolePrompt() {
  const prompt = $('#agent-console-prompt');
  if (!prompt) return;
  prompt.style.height = 'auto';
  prompt.style.height = `${Math.min(prompt.scrollHeight, 140)}px`;
  renderAgentConsoleCommandMenu();
}

async function refreshAgentConsoleModelCatalog({ focus = false, agentId = state.agentConsoleSelectedAgentId } = {}) {
  const status = $('#agent-console-form-status');
  if (status) status.textContent = 'Refreshing active provider models…';
  try {
    const payload = await refreshAgentConsoleModels(agentId);
    renderAgentConsole({ agents: state.agentConsoleAgents, model_catalog: payload.model_catalog, runs: state.agentConsoleRuns });
    if (status) status.textContent = '';
    if (focus) $('#agent-console-model-select')?.focus();
    return payload.model_catalog;
  } catch (err) {
    if (status) status.textContent = err.message;
    return null;
  }
}

async function applyAgentConsoleModel() {
  const model = $('#agent-console-model-select')?.value || '';
  const status = $('#agent-console-form-status');
  if (!model) return;
  if (status) status.textContent = 'Updating Hermes model…';
  try {
    const payload = await setAgentConsoleModel(model, state.agentConsoleSelectedAgentId);
    state.agentConsoleSelectedModel = payload.model || model;
    renderAgentConsole({ agents: state.agentConsoleAgents.map((agent) => ({ ...agent, model: payload.model || model })), model_catalog: payload.model_catalog, runs: state.agentConsoleRuns });
    if (status) status.textContent = payload.message || 'Hermes default model updated.';
  } catch (err) {
    if (status) status.textContent = err.message;
  }
}

async function submitAgentConsolePrompt() {
  const prompt = $('#agent-console-prompt');
  const status = $('#agent-console-form-status');
  const value = prompt?.value.trim() || '';
  if (!value) return;
  if (value.startsWith('/')) {
    const [command, ...args] = value.split(/\s+/);
    const argument = args.join(' ').trim();
    if (command === '/model') {
      const catalog = await refreshAgentConsoleModelCatalog({ focus: true });
      if (argument && catalog?.models?.includes(argument)) {
        state.agentConsoleSelectedModel = argument;
        $('#agent-console-model-select').value = argument;
        if (status) status.textContent = `${argument} selected. Apply Model to update Hermes.`;
      } else if (argument && status) status.textContent = `${argument} is not available from the current provider.`;
    } else if (command === '/new') {
      state.agentConsoleSessionId = '';
      state.agentConsoleStartFresh = true;
      if (status) status.textContent = 'New Hermes session ready.';
    } else if (command === '/help') {
      if (status) status.textContent = 'Dashboard commands: /model, /new, /help.';
    } else if (status) status.textContent = `${command} is available in the interactive Hermes CLI, not this dashboard console.`;
    prompt.value = '';
    resizeAgentConsolePrompt();
    $('#agent-console-command-menu').hidden = true;
    return;
  }
  if (status) status.textContent = 'Sending to Hermes…';
  try {
    const payload = await startAgentConsoleRun({ agent_id: $('#agent-console-agent')?.value || state.agentConsoleSelectedAgentId || 'default', prompt: value, session_id: state.agentConsoleStartFresh ? undefined : state.agentConsoleSessionId || undefined });
    state.agentConsoleStartFresh = false;
    prompt.value = '';
    resizeAgentConsolePrompt();
    renderAgentConsole({ agents: state.agentConsoleAgents, runs: [payload.run, ...state.agentConsoleRuns].filter(Boolean) });
    if (status) status.textContent = '';
  } catch (err) {
    if (status) status.textContent = err.message;
  }
}

function renderCrons(payload = {}) {
  const jobs = payload.jobs || [];
  const count = $('#cron-count');
  const list = $('#cron-list');
  if (count) count.textContent = `${jobs.length} jobs`;
  if (!list) return;
  list.innerHTML = jobs.length ? jobs.map((job) => `
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

function modelLabel(session = {}) {
  const raw = String(session.model || '').trim();
  return raw || 'unknown';
}

function sessionTokenTotal(session = {}) {
  const usage = session.usage || {};
  const directTotal = Number(session.total_tokens);
  if (Number.isFinite(directTotal) && directTotal > 0) return directTotal;

  const usageTotal = Number(usage.total_tokens);
  if (Number.isFinite(usageTotal) && usageTotal > 0) return usageTotal;

  const directInput = Math.max(0, Number(session.input_tokens) || 0);
  const directOutput = Math.max(0, Number(session.output_tokens) || 0);
  const usageInput = Math.max(0, Number(usage.input_tokens) || 0);
  const usageOutput = Math.max(0, Number(usage.output_tokens) || 0);
  const directPrompt = Math.max(0, Number(session.prompt_tokens) || 0);
  const directCompletion = Math.max(0, Number(session.completion_tokens) || 0);
  const usagePrompt = Math.max(0, Number(usage.prompt_tokens) || 0);
  const usageCompletion = Math.max(0, Number(usage.completion_tokens) || 0);

  const usageInputs = usageInput + usageOutput;
  const directInputs = directInput + directOutput;
  if (directInputs > 0 || usageInputs > 0) return Math.max(directInputs, usageInputs);

  const usagePromptCompletion = usagePrompt + usageCompletion;
  const directPromptCompletion = directPrompt + directCompletion;
  if (usagePromptCompletion > 0 || directPromptCompletion > 0) {
    return Math.max(usagePromptCompletion, directPromptCompletion);
  }

  return 0;
}

function renderModelUsageChart(payload = {}) {
  const sessions = Array.isArray(payload.sessions) ? payload.sessions : Array.isArray(payload) ? payload : [];
  const container = $('#model-usage');
  if (!container) return;

  const palette = ['#5ff3d9', '#8f7dff', '#3b9cff', '#00d68f', '#ffd166', '#4ad7ff', '#ff5f86', '#7dff84', '#be84ff', '#6fe5d6'];
  const otherColor = '#7f8594';
  const topN = 5;
  const totals = {};
  let totalTokens = 0;

  for (const session of sessions) {
    const model = modelLabel(session);
    const tokens = sessionTokenTotal(session);
    const normalizedTokens = Math.max(0, Number(tokens) || 0);
    if (!Number.isFinite(normalizedTokens) || normalizedTokens <= 0) continue;
    totals[model] = (totals[model] || 0) + normalizedTokens;
    totalTokens += normalizedTokens;
  }

  const rows = Object.entries(totals)
    .map(([model, tokens]) => ({ model, tokens: Number(tokens) }))
    .filter((row) => Number.isFinite(row.tokens) && row.tokens > 0)
    .sort((left, right) => {
      if (Number(right.tokens) !== Number(left.tokens)) {
        return Number(right.tokens) - Number(left.tokens);
      }
      return left.model.localeCompare(right.model);
    });

  if (!rows.length) {
    container.innerHTML = '<div class="empty">No recent session token totals available yet.</div>';
    return;
  }

  const topModels = rows.slice(0, topN);
  const otherRows = rows.slice(topN);
  const othersTokens = otherRows.reduce((sum, row) => sum + row.tokens, 0);
  const totalForPercent = rows.reduce((sum, row) => sum + row.tokens, 0) || 1;

  const chartRows = [...topModels.map((row, index) => ({
    ...row,
    color: palette[index % palette.length],
  }))];
  if (othersTokens > 0) {
    chartRows.push({
      model: 'other',
      tokens: othersTokens,
      color: otherColor,
    });
  }

  let cumulative = 0;
  const chartRowsWithPercent = chartRows.map((row, index) => {
    const rawPercent = (row.tokens / totalForPercent) * 100;
    const percent = (index + 1 === chartRows.length)
      ? 100 - cumulative
      : Number(rawPercent.toFixed(2));
    const start = cumulative;
    const end = cumulative + percent;
    cumulative = end;
    return {
      ...row,
      percent,
      start,
      end,
    };
  });

  const topRows = topModels.map((row) => {
    const share = (row.tokens / totalForPercent) * 100;
    return {
      ...row,
      share,
    };
  });

  const gradient = chartRowsWithPercent.map((entry) => `${entry.color} ${entry.start.toFixed(2)}% ${entry.end.toFixed(2)}%`).join(', ');

  const legend = topRows.map((entry, index) => {
    const tokenText = humanNumber(Math.round(entry.tokens));
    const shareText = `${entry.share.toFixed(1)}%`;
    return `
      <tr>
        <td><span class="model-usage-dot" style="background:${palette[index % palette.length]}"></span>${escapeHtml(entry.model)}</td>
        <td class="mono">${tokenText}</td>
        <td class="mono">${shareText}</td>
      </tr>`;
  }).join('');

  container.innerHTML = `
    <div class="model-usage-grid">
      <div class="model-usage-chart-wrap">
        <div class="model-usage-shell">
          <div class="model-pie" style="background: conic-gradient(${gradient});" aria-hidden="true"></div>
          <div class="model-pie-meta">
            <div class="model-pie-total">${humanNumber(Math.round(totalTokens))} tokens</div>
            <div class="item-meta mono">Last ${sessions.length} recent sessions</div>
            <div class="item-meta mono">Top ${topRows.length} model${topRows.length === 1 ? '' : 's'} by token share</div>
          </div>
        </div>
        ${othersTokens > 0 ? `<div class="item-meta mono">${humanNumber(Math.round(othersTokens))} tokens in ${otherRows.length} additional model${otherRows.length === 1 ? '' : 's'} (grouped as other)</div>` : ''}
      </div>
      <div class="model-usage-table-wrap">
        <div class="model-usage-table-head detail-context-label mono">Top ${topN} models</div>
        <div class="model-usage-table-scroll">
          <table class="model-usage-table">
            <thead>
              <tr>
                <th>Model</th>
                <th>Tokens</th>
                <th>Share</th>
              </tr>
            </thead>
            <tbody>
              ${legend}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  `;
}

function renderSessions(payload = {}) {
  state.sessions = payload.sessions || state.sessions || [];
  const filtered = state.sessions.filter((session) => sessionMatches(session, state.sessionFilter));
  const select = $('#session-select');
  if (!select) return;
  if (!filtered.length) {
    select.innerHTML = `<option value="">${state.sessionFilter ? 'No matching sessions' : 'No recent sessions available'}</option>`;
    select.disabled = true;
    return;
  }

  select.disabled = false;
  const selectedStillVisible = filtered.some((session) => session.id === state.selectedSessionId);
  const selectedId = selectedStillVisible ? state.selectedSessionId : '';
  select.innerHTML = `
    <option value="">Select a session…</option>
    ${filtered.map((session) => {
      const label = `${session.title || 'Untitled session'} — ${session.source || 'session'} — ${humanDate(session.ended_at || session.started_at)} — ${session.message_count ?? 0} msgs / ${session.tool_call_count ?? 0} tools`;
      return `<option value="${escapeHtml(session.id)}" ${selectedId === session.id ? 'selected' : ''}>${escapeHtml(label)}</option>`;
    }).join('')}
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

function replayStatusTone(status = 'unknown') {
  const normalized = String(status || 'unknown').toLowerCase();
  if (normalized === 'completed') return 'success';
  if (normalized === 'blocked' || normalized === 'failed') return 'danger';
  if (normalized === 'partial' || normalized === 'needs_review') return 'warn';
  return '';
}

function replayStatusLabel(status = 'unknown') {
  return String(status || 'unknown').replace(/_/g, ' ');
}

function renderTraceItems(items = [], emptyText = 'Nothing detected yet.') {
  if (!items.length) return `<div class="empty">${escapeHtml(emptyText)}</div>`;
  return items.map((item) => `
    <article class="trace-item trace-${escapeHtml(item.status || item.mode || 'neutral')}">
      <div class="item-title">
        <span>${escapeHtml(item.title || item.tool || item.path || 'Trace item')}</span>
        ${item.category ? `<span class="pill">${escapeHtml(item.category)}</span>` : ''}
        ${item.status ? `<span class="pill ${replayStatusTone(item.status)}">${escapeHtml(replayStatusLabel(item.status))}</span>` : ''}
      </div>
      <div class="item-desc">${escapeHtml(item.detail || item.result || item.summary || item.path || '')}</div>
      ${item.result && item.detail !== item.result ? `<div class="item-meta mono">${escapeHtml(item.result)}</div>` : ''}
      ${item.timestamp ? `<div class="item-meta mono">${humanDate(item.timestamp)}</div>` : ''}
    </article>
  `).join('');
}

function renderReplayView(replayPayload = {}) {
  const replay = replayPayload.replay || replayPayload || {};
  if (replay.error) return `<div class="empty">Could not build replay: ${escapeHtml(replay.error)}</div>`;
  const summary = replay.summary || {};
  const userIntent = replay.user_intent || {};
  const outcome = replay.outcome || {};
  const status = replay.status || outcome.status || 'unknown';
  const usage = summary.usage || {};
  const inputTokens = Number(usage.input_tokens || 0);
  const outputTokens = Number(usage.output_tokens || 0);
  const totalTokens = Number(usage.total_tokens ?? (inputTokens + outputTokens));
  const usageMeta = [`${humanNumber(inputTokens)} in`, `${humanNumber(outputTokens)} out`, humanCost(usage.estimated_cost_usd)].filter(Boolean).join(' · ');
  const actionCounts = replay.action_counts || {};
  const countChips = Object.entries(actionCounts).map(([name, count]) => `<span class="pill">${escapeHtml(name)} ${escapeHtml(count)}</span>`).join('');
  const files = (replay.files || []).map((file) => ({
    title: file.path,
    detail: `${file.mode || 'seen'} via ${file.tool || 'tool'}`,
    status: file.mode === 'changed' ? 'completed' : '',
  }));
  const relatedTasks = (replay.related_tasks || []).map((task) => ({
    title: task.title || task.id,
    detail: [task.id, task.status, task.priority].filter(Boolean).join(' · '),
    status: task.status,
  }));

  return `
    <div class="replay-view">
      <section class="replay-summary-grid">
        <article class="replay-summary-card">
          <span>Status</span>
          <strong class="replay-status replay-status-${escapeHtml(status)}">${escapeHtml(replayStatusLabel(status))}</strong>
        </article>
        <article class="replay-summary-card replay-token-card">
          <span>Tokens</span>
          <strong>${humanNumber(totalTokens)}</strong>
          <small class="item-meta mono">${escapeHtml(usageMeta || 'usage n/a')}</small>
        </article>
        <article class="replay-summary-card">
          <span>Actions</span>
          <strong>${escapeHtml(summary.actions_detected ?? (replay.actions || []).length ?? 0)}</strong>
        </article>
        <article class="replay-summary-card">
          <span>Blockers</span>
          <strong>${escapeHtml(summary.blockers_detected ?? (replay.blockers || []).length ?? 0)}</strong>
        </article>
        <article class="replay-summary-card">
          <span>Purpose</span>
          <strong>Review + debug</strong>
        </article>
      </section>

      <section class="trace-section">
        <div class="trace-section-head">
          <h4>Run Summary</h4>
          <span class="pill">read-only</span>
        </div>
        <div class="item-desc">${escapeHtml(summary.title || 'Untitled session')}</div>
        <div class="item-meta mono">${[summary.source, summary.model, humanDate(summary.ended_at || summary.started_at)].filter(Boolean).map((value) => escapeHtml(value)).join(' · ')}</div>
        ${countChips ? `<div class="trace-chip-row">${countChips}</div>` : ''}
      </section>

      <section class="trace-section">
        <div class="trace-section-head"><h4>User Intent</h4></div>
        <div class="trace-intent">${escapeHtml(userIntent.initial || 'No initiating intent captured.')}</div>
        ${Array.isArray(userIntent.steering) && userIntent.steering.length ? `<div class="trace-sublist">${userIntent.steering.map((item) => `<div class="item-meta">Steering: ${escapeHtml(item)}</div>`).join('')}</div>` : ''}
      </section>

      <section class="trace-section outcome-priority-section">
        <div class="trace-section-head"><h4>Outcome + Suggested Next Step</h4><span class="pill ${replayStatusTone(status)}">${escapeHtml(replayStatusLabel(status))}</span></div>
        <div class="trace-intent">${escapeHtml(outcome.summary || 'No final assistant summary captured yet.')}</div>
        <div class="trace-list compact">${renderTraceItems(relatedTasks, 'No related task link inferred yet.')}</div>
        <div class="item-meta mono">Suggest first, write later: this view does not update tasks automatically.</div>
      </section>

      <section class="trace-section">
        <div class="trace-section-head"><h4>Agent Actions</h4><span class="pill">medium detail</span></div>
        <div class="trace-list">${renderTraceItems((replay.actions || []).slice(0, 24), 'No tool actions detected in this session window.')}</div>
      </section>

      <section class="trace-section trace-section-grid">
        <div>
          <div class="trace-section-head"><h4>Error Blockers</h4></div>
          <div class="trace-list">${renderTraceItems(replay.blockers || [], 'No blockers detected.')}</div>
        </div>
        <div>
          <div class="trace-section-head"><h4>Code / File Summary</h4></div>
          <div class="trace-list">${renderTraceItems(files.slice(0, 12), 'No code or file activity detected.')}</div>
        </div>
      </section>

      <section class="trace-section">
        <div class="trace-section-head"><h4>Verification</h4></div>
        <div class="trace-list">${renderTraceItems(replay.verification || [], 'No explicit verification commands detected.')}</div>
      </section>
    </div>
  `;
}

function renderSessionDetail(payload = null, context = {}) {
  const detail = $('#session-detail');
  if (!detail) return;
  if (!payload) {
    state.selectedSessionDetailPayload = null;
    state.selectedSessionDetailContext = null;
    detail.innerHTML = `<div class="empty">Select a session to review the replay or transcript.</div>`;
    return;
  }

  state.selectedSessionDetailPayload = payload;
  state.selectedSessionDetailContext = context;
  const session = payload.session || {};
  const messages = payload.messages || [];
  const windowInfo = payload.message_window || {};
  const targetId = Number(context.messageId || windowInfo.target_message_id || 0);
  const query = context.query || '';
  const totalVisible = windowInfo.total_visible ?? messages.length;
  const visibleLabel = windowInfo.truncated ? `${messages.length} of ${totalVisible} visible messages` : `${messages.length} visible messages`;
  const activeTab = state.selectedSessionDetailTab || 'replay';
  const transcriptHtml = `
    ${windowInfo.truncated ? `<div class="conversation-window-note mono">${windowInfo.mode === 'around_target' ? 'Showing a focused window around the selected search match.' : 'Showing the first conversation window.'} ${escapeHtml(visibleLabel)}.</div>` : ''}
    <div class="message-list">
      ${messages.length ? messages.map((message) => {
        const isTarget = targetId && Number(message.id) === targetId;
        return `
          <article id="message-${escapeHtml(message.id)}" class="message-card ${escapeHtml(message.role)} ${isTarget ? 'target-message' : ''}" data-message-id="${escapeHtml(message.id)}">
            <div class="message-meta mono">${escapeHtml(message.role)} · msg ${escapeHtml(message.id)} · ${humanDate(message.timestamp)}</div>
            <div class="message-content markdown-body">${renderMarkdown(message.content || '', query)}</div>
          </article>
        `;
      }).join('') : `<div class="empty">No user/assistant messages found for this session.</div>`}
    </div>
  `;
  detail.innerHTML = `
    <div class="session-detail-head">
      <div>
        <h3>${escapeHtml(session.title || 'Untitled session')}</h3>
        <div class="item-meta mono">${humanDate(session.ended_at || session.started_at)} · ${escapeHtml(visibleLabel)} · ${session.model ? escapeHtml(session.model) : 'model n/a'}</div>
      </div>
      <span class="pill">read-only</span>
    </div>
    <div class="session-detail-tabs" role="tablist" aria-label="Session detail view">
      <button class="session-detail-tab ${activeTab === 'replay' ? 'active' : ''}" type="button" data-session-detail-tab="replay" role="tab" aria-selected="${activeTab === 'replay'}">Replay</button>
      <button class="session-detail-tab ${activeTab === 'transcript' ? 'active' : ''}" type="button" data-session-detail-tab="transcript" role="tab" aria-selected="${activeTab === 'transcript'}">Transcript</button>
    </div>
    <div class="session-tab-panel ${activeTab === 'replay' ? 'active' : ''}" data-session-tab-panel="replay" ${activeTab === 'replay' ? '' : 'hidden'}>
      ${renderReplayView(payload.replay || {})}
    </div>
    <div class="session-tab-panel ${activeTab === 'transcript' ? 'active' : ''}" data-session-tab-panel="transcript" ${activeTab === 'transcript' ? '' : 'hidden'}>
      ${transcriptHtml}
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
  state.selectedSessionDetailTab = options.messageId ? 'transcript' : (state.selectedSessionDetailTab || 'replay');
  renderSessions({ sessions: state.sessions });
  const detail = $('#session-detail');
  if (detail) detail.innerHTML = `<div class="empty">Loading session replay…</div>`;
  try {
    const [detailPayload, replayPayload] = await Promise.all([
      fetchSessionDetail(sessionId, options.messageId),
      fetchSessionReplay(sessionId),
    ]);
    renderSessionDetail({ ...detailPayload, replay: replayPayload }, options);
    if (options.messageId) {
      requestAnimationFrame(() => scrollDetailToMessage(options.messageId));
    }
  } catch (err) {
    console.error(err);
    if (detail) detail.innerHTML = `<div class="empty">Could not load session: ${escapeHtml(err.message)}</div>`;
  }
}

function agentCreatorForm() {
  return $('#agent-creator-form');
}

function renderHermesProfiles(payload = {}) {
  const list = $('#managed-agent-list');
  const count = $('#managed-agent-count');
  if (!list) return;
  const profiles = Array.isArray(payload.profiles) ? payload.profiles : [];
  state.hermesProfiles = profiles;
  const activeProfile = payload.active_profile || '';
  state.hermesProfileCapabilities = payload.capabilities || {};
  state.activeHermesProfileId = activeProfile;
  const deletionAvailable = state.hermesProfileCapabilities['profiles.delete'] === true;
  const consoleBusy = state.agentConsoleRuns.some(agentConsoleRunIsActive);
  if (count) count.textContent = `${profiles.length} profile${profiles.length === 1 ? '' : 's'}`;
  if (payload.status && payload.status !== 'available') {
    const message = payload.error?.message || 'Hermes profile discovery is unavailable.';
    list.innerHTML = `<div class="empty" role="alert">${escapeHtml(message)}</div>`;
    return;
  }
  if (!profiles.length) {
    list.innerHTML = '<div class="empty">No Hermes profiles are available yet. Create an agent to add one.</div>';
    return;
  }
  list.innerHTML = profiles.map((profile) => {
    const selected = profile.id === state.selectedHermesProfileId;
    const labels = [
      profile.is_default ? '<span class="pill success">default</span>' : '',
      profile.id === activeProfile ? '<span class="pill">active</span>' : '',
    ].filter(Boolean).join('');
    const runtime = [profile.provider, profile.model].filter(Boolean).join(' · ') || 'Uses Hermes profile configuration';
    const canDelete = deletionAvailable && !profile.is_default && profile.id !== activeProfile && !consoleBusy;
    const deleteAction = canDelete
      ? `<button class="mini-button managed-agent-delete" type="button" data-delete-hermes-profile="${escapeHtml(profile.id)}" aria-label="Delete ${escapeHtml(profile.name || profile.id)}">Delete</button>`
      : '';
    return `
      <article class="managed-agent-card ${selected ? 'selected' : ''}" role="listitem" data-hermes-profile-id="${escapeHtml(profile.id)}">
        <div class="managed-agent-card-head">
          <div>
            <div class="managed-agent-name">${escapeHtml(profile.name || profile.id)}</div>
            <div class="item-desc">${escapeHtml(profile.description || 'No role description supplied.')}</div>
          </div>
          <div class="managed-agent-badges">${labels}</div>
        </div>
        <div class="item-meta mono">${escapeHtml(runtime)} · ${Number(profile.skill_count || 0)} skills</div>
        <div class="managed-agent-actions">
          <button class="mini-button" type="button" data-use-hermes-profile="${escapeHtml(profile.id)}">Use in Console</button>
          ${deleteAction}
        </div>
      </article>
    `;
  }).join('');
}

function closeAgentDeletion() {
  $('#agent-delete-dialog')?.close();
  state.agentDeletionPreview = null;
  const status = $('#agent-delete-status');
  if (status) status.textContent = '';
}

async function openAgentDeletion(profileId) {
  const dialog = $('#agent-delete-dialog');
  const review = $('#agent-delete-review');
  const status = $('#agent-delete-status');
  const confirm = $('[data-agent-delete-confirm]');
  if (!dialog || !review) return;
  state.agentDeletionPreview = null;
  review.innerHTML = `<div class="empty">Loading the exact Hermes deletion effects…</div>`;
  if (status) status.textContent = '';
  if (confirm) confirm.disabled = true;
  dialog.showModal();
  try {
    const preview = await previewHermesProfileDeletion(profileId);
    state.agentDeletionPreview = preview;
    const name = preview.profile?.name || preview.normalized?.profile_id || profileId;
    review.innerHTML = `
      <article class="agent-creator-review-card agent-creator-warning">
        <h3>Delete ${escapeHtml(name)}?</h3>
        <p class="item-desc">This permanently removes the Hermes profile named <strong>${escapeHtml(name)}</strong>.</p>
        <ul>${(preview.effects || []).map((effect) => `<li>${escapeHtml(effect)}</li>`).join('')}</ul>
        ${(preview.warnings || []).map((warning) => `<p class="agent-delete-warning">${escapeHtml(warning)}</p>`).join('')}
      </article>`;
    if (confirm) confirm.disabled = false;
    if (status) status.textContent = `Confirm deletion of ${name}.`;
  } catch (err) {
    review.innerHTML = `<div class="empty" role="alert">Deletion is unavailable: ${escapeHtml(err.message)}</div>`;
    if (status) status.textContent = '';
  }
}

async function submitAgentDeletion() {
  const preview = state.agentDeletionPreview;
  const profileId = preview?.normalized?.profile_id;
  const confirm = $('[data-agent-delete-confirm]');
  const status = $('#agent-delete-status');
  if (!profileId || !preview.confirmation_id) return;
  if (confirm) confirm.disabled = true;
  if (status) status.textContent = `Deleting ${profileId}…`;
  try {
    const result = await deleteHermesProfile(profileId, preview.confirmation_id);
    const refreshed = result.profiles || await fetchHermesProfiles();
    renderHermesProfiles(refreshed);
    if (state.selectedHermesProfileId === profileId) state.selectedHermesProfileId = '';
    closeAgentDeletion();
  } catch (err) {
    // Keep the profile row and confirmation open so the failure is visible and retryable.
    if (status) status.textContent = `Deletion failed: ${err.message}`;
    if (confirm) confirm.disabled = false;
  }
}

function agentCreatorPayloadFromForm() {
  const form = agentCreatorForm();
  if (!form) return {};
  const mode = form.elements.mode?.value || 'fresh';
  const skillMode = form.elements.skill_mode?.value || 'default';
  return {
    name: form.elements.name?.value || '',
    description: form.elements.description?.value || '',
    mode,
    source_profile: mode === 'clone_config' ? form.elements.source_profile?.value || '' : '',
    skill_mode: skillMode,
    enabled_builtin_skills: skillMode === 'custom' ? [...state.agentCreatorSelectedSkills] : [],
  };
}

function agentCreatorVisibleSkills() {
  const query = ($('#agent-creator-skill-search')?.value || '').trim().toLowerCase();
  if (!query) return state.agentCreatorSkills;
  return state.agentCreatorSkills.filter((skill) => (
    `${skill.name || ''} ${skill.category || ''} ${skill.description || ''}`.toLowerCase().includes(query)
  ));
}

function renderAgentCreatorSkills() {
  const list = $('#agent-creator-skill-list');
  const count = $('#agent-creator-skill-count');
  if (!list) return;
  const selected = new Set(state.agentCreatorSelectedSkills);
  const visible = agentCreatorVisibleSkills();
  if (count) count.textContent = `${selected.size} of ${state.agentCreatorSkills.length} enabled`;
  list.innerHTML = visible.length ? visible.map((skill) => `
    <label class="agent-creator-skill-item">
      <input type="checkbox" value="${escapeHtml(skill.id)}" ${selected.has(skill.id) ? 'checked' : ''} />
      <span>
        <span class="agent-creator-skill-category">${escapeHtml(skill.category || 'uncategorized')}</span>
        <strong>${escapeHtml(skill.name || skill.id)}</strong>
        <small>${escapeHtml(skill.description || 'No description provided by Hermes.')}</small>
      </span>
    </label>
  `).join('') : '<div class="empty">No built-in skills match this filter.</div>';
}

function syncAgentCreatorConfiguration() {
  const form = agentCreatorForm();
  if (!form) return;
  const mode = form.elements.mode?.value || 'fresh';
  const skillMode = form.elements.skill_mode?.value || 'default';
  const sourceField = $('#agent-creator-source-field');
  const noSkillsOption = $('#agent-creator-no-skills-option');
  const skillPicker = $('#agent-creator-skill-picker');
  if (sourceField) sourceField.hidden = mode !== 'clone_config';
  if (noSkillsOption) noSkillsOption.hidden = mode === 'clone_config';
  if (mode === 'clone_config' && skillMode === 'none') {
    const defaultMode = form.querySelector('input[name="skill_mode"][value="default"]');
    if (defaultMode) defaultMode.checked = true;
  }
  const activeSkillMode = form.elements.skill_mode?.value || 'default';
  if (skillPicker) skillPicker.hidden = activeSkillMode !== 'custom';
  const note = $('#agent-creator-config-note');
  if (note) {
    note.textContent = mode === 'clone_config'
      ? 'Hermes will copy config, .env, SOUL.md, and skills from the selected profile. A custom skill selection is applied afterward.'
      : activeSkillMode === 'none'
        ? 'This fresh profile opts out of bundled skill seeding.'
        : 'Mentat stores only skill identifiers and never edits skill contents.';
  }
  if (activeSkillMode === 'custom') renderAgentCreatorSkills();
}

function setAgentCreatorStep(step) {
  state.agentCreatorStep = step;
  $$('[data-agent-creator-step]').forEach((section) => {
    section.hidden = section.dataset.agentCreatorStep !== step;
  });
  const order = ['details', 'configuration', 'review'];
  const currentIndex = Math.max(0, order.indexOf(step));
  $$('[data-agent-creator-progress]').forEach((item) => {
    const index = order.indexOf(item.dataset.agentCreatorProgress);
    item.classList.toggle('active', index === currentIndex);
    item.classList.toggle('complete', index < currentIndex);
    if (index === currentIndex) item.setAttribute('aria-current', 'step');
    else item.removeAttribute('aria-current');
  });
  const back = $('[data-agent-creator-back]');
  const next = $('[data-agent-creator-next]');
  const create = $('[data-agent-creator-create]');
  if (back) back.hidden = step === 'details';
  if (next) next.hidden = step === 'review';
  if (create) create.hidden = step !== 'review';
  if (step === 'configuration') syncAgentCreatorConfiguration();
}

function renderAgentCreatorReview(preview) {
  const review = $('#agent-creator-review');
  if (!review) return;
  const normalized = preview.normalized || {};
  const effects = Array.isArray(preview.effects) ? preview.effects : [];
  const warnings = Array.isArray(preview.warnings) ? preview.warnings : [];
  review.innerHTML = `
    <article class="agent-creator-review-card">
      <h3>${escapeHtml(normalized.name || 'New profile')}</h3>
      <div class="item-desc">${escapeHtml(normalized.description || 'No role description supplied.')}</div>
      <div class="item-meta mono">${escapeHtml(normalized.mode || 'fresh')} · ${escapeHtml(normalized.skill_mode || 'default')} skills${normalized.skill_mode === 'custom' ? ` · ${(normalized.enabled_builtin_skills || []).length} enabled` : ''}</div>
    </article>
    <article class="agent-creator-review-card">
      <h3>Hermes will</h3>
      <ul>${effects.map((effect) => `<li>${escapeHtml(effect)}</li>`).join('')}</ul>
    </article>
    ${warnings.length ? `<article class="agent-creator-review-card agent-creator-warning"><h3>Review carefully</h3><ul>${warnings.map((warning) => `<li>${escapeHtml(warning)}</li>`).join('')}</ul></article>` : ''}
    <article class="agent-creator-review-card">
      <h3>Safety boundary</h3>
      <div class="item-desc">Mentat will execute the fixed, shell-free Hermes profile operation shown by this preview. No wrapper alias, provider change, skill-content edit, or credential read is requested.</div>
    </article>
  `;
}

async function openAgentCreator() {
  const dialog = $('#agent-creator-dialog');
  const form = agentCreatorForm();
  if (!dialog || !form) return;
  form.reset();
  state.agentCreatorPreview = null;
  state.agentCreatorProfiles = [];
  state.agentCreatorSkills = [];
  state.agentCreatorSelectedSkills = [];
  setAgentCreatorStep('details');
  const createButton = $('[data-agent-creator-create]');
  if (createButton) createButton.disabled = false;
  const status = $('#agent-creator-status');
  if (status) status.textContent = 'Loading Hermes profiles and built-in skills…';
  dialog.showModal();
  try {
    const [profilesPayload, skillsPayload] = await Promise.all([
      fetchHermesProfiles(),
      fetchHermesSkillCatalog(),
    ]);
    state.agentCreatorProfiles = Array.isArray(profilesPayload.profiles) ? profilesPayload.profiles : [];
    renderHermesProfiles(profilesPayload);
    state.agentCreatorSkills = Array.isArray(skillsPayload.skills) ? skillsPayload.skills : [];
    state.agentCreatorSelectedSkills = state.agentCreatorSkills.map((skill) => skill.id);
    const source = form.elements.source_profile;
    if (source) {
      source.innerHTML = state.agentCreatorProfiles.map((profile) => `
        <option value="${escapeHtml(profile.id)}">${escapeHtml(profile.name || profile.id)}${profile.is_default ? ' · default' : ''}</option>
      `).join('');
    }
    renderAgentCreatorSkills();
    if (status) status.textContent = `${state.agentCreatorProfiles.length} profiles · ${state.agentCreatorSkills.length} built-in skills available`;
  } catch (err) {
    console.error(err);
    if (status) status.textContent = `Agent Creator unavailable: ${err.message}`;
  }
  form.elements.name?.focus();
}

async function previewAgentCreator() {
  const status = $('#agent-creator-status');
  if (status) status.textContent = 'Validating with Hermes…';
  const preview = await previewHermesProfile(agentCreatorPayloadFromForm());
  state.agentCreatorPreview = preview;
  renderAgentCreatorReview(preview);
  setAgentCreatorStep('review');
  const createButton = $('[data-agent-creator-create]');
  if (createButton) createButton.disabled = false;
  if (status) status.textContent = 'Review the exact effects, then confirm creation.';
}

async function submitAgentCreator() {
  const preview = state.agentCreatorPreview;
  const status = $('#agent-creator-status');
  if (!preview?.confirmation_id) return;
  if (status) status.textContent = 'Creating Hermes profile…';
  const createButton = $('[data-agent-creator-create]');
  if (createButton) createButton.disabled = true;
  try {
    const result = await createHermesProfile({
      ...agentCreatorPayloadFromForm(),
      confirmed: true,
      confirmation_id: preview.confirmation_id,
    });
    state.agentCreatorProfiles = result.profiles?.profiles || state.agentCreatorProfiles;
    state.selectedHermesProfileId = result.profile?.id || result.profile?.name || '';
    if (result.profiles) renderHermesProfiles(result.profiles);
    const review = $('#agent-creator-review');
    if (review) review.innerHTML = `
      <article class="agent-creator-review-card agent-creator-success">
        <h3>${escapeHtml(result.profile?.name || result.profile?.id || 'Agent')} created</h3>
        <div class="item-desc">The Hermes profile is ready and now appears in Managed Agents.</div>
        <div class="item-meta mono">${result.skill_selection ? `${result.skill_selection.enabled_builtin_skills?.length || 0} built-in skills enabled` : 'Hermes default skill configuration'}</div>
        <button class="action-button" type="button" data-agent-creator-view-agents>View managed agents</button>
      </article>
    `;
    $('[data-agent-creator-back]')?.setAttribute('hidden', '');
    $('[data-agent-creator-create]')?.setAttribute('hidden', '');
    if (status) status.textContent = result.message || 'Agent created.';
  } catch (err) {
    console.error(err);
    if (status) status.textContent = `Creation failed: ${err.message}`;
    if (createButton) createButton.disabled = false;
  }
}

function agentStatusLabel(status = 'idle') {
  const normalized = String(status || 'idle').trim().toLowerCase();
  if (normalized === 'running') return 'Running';
  if (normalized === 'blocked') return 'Blocked';
  if (normalized === 'done') return 'Done';
  if (normalized === 'failed') return 'Failed';
  return 'Idle';
}

function agentStatusTone(status = '') {
  const normalized = String(status || '').toLowerCase();
  if (normalized === 'running' || normalized === 'done') return 'success';
  if (normalized === 'blocked' || normalized === 'failed') return 'danger';
  return 'warn';
}

function messageStatusTone(status = '') {
  const normalized = String(status || '').toLowerCase();
  if (normalized === 'delivered') return 'success';
  if (normalized === 'failed' || normalized === 'cancelled') return 'danger';
  if (normalized === 'needs user input' || normalized === 'queued') return 'warn';
  return '';
}

function agentMessagePayloadFromForm(form) {
  return {
    recipient: form.elements.recipient?.value || 'Hermes',
    project: form.elements.project?.value || state.projectFilter || 'Mentat',
    priority: form.elements.priority?.value || 'normal',
    related_task_id: form.elements.related_task_id?.value || '',
    message: form.elements.message?.value || '',
  };
}

function renderAgentMessageCompose() {
  const container = $('#agent-message-compose');
  if (!container) return;
  const projectOptions = projectOptionsFromTasks(state.tasks);
  const selectedProjectName = state.projectFilter || (projectOptions.includes('Mentat') ? 'Mentat' : projectOptions[0] || 'Mentat');
  container.innerHTML = `
    <form id="agent-message-form" class="task-editor-form agent-message-form">
      <div class="task-editor-grid">
        <label class="task-editor-field"><span class="task-editor-label">Recipient</span><input name="recipient" maxlength="120" value="Hermes" /></label>
        <label class="task-editor-field"><span class="task-editor-label">Project</span><select name="project">${projectOptions.map((name) => `<option value="${escapeHtml(name)}" ${name === selectedProjectName ? 'selected' : ''}>${escapeHtml(name)}</option>`).join('')}</select></label>
        <label class="task-editor-field"><span class="task-editor-label">Priority</span><select name="priority"><option value="normal">Normal</option><option value="high">High</option><option value="urgent">Urgent</option></select></label>
        <label class="task-editor-field"><span class="task-editor-label">Related task ID</span><input name="related_task_id" maxlength="80" placeholder="optional" /></label>
        <label class="task-editor-field field-span-2"><span class="task-editor-label">Message</span><textarea name="message" required maxlength="2000" placeholder="Queue a safe local-only instruction or question for an agent…"></textarea></label>
      </div>
      <div class="task-editor-actions">
        <button class="action-button" type="submit">Queue Message</button>
        <span class="task-editor-status" id="agent-message-status">Safety: queued only; browser text cannot execute shell commands.</span>
      </div>
    </form>
  `;
}

function renderAgentMessages(payload = {}) {
  const messages = payload.messages || [];
  state.agentMessages = messages;
  const count = $('#agent-message-count');
  const list = $('#agent-message-list');
  renderAgentMessageCompose();
  if (count) {
    const pending = Number(payload.summary?.pending || 0);
    count.textContent = pending ? `${pending} queued` : `${messages.length} messages`;
    count.className = pending ? 'pill warn' : 'pill';
  }
  if (!list) return;
  list.innerHTML = messages.length ? messages.slice(0, 8).map((message) => `
    <article class="item agent-message-item">
      <div class="item-title"><span>${escapeHtml(message.recipient || 'Agent')}</span><span class="pill ${messageStatusTone(message.status)}">${escapeHtml(message.status || 'queued')}</span></div>
      <div class="item-desc">${escapeHtml(message.message || '')}</div>
      <div class="item-meta mono">${escapeHtml(message.project || 'General')} · ${escapeHtml(message.priority || 'normal')} · ${humanDate(message.updated_at || message.created_at)}</div>
      <div class="item-meta mono">Audit events: ${(message.audit || []).length} · shell execution ${escapeHtml(message.safety?.shell_execution || 'forbidden')}</div>
    </article>
  `).join('') : `<div class="empty">No queued agent messages. Compose one above; Mentat stores it in project-owned local JSON only.</div>`;
}

function agentPulseDismissKey(agent = {}) {
  const status = String(agent.status || '').toLowerCase();
  const id = String(agent.id || agent.session_id || '').trim();
  if (id) return `id:${id}`;
  const name = String(agent.name || '').trim();
  const project = String(agent.project || '').trim();
  const source = String(agent.source || '').trim();
  return `agent:${name.toLowerCase()}|project:${project.toLowerCase()}|source:${source.toLowerCase()}|status:${status}`;
}

function isAgentPulseDismissed(agent = {}) {
  const key = agentPulseDismissKey(agent);
  if (!key) return false;
  return state.dismissedAgentPulseIds.has(key);
}

function dismissAgentPulse(agent = {}) {
  const key = agentPulseDismissKey(agent);
  if (!key) return false;
  const before = state.dismissedAgentPulseIds.size;
  state.dismissedAgentPulseIds.add(key);
  const added = state.dismissedAgentPulseIds.size > before;
  if (added) {
    persistDismissedAgentPulseIds();
  }
  return added;
}

function filterDismissedAgents(agents = []) {
  return agents.filter((agent) => !isAgentPulseDismissed(agent));
}

const AGENT_PULSE_DISMISSED_STORAGE_KEY = 'mentat-agent-pulse-dismissed-v1';

function normalizeDismissedAgentPulseKey(value = '') {
  return String(value).trim();
}

function loadDismissedAgentPulseIds() {
  if (typeof localStorage === 'undefined') return;
  try {
    const raw = localStorage.getItem(AGENT_PULSE_DISMISSED_STORAGE_KEY);
    if (!raw) return;

    const parsed = JSON.parse(raw);
    const ids = new Set();

    if (Array.isArray(parsed)) {
      parsed.forEach((value) => {
        const key = normalizeDismissedAgentPulseKey(value);
        if (key) ids.add(key);
      });
    } else if (parsed && typeof parsed === 'object') {
      Object.entries(parsed).forEach(([key]) => {
        const normalized = normalizeDismissedAgentPulseKey(key);
        if (!normalized) return;
        ids.add(normalized);
      });
    }

    state.dismissedAgentPulseIds = ids;
  } catch (error) {
    console.warn('Failed to load persisted Agent Pulse dismissals:', error);
  }
}

function persistDismissedAgentPulseIds() {
  if (typeof localStorage === 'undefined') return;
  try {
    if (!state.dismissedAgentPulseIds || !state.dismissedAgentPulseIds.size) {
      localStorage.removeItem(AGENT_PULSE_DISMISSED_STORAGE_KEY);
      return;
    }
    const now = Date.now();
    const payload = {};
    state.dismissedAgentPulseIds.forEach((key) => {
      payload[key] = now;
    });
    localStorage.setItem(AGENT_PULSE_DISMISSED_STORAGE_KEY, JSON.stringify(payload));
  } catch (error) {
    console.warn('Failed to persist Agent Pulse dismissals:', error);
  }
}


async function submitAgentMessageForm(form) {
  const status = $('#agent-message-status');
  if (status) status.textContent = 'Queueing message…';
  try {
    const result = await sendAgentMessage(agentMessagePayloadFromForm(form));
    form.reset();
    renderAgentMessages({ messages: result.messages || [], summary: result.summary || {} });
    const updatedStatus = $('#agent-message-status');
    if (updatedStatus) updatedStatus.textContent = 'Message queued locally. An agent must explicitly read/acknowledge it; no shell execution was triggered.';
  } catch (err) {
    console.error(err);
    if (status) status.textContent = `Message queue failed: ${err.message}`;
  }
}

function renderAgentPulse(payload = {}) {
  const rawAgents = Array.isArray(payload.agents) ? payload.agents : [];
  const agents = filterDismissedAgents(rawAgents);
  const sessions = Array.isArray(payload.sessions) ? payload.sessions : [];
  const latestSession = sessions[0];
  const messageSummary = payload.messageSummary || payload.agent_messages?.summary || {};
  const guidance = payload.guidance || {};
  const container = $('#agent-pulse');
  const pill = $('#agent-pulse-pill');
  if (!container) return;

  const staleAfterSeconds = Number(guidance.stale_after_seconds || AGENT_PULSE_STALE_AFTER_SECONDS) || AGENT_PULSE_STALE_AFTER_SECONDS;

  const activeAgents = agents
    .filter((agent) => {
      const status = String(agent.status || '').toLowerCase();
      return AGENT_PULSE_ACTIVE_STATUSES.has(status) && !isStaleAgent(agent, staleAfterSeconds);
    })
    .sort((left, right) => {
      const leftTs = parseAgentTimestamp(left, ['last_heartbeat', 'updated_at', 'started_at', 'created_at']) || 0;
      const rightTs = parseAgentTimestamp(right, ['last_heartbeat', 'updated_at', 'started_at', 'created_at']) || 0;
      return rightTs - leftTs;
    });

  const staleRunningAgents = agents
    .filter((agent) => {
      const status = String(agent.status || '').toLowerCase();
      return AGENT_PULSE_ACTIVE_STATUSES.has(status) && isStaleAgent(agent, staleAfterSeconds);
    })
    .sort((left, right) => {
      const leftTs = parseAgentTimestamp(left, ['last_heartbeat', 'updated_at', 'started_at', 'created_at']) || 0;
      const rightTs = parseAgentTimestamp(right, ['last_heartbeat', 'updated_at', 'started_at', 'created_at']) || 0;
      return rightTs - leftTs;
    });

  const nowMs = Date.now();
  const recentlyCompleted = agents
    .filter((agent) => {
      const status = String(agent.status || '').toLowerCase();
      if (status !== 'done' && status !== 'failed') return false;
      const resolvedAt = parseAgentTimestamp(agent, ['resolved_at', 'last_heartbeat', 'updated_at']);
      return resolvedAt !== null && nowMs - resolvedAt <= AGENT_PULSE_COMPLETED_RETENTION_MS;
    })
    .sort((left, right) => {
      const leftTs = parseAgentTimestamp(left, ['resolved_at', 'updated_at', 'last_heartbeat']) || 0;
      const rightTs = parseAgentTimestamp(right, ['resolved_at', 'updated_at', 'last_heartbeat']) || 0;
      return rightTs - leftTs;
    })
    .slice(0, AGENT_PULSE_MAX_RECENT_COMPLETED);

  const totalCompleted = agents.filter((agent) => {
    const status = String(agent.status || '').toLowerCase();
    return status === 'done' || status === 'failed';
  }).length;

  const visibleSummary = {
    running: 0,
    done: 0,
    failed: 0,
    needs_user_input: 0,
    stale: 0,
  };

  for (const agent of agents) {
    const status = String(agent.status || '').toLowerCase();
    if (status === 'running') visibleSummary.running += 1;
    if (status === 'done') visibleSummary.done += 1;
    if (status === 'failed') visibleSummary.failed += 1;
    if (agent.needs_user_input) visibleSummary.needs_user_input += 1;
  }

  visibleSummary.stale = staleRunningAgents.length;

  const hiddenCompleted = Math.max(0, totalCompleted - recentlyCompleted.length);
  const activeTotal = activeAgents.length;
  const staleCount = staleRunningAgents.length;
  const pendingMessages = Number(messageSummary.pending || 0) || 0;
  const retentionMinutes = Math.round(AGENT_PULSE_COMPLETED_RETENTION_MS / 60000);
  const doneCount = Number(visibleSummary.done || 0);
  const failedCount = Number(visibleSummary.failed || 0);
  const needsInputCount = Number(visibleSummary.needs_user_input || 0);
  const hiddenDismissedCount = rawAgents.filter((agent) => isAgentPulseDismissed(agent)).length;
  const hasVisibleRows = activeAgents.length + recentlyCompleted.length;

  if (pill) {
    if (pendingMessages) {
      pill.textContent = `${pendingMessages} pending message${pendingMessages === 1 ? '' : 's'}`;
      pill.className = 'pill warn';
    } else if (hasVisibleRows) {
      const labels = [];
      if (activeTotal) labels.push(`${activeTotal} running`);
      if (doneCount) labels.push(`${doneCount} done`);
      if (failedCount) labels.push(`${failedCount} failed`);
      if (!labels.length && recentlyCompleted.length) labels.push('recently completed');
      if (!labels.length) labels.push(`${retentionMinutes}m completed`);
      if (hiddenDismissedCount) labels.push(`${hiddenDismissedCount} dismissed`);
      pill.textContent = labels.join(' · ');
      pill.className = activeTotal ? 'pill success' : 'pill warn';
    } else {
      pill.textContent = staleCount ? 'no active heartbeat (all running entries stale)' : 'historical';
      pill.className = 'pill warn';
    }
  }

  if (!hasVisibleRows) {
    const latestSessionLabel = latestSession
      ? `${escapeHtml(latestSession.title || 'Untitled')} · ${humanDate(latestSession.ended_at || latestSession.started_at)}`
      : 'No session data yet';
    const staleAfter = staleAfterSeconds;
    const staleHint = staleCount
      ? `<div class="item-meta mono">${staleCount} heartbeat entr${staleCount === 1 ? 'y' : 'ies'} older than ${escapeHtml(humanDurationApprox(staleAfter))} are hidden until refreshed.</div>`
      : '';
    const dismissedHint = hiddenDismissedCount
      ? `<div class="item-meta mono">${hiddenDismissedCount} dismissed entr${hiddenDismissedCount === 1 ? 'y' : 'ies'} hidden from the pulse.</div>`
      : '';
    const exampleBeat = guidance.beat_command
      ? `<div class="agent-pulse-command mono">${escapeHtml(guidance.beat_command)}</div>`
      : '';
    const exampleRun = guidance.run_command
      ? `<div class="agent-pulse-command mono">${escapeHtml(guidance.run_command)}</div>`
      : '';
    container.innerHTML = `
      <div class="agent-pulse-list"><div class="agent-pulse-empty">No active agents with a live heartbeat are currently registered.</div></div>
      <div>
        <div class="item-title"><span>Historical session pulse · no live agents registered</span></div>
        <div class="item-desc">No running heartbeats are currently live, so Agent Pulse is showing the recent Hermes session cue. Agents can publish project-owned status through /api/agents/heartbeat without touching Hermes core files.</div>
        <div class="item-meta mono">Latest: ${latestSessionLabel}</div>
        ${staleHint}
        ${dismissedHint}
        <div class="agent-pulse-guidance">
          <div class="item-meta mono">Producer wiring ready · stale cutoff is about ${escapeHtml(humanDurationApprox(staleAfter))}</div>
          ${exampleBeat}
          ${exampleRun}
        </div>
      </div>
    `;
    return;
  }

  const statusChips = [
    activeTotal ? `${activeTotal} running` : null,
    doneCount ? `${doneCount} done` : null,
    failedCount ? `${failedCount} failed` : null,
    needsInputCount ? `${needsInputCount} needs user input` : null,
    staleCount ? `${staleCount} stale` : null,
    pendingMessages ? `${pendingMessages} pending messages` : null,
    hiddenDismissedCount ? `${hiddenDismissedCount} dismissed` : null,
  ].filter(Boolean).map((text) => `<span class="pill warn">${escapeHtml(text)}</span>`).join('');

  const renderRows = (rows) => rows.map((agent) => {
    const meta = [agent.project, agent.model, agent.source, agent.cwd].filter(Boolean).map((value) => escapeHtml(value)).join(' · ');
    const timestamp = parseAgentTimestamp(agent, ['last_heartbeat', 'updated_at', 'started_at', 'created_at', 'resolved_at']);
    const ageSeconds = timestamp ? Math.max(0, Math.round((Date.now() - timestamp) / 1000)) : null;
    const dismissKey = agentPulseDismissKey(agent);
    const noteParts = [
      agent.stale ? 'Heartbeat stale' : 'Heartbeat live',
      ageSeconds != null ? `Updated ${humanDurationApprox(ageSeconds)} ago` : 'Update time unknown',
      agent.needs_user_input ? 'Needs user input' : 'No user input needed',
      agent.related_task_id ? `task ${agent.related_task_id}` : '',
    ].filter(Boolean).map(escapeHtml).join(' · ');
    const agentLabel = escapeHtml(agent.name || agent.id || 'Agent');

    return `
      <article class="agent-pulse-item">
        <div class="item-title">
          <span>${agentLabel}</span>
          <span class="agent-pulse-title-actions">
            <button class="agent-pulse-dismiss" type="button" data-agent-pulse-key="${escapeHtml(dismissKey)}" aria-label="Dismiss ${agentLabel} from Agent Pulse">×</button>
            <span class="pill ${agentStatusTone(agent.status)}">${escapeHtml(agentStatusLabel(agent.status))}</span>
          </span>
          ${agent.stale ? '<span class="pill warn">Stale</span>' : ''}
        </div>
        <div class="item-desc">${escapeHtml(agent.current_task || 'No current task reported.')}</div>
        ${meta ? `<div class="item-meta mono">${meta}</div>` : ''}
        ${agent.latest_output ? `<div class="agent-pulse-output">${escapeHtml(agent.latest_output)}</div>` : ''}
        <div class="item-meta mono">${noteParts}</div>
      </article>
    `;
  }).join('');

  container.innerHTML = `
    <div class="agent-pulse-summary">
      <div>
        <div class="item-title"><span>Live agent heartbeat registry</span></div>
        <div class="item-desc">Project-owned status for active and recently completed agents. Completed entries auto-expire from this view so the panel stays focused on what is currently running.</div>
        <div class="agent-pulse-chips">${statusChips}</div>
      </div>
    </div>
    <div class="agent-pulse-group">
      <div class="agent-pulse-group-title">Currently active</div>
      ${activeAgents.length ? `<div class="agent-pulse-list">${renderRows(activeAgents)}</div>` : '<div class="agent-pulse-empty">No active agents.</div>'}
    </div>
    ${recentlyCompleted.length
      ? `<div class="agent-pulse-group">
          <div class="agent-pulse-group-title">Recently completed · ${retentionMinutes}m retention</div>
          <div class="agent-pulse-list">${renderRows(recentlyCompleted)}</div>
          ${hiddenCompleted ? `<div class="agent-pulse-note">${hiddenCompleted} completed agents are older than ${retentionMinutes}m and hidden.</div>` : ''}
        </div>`
      : ''}
  `;
}

const AGENT_PULSE_COMPLETED_RETENTION_MS = 10 * 60 * 1000;
const AGENT_PULSE_MAX_RECENT_COMPLETED = 8;
const AGENT_PULSE_ACTIVE_STATUSES = new Set(['running']);
const AGENT_PULSE_STALE_AFTER_SECONDS = 60;

function isStaleAgent(agent, staleAfterSeconds = AGENT_PULSE_STALE_AFTER_SECONDS) {
  if (agent && typeof agent.stale === 'boolean') {
    return !!agent.stale;
  }

  const timestamp = parseAgentTimestamp(agent, ['last_heartbeat', 'updated_at', 'started_at', 'created_at']);
  if (timestamp == null) {
    return false;
  }
  return Math.max(0, Math.round((Date.now() - timestamp) / 1000)) >= staleAfterSeconds;
}

function parseAgentTimestamp(agent, keys = []) {
  for (const key of keys) {
    const value = String(agent?.[key] || '').trim();
    if (!value) continue;
    const ms = Date.parse(value);
    if (Number.isFinite(ms)) return ms;
  }
  return null;
}

function renderNotes(payload = {}) {
  const notes = payload.notes || [];
  const countPill = $('#notes-count-pill');
  const vaultMeta = $('#notes-vault-meta');
  if (countPill) countPill.textContent = `${notes.length} notes`;
  if (vaultMeta) {
    vaultMeta.textContent = payload.exists === false
      ? `Vault missing: ${payload.vault || 'Unknown vault path'}`
      : `${notes.length} markdown note${notes.length === 1 ? '' : 's'} from ${payload.vault || 'Obsidian vault'}`;
  }
  $('#notes-list').innerHTML = notes.length ? notes.map((note) => `
    <article class="note-card">
      <div class="item-title"><span>${escapeHtml(note.title || note.name)}</span></div>
      <div class="item-desc">${escapeHtml(note.excerpt || '')}</div>
      <div class="item-meta mono">${[
        note.relative_path,
        note.size,
        humanDate(note.modified_at),
      ].filter(Boolean).map((value) => escapeHtml(value)).join(' · ')}</div>
    </article>
  `).join('') : `<div class="empty">No Obsidian markdown notes found.</div>`;
}

function healthTone(status = 'healthy') {
  if (status === 'error') return 'danger';
  if (status === 'degraded') return 'warn';
  return 'success';
}

function renderHealth(payload = {}) {
  const dot = $('#health-dot');
  const label = $('#health-label');
  const pill = $('#health-status-pill');
  const summary = $('#health-summary');
  const status = payload.status || 'healthy';
  const statusLabel = payload.status_label || (status ? `${status.charAt(0).toUpperCase()}${status.slice(1)}` : 'Healthy');
  const dotClass = status === 'healthy' ? 'healthy' : 'degraded';
  if (dot) dot.className = `dot ${dotClass}`;
  if (label) label.textContent = `${statusLabel} · ${payload.summary || 'No subsystem summary available.'}`;
  if (pill) {
    pill.textContent = statusLabel;
    pill.className = `pill ${healthTone(status)}`;
  }
  if (!summary) return;
  const subsystems = Array.isArray(payload.subsystems) ? payload.subsystems : [];
  summary.innerHTML = subsystems.length ? subsystems.map((item) => {
    const meta = [item.path, item.size, item.modified_at].filter(Boolean).map((value) => escapeHtml(value)).join(' · ');
    return `
      <article class="item health-item health-${escapeHtml(item.status || 'healthy')}">
        <div class="item-title">
          <span>${escapeHtml(item.name || item.key || 'Subsystem')}</span>
          <span class="pill ${healthTone(item.status)}">${escapeHtml(item.status || 'healthy')}</span>
        </div>
        <div class="item-desc">${escapeHtml(item.summary || 'No details available.')}</div>
        ${meta ? `<div class="item-meta mono">${meta}</div>` : ''}
      </article>
    `;
  }).join('') : `<div class="empty">No subsystem health checks returned.</div>`;
}

async function ensureProjectsLoaded() {
  if (state.projectsLoaded) return;
  const payload = await api(endpoints.projects);
  state.projects = payload.projects || [];
  state.projectsLoaded = true;
  renderProjects(state.projects);
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
    health: api(endpoints.health),
  };

  if (activeView === 'calendar') requests.calendar = api(endpoints.calendar);
  if (activeView === 'today') requests.agentConsole = api(endpoints.agentConsole);
  if (activeView === 'today' || activeView === 'agents') {
    requests.sessions = api(endpoints.sessions);
    if (activeView === 'agents') {
      requests.agents = api(endpoints.agents);
      requests.agentMessages = api(endpoints.agentMessages);
      requests.hermesProfiles = fetchHermesProfiles();
    }
  }
  if (activeView === 'today' || activeView === 'projects' || activeView === 'agents') requests.projects = api(endpoints.projects);
  if (activeView === 'agents') requests.crons = api(endpoints.crons);
  if (activeView === 'notes') requests.notes = api(endpoints.notes);
  if (activeView === 'settings') requests.config = api(endpoints.config);

  try {
    const entries = await Promise.all(Object.entries(requests).map(async ([key, promise]) => [key, await promise]));
    const data = Object.fromEntries(entries);

    renderGreeting(data.overview.identity || {});
    renderIfChanged('overview-cards', data.overview.cards, renderCards);
    if (data.projects) {
      state.projects = data.projects.projects || [];
      state.projectsLoaded = true;
    }
    if (data.agents) {
      state.agents = data.agents.agents || [];
    }
    const tasks = data.tasks.tasks || [];
    state.tasks = tasks;
    renderIfChanged(`tasks-${state.taskStatusFilter}-${state.taskFilter}-${state.projectFilter}-${state.selectedTaskId}-${state.taskEditorMode}`, tasks, renderTaskList);
    if (data.projects) renderIfChanged(`projects-${state.projectFilter}-${state.projectEditorMode}`, state.projects, renderProjects);
    renderIfChanged(`focus-${state.projectFilter}`, tasks, renderFocusTasks);
    renderIfChanged(`completed-${state.projectFilter}`, tasks, renderCompletedWork);
    if (data.calendar) renderIfChanged('calendar', data.calendar, renderCalendar);
    if (data.agentConsole) renderAgentConsole(data.agentConsole);
    if (data.crons) renderIfChanged('crons', data.crons, renderCrons);
    if (data.hermesProfiles) renderIfChanged('hermes-profiles', data.hermesProfiles, renderHermesProfiles);
    if (data.sessions || data.agents || data.agentMessages) {
      if (data.sessions) renderIfChanged(`sessions-${state.sessionFilter}-${state.selectedSessionId}`, data.sessions, renderSessions);
      if (data.sessions) renderIfChanged('model-usage', data.sessions, renderModelUsageChart);
      if (data.agentMessages) renderIfChanged(`agent-messages-${state.projectFilter}`, data.agentMessages, renderAgentMessages);
      if (activeView === 'agents') {
        const agentPulsePayload = {
          ...(data.agents || {}),
          messageSummary: data.agentMessages?.summary || {},
          sessions: data.sessions?.sessions || data.sessions || [],
        };
        state.lastAgentPulsePayload = agentPulsePayload;
        renderIfChanged('agent-pulse', agentPulsePayload, renderAgentPulse);
      }
    }
    if (data.notes) renderIfChanged('notes', data.notes, renderNotes);

    renderIfChanged('health', data.health, renderHealth);
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

initializeTheme();

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

$('#focus-task-list').addEventListener('change', (event) => {
  const projectSelect = event.target.closest('#today-project-select');
  if (!projectSelect) return;
  state.projectFilter = projectSelect.value || '';
  state.taskEditorMode = 'view';
  state.taskEditorTaskId = '';
  state.taskEditorDraft = null;
  renderProjectScopedViews();
});

$('#focus-task-list').addEventListener('click', async (event) => {
  const taskButton = event.target.closest('.focus-task-button');
  if (!taskButton) return;

  state.projectFilter = taskButton.dataset.focusProjectName || '';
  const focusArea = taskButton.dataset.focusTaskArea || 'open';
  state.taskStatusFilter = focusArea === 'completed' ? 'completed' : 'open';
  state.taskFilter = '';
  syncTaskStatusControl();
  const globalSearch = $('#global-search');
  if (globalSearch) globalSearch.value = '';

  await setView('projects');
  const scopedVisible = visibleTasks(state.tasks);
  const focusTaskId = taskButton.dataset.focusTaskId || '';
  const focusTitle = normalizeFilterValue(taskButton.dataset.focusTaskTitle || '');
  const focusProject = normalizeFilterValue(taskButton.dataset.focusProjectName || '');
  let selected = scopedVisible.find((task) => focusTaskId && String(task.id || '') === focusTaskId);
  if (!selected) {
    selected = scopedVisible.find((task) => normalizeFilterValue(task.title || '') === focusTitle && normalizeFilterValue(task.project || '') === focusProject);
  }
  if (selected) state.selectedTaskId = taskId(selected, scopedVisible.indexOf(selected));

  renderProjectScopedViews();
  const tasksPanel = $('#tasks-panel');
  const detailPanel = $('#selected-task-panel');
  tasksPanel?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  flashTarget(detailPanel || tasksPanel);
});

const globalSearch = $('#global-search');
if (globalSearch) {
  globalSearch.addEventListener('input', async (event) => {
    const query = event.target.value.trim();
    state.sessionFilter = query;
    state.taskFilter = query;
    const sessionSearch = $('#session-search');
    if (sessionSearch && sessionSearch.value !== event.target.value) sessionSearch.value = event.target.value;
    renderSessions({ sessions: state.sessions });
    renderTaskList(state.tasks);
    if (query) {
      const taskHits = state.tasks.filter((task) => taskMatches(task, query));
      if (taskHits.length) {
        try {
          await ensureProjectsLoaded();
        } catch (err) {
          console.error(err);
        }
        await setView('projects', { refreshOnChange: false });
        renderProjectScopedViews();
      } else {
        void setView('agents', { refreshOnChange: false });
        queueMessageSearch(query);
      }
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

const taskStatusFilter = $('#task-status-filter');
if (taskStatusFilter) {
  taskStatusFilter.addEventListener('change', (event) => {
    applyTaskStatusFilter(event.target.value);
  });
}

const themeSelect = $('#theme-select');
if (themeSelect) {
  themeSelect.addEventListener('change', (event) => {
    applyTheme(event.target.value);
  });
}

$('#agent-console-form')?.addEventListener('submit', async (event) => {
  event.preventDefault();
  await submitAgentConsolePrompt();
});

$('#agent-console-prompt')?.addEventListener('input', resizeAgentConsolePrompt);
$('#agent-console-prompt')?.addEventListener('keydown', (event) => {
  if (event.key === 'Tab') {
    const suggestion = agentConsoleCommandSuggestions(event.currentTarget.value)[0];
    if (suggestion) {
      event.preventDefault();
      event.currentTarget.value = `${suggestion.command} `;
      resizeAgentConsolePrompt();
      return;
    }
  }
  if (event.key !== 'Enter' || event.shiftKey || event.isComposing) return;
  event.preventDefault();
  event.currentTarget.form?.requestSubmit();
});

$('#agent-console-command-menu')?.addEventListener('click', (event) => {
  const option = event.target.closest('[data-agent-console-command]');
  if (!option) return;
  const prompt = $('#agent-console-prompt');
  if (!prompt) return;
  prompt.value = `${option.dataset.agentConsoleCommand || ''} `;
  resizeAgentConsolePrompt();
  prompt.focus();
});

$('#agent-console-agent')?.addEventListener('change', async (event) => {
  state.agentConsoleSelectedAgentId = event.target.value || 'default';
  state.agentConsoleSelectedModel = '';
  state.agentConsoleSessionId = '';
  state.agentConsoleStartFresh = true;
  renderAgentConsole({ agents: state.agentConsoleAgents, model_catalog: {}, runs: state.agentConsoleRuns });
  await refreshAgentConsoleModelCatalog({ agentId: state.agentConsoleSelectedAgentId });
  const status = $('#agent-console-form-status');
  if (status) status.textContent = `New ${state.agentConsoleSelectedAgentId} session ready.`;
});

$('#agent-console-model-select')?.addEventListener('change', (event) => {
  state.agentConsoleSelectedModel = event.target.value || '';
});
$('#agent-console-apply-model')?.addEventListener('click', () => void applyAgentConsoleModel());
$('#agent-console-new-session')?.addEventListener('click', () => {
  state.agentConsoleSessionId = '';
  state.agentConsoleStartFresh = true;
  const status = $('#agent-console-form-status');
  if (status) status.textContent = 'New Hermes session ready.';
  $('#agent-console-prompt')?.focus();
});
$('#agent-console-stop')?.addEventListener('click', async () => {
  const status = $('#agent-console-form-status');
  if (!state.agentConsoleRunId) return;
  if (status) status.textContent = 'Stopping Hermes…';
  try {
    const payload = await stopAgentConsoleRun(state.agentConsoleRunId);
    renderAgentConsole({ agents: state.agentConsoleAgents, runs: state.agentConsoleRuns.map((run) => run.id === payload.run?.id ? payload.run : run) });
  } catch (err) {
    if (status) status.textContent = err.message;
  }
});

$('#project-scroll-left')?.addEventListener('click', () => scrollProjectRail(-1));
$('#project-scroll-right')?.addEventListener('click', () => scrollProjectRail(1));
$('#project-list')?.addEventListener('scroll', updateProjectRailButtons, { passive: true });
window.addEventListener('resize', updateProjectRailButtons);

const clearProjectFilter = $('#clear-project-filter');
if (clearProjectFilter) {
  clearProjectFilter.addEventListener('click', () => {
    state.projectFilter = '';
    renderProjectScopedViews();
  });
}

document.addEventListener('click', async (event) => {
  const deleteProfile = event.target.closest('[data-delete-hermes-profile]');
  if (deleteProfile) {
    await openAgentDeletion(deleteProfile.dataset.deleteHermesProfile || '');
    return;
  }

  if (event.target.closest('[data-agent-delete-cancel]')) {
    closeAgentDeletion();
    return;
  }

  if (event.target.closest('[data-agent-delete-confirm]')) {
    await submitAgentDeletion();
    return;
  }

  if (event.target.closest('#create-agent-button')) {
    await openAgentCreator();
    return;
  }

  if (event.target.closest('[data-agent-creator-view-agents]')) {
    $('#agent-creator-dialog')?.close();
    const panel = $('#managed-agents-panel');
    panel?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    flashTarget(panel);
    return;
  }

  const useProfile = event.target.closest('[data-use-hermes-profile]');
  if (useProfile) {
    state.agentConsoleSelectedAgentId = useProfile.dataset.useHermesProfile || 'default';
    state.agentConsoleSessionId = '';
    state.agentConsoleStartFresh = true;
    state.agentConsoleSelectedModel = '';
    await setView('today');
    await refreshAgentConsoleModelCatalog({ agentId: state.agentConsoleSelectedAgentId, focus: true });
    $('#agent-console-panel')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    return;
  }

  if (event.target.closest('[data-agent-creator-close]')) {
    $('#agent-creator-dialog')?.close();
    return;
  }

  if (event.target.closest('[data-agent-creator-back]')) {
    setAgentCreatorStep(state.agentCreatorStep === 'review' ? 'configuration' : 'details');
    return;
  }

  if (event.target.closest('[data-agent-creator-next]')) {
    const form = agentCreatorForm();
    if (!form) return;
    if (state.agentCreatorStep === 'details') {
      if (!form.elements.name?.reportValidity()) return;
      setAgentCreatorStep('configuration');
    } else if (state.agentCreatorStep === 'configuration') {
      try {
        await previewAgentCreator();
      } catch (err) {
        console.error(err);
        const status = $('#agent-creator-status');
        if (status) status.textContent = `Preview failed: ${err.message}`;
      }
    }
    return;
  }

  if (event.target.closest('[data-agent-skills-select-visible]')) {
    const selected = new Set(state.agentCreatorSelectedSkills);
    agentCreatorVisibleSkills().forEach((skill) => selected.add(skill.id));
    state.agentCreatorSelectedSkills = [...selected].sort();
    renderAgentCreatorSkills();
    return;
  }

  if (event.target.closest('[data-agent-skills-clear]')) {
    state.agentCreatorSelectedSkills = [];
    renderAgentCreatorSkills();
    return;
  }

  const pulseDismiss = event.target.closest('.agent-pulse-dismiss');
  if (pulseDismiss) {
    const key = pulseDismiss.dataset.agentPulseKey || '';
    if (key) {
      const rawKey = key.startsWith('id:') ? key.slice(3) : key;
      const dismissed = dismissAgentPulse({ id: rawKey });
      if (dismissed && state.lastAgentPulsePayload) {
        renderAgentPulse(state.lastAgentPulsePayload);
      } else if (dismissed && !state.lastAgentPulsePayload) {
        renderAgentPulse({});
      }
    }
    return;
  }

  const themeChoice = event.target.closest('[data-theme-choice]');
  if (themeChoice) {
    applyTheme(themeChoice.dataset.themeChoice || THEMES[0].id);
    return;
  }

  if (event.target.closest('#create-project-button')) {
    await setView('projects', { refreshOnChange: false });
    openProjectEditor('create');
    return;
  }

  if (event.target.closest('#edit-project-button')) {
    const project = selectedProject();
    if (!project) return;
    await setView('projects', { refreshOnChange: false });
    openProjectEditor('edit', project);
    return;
  }

  if (event.target.closest('[data-project-editor-cancel]')) {
    closeProjectEditor();
    return;
  }

  if (event.target.closest('#create-task-button')) {
    await setView('projects', { refreshOnChange: false });
    openTaskEditor('create');
    return;
  }

  if (event.target.closest('#selected-task-edit')) {
    const selected = selectedTaskFrom(visibleTasks(state.tasks));
    if (!selected) return;
    openTaskEditor('edit', selected);
    return;
  }

  if (event.target.closest('#selected-task-cancel') || event.target.closest('[data-task-editor-cancel]')) {
    closeTaskEditor();
  }
});

$('#selected-task-detail')?.addEventListener('input', (event) => {
  const form = event.target.closest('#task-editor-form');
  if (!form) return;
  state.taskEditorDraft = taskPayloadFromForm(form);
});

$('#selected-task-detail')?.addEventListener('change', (event) => {
  const form = event.target.closest('#task-editor-form');
  if (!form) return;
  state.taskEditorDraft = taskPayloadFromForm(form);
});

$('#selected-task-detail')?.addEventListener('submit', async (event) => {
  const form = event.target.closest('#task-editor-form');
  if (!form) return;
  event.preventDefault();
  state.taskEditorDraft = taskPayloadFromForm(form);
  await submitTaskEditorForm(form);
});

document.addEventListener('input', (event) => {
  if (event.target.closest('#agent-creator-skill-search')) {
    renderAgentCreatorSkills();
    return;
  }
  const projectForm = event.target.closest('#project-editor-form');
  if (projectForm) state.projectEditorDraft = projectPayloadFromForm(projectForm);
});

document.addEventListener('change', (event) => {
  const creatorForm = event.target.closest('#agent-creator-form');
  if (creatorForm) {
    if (event.target.matches('input[name="skill_mode"], select[name="mode"]')) {
      syncAgentCreatorConfiguration();
    }
    if (event.target.closest('#agent-creator-skill-list input[type="checkbox"]')) {
      const selected = new Set(state.agentCreatorSelectedSkills);
      if (event.target.checked) selected.add(event.target.value);
      else selected.delete(event.target.value);
      state.agentCreatorSelectedSkills = [...selected].sort();
      renderAgentCreatorSkills();
    }
    state.agentCreatorPreview = null;
    return;
  }
  const projectForm = event.target.closest('#project-editor-form');
  if (projectForm) state.projectEditorDraft = projectPayloadFromForm(projectForm);
});

document.addEventListener('submit', async (event) => {
  const creatorForm = event.target.closest('#agent-creator-form');
  if (creatorForm) {
    event.preventDefault();
    if (state.agentCreatorStep === 'review') await submitAgentCreator();
    return;
  }
  const projectForm = event.target.closest('#project-editor-form');
  if (projectForm) {
    event.preventDefault();
    state.projectEditorDraft = projectPayloadFromForm(projectForm);
    await submitProjectEditorForm(projectForm);
    return;
  }
  const messageForm = event.target.closest('#agent-message-form');
  if (messageForm) {
    event.preventDefault();
    await submitAgentMessageForm(messageForm);
  }
});

$('#project-list').addEventListener('click', async (event) => {
  const card = event.target.closest('.project-card-button');
  if (!card) return;
  state.projectFilter = card.dataset.projectName || '';
  await setView('projects');
  renderProjectScopedViews();
});

$('#task-list')?.addEventListener('click', (event) => {
  const taskButton = event.target.closest('.task-list-item-button');
  if (!taskButton) return;
  state.taskEditorMode = 'view';
  state.taskEditorTaskId = '';
  state.taskEditorDraft = null;
  state.selectedTaskId = taskButton.dataset.taskId || '';
  renderTaskList(state.tasks);
  const detailPanel = $('#selected-task-panel');
  if (window.matchMedia('(max-width: 1120px)').matches) {
    detailPanel?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  } else {
    flashTarget(detailPanel);
  }
});

$('#selected-task-back')?.addEventListener('click', () => {
  $('#tasks-panel')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
});

const sessionSelect = $('#session-select');
if (sessionSelect) {
  sessionSelect.addEventListener('change', (event) => {
    const sessionId = event.target.value;
    if (sessionId) loadSessionDetail(sessionId);
  });
}

$('#session-detail')?.addEventListener('click', (event) => {
  const tab = event.target.closest('[data-session-detail-tab]');
  if (!tab) return;
  state.selectedSessionDetailTab = tab.dataset.sessionDetailTab || 'replay';
  if (state.selectedSessionDetailPayload) {
    renderSessionDetail(state.selectedSessionDetailPayload, state.selectedSessionDetailContext || {});
  }
});

$('#message-search-results').addEventListener('click', (event) => {
  const result = event.target.closest('.message-result');
  if (!result) return;
  const sessionId = result.dataset.sessionId;
  if (sessionId) loadSessionDetail(sessionId, { messageId: result.dataset.messageId, query: result.dataset.query || state.sessionFilter });
});



loadDismissedAgentPulseIds();
setView('today');
refresh();
setInterval(refresh, REFRESH_MS);
