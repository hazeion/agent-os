function humanDate(value) {
  if (!value) return '—';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return 'Invalid date';
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
  { id: 'compact-dark', label: 'Compact Dark', pill: 'compact dark', mode: 'dark' },
  { id: 'catppuccin', label: 'Catppuccin Mocha', pill: 'catppuccin mocha', mode: 'dark' },
  { id: 'nord', label: 'Nord', pill: 'nord', mode: 'dark' },
  { id: 'aurora', label: 'Aurora', pill: 'aurora', mode: 'dark' },
  { id: 'tokyo-night', label: 'Tokyo Night', pill: 'tokyo night', mode: 'dark' },
  { id: 'gruvbox-dark', label: 'Gruvbox Dark', pill: 'gruvbox dark', mode: 'dark' },
  { id: 'dracula', label: 'Dracula', pill: 'dracula', mode: 'dark' },
  { id: 'one-dark', label: 'One Dark', pill: 'one dark', mode: 'dark' },
  { id: 'solarized-dark', label: 'Solarized Dark', pill: 'solarized dark', mode: 'dark' },
  { id: 'light', label: 'Soft Light', pill: 'soft light', mode: 'light' },
  { id: 'github-light', label: 'GitHub Light', pill: 'github light', mode: 'light' },
  { id: 'gruvbox-light', label: 'Gruvbox Light', pill: 'gruvbox light', mode: 'light' },
  { id: 'solarized-light', label: 'Solarized Light', pill: 'solarized light', mode: 'light' },
  { id: 'catppuccin-latte', label: 'Catppuccin Latte', pill: 'catppuccin latte', mode: 'light' },
  { id: 'rose-pine-dawn', label: 'Rosé Pine Dawn', pill: 'rosé pine dawn', mode: 'light' },
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
    preview.innerHTML = [
      { mode: 'dark', label: 'Dark themes' },
      { mode: 'light', label: 'Light themes' },
    ].map((group) => `
      <section class="theme-preview-group" aria-labelledby="theme-${group.mode}-label">
        <div id="theme-${group.mode}-label" class="theme-preview-group-title mono">${group.label}</div>
        <div class="theme-preview-list">
          ${THEMES.filter((item) => item.mode === group.mode).map((item) => `
            <button class="theme-swatch ${item.id === theme.id ? 'active' : ''}" type="button" data-theme-choice="${escapeHtml(item.id)}" aria-pressed="${item.id === theme.id ? 'true' : 'false'}">
              <span class="theme-swatch-chip theme-${escapeHtml(item.id)}" aria-hidden="true"></span>
              <span>${escapeHtml(item.label)}</span>
            </button>
          `).join('')}
        </div>
      </section>
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
  if (state.taskStatusFilter === 'today') return isOpenTask(task) && Boolean(task.planned_for_today);
  if (state.taskStatusFilter === 'review') return task.planning_state === 'review' || task.delegation?.state === 'ready_for_review';
  if (state.taskStatusFilter === 'someday') return task.planning_state === 'someday';
  if (state.taskStatusFilter === 'blocked') return task.planning_state === 'blocked' || task.delegation?.state === 'needs_input' || taskArea(task) === 'needs attention';
  if (state.taskStatusFilter === 'waiting') return task.planning_state === 'waiting' || ['queued', 'running'].includes(task.delegation?.state) || taskArea(task) === 'waiting';
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
    planned_for_today: false,
    manual_rank: 100,
    estimated_minutes: 30,
    planning_state: 'inbox',
    subtasks: [],
    depends_on: [],
    reminders: [],
  };
  return draft ? { ...base, ...draft } : base;
}

function parseTaskTagsInput(value = '') {
  return String(value)
    .split(',')
    .map((part) => part.trim())
    .filter(Boolean);
}

function localDateTimeInputValue(value = '') {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  const offset = date.getTimezoneOffset() * 60000;
  return new Date(date.getTime() - offset).toISOString().slice(0, 16);
}

function isoDateTimeInputValue(value = '') {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date.toISOString();
}

function parseSubtasksInput(value = '', existing = []) {
  const prior = new Map((existing || []).map((item) => [String(item.title || '').trim().toLowerCase(), item]));
  return String(value).split('\n').map((title) => title.trim()).filter(Boolean).slice(0, 200).map((title, index) => {
    const matched = prior.get(title.toLowerCase());
    const slug = title.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '').slice(0, 60) || `item_${index + 1}`;
    return { id: matched?.id || `subtask_${index + 1}_${slug}`, title, completed: Boolean(matched?.completed), rank: index };
  });
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
  const deleteButton = $('#selected-task-delete');
  const delegateButton = $('#selected-task-delegate');
  const cancelButton = $('#selected-task-cancel');
  const editorActive = state.taskEditorMode === 'create' || state.taskEditorMode === 'edit';
  const selected = selectedTaskFrom(tasks);
  if (editButton) {
    editButton.hidden = editorActive;
    editButton.disabled = !selected;
  }
  if (deleteButton) {
    deleteButton.hidden = editorActive;
    deleteButton.disabled = !selected;
  }
  if (delegateButton) {
    delegateButton.hidden = editorActive;
    delegateButton.disabled = !selected;
    delegateButton.textContent = selected?.delegation ? 'Agent Work' : 'Delegate to Agent';
  }
  if (cancelButton) cancelButton.hidden = !editorActive;
}

function taskPayloadFromForm(form) {
  const formData = new FormData(form);
  const scheduledStart = isoDateTimeInputValue(formData.get('scheduled_start'));
  const scheduledEnd = isoDateTimeInputValue(formData.get('scheduled_end'));
  const reminderAt = isoDateTimeInputValue(formData.get('reminder_at'));
  const recurrenceFrequency = String(formData.get('recurrence_frequency') || '').trim();
  const existing = state.tasks.find((task) => String(task.id || '') === String(form.dataset.taskId || '')) || {};
  const localTimezone = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
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
    planned_for_today: formData.get('planned_for_today') === 'on',
    manual_rank: Number(formData.get('manual_rank') || 100),
    estimated_minutes: Number(formData.get('estimated_minutes') || 30),
    planning_state: String(formData.get('planning_state') || 'inbox'),
    scheduled_block: scheduledStart && scheduledEnd ? { start: scheduledStart, end: scheduledEnd, timezone: localTimezone } : null,
    recurrence: recurrenceFrequency ? { frequency: recurrenceFrequency, interval: Number(formData.get('recurrence_interval') || 1) } : null,
    reminders: reminderAt ? [{ id: 'primary', at: reminderAt, channel: 'browser', enabled: true, timezone: localTimezone }] : [],
    subtasks: parseSubtasksInput(formData.get('subtasks') || '', existing.subtasks),
    depends_on: parseTaskTagsInput(formData.get('depends_on') || ''),
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

function closeTaskDeletion() {
  state.taskDeletionRequestToken += 1;
  state.taskDeletionPreview = null;
  $('#task-delete-dialog')?.close();
  const status = $('#task-delete-status');
  if (status) status.textContent = '';
}

async function openTaskDeletion(taskId) {
  const dialog = $('#task-delete-dialog');
  const review = $('#task-delete-review');
  const status = $('#task-delete-status');
  const confirm = $('[data-task-delete-confirm]');
  if (!dialog || !review || !taskId) return;
  const requestToken = ++state.taskDeletionRequestToken;
  state.taskDeletionPreview = null;
  review.innerHTML = '<div class="empty">Loading the exact task deletion effect…</div>';
  if (status) status.textContent = '';
  if (confirm) confirm.disabled = true;
  dialog.showModal();
  try {
    const preview = await previewTaskDeletion(taskId);
    if (requestToken !== state.taskDeletionRequestToken || !dialog.open) return;
    state.taskDeletionPreview = preview;
    review.innerHTML = `
      <article class="agent-creator-review-card agent-creator-warning">
        <h3>Delete ${escapeHtml(preview.task?.title || taskId)}?</h3>
        <ul>${(preview.effects || []).map((effect) => `<li>${escapeHtml(effect)}</li>`).join('')}</ul>
        ${(preview.warnings || []).map((warning) => `<p class="agent-delete-warning">${escapeHtml(warning)}</p>`).join('')}
      </article>`;
    if (confirm) confirm.disabled = false;
  } catch (err) {
    if (requestToken === state.taskDeletionRequestToken && status) status.textContent = err.message;
  }
}

async function submitTaskDeletion() {
  const preview = state.taskDeletionPreview;
  const status = $('#task-delete-status');
  if (!preview?.confirmation_id || !preview.task?.id) return;
  if (status) status.textContent = 'Deleting task…';
  try {
    const result = await deleteTask(preview.task.id, preview.confirmation_id);
    state.tasks = Array.isArray(result.tasks) ? result.tasks : state.tasks.filter((task) => task.id !== preview.task.id);
    state.selectedTaskId = '';
    closeTaskDeletion();
    await refresh();
    renderProjectScopedViews();
  } catch (err) {
    if (status) status.textContent = err.message;
  }
}

function closeTaskDelegation() {
  state.taskDelegationRequestToken += 1;
  state.taskDelegationPreview = null;
  state.taskDelegationTaskId = '';
  $('#task-delegation-dialog')?.close();
}

function taskDelegationFormPayload() {
  const form = $('#task-delegation-form');
  const data = new FormData(form);
  return {
    profile_id: String(data.get('profile_id') || '').trim(),
    board_id: String(data.get('board_id') || 'default').trim(),
    workspace: String(data.get('workspace') || 'scratch').trim(),
    context_pack_id: String(data.get('context_pack_id') || '').trim(),
    instructions: String(data.get('instructions') || '').trim(),
  };
}

async function openTaskDelegation(task) {
  const dialog = $('#task-delegation-dialog');
  const form = $('#task-delegation-form');
  const status = $('#task-delegation-status');
  if (!dialog || !form || !task?.id) return;
  state.taskDelegationTaskId = String(task.id);
  state.taskDelegationPreview = null;
  $('#task-delegation-review').innerHTML = `<div class="empty">Choose an agent and review the exact delegation.</div>`;
  $('[data-task-delegation-confirm]').disabled = true;
  if (status) status.textContent = 'Loading Hermes profiles and Kanban boards…';
  dialog.showModal();
  try {
    const [profilesPayload, kanban, contextPacksPayload] = await Promise.all([
      fetchHermesProfiles(),
      fetchHermesKanbanCapabilities(),
      fetchContextPacks(),
    ]);
    state.hermesProfiles = Array.isArray(profilesPayload.profiles) ? profilesPayload.profiles : [];
    state.hermesKanbanCapabilities = kanban;
    const profileSelect = form.elements.profile_id;
    const boardSelect = form.elements.board_id;
    const contextPackSelect = form.elements.context_pack_id;
    profileSelect.innerHTML = state.hermesProfiles.length
      ? state.hermesProfiles.map((profile) => `<option value="${escapeHtml(profile.id)}">${escapeHtml(profile.name || profile.id)}</option>`).join('')
      : '<option value="">No Hermes profiles available</option>';
    boardSelect.innerHTML = Array.isArray(kanban.boards) && kanban.boards.length
      ? kanban.boards.map((board) => `<option value="${escapeHtml(board.id)}">${escapeHtml(board.name || board.id)}</option>`).join('')
      : '<option value="default">Default</option>';
    state.contextPacks = Array.isArray(contextPacksPayload.context_packs) ? contextPacksPayload.context_packs : [];
    contextPackSelect.innerHTML = '<option value="">No context pack</option>' + state.contextPacks.map((pack) => `<option value="${escapeHtml(pack.id)}">${escapeHtml(pack.name)}</option>`).join('');
    if (task.delegation?.profile_id) profileSelect.value = task.delegation.profile_id;
    if (task.delegation?.board_id) boardSelect.value = task.delegation.board_id;
    if (status) status.textContent = kanban.status === 'available'
      ? 'Hermes Kanban is available. Review is required before delegation.'
      : 'Hermes Kanban is unavailable in this Hermes installation.';
  } catch (err) {
    if (status) status.textContent = err.message;
  }
}

async function reviewTaskDelegation() {
  const taskId = state.taskDelegationTaskId;
  const status = $('#task-delegation-status');
  const review = $('#task-delegation-review');
  const confirm = $('[data-task-delegation-confirm]');
  if (!taskId || !review) return;
  const requestToken = ++state.taskDelegationRequestToken;
  state.taskDelegationPreview = null;
  confirm.disabled = true;
  if (status) status.textContent = 'Preparing exact delegation preview…';
  try {
    const preview = await previewTaskDelegation(taskId, taskDelegationFormPayload());
    if (requestToken !== state.taskDelegationRequestToken) return;
    state.taskDelegationPreview = preview;
    review.innerHTML = `
      <article class="agent-creator-review-card">
        <h3>${escapeHtml(preview.task?.title || 'Task')}</h3>
        <div class="task-detail-meta-row mono"><span>${escapeHtml(preview.target?.profile_id || '')}</span><span>${escapeHtml(preview.target?.board_id || '')}</span><span>${escapeHtml(preview.target?.workspace || '')}</span></div>
        <pre class="delegation-context-preview">${escapeHtml(preview.context || '')}</pre>
        <ul>${(preview.effects || []).map((effect) => `<li>${escapeHtml(effect)}</li>`).join('')}</ul>
        ${(preview.warnings || []).map((warning) => `<p class="agent-delete-warning">${escapeHtml(warning)}</p>`).join('')}
      </article>`;
    confirm.disabled = false;
    if (status) status.textContent = 'Review the exact effects, then confirm.';
  } catch (err) {
    if (status) status.textContent = err.message;
  }
}

async function submitTaskDelegation() {
  const preview = state.taskDelegationPreview;
  const status = $('#task-delegation-status');
  if (!preview?.confirmation_id || !state.taskDelegationTaskId) return;
  if (status) status.textContent = 'Delegating through Hermes Kanban…';
  try {
    const result = await delegateTask(state.taskDelegationTaskId, taskDelegationFormPayload(), preview.confirmation_id);
    closeTaskDelegation();
    state.tasks = Array.isArray(result.tasks) ? result.tasks : state.tasks.map((task) => task.id === result.task?.id ? result.task : task);
    await refresh();
    renderProjectScopedViews();
    flashTarget($('#selected-task-panel'));
  } catch (err) {
    if (status) status.textContent = err.message;
  }
}

function closeDelegationAction() {
  state.delegationActionRequestToken += 1;
  state.delegationActionPreview = null;
  $('#delegation-action-dialog')?.close();
}

async function openDelegationAction(action) {
  const selected = selectedTaskFrom(visibleTasks(state.tasks));
  const dialog = $('#delegation-action-dialog');
  const review = $('#delegation-action-review');
  const status = $('#delegation-action-status');
  if (!selected?.id || !dialog || !review) return;
  const needsNote = ['reply', 'request_revision', 'mark_blocked'].includes(action);
  const labels = { accept: 'Accept Result', reply: 'Reply to Agent', retry: 'Retry Work', stop: 'Stop Work', request_revision: 'Request Revision', mark_blocked: 'Mark Blocked' };
  $('#delegation-action-title').textContent = labels[action] || 'Review Agent Work';
  review.innerHTML = `
    <article class="agent-creator-review-card">
      <h3>${escapeHtml(selected.title || 'Task')}</h3>
      <p>${escapeHtml(selected.delegation?.summary || selected.delegation?.latest_question || 'Review this linked agent action.')}</p>
      ${needsNote ? `<label class="task-editor-field"><span class="task-editor-label mono">Your note</span><textarea id="delegation-action-note" rows="4" maxlength="8000" required></textarea></label>` : ''}
      <div id="delegation-action-effects"></div>
    </article>`;
  state.delegationActionPreview = { taskId: selected.id, action, confirmation_id: '' };
  if (status) status.textContent = needsNote ? 'Add a note, then confirm the exact action.' : 'Preparing action preview…';
  dialog.showModal();
  if (!needsNote) await reviewDelegationAction();
}

async function reviewDelegationAction() {
  const draft = state.delegationActionPreview;
  const note = $('#delegation-action-note')?.value.trim() || '';
  const status = $('#delegation-action-status');
  if (!draft?.taskId || !draft.action) return null;
  const requestToken = ++state.delegationActionRequestToken;
  try {
    const preview = await previewTaskDelegationAction(draft.taskId, draft.action, note);
    if (requestToken !== state.delegationActionRequestToken) return null;
    state.delegationActionPreview = preview;
    $('#delegation-action-effects').innerHTML = `<ul>${(preview.effects || []).map((effect) => `<li>${escapeHtml(effect)}</li>`).join('')}</ul>`;
    if (status) status.textContent = 'Exact action ready for confirmation.';
    return preview;
  } catch (err) {
    if (status) status.textContent = err.message;
    return null;
  }
}

async function submitDelegationAction() {
  let preview = state.delegationActionPreview;
  if (!preview?.confirmation_id) preview = await reviewDelegationAction();
  if (!preview?.confirmation_id) return;
  const status = $('#delegation-action-status');
  try {
    const result = await runTaskDelegationAction(preview.task.id, preview.action, preview.note || '', preview.confirmation_id);
    closeDelegationAction();
    state.tasks = state.tasks.map((task) => task.id === result.task?.id ? result.task : task);
    await refresh();
    renderProjectScopedViews();
  } catch (err) {
    if (status) status.textContent = err.message;
  }
}

async function refreshSelectedTaskDelegation(taskId) {
  try {
    const result = await refreshTaskDelegation(taskId);
    state.tasks = state.tasks.map((task) => task.id === result.task?.id ? result.task : task);
    renderProjectScopedViews();
    renderAgentActivity(await api(endpoints.agentActivity));
  } catch (err) {
    $('#health-label').textContent = `Agent work refresh failed: ${err.message}`;
  }
}

function renderAgentActivity(payload = {}) {
  state.agentActivity = payload;
  const groups = payload.groups || {};
  const order = [
    ['needs_input', 'Needs your input'],
    ['ready_for_review', 'Ready for review'],
    ['running', 'Running'],
    ['failed', 'Failed'],
    ['recently_completed', 'Recently completed'],
  ];
  const total = order.reduce((sum, [key]) => sum + (groups[key]?.length || 0), 0);
  const summary = $('#agent-activity-summary');
  if (summary) summary.textContent = `${total} linked item${total === 1 ? '' : 's'}`;
  const list = $('#agent-activity-list');
  if (!list) return;
  list.innerHTML = total ? order.map(([key, label]) => {
    const items = groups[key] || [];
    if (!items.length) return '';
    return `<section class="agent-activity-group"><h3>${escapeHtml(label)} <span class="mono">${items.length}</span></h3>${items.map((item) => `
      <button class="agent-activity-item" type="button" data-activity-task-id="${escapeHtml(item.task_id || '')}" data-activity-project="${escapeHtml(item.project || '')}">
        <span><strong>${escapeHtml(item.title || 'Untitled task')}</strong><small>${escapeHtml(item.project || 'General')} · ${escapeHtml(item.profile_id || 'agent')}</small></span>
        <span class="task-state-text ${escapeHtml(item.state || '')}">${escapeHtml(item.state || '')}</span>
      </button>`).join('')}</section>`;
  }).join('') : '<div class="empty">No linked agent work yet. Delegate a task to begin.</div>';
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
    const planningOptions = ['inbox', 'planned', 'in_progress', 'waiting', 'review', 'someday', 'blocked', 'done']
      .map((value) => `<option value="${escapeHtml(value)}" ${value === (draft?.planning_state || 'inbox') ? 'selected' : ''}>${escapeHtml(value.replaceAll('_', ' '))}</option>`)
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
          <label class="task-editor-field">
            <span class="task-editor-label mono">Planning state</span>
            <select name="planning_state">${planningOptions}</select>
          </label>
          <label class="task-editor-field">
            <span class="task-editor-label mono">Estimate (minutes)</span>
            <input name="estimated_minutes" type="number" min="1" max="10080" value="${escapeHtml(String(draft?.estimated_minutes || 30))}" />
          </label>
          <label class="task-editor-field">
            <span class="task-editor-label mono">Today order</span>
            <input name="manual_rank" type="number" min="0" max="1000000" value="${escapeHtml(String(draft?.manual_rank ?? 100))}" />
          </label>
          <label class="task-editor-toggle">
            <input name="planned_for_today" type="checkbox" ${draft?.planned_for_today ? 'checked' : ''} />
            <span>Plan for today</span>
          </label>
          <label class="task-editor-field">
            <span class="task-editor-label mono">Time block starts</span>
            <input name="scheduled_start" type="datetime-local" value="${escapeHtml(localDateTimeInputValue(draft?.scheduled_block?.start))}" />
          </label>
          <label class="task-editor-field">
            <span class="task-editor-label mono">Time block ends</span>
            <input name="scheduled_end" type="datetime-local" value="${escapeHtml(localDateTimeInputValue(draft?.scheduled_block?.end))}" />
          </label>
          <label class="task-editor-field">
            <span class="task-editor-label mono">Reminder</span>
            <input name="reminder_at" type="datetime-local" value="${escapeHtml(localDateTimeInputValue(draft?.reminders?.[0]?.at))}" />
          </label>
          <label class="task-editor-field">
            <span class="task-editor-label mono">Repeats</span>
            <select name="recurrence_frequency">
              <option value="">Does not repeat</option>
              ${['daily', 'weekly', 'monthly', 'yearly'].map((value) => `<option value="${value}" ${draft?.recurrence?.frequency === value ? 'selected' : ''}>${value}</option>`).join('')}
            </select>
          </label>
          <label class="task-editor-field">
            <span class="task-editor-label mono">Repeat every</span>
            <input name="recurrence_interval" type="number" min="1" max="365" value="${escapeHtml(String(draft?.recurrence?.interval || 1))}" />
          </label>
          <label class="task-editor-field field-span-2">
            <span class="task-editor-label mono">Assignee</span>
            <input name="assignee" type="text" maxlength="120" value="${escapeHtml(draft?.assignee || '')}" placeholder="Operator, Hermes, or another owner" />
          </label>
          <label class="task-editor-field field-span-2">
            <span class="task-editor-label mono">Tags</span>
            <input name="tags" type="text" value="${escapeHtml(Array.isArray(draft?.tags) ? draft.tags.join(', ') : '')}" placeholder="phase-3, write-back" />
          </label>
          <label class="task-editor-field field-span-2">
            <span class="task-editor-label mono">Checklist (one item per line)</span>
            <textarea name="subtasks" rows="4" placeholder="First step&#10;Second step">${escapeHtml((draft?.subtasks || []).map((item) => item.title || '').join('\n'))}</textarea>
          </label>
          <label class="task-editor-field field-span-2">
            <span class="task-editor-label mono">Depends on task IDs</span>
            <input name="depends_on" type="text" value="${escapeHtml((draft?.depends_on || []).join(', '))}" placeholder="task_abc, task_xyz" />
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
  const delegation = selected.delegation && typeof selected.delegation === 'object' ? selected.delegation : null;
  const delegationActions = delegation ? `
    <div class="task-delegation-actions">
      <button class="mini-button" type="button" data-delegation-refresh="${escapeHtml(String(selected.id || ''))}">Refresh</button>
      ${delegation.state === 'ready_for_review' ? `<button class="action-button" type="button" data-delegation-action="accept">Accept Result</button><button class="mini-button" type="button" data-delegation-action="request_revision">Request Revision</button>` : ''}
      ${delegation.state === 'needs_input' ? `<button class="action-button" type="button" data-delegation-action="reply">Reply</button><button class="mini-button" type="button" data-delegation-action="retry">Retry</button>` : ''}
      ${delegation.state === 'running' ? `<button class="mini-button danger-button" type="button" data-delegation-action="stop">Stop</button>` : ''}
      ${['queued', 'running', 'failed'].includes(delegation.state) ? `<button class="mini-button" type="button" data-delegation-action="mark_blocked">Mark Blocked</button>` : ''}
      ${['failed', 'cancelled'].includes(delegation.state) ? `<button class="action-button" type="button" data-delegation-action="retry">Retry Work</button>` : ''}
    </div>` : '';
  const delegationCard = delegation ? `
    <section class="task-delegation-card task-delegation-${escapeHtml(delegation.state || 'queued')}">
      <div class="task-detail-kicker mono">Agent work · ${escapeHtml(delegation.state || 'queued')}</div>
      <div class="task-detail-meta-row mono"><span>${escapeHtml(delegation.profile_id || 'agent')}</span><span>${escapeHtml(delegation.board_id || 'default')}</span><span>${Number(delegation.attempts || 0)} attempt${Number(delegation.attempts || 0) === 1 ? '' : 's'}</span></div>
      ${delegation.latest_question ? `<div class="task-agent-question"><strong>Agent needs your input</strong><p>${escapeHtml(delegation.latest_question)}</p></div>` : ''}
      ${delegation.summary ? `<div class="task-agent-summary"><strong>Latest result</strong><p>${escapeHtml(delegation.summary)}</p></div>` : ''}
      ${delegationActions}
    </section>` : '';
  const checklist = Array.isArray(selected.subtasks) && selected.subtasks.length ? `
    <section class="task-checklist">
      <strong>Checklist</strong>
      ${selected.subtasks.map((item) => `<label><input type="checkbox" data-subtask-toggle="${escapeHtml(item.id)}" ${item.completed ? 'checked' : ''} /><span>${escapeHtml(item.title || '')}</span></label>`).join('')}
    </section>` : '';
  const planningMeta = [
    selected.planned_for_today ? 'planned today' : '',
    selected.estimated_minutes ? `${selected.estimated_minutes} min` : '',
    selected.scheduled_block?.start ? `starts ${humanDate(selected.scheduled_block.start)}` : '',
    selected.recurrence?.frequency ? `repeats ${selected.recurrence.frequency}` : '',
    selected.depends_on?.length ? `depends on ${selected.depends_on.length}` : '',
  ].filter(Boolean).join(' · ');
  const planningActions = selected.planned_for_today ? `<div class="task-delegation-actions"><button class="mini-button" type="button" data-today-move="up">Move Earlier</button><button class="mini-button" type="button" data-today-move="down">Move Later</button></div>` : '';
  const noteLinks = Array.isArray(selected.note_links) && selected.note_links.length ? `
    <section class="task-checklist"><strong>Context notes</strong>${selected.note_links.map((note) => `<div class="task-note-link"><span>${escapeHtml(note.title || note.path)}</span><button class="mini-button" type="button" data-detach-note="${escapeHtml(note.path || '')}">Detach</button></div>`).join('')}<button class="mini-button" type="button" data-view-task-notes>Browse Notes</button></section>` : '';
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
      ${planningMeta ? `<div class="task-detail-footer mono">${escapeHtml(planningMeta)}</div>` : ''}
      ${planningActions}
      ${checklist}
      ${noteLinks}
      <div class="task-detail-footer mono">${escapeHtml(updatedLabel)}${selected.source ? ` · ${escapeHtml(selected.source)}` : ''}${tags.length ? ` · tags: ${escapeHtml(tags.join(' · '))}` : ''}</div>
      ${delegationCard}
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
  const open = scoped.filter(isOpenTask).sort((a, b) => {
    const aPlanned = Boolean(a.planned_for_today);
    const bPlanned = Boolean(b.planned_for_today);
    if (aPlanned !== bPlanned) return aPlanned ? -1 : 1;
    if (aPlanned && bPlanned && Number(a.manual_rank || 0) !== Number(b.manual_rank || 0)) {
      return Number(a.manual_rank || 0) - Number(b.manual_rank || 0);
    }
    return taskSortScore(a) - taskSortScore(b);
  });
  const focus = open.slice(0, 8);

  const projectOptions = projectOptionsFromTasks(tasks);
  const quickProject = $('#quick-capture-project');
  if (quickProject) {
    const previous = quickProject.value;
    quickProject.innerHTML = projectOptions.map((name) => `<option value="${escapeHtml(name)}">${escapeHtml(name)}</option>`).join('');
    if (projectOptions.includes(previous)) quickProject.value = previous;
    else if (state.projectFilter && projectOptions.includes(state.projectFilter)) quickProject.value = state.projectFilter;
  }
  const scopeLabel = state.projectFilter || (projectOptions.length === 1 ? projectOptions[0] : 'All Projects');
  const inProgress = open.filter((task) => taskArea(task) === 'in progress').length;
  const needsAttention = open.filter((task) => taskArea(task) === 'needs attention').length;
  const due = open.filter(isDueTask).length;
  const nextTask = open[0];
  const plannedCount = open.filter((task) => task.planned_for_today).length;
  const statusLine = nextTask
    ? `Next: ${escapeHtml(nextTask.title)} · ${escapeHtml(taskArea(nextTask))}${plannedCount ? ` · ${plannedCount} deliberately planned` : ''}`
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
        <span class="focus-task-rank mono">${task.planned_for_today ? String(index + 1).padStart(2, '0') : '··'}</span>
        <div class="focus-task-body">
          <div class="item-title"><span>${escapeHtml(task.title)}</span><span class="task-state-text ${taskTone(area)}">${escapeHtml(indicator.label)}</span></div>
          <div class="item-desc">${escapeHtml(task.description || '')}</div>
          <div class="item-meta mono">${escapeHtml(task.project || 'General')} · due ${escapeHtml(task.due_date || 'none')} · ${escapeHtml(taskArea(task))}${task.estimated_minutes ? ` · ${Number(task.estimated_minutes)} min` : ''}</div>
        </div>
      </button>
    `;
  }).join('') : `
      <div class="empty clear-skies">No tasks found in this project scope.</div>
  `;

  $('#focus-task-list').innerHTML = `${header}${taskCards}</div></section>`;
}

function dueTaskReminders(tasks = state.tasks) {
  const now = Date.now();
  return tasks.flatMap((task) => (task.reminders || []).filter((reminder) => reminder.enabled !== false && Date.parse(reminder.at) <= now).map((reminder) => ({ task, reminder })));
}

function reminderStorageKey(task, reminder) {
  return `mentat-reminder:${task.id}:${reminder.id}:${reminder.at}`;
}

function renderAndNotifyReminders(tasks = state.tasks) {
  const due = dueTaskReminders(tasks);
  const list = $('#reminder-list');
  if (list) list.innerHTML = due.length ? `<section class="reminder-inbox"><strong>Reminders</strong>${due.map(({ task, reminder }) => `<button type="button" class="mini-button" data-reminder-task="${escapeHtml(task.id || '')}" data-reminder-project="${escapeHtml(task.project || '')}">${escapeHtml(task.title || 'Task')} · ${escapeHtml(humanDate(reminder.at))}</button>`).join('')}</section>` : '';
  if (typeof Notification === 'undefined' || Notification.permission !== 'granted') return;
  due.forEach(({ task, reminder }) => {
    const key = reminderStorageKey(task, reminder);
    try {
      if (localStorage.getItem(key)) return;
      new Notification(task.title || 'Mentat reminder', { body: task.description || `Due in ${task.project || 'Mentat'}` });
      localStorage.setItem(key, new Date().toISOString());
    } catch {}
  });
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

function taskLinkedToCalendarEvent(eventId = '') {
  return state.tasks.find((task) => (task.calendar_links || []).some((link) => link.event_id === eventId));
}

function calendarPayloadIsVerified(payload = {}) {
  return !Array.isArray(payload) && payload.source === 'google' && payload.auth === 'connected';
}

function calendarEventActionMarkup(item = {}, linkedTask = null, { verified = false, actionContext = '' } = {}) {
  if (linkedTask?.id) {
    return `<button class="mini-button" type="button" data-calendar-linked-task="${escapeHtml(linkedTask.id)}">Open linked task</button>`;
  }
  if (!verified || !item.id) return '';
  const title = item.title || 'calendar event';
  return `<button class="mini-button" type="button" data-calendar-create-task="${escapeHtml(item.id)}" aria-label="Create task from ${escapeHtml(title)}"${actionContext}>Create task</button><button class="mini-button" type="button" data-calendar-link-task="${escapeHtml(item.id)}" aria-label="Link selected task to ${escapeHtml(title)}"${actionContext}>Link selected task</button>`;
}

const CALENDAR_DEFAULT_START_HOUR = 6;
const CALENDAR_DEFAULT_END_HOUR = 22;

function calendarDateKey(value) {
  const date = value instanceof Date ? value : calendarDate(value);
  if (!date) return '';
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

function calendarAddDays(value, amount) {
  const date = value instanceof Date ? new Date(value) : calendarDate(value);
  if (!date) return null;
  date.setDate(date.getDate() + amount);
  return date;
}

function startOfCalendarWeek(value = new Date()) {
  const date = value instanceof Date ? new Date(value) : calendarDate(value);
  if (!date) return null;
  date.setHours(0, 0, 0, 0);
  date.setDate(date.getDate() - date.getDay());
  return date;
}

function calendarWeekStartDate() {
  const selected = calendarDate(state.calendarWeekStart || '');
  return startOfCalendarWeek(selected || new Date());
}

function calendarWeekDates(weekStart) {
  return Array.from({ length: 7 }, (_, index) => calendarAddDays(weekStart, index));
}

function calendarWeekLabel(weekStart) {
  const weekEnd = calendarAddDays(weekStart, 6);
  if (!weekStart || !weekEnd) return 'Current week';
  const month = new Intl.DateTimeFormat(undefined, { month: 'long' });
  if (weekStart.getFullYear() === weekEnd.getFullYear() && weekStart.getMonth() === weekEnd.getMonth()) {
    return `${month.format(weekStart)} ${weekStart.getDate()}–${weekEnd.getDate()}, ${weekEnd.getFullYear()}`;
  }
  const startLabel = new Intl.DateTimeFormat(undefined, {
    month: 'short',
    day: 'numeric',
    ...(weekStart.getFullYear() !== weekEnd.getFullYear() ? { year: 'numeric' } : {}),
  }).format(weekStart);
  const endLabel = new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric', year: 'numeric' }).format(weekEnd);
  return `${startLabel}–${endLabel}`;
}

function calendarTimezoneId() {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || '';
  } catch {
    return '';
  }
}

function calendarTimezoneLabel(payload = {}) {
  if (payload.timezone?.name) return payload.timezone.name;
  if (payload.timezone?.id) return payload.timezone.id;
  try {
    const zone = new Intl.DateTimeFormat(undefined, { timeZoneName: 'short' })
      .formatToParts(new Date())
      .find((part) => part.type === 'timeZoneName')?.value;
    return zone || calendarTimezoneId() || 'Local time';
  } catch {
    return calendarTimezoneId() || 'Local time';
  }
}

function calendarWeekRequestUrl(weekStart) {
  const params = new URLSearchParams({ start: calendarDateKey(weekStart), days: '7' });
  const timezone = calendarTimezoneId();
  if (timezone) params.set('timezone', timezone);
  return `${endpoints.calendar}?${params.toString()}`;
}

function calendarItemKey(item = {}, index = 0) {
  return String(item.id || `${item.title || 'event'}:${item.start || 'unscheduled'}:${index}`);
}

function isCalendarAllDay(item = {}) {
  return item.all_day === true || isDateOnly(item.start);
}

function normalizedCalendarEventEnd(item = {}, start = calendarDate(item.start)) {
  const end = calendarDate(item.end);
  if (end && start && end > start) return end;
  if (!start) return null;
  return isCalendarAllDay(item) ? calendarAddDays(start, 1) : new Date(start.getTime() + 30 * 60_000);
}

function calendarPreviewEvents(weekStart) {
  const definitions = [
    [2, 9, 0, 60, 'Weekly planning'],
    [3, 13, 0, 45, 'Project review'],
    [5, 10, 0, 120, 'Focus block'],
  ];
  return definitions.map(([dayOffset, hour, minute, duration, title], index) => {
    const start = calendarAddDays(weekStart, dayOffset);
    start.setHours(hour, minute, 0, 0);
    const end = new Date(start.getTime() + duration * 60_000);
    return {
      id: `preview:${calendarDateKey(weekStart)}:${index}`,
      title,
      start: start.toISOString(),
      end: end.toISOString(),
      type: 'preview',
      description: 'Generic preview appointment. Connect Google Calendar to replace this sample week.',
      preview: true,
    };
  });
}

function calendarWeekItems(payload = {}, weekStart) {
  const sourceItems = Array.isArray(payload) ? payload : (payload.items || []);
  const hasDatedItems = sourceItems.some((item) => calendarDate(item?.start));
  const preview = !Array.isArray(payload)
    && payload.source === 'local'
    && payload.auth === 'not_connected'
    && !hasDatedItems;
  const items = preview ? calendarPreviewEvents(weekStart) : sourceItems;
  const verified = calendarPayloadIsVerified(payload);
  const weekEnd = calendarAddDays(weekStart, 7);
  return {
    preview,
    items: items.map((item, index) => ({
      ...item,
      _calendarKey: calendarItemKey(item, index),
      _calendarVerified: verified,
    })).filter((item) => {
      const start = calendarDate(item.start);
      const end = normalizedCalendarEventEnd(item, start);
      return start && end && start < weekEnd && end > weekStart;
    }),
  };
}

function calendarAllDayItemsByDay(items, weekStart) {
  const days = Array.from({ length: 7 }, () => []);
  items.filter(isCalendarAllDay).forEach((item) => {
    const itemStart = calendarDate(item.start);
    const itemEnd = normalizedCalendarEventEnd(item, itemStart);
    calendarWeekDates(weekStart).forEach((day, dayIndex) => {
      const nextDay = calendarAddDays(day, 1);
      if (itemStart < nextDay && itemEnd > day) days[dayIndex].push(item);
    });
  });
  return days;
}

function calendarTimedSegmentMetrics(segmentStart, segmentEnd, day, nextDay) {
  const startMinute = segmentStart.getTime() === day.getTime()
    ? 0
    : segmentStart.getHours() * 60 + segmentStart.getMinutes() + segmentStart.getSeconds() / 60;
  let endMinute = segmentEnd.getTime() === nextDay.getTime()
    ? 24 * 60
    : segmentEnd.getHours() * 60 + segmentEnd.getMinutes() + segmentEnd.getSeconds() / 60;
  const elapsedMinutes = (segmentEnd.getTime() - segmentStart.getTime()) / 60_000;
  const wallMinutes = endMinute - startMinute;
  // During a fall-back fold the same wall time occurs twice. Keep the event at
  // its visible wall-clock start, but preserve its real duration so it does not
  // collapse to zero height or disappear from overlap layout.
  if (elapsedMinutes > wallMinutes && elapsedMinutes > 0) endMinute = startMinute + elapsedMinutes;
  return { startMinute, endMinute };
}

function calendarTimedSegmentsByDay(items, weekStart) {
  const days = Array.from({ length: 7 }, () => []);
  items.filter((item) => !isCalendarAllDay(item)).forEach((item) => {
    const itemStart = calendarDate(item.start);
    const itemEnd = normalizedCalendarEventEnd(item, itemStart);
    calendarWeekDates(weekStart).forEach((day, dayIndex) => {
      const nextDay = calendarAddDays(day, 1);
      if (itemStart >= nextDay || itemEnd <= day) return;
      const segmentStart = itemStart > day ? itemStart : day;
      const segmentEnd = itemEnd < nextDay ? itemEnd : nextDay;
      const { startMinute, endMinute } = calendarTimedSegmentMetrics(segmentStart, segmentEnd, day, nextDay);
      days[dayIndex].push({ item, startMinute, endMinute });
    });
  });
  return days;
}

function layoutCalendarDayOverlaps(segments = []) {
  const sorted = [...segments].sort((a, b) => (
    a.startMinute - b.startMinute
    || a.endMinute - b.endMinute
    || a.item._calendarKey.localeCompare(b.item._calendarKey)
  ));
  const groups = [];
  sorted.forEach((segment) => {
    const group = groups.at(-1);
    if (!group || segment.startMinute >= group.endMinute) {
      groups.push({ endMinute: segment.endMinute, segments: [segment] });
      return;
    }
    group.segments.push(segment);
    group.endMinute = Math.max(group.endMinute, segment.endMinute);
  });
  return groups.flatMap((group) => {
    const active = [];
    let columnCount = 1;
    const laidOut = group.segments.map((segment) => {
      active.forEach((entry, column) => {
        if (entry && entry.endMinute <= segment.startMinute) active[column] = null;
      });
      let column = active.findIndex((entry) => !entry);
      if (column < 0) column = active.length;
      active[column] = segment;
      columnCount = Math.max(columnCount, column + 1);
      return { ...segment, column };
    });
    return laidOut.map((segment) => ({ ...segment, columnCount }));
  });
}

function calendarVisibleHours(segmentsByDay) {
  const segments = segmentsByDay.flat();
  const earliest = segments.length ? Math.floor(Math.min(...segments.map((item) => item.startMinute)) / 60) : CALENDAR_DEFAULT_START_HOUR;
  const latest = segments.length ? Math.ceil(Math.max(...segments.map((item) => item.endMinute)) / 60) : CALENDAR_DEFAULT_END_HOUR;
  return {
    startHour: Math.max(0, Math.min(CALENDAR_DEFAULT_START_HOUR, earliest)),
    endHour: Math.min(24, Math.max(CALENDAR_DEFAULT_END_HOUR, latest)),
  };
}

function calendarWeekEventButton(item, { timed = false, segment = null, startHour = 0, endHour = 24 } = {}) {
  const selected = state.calendarSelectedEventKey === item._calendarKey;
  const source = item.preview ? 'preview' : (item._calendarVerified ? 'google' : 'local');
  const title = item.title || 'Untitled event';
  let style = '';
  if (timed && segment) {
    const visibleMinutes = (endHour - startHour) * 60;
    const visibleStart = startHour * 60;
    const clampedStart = Math.max(visibleStart, segment.startMinute);
    const clampedEnd = Math.min(endHour * 60, segment.endMinute);
    const top = ((clampedStart - visibleStart) / visibleMinutes) * 100;
    const height = Math.max(0.7, ((clampedEnd - clampedStart) / visibleMinutes) * 100);
    const columnWidth = 100 / segment.columnCount;
    const left = segment.column * columnWidth;
    style = ` style="top:${top.toFixed(4)}%;height:${height.toFixed(4)}%;left:calc(${left.toFixed(4)}% + 2px);width:calc(${columnWidth.toFixed(4)}% - 4px)"`;
  }
  const date = calendarDate(item.start);
  const accessibleDate = date ? new Intl.DateTimeFormat(undefined, { weekday: 'long', month: 'long', day: 'numeric' }).format(date) : '';
  const accessibleTime = calendarTimeLabel(item);
  return `
    <button class="calendar-week-event ${source === 'google' ? 'google-event' : ''} ${item.preview ? 'preview-event' : ''}" type="button"
      data-calendar-event-select="${escapeHtml(item._calendarKey)}"
      data-calendar-source="${escapeHtml(source)}" aria-selected="${selected ? 'true' : 'false'}" aria-pressed="${selected ? 'true' : 'false'}"
      aria-label="${escapeHtml(`${title}, ${accessibleDate}, ${accessibleTime}${item.preview ? ', preview' : ''}`)}"${style}>
      <span class="calendar-week-event-title">${escapeHtml(title)}</span>
      ${timed ? `<span class="calendar-week-event-time">${escapeHtml(calendarTimeLabel(item))}</span>` : ''}
      ${item.location ? `<span class="calendar-week-event-meta">${escapeHtml(item.location)}</span>` : ''}
    </button>`;
}

function renderCalendarEventInspector() {
  const inspector = $('#calendar-event-inspector');
  const content = $('#calendar-inspector-content');
  if (!inspector || !content) return;
  const item = (state.calendarWeekRenderedItems || []).find((event) => event._calendarKey === state.calendarSelectedEventKey);
  if (!item) {
    inspector.hidden = true;
    content.innerHTML = '<p class="empty">Select an appointment to inspect its details and Mentat actions.</p>';
    return;
  }
  const linkedTask = item.preview ? null : taskLinkedToCalendarEvent(item.id || '');
  const googleUrl = item._calendarVerified ? safeExternalUrl(item.htmlLink || '') : '';
  const weekStart = state.calendarWeekStart || '';
  const timezone = state.calendarWeekTimezone || calendarTimezoneId();
  const actionContext = weekStart && timezone
    ? ` data-calendar-week-start="${escapeHtml(weekStart)}" data-calendar-timezone="${escapeHtml(timezone)}"`
    : '';
  const realEventActions = calendarEventActionMarkup(item, linkedTask, {
    verified: item._calendarVerified === true,
    actionContext,
  });
  const sourceLabel = item.preview ? 'Preview appointment' : item._calendarVerified ? 'Google Calendar · read-only' : 'Local calendar · read-only';
  content.innerHTML = `
    <div class="item-title"><span>${escapeHtml(item.title || 'Untitled event')}</span><span class="pill">${escapeHtml(item.preview ? 'preview' : item.type || 'event')}</span></div>
    <div class="item-meta mono">${escapeHtml(calendarDayLabel(calendarDate(item.start)))} · ${escapeHtml(calendarTimeLabel(item))}</div>
    <div class="item-meta mono">${escapeHtml(sourceLabel)}</div>
    ${item.location ? `<div class="item-desc"><strong>Location</strong><br>${escapeHtml(item.location)}</div>` : ''}
    ${item.description ? `<div class="item-desc">${escapeHtml(item.description)}</div>` : ''}
    ${item.preview ? '<div class="calendar-preview-notice">Preview events are client-only examples. They cannot create or link tasks.</div>' : ''}
    ${(realEventActions || googleUrl) ? `<div class="calendar-task-actions">${realEventActions}${googleUrl ? `<a class="mini-button" href="${escapeHtml(googleUrl)}" target="_blank" rel="noreferrer">Open in Google</a>` : ''}</div>` : ''}
  `;
  inspector.hidden = false;
}

function selectCalendarEvent(eventKey = '') {
  state.calendarSelectedEventKey = eventKey;
  $$('[data-calendar-event-select]').forEach((button) => {
    const selected = button.dataset.calendarEventSelect === eventKey;
    button.setAttribute('aria-selected', selected ? 'true' : 'false');
    button.setAttribute('aria-pressed', selected ? 'true' : 'false');
  });
  renderCalendarEventInspector();
}

function calendarMutationContext(element) {
  const weekStart = element?.dataset?.calendarWeekStart || '';
  const timezone = element?.dataset?.calendarTimezone || '';
  return weekStart && timezone ? { week_start: weekStart, timezone } : {};
}

function renderCalendarWeek(payload = {}, weekStart = calendarWeekStartDate()) {
  const shell = $('#calendar-week');
  const dayHeaders = $('#calendar-week-days');
  const allDayEvents = $('#calendar-all-day-events');
  const timeLabels = $('#calendar-time-labels');
  const events = $('#calendar-week-events');
  if (!shell || !dayHeaders || !allDayEvents || !timeLabels || !events || !weekStart) return;

  state.calendarWeekStart = calendarDateKey(weekStart);
  state.calendarWeekTimezone = payload.timezone?.id && payload.timezone.id !== 'local'
    ? payload.timezone.id
    : calendarTimezoneId();
  const { items, preview } = calendarWeekItems(payload, weekStart);
  state.calendarWeekRenderedItems = items;
  if (!items.some((item) => item._calendarKey === state.calendarSelectedEventKey)) state.calendarSelectedEventKey = '';

  const rangeLabel = payload.window?.label || calendarWeekLabel(weekStart);
  const label = $('#calendar-week-range') || $('#calendar-week-label');
  if (label) label.textContent = rangeLabel;
  const sourceStatus = $('#calendar-source-status');
  if (sourceStatus) {
    sourceStatus.textContent = preview ? 'Preview week · Google not connected' : payload.source === 'google' ? 'Google Calendar · read-only' : 'Local calendar · read-only';
    sourceStatus.dataset.source = preview ? 'preview' : (payload.source || 'local');
    sourceStatus.className = `calendar-status-chip ${payload.source === 'google' ? 'live' : 'fallback'}`;
  }
  const timezone = $('#calendar-timezone');
  if (timezone) timezone.textContent = calendarTimezoneLabel(payload);

  const dates = calendarWeekDates(weekStart);
  const today = new Date();
  dayHeaders.innerHTML = `<div class="calendar-week-corner" aria-hidden="true"></div>${dates.map((date) => {
    const isToday = sameCalendarDay(date, today);
    return `<div class="calendar-week-day-header ${isToday ? 'is-today' : ''}" data-calendar-date="${calendarDateKey(date)}"${isToday ? ' aria-current="date"' : ''}><span class="calendar-week-day-name">${escapeHtml(new Intl.DateTimeFormat(undefined, { weekday: 'short' }).format(date))}</span><strong class="calendar-week-day-number">${date.getDate()}</strong></div>`;
  }).join('')}`;

  const allDayByDay = calendarAllDayItemsByDay(items, weekStart);
  allDayEvents.innerHTML = allDayByDay.map((dayItems, index) => `<div class="calendar-week-all-day-cell" data-calendar-date="${calendarDateKey(dates[index])}">${dayItems.map((item) => calendarWeekEventButton(item)).join('')}</div>`).join('');

  const timedByDay = calendarTimedSegmentsByDay(items, weekStart);
  const { startHour, endHour } = calendarVisibleHours(timedByDay);
  const visibleHours = endHour - startHour;
  shell.style.setProperty('--calendar-grid-height', `calc(var(--calendar-hour-height) * ${visibleHours})`);
  timeLabels.innerHTML = Array.from({ length: visibleHours + 1 }, (_, index) => {
    const hour = startHour + index;
    const labelDate = new Date(2020, 0, 1, hour % 24);
    const top = (index / visibleHours) * 100;
    return `<span class="calendar-week-hour-label" style="top:${top.toFixed(4)}%">${escapeHtml(new Intl.DateTimeFormat(undefined, { hour: 'numeric' }).format(labelDate))}</span>`;
  }).join('');
  events.innerHTML = timedByDay.map((segments, dayIndex) => {
    const laidOut = layoutCalendarDayOverlaps(segments);
    return `<div class="calendar-week-day-column ${sameCalendarDay(dates[dayIndex], today) ? 'is-today' : ''}" data-calendar-date="${calendarDateKey(dates[dayIndex])}">${laidOut.map((segment) => calendarWeekEventButton(segment.item, { timed: true, segment, startHour, endHour })).join('')}</div>`;
  }).join('');

  const nowLine = $('#calendar-now-line');
  if (nowLine) {
    const todayInWeek = today >= weekStart && today < calendarAddDays(weekStart, 7);
    const minute = today.getHours() * 60 + today.getMinutes();
    const visibleNow = minute >= startHour * 60 && minute <= endHour * 60;
    nowLine.hidden = !(todayInWeek && visibleNow);
    if (!nowLine.hidden) {
      nowLine.style.top = `${((minute - startHour * 60) / (visibleHours * 60) * 100).toFixed(4)}%`;
      const nowLabel = nowLine.querySelector('.calendar-week-now-label');
      if (nowLabel) nowLabel.textContent = timeFmt.format(today);
    }
  }
  shell.setAttribute('aria-busy', 'false');
  renderCalendarEventInspector();
}

function renderCalendarWeekLoading(weekStart) {
  const shell = $('#calendar-week');
  if (shell) shell.setAttribute('aria-busy', 'true');
  const label = $('#calendar-week-range') || $('#calendar-week-label');
  if (label) label.textContent = calendarWeekLabel(weekStart);
  const status = $('#calendar-source-status');
  if (status) status.textContent = 'Loading calendar week…';
  const dates = calendarWeekDates(weekStart);
  const today = new Date();
  const dayHeaders = $('#calendar-week-days');
  if (dayHeaders) dayHeaders.innerHTML = `<div class="calendar-week-corner" aria-hidden="true"></div>${dates.map((date) => {
    const isToday = sameCalendarDay(date, today);
    return `<div class="calendar-week-day-header ${isToday ? 'is-today' : ''}" data-calendar-date="${calendarDateKey(date)}"${isToday ? ' aria-current="date"' : ''}><span class="calendar-week-day-name">${escapeHtml(new Intl.DateTimeFormat(undefined, { weekday: 'short' }).format(date))}</span><strong class="calendar-week-day-number">${date.getDate()}</strong></div>`;
  }).join('')}`;
  ['#calendar-all-day-events', '#calendar-time-labels', '#calendar-week-events'].forEach((selector) => {
    const container = $(selector);
    if (container) container.innerHTML = '';
  });
  const nowLine = $('#calendar-now-line');
  if (nowLine) nowLine.hidden = true;
  state.calendarWeekRenderedItems = [];
  renderCalendarEventInspector();
}

async function loadCalendarWeek(weekStart) {
  const normalizedStart = startOfCalendarWeek(weekStart);
  if (!normalizedStart) return;
  const weekKey = calendarDateKey(normalizedStart);
  state.calendarWeekStart = weekKey;
  state.calendarSelectedEventKey = '';
  const requestToken = (state.calendarWeekRequestToken || 0) + 1;
  state.calendarWeekRequestToken = requestToken;
  renderCalendarWeekLoading(normalizedStart);
  try {
    const payload = await api(calendarWeekRequestUrl(normalizedStart));
    if (requestToken !== state.calendarWeekRequestToken || state.calendarWeekStart !== weekKey || state.activeView !== 'calendar') return;
    renderCalendar(payload, { view: 'calendar' });
  } catch (err) {
    if (requestToken !== state.calendarWeekRequestToken || state.calendarWeekStart !== weekKey) return;
    const shell = $('#calendar-week');
    if (shell) shell.setAttribute('aria-busy', 'false');
    const status = $('#calendar-source-status');
    if (status) status.textContent = `Calendar failed: ${err.message}`;
  }
}

function navigateCalendarWeek(direction) {
  const current = calendarWeekStartDate();
  const target = direction === 'today'
    ? startOfCalendarWeek(new Date())
    : calendarAddDays(current, direction === 'previous' ? -7 : 7);
  return loadCalendarWeek(target);
}

function renderCalendarInto(selector, payload = {}, { limit = Infinity } = {}) {
  const container = $(selector);
  if (!container) return;
  const items = Array.isArray(payload) ? payload : (payload.items || []);
  const visible = sortedCalendarItems(items).slice(0, limit);
  const source = Array.isArray(payload) ? 'local' : (payload.source || 'local');
  const auth = Array.isArray(payload) ? 'legacy' : (payload.auth || 'unknown');
  const verified = calendarPayloadIsVerified(payload);
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
        ${groupItems.map((item) => {
          const linkedTask = taskLinkedToCalendarEvent(item.id || '');
          const actions = calendarEventActionMarkup(item, linkedTask, { verified });
          return `
          <article class="item calendar-event ${source === 'google' ? 'google-event' : 'local-event'}">
            <div class="calendar-event-time mono">${escapeHtml(calendarTimeLabel(item))}</div>
            <div class="calendar-event-body">
              <div class="item-title"><span>${escapeHtml(item.title || 'Untitled event')}</span><span class="pill">${escapeHtml(item.type || 'event')}</span></div>
              <div class="item-desc">${escapeHtml(item.description || item.location || '')}</div>
              <div class="item-meta mono">${escapeHtml(item.location || source)}${verified ? calendarEventLink(item) : ''}</div>
              ${actions ? `<div class="calendar-task-actions">${actions}</div>` : ''}
            </div>
          </article>
        `; }).join('')}
      </div>
    </section>
  `).join('');

  const overflow = items.length > visible.length
    ? `<div class="item-meta mono calendar-overflow">+${items.length - visible.length} later events hidden in this compact view.</div>`
    : '';
  container.innerHTML = `${summaryMarkup}${groupMarkup}${overflow}`;
}

function renderCalendar(payload = {}, { view = state.activeView } = {}) {
  if (view === 'calendar') {
    renderCalendarWeek(payload, calendarWeekStartDate());
    return;
  }
  renderCalendarInto('#calendar-list', payload, { limit: 5 });
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

const agentConsoleCommandHandlers = new Set([
  'agent_console.refresh_models',
  'agent_console.new_session',
  'agent_console.show_help',
]);

function normalizeAgentConsoleCommandManifest(payload = {}) {
  if (payload.schema_version !== 1 || payload.source !== 'mentat') return null;
  if (payload.capabilities?.['commands.manifest.read'] !== true) return null;
  const commands = Array.isArray(payload.commands) ? payload.commands.filter((item) => (
    typeof item?.command === 'string'
    && /^\/[a-z][a-z0-9-]*$/.test(item.command)
    && agentConsoleCommandHandlers.has(item.handler)
    && Array.isArray(item.arguments)
    && item.arguments.every((argument) => (
      typeof argument?.name === 'string'
      && typeof argument.required === 'boolean'
      && typeof argument.description === 'string'
    ))
    && typeof item.description === 'string'
    && ['read_only', 'local_state'].includes(item.safety)
  )) : [];
  if (!commands.length || commands.length !== payload.commands?.length) return null;
  if (new Set(commands.map((item) => item.command)).size !== commands.length) return null;
  return { ...payload, commands };
}

function setAgentConsoleCommandManifest(payload = {}) {
  state.agentConsoleCommandManifest = normalizeAgentConsoleCommandManifest(payload);
  renderAgentConsoleCommandMenu();
}

function agentConsoleCommands() {
  return state.agentConsoleCommandManifest?.commands || [];
}

function agentConsoleRunIsActive(run = {}) {
  return ['queued', 'running', 'cancelling'].includes(run.status);
}

function agentConsoleEventCursor(run = {}) {
  const cursors = (run.events || []).map((event) => Number(event.cursor || event.sequence || 0));
  return Math.max(Number(run.event_cursor || 0), ...cursors, 0);
}

function mergeAgentConsoleRunUpdate(current = {}, incoming = {}, events = [], reset = false) {
  const retained = reset ? [] : (current.events || []);
  const byCursor = new Map();
  [...retained, ...events].forEach((event) => {
    const cursor = Number(event.cursor || event.sequence || 0);
    if (cursor > 0) byCursor.set(cursor, event);
  });
  return {
    ...current,
    ...incoming,
    events: [...byCursor.entries()].sort(([left], [right]) => left - right).map(([, event]) => event),
  };
}

function agentConsoleCommandSuggestions(value = '') {
  const query = String(value || '').trim().toLowerCase();
  if (!query.startsWith('/')) return [];
  return agentConsoleCommands().filter((item) => item.command.startsWith(query) || query === '/help');
}

function renderAgentConsoleCommandMenu() {
  const prompt = $('#agent-console-prompt');
  const menu = $('#agent-console-command-menu');
  if (!prompt || !menu) return;
  const suggestions = agentConsoleCommandSuggestions(prompt.value);
  menu.hidden = !suggestions.length;
  menu.innerHTML = suggestions.map((item) => `
    <button type="button" class="agent-console-command-option" data-agent-console-command="${escapeHtml(item.command)}">
      <code>${escapeHtml(item.command)}</code><span>${escapeHtml(item.description)}</span>
    </button>
  `).join('');
}

function safeAgentConsoleContentUrl(value = '') {
  try {
    const url = new URL(String(value || ''), window.location.origin);
    if (!['http:', 'https:'].includes(url.protocol) || url.origin !== window.location.origin) return '';
    if (!/^\/api\/agent-console\/attachments\/attachment_[a-f0-9]{32}\/content$/.test(url.pathname)) return '';
    return `${url.pathname}${url.search}`;
  } catch {
    return '';
  }
}

function agentConsoleAttachmentSize(value) {
  const bytes = Number(value || 0);
  if (!Number.isFinite(bytes) || bytes <= 0) return '';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

const AGENT_CONSOLE_INLINE_IMAGE_TYPES = new Set([
  'image/png',
  'image/jpeg',
  'image/gif',
  'image/webp',
]);

function agentConsoleAttachmentCards(attachments = [], { removable = false } = {}) {
  return attachments.map((attachment) => {
    const id = String(attachment?.id || '');
    const name = String(attachment?.name || 'Attachment');
    const kind = String(attachment?.kind || 'file');
    const mimeType = String(attachment?.mime_type || '');
    const contentUrl = safeAgentConsoleContentUrl(attachment?.content_url);
    const isImage = kind === 'image' || mimeType.startsWith('image/');
    const canEmbedImage = isImage && AGENT_CONSOLE_INLINE_IMAGE_TYPES.has(mimeType.toLowerCase());
    const preview = canEmbedImage && contentUrl
      ? `<img src="${escapeHtml(contentUrl)}" alt="" loading="lazy" />`
      : `<span class="agent-console-attachment-icon mono" aria-hidden="true">${isImage ? 'IMG' : 'FILE'}</span>`;
    const size = agentConsoleAttachmentSize(attachment?.byte_size);
    const attachmentState = removable ? [size, 'Attached'].filter(Boolean).join(' · ') : size || (isImage ? 'Image' : 'File');
    const remove = removable && id
      ? `<button type="button" class="agent-console-attachment-remove" data-remove-agent-console-attachment="${escapeHtml(id)}" aria-label="Remove ${escapeHtml(name)}" title="Remove attachment">×</button>`
      : '';
    const download = contentUrl && !removable
      ? `<a class="agent-console-attachment-download mono" href="${escapeHtml(contentUrl)}" download="${escapeHtml(name)}" aria-label="Download ${escapeHtml(name)}">Download</a>`
      : '';
    return `<div class="agent-console-attachment-card" data-agent-console-attachment-id="${escapeHtml(id)}">${preview}<span class="agent-console-attachment-copy"><strong>${escapeHtml(name)}</strong><small class="mono">${escapeHtml(attachmentState)}</small></span>${download}${remove}</div>`;
  }).join('');
}

function agentConsoleArtifactCards(artifacts = []) {
  if (!artifacts.length) return '';
  const cards = artifacts.map((artifact) => {
    const name = String(artifact?.name || 'Generated file');
    const kind = String(artifact?.kind || 'file');
    const mimeType = String(artifact?.mime_type || '').toLowerCase();
    const contentUrl = safeAgentConsoleContentUrl(artifact?.content_url);
    const canEmbedImage = kind === 'image' && AGENT_CONSOLE_INLINE_IMAGE_TYPES.has(mimeType) && contentUrl;
    const preview = canEmbedImage
      ? `<img src="${escapeHtml(contentUrl)}" alt="${escapeHtml(name)}" loading="lazy" />`
      : `<span class="agent-console-artifact-icon mono" aria-hidden="true">${kind === 'code' ? 'CODE' : kind === 'image' ? 'IMG' : 'FILE'}</span>`;
    const size = agentConsoleAttachmentSize(artifact?.byte_size);
    const download = contentUrl
      ? `<a class="mini-button agent-console-artifact-download" href="${escapeHtml(contentUrl)}" download="${escapeHtml(name)}">Download</a>`
      : '<span class="mono agent-console-artifact-unavailable">Unavailable</span>';
    return `<article class="agent-console-artifact-card ${canEmbedImage ? 'image' : ''}">${preview}<div class="agent-console-artifact-copy"><strong>${escapeHtml(name)}</strong><span class="mono">${escapeHtml([kind, size].filter(Boolean).join(' · '))}</span></div>${download}</article>`;
  }).join('');
  return `<section class="agent-console-artifacts" aria-label="Generated files"><h4 class="mono">Generated files</h4><div class="agent-console-artifact-grid">${cards}</div></section>`;
}

async function copyRenderedCode(button) {
  const code = button.closest('.markdown-code-block')?.querySelector('code')?.textContent || '';
  if (!code) return;
  const originalLabel = button.textContent;
  try {
    if (!navigator.clipboard?.writeText) throw new Error('Clipboard unavailable');
    await navigator.clipboard.writeText(code);
    button.textContent = 'Copied';
  } catch {
    button.textContent = 'Copy failed';
  }
  window.setTimeout(() => {
    if (button.isConnected) button.textContent = originalLabel;
  }, 1600);
}

function clearAgentConsoleRemoteContext({ removeAttachments = false } = {}) {
  const staged = state.agentConsoleRemoteContext;
  if (removeAttachments && staged) {
    const stagedIds = new Set(staged.attachment_ids || []);
    state.agentConsoleAttachments = state.agentConsoleAttachments.filter((item) => !stagedIds.has(item.id));
  }
  state.agentConsoleRemoteContext = null;
}

function renderAgentConsoleAttachmentTray() {
  const tray = $('#agent-console-attachment-tray');
  if (!tray) return;
  const attachmentCount = state.agentConsoleAttachments.length;
  const uploadError = String(state.agentConsoleAttachmentError || '');
  tray.hidden = !attachmentCount && !state.agentConsoleAttachmentsUploading && !uploadError;
  if (tray.hidden) {
    tray.innerHTML = '';
    return;
  }
  const summary = state.agentConsoleAttachmentsUploading
    ? 'Uploading…'
    : attachmentCount
      ? `${attachmentCount} ready for next prompt`
      : 'Upload failed';
  const items = attachmentCount || state.agentConsoleAttachmentsUploading
    ? `<div class="agent-console-attachment-items">${agentConsoleAttachmentCards(state.agentConsoleAttachments, { removable: true })}${state.agentConsoleAttachmentsUploading ? '<div class="agent-console-attachment-card uploading mono" role="status">Uploading…</div>' : ''}</div>`
    : '';
  const error = uploadError
    ? `<div class="agent-console-attachment-error" role="alert"><span aria-hidden="true">!</span><strong>${escapeHtml(uploadError)}</strong><button type="button" data-dismiss-agent-console-attachment-error aria-label="Dismiss attachment error">×</button></div>`
    : '';
  tray.innerHTML = `<div class="agent-console-attachment-tray-head"><strong>Prompt attachments</strong><span class="mono">${escapeHtml(summary)}</span></div>${items}${error}`;
}

function agentConsoleUploadErrorMessage(error) {
  const message = String(error?.message || error || 'Attachment upload failed.');
  if (message.includes('256,000 bytes or fewer')) {
    return 'Upload failed because Mentat is running an older server build. Restart Mentat and try again.';
  }
  return `Upload failed: ${message}`;
}

function setAgentConsoleAttachmentMenu(open) {
  const menu = $('#agent-console-attachment-menu');
  const trigger = $('#agent-console-attach');
  if (menu) menu.hidden = !open;
  if (trigger) trigger.setAttribute('aria-expanded', open ? 'true' : 'false');
  if (!open) closeAgentConsoleWorkspacePicker();
}

function safeAgentConsoleWorkspaceChoice(rootId, relativePath) {
  const normalizedRootId = String(rootId || '').trim();
  const normalizedPath = String(relativePath || '').trim();
  const parts = normalizedPath.split('/');
  if (!/^[A-Za-z0-9_-]{1,64}$/.test(normalizedRootId)) return null;
  if (
    !normalizedPath
    || normalizedPath.length > 500
    || normalizedPath.includes('\0')
    || normalizedPath.startsWith('/')
    || normalizedPath.includes('\\')
    || /^[A-Za-z]:/.test(normalizedPath)
    || parts.some((part) => !part || part === '.' || part === '..')
  ) return null;
  return { root_id: normalizedRootId, relative_path: normalizedPath };
}

function closeAgentConsoleWorkspacePicker() {
  clearTimeout(state.agentConsoleWorkspaceSearchTimer);
  state.agentConsoleWorkspaceSearchTimer = null;
  state.agentConsoleWorkspaceRequestToken += 1;
  const choices = $('#agent-console-attachment-choices');
  const picker = $('#agent-console-workspace-picker');
  const contextPicker = $('#agent-console-context-pack-picker');
  if (choices) choices.hidden = false;
  if (picker) picker.hidden = true;
  if (contextPicker) contextPicker.hidden = true;
}

function renderAgentConsoleWorkspaceResults(payload = {}, status = 'ready') {
  const results = $('#agent-console-workspace-results');
  if (!results) return;
  if (status === 'loading') {
    results.innerHTML = '<div class="agent-console-workspace-state mono" role="status">Loading workspace files…</div>';
    return;
  }
  if (status === 'error') {
    results.innerHTML = `<div class="agent-console-workspace-state error mono" role="alert">${escapeHtml(payload.error || 'Workspace files are unavailable.')}</div>`;
    return;
  }
  const rawFiles = Array.isArray(payload.files) ? payload.files : Array.isArray(payload.results) ? payload.results : [];
  const files = rawFiles.map((file) => {
    const choice = safeAgentConsoleWorkspaceChoice(file?.root_id, file?.relative_path ?? file?.path);
    return choice ? {
      ...choice,
      kind: String(file?.kind || 'file'),
      byte_size: Number(file?.byte_size || 0),
    } : null;
  }).filter(Boolean).slice(0, 40);
  if (!files.length) {
    results.innerHTML = '<div class="agent-console-workspace-state mono">No matching workspace files.</div>';
    return;
  }
  results.innerHTML = files.map((file) => `
    <button type="button" class="agent-console-workspace-result" role="option" data-agent-console-workspace-root="${escapeHtml(file.root_id)}" data-agent-console-workspace-path="${escapeHtml(file.relative_path)}">
      <strong>${escapeHtml(file.relative_path)}</strong>
      <span class="mono">${escapeHtml([file.kind || 'file', agentConsoleAttachmentSize(file.byte_size)].filter(Boolean).join(' · '))}</span>
    </button>
  `).join('');
}

async function searchAgentConsoleWorkspaceFiles(query = '') {
  const requestToken = ++state.agentConsoleWorkspaceRequestToken;
  renderAgentConsoleWorkspaceResults({}, 'loading');
  try {
    const payload = await fetchAgentConsoleWorkspaceFiles(query);
    if (requestToken !== state.agentConsoleWorkspaceRequestToken) return;
    renderAgentConsoleWorkspaceResults(payload);
  } catch (err) {
    if (requestToken !== state.agentConsoleWorkspaceRequestToken) return;
    renderAgentConsoleWorkspaceResults({ error: err.message }, 'error');
  }
}

function queueAgentConsoleWorkspaceSearch() {
  clearTimeout(state.agentConsoleWorkspaceSearchTimer);
  state.agentConsoleWorkspaceSearchTimer = setTimeout(() => {
    void searchAgentConsoleWorkspaceFiles($('#agent-console-workspace-query')?.value || '');
  }, 180);
}

function openAgentConsoleWorkspacePicker() {
  const choices = $('#agent-console-attachment-choices');
  const picker = $('#agent-console-workspace-picker');
  if (choices) choices.hidden = true;
  if (picker) picker.hidden = false;
  const query = $('#agent-console-workspace-query');
  if (query) query.value = '';
  void searchAgentConsoleWorkspaceFiles('');
  query?.focus();
}

async function addAgentConsoleWorkspaceFile(rootId, relativePath) {
  const status = $('#agent-console-form-status');
  const choice = safeAgentConsoleWorkspaceChoice(rootId, relativePath);
  if (!choice || state.agentConsoleAttachmentsUploading) {
    if (status && !choice) status.textContent = 'Mentat rejected an unsafe workspace file selection.';
    return;
  }
  clearAgentConsoleRemoteContext({ removeAttachments: true });
  state.agentConsoleAttachmentError = '';
  state.agentConsoleAttachmentsUploading = true;
  renderAgentConsoleWorkspaceResults({}, 'loading');
  try {
    const payload = await createAgentConsoleWorkspaceAttachment(choice.root_id, choice.relative_path);
    const attachment = payload.attachment || payload;
    if (!attachment?.id) throw new Error('Mentat returned an invalid workspace attachment.');
    if (!state.agentConsoleAttachments.some((item) => item.id === attachment.id)) {
      state.agentConsoleAttachments.push(attachment);
    }
    renderAgentConsoleAttachmentTray();
    setAgentConsoleAttachmentMenu(false);
    if (status) status.textContent = `${choice.relative_path} attached as a private snapshot.`;
    $('#agent-console-prompt')?.focus();
  } catch (err) {
    state.agentConsoleAttachmentError = agentConsoleUploadErrorMessage(err);
    renderAgentConsoleWorkspaceResults({ error: err.message }, 'error');
    if (status) status.textContent = state.agentConsoleAttachmentError;
  } finally {
    state.agentConsoleAttachmentsUploading = false;
    renderAgentConsoleAttachmentTray();
    const activeRun = state.agentConsoleRuns.some(agentConsoleRunIsActive);
    const selectedAgent = state.agentConsoleAgents.find((agent) => agent.id === state.agentConsoleSelectedAgentId);
    const attach = $('#agent-console-attach');
    const send = $('#agent-console-form .agent-console-send');
    if (attach) attach.disabled = !selectedAgent?.available || activeRun;
    if (send) send.disabled = !selectedAgent?.available || activeRun;
  }
}

async function addAgentConsoleFiles(files = []) {
  const status = $('#agent-console-form-status');
  if (!files.length || state.agentConsoleAttachmentsUploading) return;
  clearAgentConsoleRemoteContext({ removeAttachments: true });
  state.agentConsoleAttachmentError = '';
  state.agentConsoleAttachmentsUploading = true;
  const attach = $('#agent-console-attach');
  const send = $('#agent-console-form .agent-console-send');
  if (attach) attach.disabled = true;
  if (send) send.disabled = true;
  renderAgentConsoleAttachmentTray();
  if (status) status.textContent = `Uploading ${files.length} attachment${files.length === 1 ? '' : 's'}…`;
  try {
    const knownIds = new Set(state.agentConsoleAttachments.map((item) => item.id));
    const uploaded = await uploadAgentConsoleAttachments(files, (item) => {
      if (!item?.id || knownIds.has(item.id)) return;
      knownIds.add(item.id);
      state.agentConsoleAttachments.push(item);
      renderAgentConsoleAttachmentTray();
    });
    if (status) status.textContent = `${uploaded.length} attachment${uploaded.length === 1 ? '' : 's'} ready.`;
  } catch (err) {
    state.agentConsoleAttachmentError = agentConsoleUploadErrorMessage(err);
    if (status) status.textContent = state.agentConsoleAttachmentError;
  } finally {
    state.agentConsoleAttachmentsUploading = false;
    const input = $('#agent-console-file-input');
    if (input) input.value = '';
    renderAgentConsoleAttachmentTray();
    const activeRun = state.agentConsoleRuns.some(agentConsoleRunIsActive);
    const selectedAgent = state.agentConsoleAgents.find((agent) => agent.id === state.agentConsoleSelectedAgentId);
    if (attach) attach.disabled = !selectedAgent?.available || activeRun;
    if (send) send.disabled = !selectedAgent?.available || activeRun;
  }
}

function renderAgentConsole(payload = {}) {
  const chat = $('#agent-console-chat');
  const agentSelect = $('#agent-console-agent');
  const providerSelect = $('#agent-console-provider-select');
  const modelSelect = $('#agent-console-model-select');
  const applyModel = $('#agent-console-apply-model');
  const prompt = $('#agent-console-prompt');
  const send = $('#agent-console-form .agent-console-send');
  const stop = $('#agent-console-stop');
  const newSession = $('#agent-console-new-session');
  const stateLabel = $('#agent-console-state');
  const presence = $('#agent-console-presence');
  if (!chat || !agentSelect) return;

  if (payload.transport?.mode && payload.transport?.binding_id) {
    const nextBinding = `${payload.transport.mode}:${payload.transport.binding_id}`;
    if (
      state.agentConsoleRemoteContext
      && state.agentConsoleRemoteContext.transport_binding !== nextBinding
    ) {
      clearAgentConsoleRemoteContext({ removeAttachments: true });
      renderAgentConsoleAttachmentTray();
    }
    state.agentConsoleTransportBinding = nextBinding;
  }

  const agents = Array.isArray(payload.agents) ? payload.agents : state.agentConsoleAgents;
  const requestedAgentId = state.agentConsoleSelectedAgentId || agentSelect.value || payload.selected_agent_id || 'default';
  const selectedAgentId = agents.some((agent) => agent.id === requestedAgentId)
    ? requestedAgentId
    : agents[0]?.id || 'default';
  const incomingCatalog = payload.model_catalog;
  const catalog = incomingCatalog?.profile_id && incomingCatalog.profile_id !== selectedAgentId
    && state.agentConsoleModelCatalog?.profile_id === selectedAgentId
    ? state.agentConsoleModelCatalog
    : incomingCatalog || state.agentConsoleModelCatalog || {};
  const incomingProviderInventory = payload.provider_inventory;
  const providerInventory = incomingProviderInventory?.profile_id && incomingProviderInventory.profile_id !== selectedAgentId
    && state.agentConsoleProviderInventory?.profile_id === selectedAgentId
    ? state.agentConsoleProviderInventory
    : incomingProviderInventory || state.agentConsoleProviderInventory || {};
  const providers = Array.isArray(providerInventory.providers) ? providerInventory.providers : [];
  const runs = Array.isArray(payload.runs) ? payload.runs : state.agentConsoleRuns;
  state.agentConsoleAgents = agents;
  state.agentConsoleModelCatalog = catalog;
  state.agentConsoleProviderInventory = providerInventory;
  state.agentConsoleRuns = runs;
  runs.forEach((run) => {
    const cursor = agentConsoleEventCursor(run);
    if (cursor > Number(state.agentConsoleEventCursors[run.id] || 0)) {
      state.agentConsoleEventCursors[run.id] = cursor;
    }
  });

  agentSelect.innerHTML = agents.length
    ? agents.map((agent) => `<option value="${escapeHtml(agent.id)}" ${agent.id === selectedAgentId ? 'selected' : ''}>${escapeHtml(agent.name)}</option>`).join('')
    : '<option value="default">Hermes · default</option>';
  state.agentConsoleSelectedAgentId = agentSelect.value || selectedAgentId;
  const selectedAgent = agents.find((agent) => agent.id === agentSelect.value) || agents[0] || { available: false, model: '' };
  const inventoryMatchesAgent = !providerInventory.profile_id || providerInventory.profile_id === selectedAgent.id;
  const scopedProviders = inventoryMatchesAgent ? providers : [];
  const providerSwitchAvailable = providerInventory.capabilities?.['providers.switch'] === true;
  const providerSwitchUnavailable = inventoryMatchesAgent
    && Object.prototype.hasOwnProperty.call(providerInventory.capabilities || {}, 'providers.switch')
    && !providerSwitchAvailable;
  const requestedProvider = state.agentConsoleSelectedProvider || providerInventory.current_provider || selectedAgent.provider || '';
  const selectedProvider = scopedProviders.find((item) => item.id === requestedProvider) || scopedProviders.find((item) => item.current) || scopedProviders[0];
  if (providerSelect) {
    providerSelect.innerHTML = scopedProviders.length
      ? scopedProviders.map((item) => `<option value="${escapeHtml(item.id)}" ${item.id === selectedProvider?.id ? 'selected' : ''}>${escapeHtml(item.name || item.id)}${item.current ? ' · current' : ''}</option>`).join('')
      : `<option value="">${escapeHtml(inventoryMatchesAgent ? providerInventory.error || 'No authenticated providers available' : 'Refresh providers for this profile')}</option>`;
    state.agentConsoleSelectedProvider = providerSelect.value;
  }
  const scopedModels = Array.isArray(selectedProvider?.models) ? selectedProvider.models : [];
  state.agentConsoleModels = scopedModels;
  const currentModelForProvider = selectedProvider?.id === providerInventory.current_provider ? providerInventory.current_model : '';
  const defaultModel = [state.agentConsoleSelectedModel, currentModelForProvider, selectedAgent.model].find((item) => scopedModels.includes(item)) || scopedModels[0] || '';
  if (modelSelect) {
    modelSelect.innerHTML = scopedModels.length
      ? scopedModels.map((model) => `<option value="${escapeHtml(model)}" ${model === defaultModel ? 'selected' : ''}>${escapeHtml(model)}</option>`).join('')
      : `<option value="">${escapeHtml(inventoryMatchesAgent ? providerInventory.error || 'No models available for this provider' : 'Refresh providers for this profile')}</option>`;
    state.agentConsoleSelectedModel = modelSelect.value;
  }

  const activeRun = runs.find(agentConsoleRunIsActive);
  const selectedRuns = runs.filter((run) => (run.agent_id || 'default') === selectedAgent.id);
  const latestRun = selectedRuns[0];
  if (latestRun?.session_id && !state.agentConsoleStartFresh) state.agentConsoleSessionId = latestRun.session_id;
  state.agentConsoleRunId = activeRun?.id || '';
  const available = Boolean(selectedAgent.available);
  const modelLabel = modelSelect?.value || selectedAgent.model || 'configured model';
  const providerLabel = selectedProvider?.name || selectedProvider?.id || catalog.provider_label || catalog.provider || 'Hermes';
  const providerCapabilityLabel = providerSwitchUnavailable ? ' · provider switching unsupported by this Hermes runtime' : '';
  if (stateLabel) {
    stateLabel.textContent = !available
      ? `Hermes CLI unavailable${providerCapabilityLabel}`
      : activeRun
        ? `${providerLabel} · ${modelLabel} · working${providerCapabilityLabel}`
        : `${providerLabel} · ${modelLabel} · ready${providerCapabilityLabel}`;
    stateLabel.title = providerSwitchUnavailable
      ? available
        ? 'This Hermes runtime does not expose supported provider switching. Agent execution remains available with the current provider and model.'
        : 'This Hermes runtime does not expose supported provider switching.'
      : '';
  }
  if (presence) presence.className = `agent-console-presence ${activeRun ? 'working' : available ? 'ready' : 'offline'}`;
  if (prompt) prompt.disabled = !available || Boolean(activeRun);
  if (send) send.disabled = !available || Boolean(activeRun);
  const attach = $('#agent-console-attach');
  if (attach) attach.disabled = !available || Boolean(activeRun) || state.agentConsoleAttachmentsUploading;
  if (providerSelect) providerSelect.disabled = !available || !providerSwitchAvailable || Boolean(activeRun) || !scopedProviders.length;
  if (modelSelect) modelSelect.disabled = !available || !providerSwitchAvailable || Boolean(activeRun) || !scopedModels.length;
  if (applyModel) applyModel.disabled = !available || !providerSwitchAvailable || Boolean(activeRun) || !modelSelect?.value;
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
        <time class="mono">${escapeHtml(timeFmt.format(new Date(event.timestamp || Date.now())))}</time><span>${escapeHtml(runAgentName)}</span><span>${escapeHtml(event.display_text || event.message || 'Working')}</span>
      </div>`).join('');
    const working = agentConsoleRunIsActive(run) ? `
      <div class="agent-console-log-row agent-console-working" role="status"><span class="agent-console-working-mark" aria-hidden="true"><i></i><i></i><i></i></span><span>${escapeHtml(runAgentName)}</span><span>${run.status === 'cancelling' ? 'Stopping' : 'Working'}</span></div>` : '';
    const storedSummaryLabel = run.persisted_summary ? 'Stored summary' : '';
    const promptExcerpt = run.prompt_truncated || storedSummaryLabel ? `<span class="mono">${run.prompt_truncated ? 'Stored excerpt' : storedSummaryLabel}</span>` : '';
    const responseExcerpt = run.response_truncated || storedSummaryLabel ? `<span class="mono">${run.response_truncated ? 'Stored excerpt' : storedSummaryLabel}</span>` : '';
    const outputArtifacts = Array.isArray(run.artifacts) ? run.artifacts : Array.isArray(run.output_artifacts) ? run.output_artifacts : [];
    const artifactCards = agentConsoleArtifactCards(outputArtifacts);
    const response = run.response || artifactCards ? `<div class="agent-console-log-row agent-console-log-response"><span class="mono">${escapeHtml(runAgentName)}</span><div class="message-content markdown-body">${run.response ? renderMarkdown(run.response) : ''}${artifactCards}</div>${responseExcerpt}</div>` : '';
    const errorExcerpt = run.error_truncated || storedSummaryLabel ? `<span class="mono">${run.error_truncated ? 'Stored excerpt' : storedSummaryLabel}</span>` : '';
    const error = run.error ? `<div class="agent-console-log-row agent-console-log-error"><span class="mono">${run.status === 'cancelled' ? 'Stopped' : 'Error'}</span><div class="message-content">${escapeHtml(run.error)}</div>${errorExcerpt}</div>` : '';
    const inputAttachments = Array.isArray(run.attachments) ? run.attachments : Array.isArray(run.input_attachments) ? run.input_attachments : [];
    const attachmentCards = inputAttachments.length
      ? `<section class="agent-console-run-attachment-context" aria-label="Files used as prompt context"><span class="mono">Used as prompt context · ${inputAttachments.length} file${inputAttachments.length === 1 ? '' : 's'}</span><div class="agent-console-run-attachments">${agentConsoleAttachmentCards(inputAttachments)}</div></section>`
      : '';
    return `<section class="agent-console-turn"><div class="agent-console-log-row agent-console-log-prompt"><time class="mono">${escapeHtml(timeFmt.format(new Date(run.created_at || Date.now())))}</time><span>You</span><div class="message-content">${escapeHtml(run.prompt || '')}${attachmentCards}</div>${promptExcerpt}</div><div class="agent-console-events">${events}</div>${working}${response}${error}</section>`;
  }).join('') : `<div class="agent-console-empty mono">${escapeHtml(payload.error || (available ? 'Hermes ready.' : 'Hermes CLI unavailable.'))}</div>`;
  if (wasNearBottom || activeRun) chat.scrollTop = chat.scrollHeight;
  scheduleAgentConsolePoll(Boolean(activeRun));
}

function scheduleAgentConsolePoll(shouldPoll = true) {
  clearTimeout(state.agentConsolePollTimer);
  state.agentConsolePollTimer = null;
  if (!shouldPoll || state.activeView !== 'today') return;
  state.agentConsolePollTimer = setTimeout(async () => {
    const activeRun = state.agentConsoleRuns.find(agentConsoleRunIsActive);
    if (!activeRun) return;
    const cursor = Number(state.agentConsoleEventCursors[activeRun.id] ?? agentConsoleEventCursor(activeRun));
    try {
      const payload = await fetchAgentConsoleRun(activeRun.id, cursor);
      const updated = mergeAgentConsoleRunUpdate(
        activeRun,
        payload.run || {},
        payload.events || payload.run?.events || [],
        Boolean(payload.cursor_reset_required),
      );
      state.agentConsoleEventCursors[activeRun.id] = Number(payload.next_cursor ?? agentConsoleEventCursor(updated));
      renderAgentConsole({
        agents: state.agentConsoleAgents,
        model_catalog: state.agentConsoleModelCatalog,
        runs: state.agentConsoleRuns.map((run) => run.id === activeRun.id ? updated : run),
      });
    } catch (err) {
      const status = $('#agent-console-form-status');
      if (status) status.textContent = err.message;
      scheduleAgentConsolePoll(true);
    }
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
    renderAgentConsole({ agents: state.agentConsoleAgents, model_catalog: payload.model_catalog, provider_inventory: payload.provider_inventory, runs: state.agentConsoleRuns });
    if (status) status.textContent = '';
    if (focus) $('#agent-console-model-select')?.focus();
    return payload.model_catalog;
  } catch (err) {
    if (status) status.textContent = err.message;
    return null;
  }
}

async function applyAgentConsoleModel() {
  const provider = $('#agent-console-provider-select')?.value || '';
  const model = $('#agent-console-model-select')?.value || '';
  const status = $('#agent-console-form-status');
  if (!provider || !model) return;
  if (status) status.textContent = 'Preparing provider change preview…';
  try {
    const preview = await previewAgentConsoleProvider(provider, model, state.agentConsoleSelectedAgentId);
    state.agentConsoleProviderPreview = preview;
    state.agentConsoleProviderPreviewSource = 'console';
    const review = $('#provider-switch-review');
    if (review) review.innerHTML = `
      <p>Apply this configuration to <strong>${escapeHtml(preview.profile_id)}</strong>?</p>
      <div class="agent-delete-effect"><span>Current</span><strong>${escapeHtml(preview.current?.provider || 'None')} · ${escapeHtml(preview.current?.model || 'None')}</strong></div>
      <div class="agent-delete-effect"><span>New</span><strong>${escapeHtml(preview.target?.provider_name || preview.target?.provider)} · ${escapeHtml(preview.target?.model)}</strong></div>
      ${(preview.warnings || []).map((warning) => `<p class="agent-delete-warning">${escapeHtml(warning)}</p>`).join('')}`;
    $('#provider-switch-dialog')?.showModal();
    if (status) status.textContent = '';
  } catch (err) {
    if (status) status.textContent = err.message;
  }
}

async function confirmAgentConsoleProviderSwitch() {
  const preview = state.agentConsoleProviderPreview;
  const status = $('#provider-switch-status');
  if (!preview?.confirmation_id) return;
  if (status) status.textContent = 'Applying and verifying with Hermes…';
  try {
    const payload = await switchAgentConsoleProvider(
      preview.target.provider,
      preview.target.model,
      preview.profile_id,
      preview.confirmation_id,
    );
    state.agentConsoleSelectedProvider = payload.provider;
    state.agentConsoleSelectedModel = payload.model;
    state.managedAgentProviderInventory = payload.provider_inventory || state.managedAgentProviderInventory;
    state.managedAgentSelectedProvider = payload.provider;
    state.managedAgentSelectedModel = payload.model;
    state.hermesProfiles = state.hermesProfiles.map((profile) => profile.id === payload.agent_id
      ? { ...profile, provider: payload.provider, model: payload.model }
      : profile);
    state.agentConsoleProviderPreview = null;
    $('#provider-switch-dialog')?.close();
    renderAgentConsole({
      agents: state.agentConsoleAgents.map((agent) => agent.id === payload.agent_id ? { ...agent, provider: payload.provider, model: payload.model } : agent),
      model_catalog: payload.model_catalog,
      provider_inventory: payload.provider_inventory,
      runs: state.agentConsoleRuns,
    });
    renderHermesProfiles({
      profiles: state.hermesProfiles,
      active_profile: state.activeHermesProfileId,
      capabilities: state.hermesProfileCapabilities,
      status: 'available',
    });
    const formStatus = $('#agent-console-form-status');
    if (formStatus) formStatus.textContent = payload.message || 'Provider configuration updated.';
  } catch (err) {
    if (status) status.textContent = err.message;
  }
}

async function submitAgentConsolePrompt() {
  const prompt = $('#agent-console-prompt');
  const status = $('#agent-console-form-status');
  const value = prompt?.value.trim() || '';
  if (state.agentConsoleAttachmentsUploading) {
    if (status) status.textContent = 'Wait for attachments to finish uploading.';
    return;
  }
  if (!value && !state.agentConsoleAttachments.length && !state.agentConsoleRemoteContext) return;
  if (value.startsWith('/')) {
    const [command, ...args] = value.split(/\s+/);
    const argument = args.join(' ').trim();
    const definition = agentConsoleCommands().find((item) => item.command === command);
    if (!definition) {
      if (status) status.textContent = `${command} is not supported by the Mentat dashboard.`;
    } else if (args.length > definition.arguments.length) {
      const usage = [definition.command, ...definition.arguments.map((item) => item.required ? `<${item.name}>` : `[${item.name}]`)].join(' ');
      if (status) status.textContent = `Usage: ${usage}`;
    } else if (definition.handler === 'agent_console.refresh_models') {
      const catalog = await refreshAgentConsoleModelCatalog({ focus: true });
      if (argument && catalog?.models?.includes(argument)) {
        const providerSwitchAvailable = state.agentConsoleProviderInventory.capabilities?.['providers.switch'] === true;
        if (providerSwitchAvailable) {
          state.agentConsoleSelectedModel = argument;
          $('#agent-console-model-select').value = argument;
          if (status) status.textContent = `${argument} selected. Choose Review Change to preview and confirm the Hermes update.`;
        } else if (status) {
          status.textContent = `${argument} is available, but this Hermes runtime does not expose supported provider/model switching.`;
        }
      } else if (argument && status) status.textContent = `${argument} is not available from the current provider.`;
    } else if (definition.handler === 'agent_console.new_session') {
      state.agentConsoleSessionId = '';
      state.agentConsoleStartFresh = true;
      if (status) status.textContent = 'New Hermes session ready.';
    } else if (definition.handler === 'agent_console.show_help') {
      const help = agentConsoleCommands().map((item) => `${item.command} — ${item.description}`).join('; ');
      if (status) status.textContent = `Dashboard commands: ${help}.`;
    }
    prompt.value = '';
    resizeAgentConsolePrompt();
    $('#agent-console-command-menu').hidden = true;
    return;
  }
  if (status) status.textContent = 'Sending to Hermes…';
  try {
    const payload = await startAgentConsoleRun({
      agent_id: $('#agent-console-agent')?.value || state.agentConsoleSelectedAgentId || 'default',
      prompt: value,
      session_id: state.agentConsoleStartFresh ? undefined : state.agentConsoleSessionId || undefined,
      attachment_ids: state.agentConsoleAttachments.map((attachment) => attachment.id),
      remote_context_token: state.agentConsoleRemoteContext?.token || undefined,
    });
    state.agentConsoleStartFresh = false;
    state.agentConsoleAttachments = [];
    clearAgentConsoleRemoteContext();
    state.agentConsoleAttachmentError = '';
    prompt.value = '';
    resizeAgentConsolePrompt();
    renderAgentConsoleAttachmentTray();
    renderAgentConsole({ agents: state.agentConsoleAgents, runs: [payload.run, ...state.agentConsoleRuns].filter(Boolean) });
    if (status) status.textContent = '';
  } catch (err) {
    if (state.agentConsoleRemoteContext) {
      clearAgentConsoleRemoteContext({ removeAttachments: true });
      renderAgentConsoleAttachmentTray();
    }
    if (status) status.textContent = err.message;
  }
}

function renderCrons(payload = {}) {
  const jobs = payload.jobs || [];
  const count = $('#cron-count');
  const list = $('#cron-list');
  if (count) count.textContent = `${jobs.length} jobs`;
  if (!list) return;
  const queueAvailable = payload.capabilities?.['crons.queue_enabled'] === true;
  const queueUnavailableReason = payload.queue_error
    || 'Queueing is unavailable because this Hermes runtime does not expose a safe atomic cron queue operation.';
  const capabilityNotice = queueAvailable
    ? ''
    : `<div class="empty" role="status">${escapeHtml(queueUnavailableReason)}</div>`;
  const consoleBusy = state.agentConsoleRuns.some(agentConsoleRunIsActive);
  const jobCards = jobs.length ? jobs.map((job) => {
    const triggerBlocked = !queueAvailable || consoleBusy || !job.enabled;
    const triggerReason = !queueAvailable
      ? queueUnavailableReason
      : consoleBusy
        ? 'Stop the active Agent Console run first'
        : !job.enabled
          ? 'Enable this job in Hermes before queueing a run'
          : '';
    const nextRun = job.next_run ? ` · next ${humanDate(job.next_run)}` : '';
    const queueFeedback = state.cronTriggerFeedback?.jobId === job.id
      ? `<div class="item-meta mono" role="status">${escapeHtml(state.cronTriggerFeedback.message)}</div>`
      : '';
    return `
      <article class="item">
        <div class="item-title"><span>${escapeHtml(job.name)}</span><span class="pill ${job.enabled ? 'success' : 'warn'}">${job.enabled ? 'enabled' : 'disabled'}</span></div>
        <div class="item-meta mono">${escapeHtml(job.schedule || 'unknown')} · last ${escapeHtml(job.last_status || 'unknown')}${escapeHtml(nextRun)}</div>
        ${queueFeedback}
        <div class="item-actions"><button class="mini-button" type="button" data-trigger-cron="${escapeHtml(job.id)}" ${triggerBlocked ? `disabled title="${escapeHtml(triggerReason)}"` : ''}>Queue run</button></div>
      </article>`;
  }).join('') : `<div class="empty">No scheduled Hermes cron jobs found yet.</div>`;
  list.innerHTML = `${capabilityNotice}${jobCards}`;
}

function closeCronTrigger() {
  state.cronTriggerRequestToken += 1;
  state.cronTriggerPreview = null;
  $('#cron-trigger-dialog')?.close();
  const status = $('#cron-trigger-status');
  if (status) status.textContent = '';
}

async function openCronTrigger(jobId) {
  const dialog = $('#cron-trigger-dialog');
  const review = $('#cron-trigger-review');
  const status = $('#cron-trigger-status');
  const confirm = $('[data-cron-trigger-confirm]');
  if (!dialog || !review || !jobId) return;
  const requestToken = ++state.cronTriggerRequestToken;
  state.cronTriggerPreview = null;
  review.innerHTML = '<div class="empty">Loading the exact Hermes cron effect…</div>';
  if (confirm) confirm.disabled = true;
  if (status) status.textContent = '';
  dialog.showModal();
  try {
    const preview = await previewCronTrigger(jobId);
    if (requestToken !== state.cronTriggerRequestToken || !dialog.open) return;
    state.cronTriggerPreview = preview;
    review.innerHTML = `
      <article class="agent-creator-review-card agent-creator-warning">
        <h3>Queue ${escapeHtml(preview.job?.name || jobId)} to run?</h3>
        <ul>${(preview.effects || []).map((effect) => `<li>${escapeHtml(effect)}</li>`).join('')}</ul>
        ${(preview.warnings || []).map((warning) => `<p class="agent-delete-warning">${escapeHtml(warning)}</p>`).join('')}
      </article>`;
    if (confirm) confirm.disabled = false;
  } catch (err) {
    if (requestToken === state.cronTriggerRequestToken && status) status.textContent = err.message;
  }
}

async function submitCronTrigger() {
  const preview = state.cronTriggerPreview;
  const status = $('#cron-trigger-status');
  if (!preview?.confirmation_id || !preview.job?.id) return;
  if (status) status.textContent = 'Queueing Hermes cron run…';
  try {
    const result = await triggerCron(preview.job.id, preview.confirmation_id);
    const nextRun = result.job?.next_run ? ` Next run: ${humanDate(result.job.next_run)}.` : '';
    state.cronTriggerFeedback = {
      jobId: preview.job.id,
      message: `${result.message || `${preview.job.name || preview.job.id} queued in Hermes.`}${nextRun}`,
    };
    closeCronTrigger();
    renderCrons(result.crons || {});
  } catch (err) {
    if (status) status.textContent = err.message;
  }
}

async function useHermesProfileInConsole(profileId = 'default') {
  const requestedProfileId = profileId || 'default';
  state.agentConsoleSelectedAgentId = requestedProfileId;
  state.selectedHermesProfileId = requestedProfileId;
  state.agentConsoleSelectedProvider = '';
  state.agentConsoleSessionId = '';
  state.agentConsoleStartFresh = true;
  state.agentConsoleSelectedModel = '';
  const panel = $('#agent-console-panel');
  try {
    await setView('today');
    const consolePayload = await api(endpoints.agentConsole);
    const requestedAgent = (consolePayload.agents || []).find((agent) => agent.id === requestedProfileId);
    if (!requestedAgent) {
      throw new Error(`Hermes profile ${requestedProfileId} is no longer available.`);
    }
    state.agentConsoleSelectedAgentId = requestedProfileId;
    renderAgentConsole(consolePayload);
    if (state.agentConsoleSelectedAgentId !== requestedProfileId) {
      throw new Error(`Hermes profile ${requestedProfileId} could not be selected.`);
    }
    const catalog = await refreshAgentConsoleModelCatalog({
      agentId: requestedProfileId,
      focus: true,
    });
    if (!catalog) {
      const detail = $('#agent-console-form-status')?.textContent.trim();
      throw new Error(detail || 'Provider and model details could not be loaded.');
    }
    panel?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    return true;
  } catch (err) {
    const status = $('#agent-console-form-status');
    const detail = err instanceof Error ? err.message : 'The profile could not be loaded.';
    if (status) status.textContent = `Could not open ${requestedProfileId} in Agent Console: ${detail}`;
    panel?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    return false;
  }
}

async function testHermesProfile(profileId) {
  const ready = await useHermesProfileInConsole(profileId);
  if (!ready) return;
  const prompt = $('#agent-console-prompt');
  if (!prompt) return;
  prompt.value = 'Identity check: without relying on this message for the answer, state your name and briefly describe your role.';
  resizeAgentConsolePrompt();
  await submitAgentConsolePrompt();
}

async function assignFirstTaskToProfile(profileId) {
  await setView('projects', { refreshOnChange: false });
  openTaskEditor('create');
  state.taskEditorDraft = {
    ...taskEditorSeedTask(),
    assignee: profileId,
    planned_for_today: true,
    planning_state: 'planned',
  };
  renderTaskList(state.tasks);
  $('#selected-task-detail input[name="title"]')?.focus();
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
  if (payload.error) {
    state.sessions = [];
    state.selectedSessionId = '';
    state.selectedSessionDetailPayload = null;
    state.selectedSessionDetailContext = null;
    state.sessionDetailRequestGeneration += 1;
    select.innerHTML = `<option value="">${escapeHtml(payload.error)}</option>`;
    select.disabled = true;
    const detail = $('#session-detail');
    if (detail) detail.innerHTML = `<div class="empty">${escapeHtml(payload.error)}</div>`;
    return;
  }
  const selectedStillAvailable = state.sessions.some((session) => session.id === state.selectedSessionId);
  if (state.selectedSessionId && !selectedStillAvailable) {
    state.selectedSessionId = '';
    state.selectedSessionDetailPayload = null;
    state.selectedSessionDetailContext = null;
    state.sessionDetailRequestGeneration += 1;
    const detail = $('#session-detail');
    if (detail) detail.innerHTML = `<div class="empty">Select a session to review the replay or transcript.</div>`;
  }
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
  if (searchQueryLength(term) < 2) {
    container.innerHTML = `<div class="empty">Type at least two characters to search Hermes messages. Remote search stays read-only and covers the recent sessions shown here.</div>`;
    return;
  }
  if (payload.error) {
    container.innerHTML = `<div class="empty">Message search unavailable: ${escapeHtml(payload.error)}</div>`;
    return;
  }
  const results = payload.results || [];
  const coverage = payload.source === 'remote' && payload.coverage ? payload.coverage : null;
  const coverageParts = [];
  if (coverage) {
    const sessionCount = Number(coverage.sessions_scanned) || 0;
    const messageCount = Number(coverage.messages_scanned) || 0;
    const compactedCount = Number(coverage.compacted_sessions) || 0;
    coverageParts.push(`${sessionCount} recent ${sessionCount === 1 ? 'session' : 'sessions'}`);
    coverageParts.push(`${messageCount} visible ${messageCount === 1 ? 'message' : 'messages'} searched`);
    if (coverage.list_truncated) coverageParts.push(`${Number(coverage.session_limit) || 12}-session limit reached; older sessions may not be included`);
    if (compactedCount > 0) coverageParts.push(`${compactedCount} compacted ${compactedCount === 1 ? 'transcript may' : 'transcripts may'} omit earlier turns`);
    if (coverage.results_truncated) coverageParts.push(`showing the first ${Number(coverage.result_limit) || 20} matches`);
  }
  const coverageMarkup = coverageParts.length
    ? `<div class="message-search-coverage mono">Remote coverage: ${escapeHtml(coverageParts.join(' · '))}.</div>`
    : '';
  container.innerHTML = results.length ? `
    <div class="message-search-head mono">${results.length} ${results.length === 1 ? 'message match' : 'message matches'} for “${escapeHtml(term)}”</div>
    ${coverageMarkup}
    <div class="message-result-grid">
      ${results.map((result) => `
        <button class="message-result" type="button" data-session-id="${escapeHtml(result.session_id)}" data-message-id="${escapeHtml(result.message_id)}" data-query="${escapeHtml(term)}" data-match-text="${escapeHtml(result.match_text || '')}">
          <div class="item-title"><span>${escapeHtml(result.title || 'Untitled session')}</span><span class="pill">${escapeHtml(result.role || 'message')}</span></div>
          <div class="item-desc">${highlightHtml(result.snippet || '', result.match_text || term)}</div>
          <div class="item-meta mono">${humanDate(result.timestamp)} · ${escapeHtml(result.source || 'session')} · msg ${escapeHtml(result.message_id)}</div>
        </button>
      `).join('')}
    </div>
  ` : `${coverageMarkup}<div class="empty">No message matches for “${escapeHtml(term)}”.</div>`;
}

function renderHermesCapabilityInventory(payload = {}) {
  const container = $('#hermes-capability-summary');
  if (!container) return;
  const status = String(payload.status || 'unavailable');
  const mode = String(payload.mode || 'unavailable');
  const label = payload.label || (mode === 'local' ? 'Local Hermes' : 'Remote Hermes');
  const message = payload.message || 'Hermes capabilities are unavailable.';
  if (status !== 'available') {
    const tone = status === 'local' ? 'success' : status === 'unsupported' ? 'warn' : 'danger';
    container.innerHTML = `
      <article class="item" ${status === 'unavailable' ? 'role="alert"' : ''}>
        <div class="item-title"><span>${escapeHtml(label)}</span><span class="pill ${tone}">${escapeHtml(status)}</span></div>
        <div class="item-desc">${escapeHtml(message)}</div>
      </article>
    `;
    return;
  }
  const skills = Array.isArray(payload.skills) ? payload.skills : [];
  const toolsets = Array.isArray(payload.toolsets) ? payload.toolsets : [];
  const summary = payload.summary || {};
  const skillCount = Number(summary.skill_count ?? skills.length);
  const toolsetCount = Number(summary.toolset_count ?? toolsets.length);
  const enabledToolsetCount = Number(summary.enabled_toolset_count ?? toolsets.filter((item) => item.enabled).length);
  container.innerHTML = `
    <article class="item">
      <div class="item-title"><span>${escapeHtml(label)}</span><span class="pill success">read-only</span></div>
      <div class="item-desc">${escapeHtml(message)}</div>
      <div class="item-meta mono">${escapeHtml(skillCount)} skills · ${escapeHtml(enabledToolsetCount)} of ${escapeHtml(toolsetCount)} toolsets enabled</div>
    </article>
    <details class="managed-agent-advanced">
      <summary>${escapeHtml(skillCount)} available skills</summary>
      <div class="settings-list">
        ${skills.length ? skills.map((skill) => `
          <article class="item">
            <div class="item-title"><span>${escapeHtml(skill.name || 'Unnamed skill')}</span></div>
          </article>
        `).join('') : '<div class="empty">No skills are visible to this Hermes host.</div>'}
      </div>
    </details>
    <details class="managed-agent-advanced">
      <summary>${escapeHtml(toolsetCount)} available toolsets</summary>
      <div class="settings-list">
        ${toolsets.length ? toolsets.map((toolset) => `
          <article class="item">
            <div class="item-title"><span>${escapeHtml(toolset.name || 'Unnamed toolset')}</span><span class="pill ${toolset.enabled ? 'success' : ''}">${toolset.enabled ? 'enabled' : 'available'}</span></div>
            <div class="item-meta mono">${escapeHtml(toolset.name || '')} · ${escapeHtml(Number(toolset.tool_count || 0))} tools</div>
          </article>
        `).join('') : '<div class="empty">No toolsets are visible to this Hermes host.</div>'}
      </div>
    </details>
  `;
}

function renderConfig(payload = {}) {
  const summary = $('#config-summary');
  const text = $('#config-text');
  if (!summary || !text) return;
  if (payload.error) {
    summary.innerHTML = `<div class="empty">Could not load Hermes config: ${escapeHtml(payload.error)}</div>`;
    text.textContent = '';
    return;
  }
  if (!payload.exists) {
    summary.innerHTML = `<div class="empty">Hermes config was not found.</div>`;
    text.textContent = '';
    return;
  }
  const rows = Object.entries(payload.summary || {});
  if (payload.mode === 'remote') {
    summary.innerHTML = `
      <article class="item"><div class="item-title"><span>Remote agent connection</span><span class="pill">selected</span></div><div class="item-desc">Mentat keeps the API key private. Live readiness appears in Subsystem Health.</div></article>
      ${rows.map(([key, value]) => `
        <article class="item"><div class="item-title"><span>${escapeHtml(key.replaceAll('_', ' '))}</span><span class="pill">remote</span></div><div class="item-desc mono">${escapeHtml(value)}</div></article>
      `).join('')}
    `;
    text.textContent = payload.masked_config || '{}';
    return;
  }
  summary.innerHTML = `
    <article class="item"><div class="item-title"><span>Configuration summary</span><span class="pill">${escapeHtml(payload.size || 'n/a')}</span></div><div class="item-meta mono">Modified ${humanDate(payload.modified_at)}</div></article>
    ${rows.length ? rows.map(([key, value]) => `
      <article class="item"><div class="item-title"><span>${escapeHtml(key.replaceAll('_', ' '))}</span><span class="pill">config</span></div><div class="item-desc mono">${escapeHtml(value)}</div></article>
    `).join('') : `<div class="empty">No allowlisted model/provider summary fields were found.</div>`}
  `;
  text.textContent = payload.masked_config || '{}';
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
  const plainTextTranscript = payload.plain_text === true;
  const visibleLabel = windowInfo.mode === 'latest_segment'
    ? `${messages.length} visible messages in the latest segment`
    : (windowInfo.truncated ? `${messages.length} of ${totalVisible} visible messages` : `${messages.length} visible messages`);
  const activeTab = state.selectedSessionDetailTab || 'replay';
  const transcriptHtml = `
    ${windowInfo.truncated ? `<div class="conversation-window-note mono">${escapeHtml(windowInfo.partial_reason || (windowInfo.mode === 'around_target' ? 'Showing a focused window around the selected search match.' : 'Showing the first conversation window.'))} ${escapeHtml(visibleLabel)}.</div>` : ''}
    <div class="message-list">
      ${messages.length ? messages.map((message) => {
        const isTarget = targetId && Number(message.id) === targetId;
        return `
          <article id="message-${escapeHtml(message.id)}" class="message-card ${escapeHtml(message.role)} ${isTarget ? 'target-message' : ''}" data-message-id="${escapeHtml(message.id)}">
            <div class="message-meta mono">${escapeHtml(message.role)} · msg ${escapeHtml(message.id)} · ${humanDate(message.timestamp)}</div>
            <div class="message-content ${plainTextTranscript ? 'plain-text-message' : 'markdown-body'}">${plainTextTranscript ? highlightHtml(message.content || '', query) : renderMarkdown(message.content || '', query)}</div>
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
  const requestGeneration = state.sessionDetailRequestGeneration + 1;
  state.sessionDetailRequestGeneration = requestGeneration;
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
    if (requestGeneration !== state.sessionDetailRequestGeneration || state.selectedSessionId !== sessionId) return;
    renderSessionDetail({ ...detailPayload, replay: replayPayload }, options);
    if (options.messageId) {
      requestAnimationFrame(() => scrollDetailToMessage(options.messageId));
    }
  } catch (err) {
    if (requestGeneration !== state.sessionDetailRequestGeneration || state.selectedSessionId !== sessionId) return;
    console.error(err);
    if (detail) detail.innerHTML = `<div class="empty">Could not load session: ${escapeHtml(err.message)}</div>`;
  }
}

function agentCreatorForm() {
  return $('#agent-creator-form');
}

function renderHermesProfiles(payload = {}) {
  const list = $('#managed-agent-list');
  const detail = $('#managed-agent-detail');
  const count = $('#managed-agent-count');
  if (!list || !detail) return;
  const profiles = Array.isArray(payload.profiles) ? payload.profiles : [];
  state.hermesProfiles = profiles;
  const activeProfile = payload.active_profile || '';
  state.hermesProfileCapabilities = payload.capabilities || {};
  state.activeHermesProfileId = activeProfile;
  const deletionAvailable = state.hermesProfileCapabilities['profiles.delete'] === true;
  const identityReadAvailable = state.hermesProfileCapabilities['profiles.identity.read'] === true;
  const identityWriteAvailable = state.hermesProfileCapabilities['profiles.identity.write'] === true;
  const consoleBusy = state.agentConsoleRuns.some(agentConsoleRunIsActive);
  if (count) count.textContent = `${profiles.length} profile${profiles.length === 1 ? '' : 's'}`;
  if (payload.status && payload.status !== 'available') {
    const message = payload.error?.message || 'Hermes profile discovery is unavailable.';
    list.innerHTML = `<div class="empty" role="alert">${escapeHtml(message)}</div>`;
    return;
  }
  if (!profiles.length) {
    list.innerHTML = '<div class="empty">No Hermes profiles are available yet. Create an agent to add one.</div>';
    detail.innerHTML = '<div class="empty">Create an agent to inspect and use it here.</div>';
    return;
  }
  if (!profiles.some((profile) => profile.id === state.selectedHermesProfileId)) {
    state.selectedHermesProfileId = profiles.find((profile) => profile.id === state.agentConsoleSelectedAgentId)?.id || activeProfile || profiles[0].id;
  }
  list.innerHTML = profiles.map((profile) => {
    const selected = profile.id === state.selectedHermesProfileId;
    const labels = [
      profile.is_default ? 'Default' : '',
      profile.id === activeProfile ? 'Hermes active' : '',
    ].filter(Boolean).join(' · ');
    const runtime = [profile.provider, profile.model].filter(Boolean).join(' · ') || 'Uses Hermes profile configuration';
    return `
      <button class="managed-agent-row ${selected ? 'selected' : ''}" type="button" role="option" aria-selected="${selected}" data-select-hermes-profile="${escapeHtml(profile.id)}">
        <span class="managed-agent-row-mark" aria-hidden="true"></span>
        <span class="managed-agent-row-copy">
          <span class="managed-agent-name">${escapeHtml(profile.name || profile.id)}</span>
          <span class="item-desc">${escapeHtml(profile.description || 'No role description supplied.')}</span>
          <span class="item-meta mono">${escapeHtml(runtime)}</span>
        </span>
        ${labels ? `<span class="managed-agent-state mono">${escapeHtml(labels)}</span>` : ''}
      </button>
    `;
  }).join('');
  const selectedProfile = profiles.find((profile) => profile.id === state.selectedHermesProfileId) || profiles[0];
  const identity = state.managedAgentIdentities[selectedProfile.id];
  const identityStatus = identity?.status || (identityReadAvailable ? 'unchecked' : 'unsupported');
  const identityReady = identityStatus === 'synced'
    && identity?.name === selectedProfile.id
    && String(identity?.role || '') === String(selectedProfile.description || '');
  const identityBlocked = ['conflict', 'unsafe'].includes(identityStatus);
  const identityStatusText = identityStatus === 'synced'
    ? 'Runtime name and role are synchronized with Hermes.'
    : identityStatus === 'missing'
      ? 'No Mentat-managed runtime identity exists yet. Review and confirm to add one.'
      : identityStatus === 'drifted'
        ? 'The runtime identity and Hermes routing role have drifted. Review and confirm to synchronize them.'
        : identityStatus === 'conflict' || identityStatus === 'unsafe'
          ? 'Identity editing is blocked because Hermes reported malformed or unsafe identity state.'
          : identityStatus === 'unsupported'
            ? 'This Hermes runtime does not support managed identity synchronization.'
            : 'Checking the Hermes runtime identity…';
  const managedInventory = state.managedAgentProviderInventory?.profile_id === selectedProfile.id
    ? state.managedAgentProviderInventory
    : state.agentConsoleProviderInventory?.profile_id === selectedProfile.id
      ? state.agentConsoleProviderInventory
      : {};
  const managedProviders = Array.isArray(managedInventory.providers) ? managedInventory.providers : [];
  const managedSwitchCapabilityKnown = Object.prototype.hasOwnProperty.call(
    managedInventory.capabilities || {},
    'providers.switch',
  );
  const managedSwitchAvailable = managedInventory.capabilities?.['providers.switch'] === true;
  const requestedManagedProvider = state.managedAgentSelectedProvider || managedInventory.current_provider || selectedProfile.provider || '';
  const managedProvider = managedProviders.find((item) => item.id === requestedManagedProvider)
    || managedProviders.find((item) => item.current)
    || managedProviders[0];
  const managedModels = Array.isArray(managedProvider?.models) ? managedProvider.models : [];
  const managedCurrentModel = managedProvider?.id === managedInventory.current_provider ? managedInventory.current_model : '';
  const managedModel = [state.managedAgentSelectedModel, managedCurrentModel, selectedProfile.model]
    .find((item) => managedModels.includes(item)) || managedModels[0] || '';
  const hasEnabledBuiltinSkillCount = selectedProfile.enabled_builtin_skill_count !== null
    && selectedProfile.enabled_builtin_skill_count !== undefined;
  const displayedSkillCount = hasEnabledBuiltinSkillCount
    ? Number(selectedProfile.enabled_builtin_skill_count || 0)
    : Number(selectedProfile.skill_count || 0);
  const displayedSkillLabel = hasEnabledBuiltinSkillCount ? 'Enabled built-ins' : 'Installed skills';
  state.managedAgentSelectedProvider = managedProvider?.id || '';
  state.managedAgentSelectedModel = managedModel;
  const selectedLabels = [
    'Selected',
    selectedProfile.is_default ? 'Default' : '',
    selectedProfile.id === activeProfile ? 'Hermes active' : '',
  ].filter(Boolean).join(' · ');
  const canDelete = deletionAvailable && !selectedProfile.is_default && selectedProfile.id !== activeProfile && !consoleBusy;
  const deleteReason = selectedProfile.is_default
    ? 'The default Hermes profile cannot be deleted.'
    : selectedProfile.id === activeProfile
      ? 'Change the Hermes active profile before deleting this agent.'
      : consoleBusy ? 'Stop the active Console run before deleting an agent.' : '';
  const hasAssignedTask = state.tasks.some((task) => task.delegation?.profile_id === selectedProfile.id);
  detail.innerHTML = `
    <div class="managed-agent-detail-head">
      <div><div class="eyebrow">Selected agent</div><h3>${escapeHtml(selectedProfile.name || selectedProfile.id)}</h3></div>
      <div class="managed-agent-state mono">${escapeHtml(selectedLabels)}</div>
    </div>
    <p class="item-desc managed-agent-description">${escapeHtml(selectedProfile.description || 'No role description supplied.')}</p>
    <section class="managed-agent-identity-editor" aria-label="Agent runtime identity">
      <div class="managed-agent-identity-head">
        <div><span class="detail-context-label mono">Runtime identity</span><strong>${escapeHtml(identityReady ? 'Synchronized' : identityStatus.replaceAll('_', ' '))}</strong></div>
        <span class="managed-agent-identity-state mono">${escapeHtml(selectedProfile.id)}</span>
      </div>
      <label class="task-editor-field" for="managed-agent-role">
        <span class="task-editor-label mono">Role / description</span>
        <textarea id="managed-agent-role" maxlength="500" rows="3" ${identityWriteAvailable && !identityBlocked && !consoleBusy ? '' : 'disabled'}>${escapeHtml(selectedProfile.description || '')}</textarea>
      </label>
      <div class="managed-agent-identity-actions">
        <p id="managed-agent-identity-status" class="item-meta mono">${escapeHtml(identityStatusText)}</p>
        <button class="mini-button" type="button" data-review-agent-identity="${escapeHtml(selectedProfile.id)}" ${identityWriteAvailable && !identityBlocked && !consoleBusy && identityStatus !== 'unchecked' ? '' : 'disabled'}>${identityReady ? 'Review identity change' : 'Set runtime identity'}</button>
      </div>
    </section>
    <div class="managed-agent-config">
      <div><span class="detail-context-label mono">Provider</span><strong>${escapeHtml(selectedProfile.provider || 'Hermes configured')}</strong></div>
      <div><span class="detail-context-label mono">Model</span><strong>${escapeHtml(selectedProfile.model || 'Configured default')}</strong></div>
      <div><span class="detail-context-label mono">${displayedSkillLabel}</span><strong>${displayedSkillCount}</strong></div>
    </div>
    <div class="agent-onboarding-checklist" aria-label="Agent readiness checklist">
      <span class="${selectedProfile.id ? 'ready' : ''}">Profile created</span>
      <span class="${identityReady ? 'ready' : ''}">Identity synchronized</span>
      <span class="${selectedProfile.provider ? 'ready' : ''}">Provider selected</span>
      <span class="${selectedProfile.model ? 'ready' : ''}">Model available</span>
      <span class="${displayedSkillCount >= 0 ? 'ready' : ''}">Skills inspected</span>
      <span class="${hasAssignedTask ? 'ready' : ''}">First task assigned</span>
    </div>
    <details class="managed-agent-advanced">
      <summary>Advanced provider &amp; model settings</summary>
      <div class="managed-agent-provider-editor">
      <label class="agent-console-select-shell" for="managed-agent-provider-select">
        <span class="detail-context-label mono">Authenticated provider</span>
        <select id="managed-agent-provider-select" class="agent-console-select" ${managedProviders.length && managedSwitchAvailable && !consoleBusy ? '' : 'disabled'}>
          ${managedProviders.length
            ? managedProviders.map((item) => `<option value="${escapeHtml(item.id)}" ${item.id === managedProvider?.id ? 'selected' : ''}>${escapeHtml(item.name || item.id)}${item.current ? ' · current' : ''}</option>`).join('')
            : `<option value="">${escapeHtml(managedInventory.error || 'Load authenticated providers')}</option>`}
        </select>
      </label>
      <label class="agent-console-select-shell" for="managed-agent-model-select">
        <span class="detail-context-label mono">Model</span>
        <select id="managed-agent-model-select" class="agent-console-select" ${managedModels.length && managedSwitchAvailable && !consoleBusy ? '' : 'disabled'}>
          ${managedModels.length
            ? managedModels.map((model) => `<option value="${escapeHtml(model)}" ${model === managedModel ? 'selected' : ''}>${escapeHtml(model)}</option>`).join('')
            : '<option value="">Choose a provider first</option>'}
        </select>
      </label>
      ${managedProviders.length
        ? `<button class="mini-button" type="button" data-review-managed-agent-provider="${escapeHtml(selectedProfile.id)}" ${managedModel && managedSwitchAvailable && !consoleBusy ? '' : 'disabled'}>Review Change</button>`
        : `<button class="mini-button" type="button" data-load-managed-agent-providers="${escapeHtml(selectedProfile.id)}" ${consoleBusy ? 'disabled' : ''}>Load providers</button>`}
      <p id="managed-agent-provider-status" class="item-meta mono managed-agent-provider-editor-status">${managedSwitchCapabilityKnown && !managedSwitchAvailable ? 'This Hermes runtime does not expose supported provider switching.' : selectedProfile.provider ? 'Choose an authenticated provider and model to change this agent.' : managedProviders.length ? 'No provider is assigned. Choose from providers already authenticated in Hermes.' : 'No provider is assigned. Load providers already authenticated in Hermes.'}</p>
      </div>
    </details>
    <div class="managed-agent-detail-actions">
      <button class="action-button" type="button" data-use-hermes-profile="${escapeHtml(selectedProfile.id)}">Use in Console</button>
      <button class="mini-button" type="button" data-test-hermes-profile="${escapeHtml(selectedProfile.id)}">Test Agent</button>
      <button class="mini-button" type="button" data-assign-first-task="${escapeHtml(selectedProfile.id)}">Assign First Task</button>
      ${canDelete ? `<button class="mini-button managed-agent-delete" type="button" data-delete-hermes-profile="${escapeHtml(selectedProfile.id)}">Delete agent</button>` : `<button class="mini-button managed-agent-delete" type="button" disabled title="${escapeHtml(deleteReason)}">Delete agent</button>`}
    </div>
    ${deleteReason ? `<p class="item-meta mono">${escapeHtml(deleteReason)}</p>` : ''}
  `;
  if (!identity && identityReadAvailable) void loadManagedAgentIdentity(selectedProfile.id);
}

function rerenderHermesProfiles() {
  renderHermesProfiles({
    profiles: state.hermesProfiles,
    active_profile: state.activeHermesProfileId,
    capabilities: state.hermesProfileCapabilities,
    status: 'available',
  });
}

async function loadManagedAgentIdentity(profileId, { force = false } = {}) {
  if (!profileId || (!force && state.managedAgentIdentities[profileId])) return state.managedAgentIdentities[profileId];
  state.managedAgentIdentities[profileId] = { status: 'loading', profile_id: profileId };
  try {
    const identity = await fetchHermesProfileIdentity(profileId);
    state.managedAgentIdentities[profileId] = identity;
  } catch (err) {
    state.managedAgentIdentities[profileId] = {
      status: 'unsafe',
      profile_id: profileId,
      can_write: false,
      error: { code: 'identity_load_failed' },
    };
  }
  if (state.selectedHermesProfileId === profileId) rerenderHermesProfiles();
  return state.managedAgentIdentities[profileId];
}

function closeAgentIdentityDialog() {
  state.managedAgentIdentityRequestToken += 1;
  state.managedAgentIdentityPreview = null;
  $('#agent-identity-dialog')?.close();
  const status = $('#agent-identity-status');
  if (status) status.textContent = '';
}

async function openAgentIdentityReview(profileId) {
  const dialog = $('#agent-identity-dialog');
  const review = $('#agent-identity-review');
  const status = $('#agent-identity-status');
  const confirm = $('[data-agent-identity-confirm]');
  const role = $('#managed-agent-role')?.value || '';
  if (!dialog || !review || !profileId) return;
  const requestToken = ++state.managedAgentIdentityRequestToken;
  state.managedAgentIdentityPreview = null;
  review.innerHTML = '<div class="empty">Loading the exact Hermes identity effects…</div>';
  if (status) status.textContent = '';
  if (confirm) confirm.disabled = true;
  dialog.showModal();
  try {
    const preview = await previewHermesProfileIdentity(profileId, role);
    if (requestToken !== state.managedAgentIdentityRequestToken || !dialog.open) return;
    state.managedAgentIdentityPreview = preview;
    review.innerHTML = `
      <article class="agent-creator-review-card">
        <h3>${escapeHtml(preview.normalized?.name || profileId)}</h3>
        <p class="item-desc">${escapeHtml(preview.normalized?.role || 'No specialized role assigned.')}</p>
        <ul>${(preview.effects || []).map((effect) => `<li>${escapeHtml(effect)}</li>`).join('')}</ul>
        ${(preview.warnings || []).map((warning) => `<p class="agent-delete-warning">${escapeHtml(warning)}</p>`).join('')}
      </article>`;
    if (confirm) confirm.disabled = false;
    if (status) status.textContent = 'Review the exact managed identity change, then confirm.';
  } catch (err) {
    if (requestToken !== state.managedAgentIdentityRequestToken || !dialog.open) return;
    review.innerHTML = `<div class="empty" role="alert">Identity update is unavailable: ${escapeHtml(err.message)}</div>`;
    if (confirm) confirm.disabled = true;
  }
}

async function submitAgentIdentityUpdate() {
  const preview = state.managedAgentIdentityPreview;
  const profileId = preview?.normalized?.profile_id;
  const role = preview?.normalized?.role || '';
  const status = $('#agent-identity-status');
  const confirm = $('[data-agent-identity-confirm]');
  if (!profileId || !preview?.confirmation_id) return;
  if (confirm) confirm.disabled = true;
  if (status) status.textContent = `Synchronizing ${profileId}…`;
  try {
    const result = await updateHermesProfileIdentity(profileId, role, preview.confirmation_id);
    state.managedAgentIdentities[profileId] = result.identity;
    if (result.profiles?.profiles) state.hermesProfiles = result.profiles.profiles;
    closeAgentIdentityDialog();
    rerenderHermesProfiles();
  } catch (err) {
    if (status) status.textContent = `Identity update failed: ${err.message}`;
    if (confirm) confirm.disabled = false;
  }
}

async function loadManagedAgentProviderInventory(profileId) {
  const status = $('#managed-agent-provider-status');
  if (status) status.textContent = 'Loading authenticated providers from Hermes…';
  try {
    const payload = await refreshAgentConsoleModels(profileId);
    state.managedAgentProviderInventory = payload.provider_inventory || {};
    state.managedAgentSelectedProvider = state.managedAgentProviderInventory.current_provider
      || state.managedAgentProviderInventory.providers?.[0]?.id
      || '';
    state.managedAgentSelectedModel = state.managedAgentProviderInventory.current_model || '';
    renderHermesProfiles({
      profiles: state.hermesProfiles,
      active_profile: state.activeHermesProfileId,
      capabilities: state.hermesProfileCapabilities,
      status: 'available',
    });
  } catch (err) {
    if (status) status.textContent = err.message;
  }
}

async function reviewManagedAgentProvider(profileId) {
  const provider = $('#managed-agent-provider-select')?.value || '';
  const model = $('#managed-agent-model-select')?.value || '';
  const status = $('#managed-agent-provider-status');
  if (!provider || !model) return;
  if (status) status.textContent = 'Preparing provider change preview…';
  try {
    const preview = await previewAgentConsoleProvider(provider, model, profileId);
    state.agentConsoleProviderPreview = preview;
    state.agentConsoleProviderPreviewSource = 'managed';
    const review = $('#provider-switch-review');
    if (review) review.innerHTML = `
      <p>Apply this configuration to <strong>${escapeHtml(preview.profile_id)}</strong>?</p>
      <div class="agent-delete-effect"><span>Current</span><strong>${escapeHtml(preview.current?.provider || 'None')} · ${escapeHtml(preview.current?.model || 'None')}</strong></div>
      <div class="agent-delete-effect"><span>New</span><strong>${escapeHtml(preview.target?.provider_name || preview.target?.provider)} · ${escapeHtml(preview.target?.model)}</strong></div>
      ${(preview.warnings || []).map((warning) => `<p class="agent-delete-warning">${escapeHtml(warning)}</p>`).join('')}`;
    $('#provider-switch-dialog')?.showModal();
    if (status) status.textContent = '';
  } catch (err) {
    if (status) status.textContent = err.message;
  }
}

function closeAgentDeletion() {
  state.agentDeletionRequestToken += 1;
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
  const requestToken = ++state.agentDeletionRequestToken;
  state.agentDeletionPreview = null;
  review.innerHTML = `<div class="empty">Loading the exact Hermes deletion effects…</div>`;
  if (status) status.textContent = '';
  if (confirm) confirm.disabled = true;
  dialog.showModal();
  try {
    const preview = await previewHermesProfileDeletion(profileId);
    if (requestToken !== state.agentDeletionRequestToken || !dialog.open) return;
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
    if (requestToken !== state.agentDeletionRequestToken || !dialog.open) return;
    state.agentDeletionPreview = null;
    review.innerHTML = `<div class="empty" role="alert">Deletion is unavailable: ${escapeHtml(err.message)}</div>`;
    if (confirm) confirm.disabled = true;
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
    if (state.selectedHermesProfileId && result.identity) {
      state.managedAgentIdentities[state.selectedHermesProfileId] = result.identity;
    }
    if (result.profiles) renderHermesProfiles(result.profiles);
    if (state.selectedHermesProfileId) await loadManagedAgentProviderInventory(state.selectedHermesProfileId);
    const review = $('#agent-creator-review');
    if (review) review.innerHTML = `
      <article class="agent-creator-review-card agent-creator-success">
        <h3>${escapeHtml(result.profile?.name || result.profile?.id || 'Agent')} created</h3>
        <div class="item-desc">The Hermes profile and its runtime name/role are synchronized and now appear in Managed Agents.</div>
        <div class="item-meta mono">${result.skill_selection ? `${result.skill_selection.enabled_builtin_skills?.length || 0} built-in skills enabled` : 'Hermes default skill configuration'}</div>
        <div class="task-delegation-actions">
          <button class="action-button" type="button" data-agent-creator-test="${escapeHtml(state.selectedHermesProfileId)}">Test Agent</button>
          <button class="mini-button" type="button" data-agent-creator-assign-first-task="${escapeHtml(state.selectedHermesProfileId)}">Assign First Task</button>
          <button class="mini-button" type="button" data-agent-creator-view-agents>View managed agents</button>
        </div>
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


function renderAgentPulse(payload = {}) {
  const rawAgents = Array.isArray(payload.agents) ? payload.agents : [];
  const agents = filterDismissedAgents(rawAgents);
  const sessions = Array.isArray(payload.sessions) ? payload.sessions : [];
  const latestSession = sessions[0];
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
  const retentionMinutes = Math.round(AGENT_PULSE_COMPLETED_RETENTION_MS / 60000);
  const doneCount = Number(visibleSummary.done || 0);
  const failedCount = Number(visibleSummary.failed || 0);
  const needsInputCount = Number(visibleSummary.needs_user_input || 0);
  const hiddenDismissedCount = rawAgents.filter((agent) => isAgentPulseDismissed(agent)).length;
  const hasVisibleRows = activeAgents.length + recentlyCompleted.length;

  if (pill) {
    if (hasVisibleRows) {
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
  state.notesPayload = payload;
  const countPill = $('#notes-count');
  const vaultMeta = $('#notes-vault-meta');
  if (countPill) countPill.textContent = `${notes.length} notes`;
  if (vaultMeta) {
    vaultMeta.textContent = payload.exists === false
      ? 'Configured Obsidian vault is unavailable.'
      : `${notes.length} markdown note${notes.length === 1 ? '' : 's'} from ${payload.vault_name || 'Obsidian vault'}`;
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
      <div class="calendar-task-actions">
        <a class="mini-button" href="obsidian://open?vault=${encodeURIComponent(payload.vault_name || '')}&file=${encodeURIComponent(String(note.relative_path || '').replace(/\.md$/i, ''))}" aria-label="Open ${escapeHtml(note.title || note.name)} in Obsidian">Open in Obsidian</a>
        <button class="mini-button" type="button" data-attach-note="${escapeHtml(note.relative_path || '')}" aria-label="Attach ${escapeHtml(note.title || note.name)} to selected task">Attach to selected task</button>
      </div>
    </article>
  `).join('') : `<div class="empty">No Obsidian markdown notes found.</div>`;
}

function renderContextPacks(payload = {}) {
  const packs = Array.isArray(payload.context_packs) ? payload.context_packs : [];
  state.contextPacks = packs;
  const list = $('#context-pack-list');
  if (list) list.innerHTML = packs.length ? packs.map((pack) => `
    <article class="item context-pack-card">
      <div class="item-title"><span>${escapeHtml(pack.name || 'Context pack')}</span><span class="detail-context-label mono">${(pack.note_paths || []).length} notes · ${(pack.workspace_files || []).length} files</span></div>
      <div class="item-desc">${escapeHtml(pack.description || pack.instructions || 'Reusable agent context')}</div>
      <div class="item-actions"><button class="mini-button" type="button" data-use-context-pack="${escapeHtml(pack.id)}">Use in Console</button><button class="mini-button" type="button" data-edit-context-pack="${escapeHtml(pack.id)}">Edit</button></div>
    </article>`).join('') : '<div class="empty">No context packs yet. Create one to reuse the same notes, files, and instructions.</div>';
  renderAgentConsoleContextPackPicker();
}

function renderAgentConsoleContextPackPicker() {
  const results = $('#agent-console-context-pack-results');
  if (!results) return;
  results.innerHTML = state.contextPacks.length ? state.contextPacks.map((pack) => `
    <button type="button" class="agent-console-workspace-result" role="option" data-apply-context-pack="${escapeHtml(pack.id)}"><strong>${escapeHtml(pack.name)}</strong><span class="mono">${(pack.note_paths || []).length + (pack.workspace_files || []).length} attachments</span></button>
  `).join('') : '<div class="agent-console-workspace-state mono">Create a context pack from the Notes view first.</div>';
}

function openAgentConsoleContextPackPicker() {
  $('#agent-console-attachment-choices').hidden = true;
  $('#agent-console-workspace-picker').hidden = true;
  $('#agent-console-context-pack-picker').hidden = false;
  renderAgentConsoleContextPackPicker();
}

async function applyContextPackToConsole(packId) {
  const status = $('#agent-console-form-status');
  if (state.agentConsoleAttachmentsUploading) return;
  const pack = state.contextPacks.find((item) => item.id === packId);
  if (!pack) return;
  const replacingRemoteContext = state.agentConsoleTransportBinding.startsWith('remote:');
  const existingAttachmentCount = replacingRemoteContext ? 0 : state.agentConsoleAttachments.length;
  if (existingAttachmentCount + (pack.note_paths || []).length + (pack.workspace_files || []).length > 8) {
    if (status) status.textContent = 'Remove attachments before applying this context pack; Console accepts 8 total.';
    return;
  }
  if (state.agentConsoleRemoteContext) {
    clearAgentConsoleRemoteContext({ removeAttachments: true });
    renderAgentConsoleAttachmentTray();
  }
  state.agentConsoleAttachmentsUploading = true;
  renderAgentConsoleAttachmentTray();
  try {
    const payload = await stageContextPack(packId);
    if (payload.remote_context_token) {
      clearAgentConsoleRemoteContext({ removeAttachments: true });
      state.agentConsoleAttachments = Array.from(payload.attachments || []);
      state.agentConsoleRemoteContext = {
        token: payload.remote_context_token,
        attachment_ids: state.agentConsoleAttachments.map((item) => item.id),
        transport_binding: `remote:${payload.transport_binding_id || ''}`,
      };
    } else {
      clearAgentConsoleRemoteContext({ removeAttachments: true });
      for (const attachment of payload.attachments || []) {
        if (!state.agentConsoleAttachments.some((item) => item.id === attachment.id)) state.agentConsoleAttachments.push(attachment);
      }
    }
    const prompt = $('#agent-console-prompt');
    const instructions = String(payload.instructions || '').trim();
    if (prompt && instructions && !payload.instructions_in_remote_context) {
      prompt.value = [instructions, prompt.value.trim()].filter(Boolean).join('\n\n');
    }
    setAgentConsoleAttachmentMenu(false);
    if (status) status.textContent = `${pack.name} staged with current private snapshots.`;
  } catch (err) {
    if (status) status.textContent = err.message;
  } finally {
    state.agentConsoleAttachmentsUploading = false;
    renderAgentConsoleAttachmentTray();
  }
}

function renderContextPackEditor() {
  const form = $('#context-pack-form');
  if (!form || !state.contextPackDraft) return;
  const draft = state.contextPackDraft;
  form.elements.name.value = draft.name || '';
  form.elements.description.value = draft.description || '';
  form.elements.instructions.value = draft.instructions || '';
  $('#context-pack-title').textContent = state.editingContextPackId ? 'Edit Context Pack' : 'Create Context Pack';
  $('[data-context-pack-delete]').hidden = !state.editingContextPackId;
  const selectedNotes = new Set(draft.note_paths || []);
  $('#context-pack-note-options').innerHTML = (state.notesPayload.notes || []).map((note) => `<label class="context-pack-option"><input type="checkbox" value="${escapeHtml(note.relative_path)}" ${selectedNotes.has(note.relative_path) ? 'checked' : ''}/><span><strong>${escapeHtml(note.title || note.name)}</strong><small class="mono">${escapeHtml(note.relative_path)}</small></span></label>`).join('') || '<div class="empty">No Obsidian notes available.</div>';
  renderContextPackWorkspaceSelected();
}

function renderContextPackWorkspaceSelected() {
  const selected = $('#context-pack-workspace-selected');
  if (!selected || !state.contextPackDraft) return;
  selected.innerHTML = (state.contextPackDraft.workspace_files || []).map((file) => `<span class="context-pack-chip"><span>${escapeHtml(file.relative_path)}</span><button type="button" data-remove-context-pack-file="${escapeHtml(file.relative_path)}" aria-label="Remove ${escapeHtml(file.relative_path)}">×</button></span>`).join('') || '<span class="section-copy">No workspace files selected.</span>';
}

function contextPackEditorDraft(pack = null) {
  const draft = pack ? JSON.parse(JSON.stringify(pack)) : {};
  return {
    ...draft,
    id: String(draft.id || ''),
    name: String(draft.name || ''),
    revision: String(draft.revision || ''),
    updated_at: String(draft.updated_at || ''),
    description: String(draft.description || ''),
    instructions: String(draft.instructions || ''),
    note_paths: Array.isArray(draft.note_paths) ? draft.note_paths : [],
    workspace_files: Array.isArray(draft.workspace_files) ? draft.workspace_files : [],
  };
}

function contextPackDeleteBinding(draft = {}, editingId = '') {
  if (!draft.id || draft.id !== editingId || (!draft.revision && !draft.updated_at)) return null;
  return {
    id: draft.id,
    name: draft.name || 'Context pack',
    revision: draft.revision || '',
    updated_at: draft.updated_at || '',
  };
}

async function openContextPackEditor(packId = '') {
  if (!state.notesPayload.notes?.length) state.notesPayload = await fetchObsidianNotes();
  const pack = state.contextPacks.find((item) => item.id === packId);
  state.editingContextPackId = pack?.id || '';
  state.contextPackDraft = contextPackEditorDraft(pack || null);
  renderContextPackEditor();
  $('#context-pack-dialog')?.showModal();
}

async function searchContextPackWorkspace() {
  const results = $('#context-pack-workspace-results');
  if (!results) return;
  results.innerHTML = '<div class="agent-console-workspace-state mono">Searching…</div>';
  try {
    const payload = await fetchAgentConsoleWorkspaceFiles($('#context-pack-workspace-query')?.value || '');
    const selected = new Set((state.contextPackDraft?.workspace_files || []).map((item) => item.relative_path));
    const files = (payload.files || []).filter((file) => file.kind !== 'image');
    results.innerHTML = files.length ? files.map((file) => `<button type="button" class="agent-console-workspace-result" data-add-context-pack-root="${escapeHtml(file.root_id)}" data-add-context-pack-file="${escapeHtml(file.relative_path || file.path)}" ${selected.has(file.relative_path || file.path) ? 'disabled' : ''}><strong>${escapeHtml(file.relative_path || file.path)}</strong><span class="mono">${escapeHtml(file.kind || 'file')}</span></button>`).join('') : '<div class="agent-console-workspace-state mono">No matching text files.</div>';
  } catch (err) {
    results.innerHTML = `<div class="agent-console-workspace-state error mono">${escapeHtml(err.message)}</div>`;
  }
}

async function submitContextPackEditor() {
  const form = $('#context-pack-form');
  const status = $('#context-pack-status');
  if (!form || !state.contextPackDraft) return;
  const payload = {
    name: form.elements.name.value,
    description: form.elements.description.value,
    instructions: form.elements.instructions.value,
    note_paths: $$('#context-pack-note-options input:checked').map((input) => input.value),
    workspace_files: state.contextPackDraft.workspace_files || [],
  };
  try {
    const result = state.editingContextPackId ? await saveContextPack(state.editingContextPackId, payload) : await createContextPack(payload);
    renderContextPacks(result);
    $('#context-pack-dialog')?.close();
  } catch (err) {
    if (status) status.textContent = err.message;
  }
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
  if (label) {
    label.textContent = `${statusLabel} · ${payload.summary || 'No subsystem summary available.'}`;
    label.title = label.textContent;
  }
  if (pill) {
    pill.textContent = statusLabel;
    pill.className = `pill ${healthTone(status)}`;
  }
  if (!summary) return;
  const subsystems = Array.isArray(payload.subsystems) ? payload.subsystems : [];
  summary.innerHTML = subsystems.length ? subsystems.map((item) => {
    const metaValues = item.key === 'remote_hermes'
      ? [item.label, item.version, item.model, item.category]
      : [item.path, item.size, item.modified_at];
    const meta = metaValues.filter(Boolean).map((value) => escapeHtml(value)).join(' · ');
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

  let calendarRequestWeekKey = '';
  if (activeView === 'calendar') {
    const weekStart = calendarWeekStartDate();
    calendarRequestWeekKey = calendarDateKey(weekStart);
    state.calendarWeekStart = calendarRequestWeekKey;
    requests.calendar = api(calendarWeekRequestUrl(weekStart));
  } else if (activeView === 'today') {
    requests.calendar = api(endpoints.calendar);
  }
  if (activeView === 'today') requests.agentConsole = api(endpoints.agentConsole);
  if (activeView === 'today' || activeView === 'agents') requests.agentActivity = api(endpoints.agentActivity);
  if (activeView === 'today') requests.agentConsoleCommandManifest = fetchAgentConsoleCommandManifest();
  if (activeView === 'today' || activeView === 'agents') {
    requests.sessions = api(endpoints.sessions);
    if (activeView === 'agents') {
      requests.agents = api(endpoints.agents);
      requests.hermesProfiles = fetchHermesProfiles();
    }
  }
  if (activeView === 'today' || activeView === 'projects' || activeView === 'agents') requests.projects = api(endpoints.projects);
  if (activeView === 'agents') requests.crons = api(endpoints.crons);
  if (activeView === 'notes') requests.notes = api(endpoints.notes);
  if (activeView === 'today' || activeView === 'notes') requests.contextPacks = fetchContextPacks();
  if (activeView === 'settings') {
    requests.config = api(endpoints.config);
    requests.hermesCapabilities = api(endpoints.hermesCapabilities);
  }

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
    renderAndNotifyReminders(tasks);
    renderIfChanged(`tasks-${state.taskStatusFilter}-${state.taskFilter}-${state.projectFilter}-${state.selectedTaskId}-${state.taskEditorMode}`, tasks, renderTaskList);
    if (data.projects) renderIfChanged(`projects-${state.projectFilter}-${state.projectEditorMode}`, state.projects, renderProjects);
    renderIfChanged(`focus-${state.projectFilter}`, tasks, renderFocusTasks);
    renderIfChanged(`completed-${state.projectFilter}`, tasks, renderCompletedWork);
    if (data.calendar && (activeView !== 'calendar' || state.calendarWeekStart === calendarRequestWeekKey)) {
      const cacheKey = activeView === 'calendar' ? `calendar-week-${calendarRequestWeekKey}` : 'calendar-agenda';
      renderIfChanged(cacheKey, data.calendar, (payload) => renderCalendar(payload, { view: activeView }));
    }
    if (data.agentConsoleCommandManifest) setAgentConsoleCommandManifest(data.agentConsoleCommandManifest);
    if (data.agentConsole) renderAgentConsole(data.agentConsole);
    if (data.agentActivity) renderIfChanged('agent-activity', data.agentActivity, renderAgentActivity);
    if (data.crons) renderIfChanged('crons', data.crons, renderCrons);
    if (data.hermesProfiles) renderIfChanged('hermes-profiles', data.hermesProfiles, renderHermesProfiles);
    if (data.sessions || data.agents) {
      if (data.sessions) renderIfChanged(`sessions-${state.sessionFilter}-${state.selectedSessionId}`, data.sessions, renderSessions);
      if (data.sessions) renderIfChanged('model-usage', data.sessions, renderModelUsageChart);
      if (activeView === 'agents') {
        const agentPulsePayload = {
          ...(data.agents || {}),
          sessions: data.sessions?.sessions || data.sessions || [],
        };
        state.lastAgentPulsePayload = agentPulsePayload;
        renderIfChanged('agent-pulse', agentPulsePayload, renderAgentPulse);
      }
    }
    if (data.notes) renderIfChanged('notes', data.notes, renderNotes);
    if (data.contextPacks) renderContextPacks(data.contextPacks);
    if (data.config) renderIfChanged('config', data.config, renderConfig);
    if (data.hermesCapabilities) renderIfChanged('hermes-capabilities', data.hermesCapabilities, renderHermesCapabilityInventory);

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

async function runMessageSearchRequest(request) {
  if (state.messageSearchInFlight) {
    state.messageSearchPending = request;
    return;
  }
  state.messageSearchInFlight = true;
  try {
    const payload = await searchMessages(request.term);
    if (request.generation !== state.messageSearchRequestGeneration) return;
    renderMessageSearchResults(payload, request.term);
  } catch (err) {
    if (request.generation !== state.messageSearchRequestGeneration) return;
    console.error(err);
    renderMessageSearchResults({ error: err.message }, request.term);
  } finally {
    state.messageSearchInFlight = false;
    const pendingRequest = state.messageSearchPending;
    state.messageSearchPending = null;
    if (
      pendingRequest
      && pendingRequest.generation === state.messageSearchRequestGeneration
    ) {
      void runMessageSearchRequest(pendingRequest);
    }
  }
}

function queueMessageSearch(query) {
  const term = (query || '').trim();
  clearTimeout(state.messageSearchTimer);
  const requestGeneration = state.messageSearchRequestGeneration + 1;
  state.messageSearchRequestGeneration = requestGeneration;
  state.messageSearchPending = null;
  if (searchQueryLength(term) < 2) {
    renderMessageSearchResults({}, term);
    return;
  }
  const container = $('#message-search-results');
  if (container) container.innerHTML = `<div class="empty">Searching Hermes messages for “${escapeHtml(term)}”…</div>`;
  state.messageSearchTimer = setTimeout(() => {
    void runMessageSearchRequest({ term, generation: requestGeneration });
  }, 250);
}

function renderGlobalSearchResults(payload = {}) {
  const container = $('#global-search-results');
  const input = $('#global-search');
  if (!container || !input) return;
  const groups = payload.groups || {};
  const groupOrder = [['tasks', 'Tasks'], ['projects', 'Projects'], ['sessions', 'Sessions'], ['notes', 'Notes'], ['calendar', 'Calendar']];
  const flat = [];
  const markup = groupOrder.map(([key, label]) => {
    const items = Array.isArray(groups[key]) ? groups[key] : [];
    if (!items.length) return '';
    return `<section class="global-search-group"><h3>${label}</h3>${items.map((item) => {
      const index = flat.length;
      flat.push(item);
      return `<button id="global-search-result-${index}" class="global-search-result" type="button" role="option" data-global-search-index="${index}" aria-selected="false"><strong>${escapeHtml(item.label || '')}</strong><small>${escapeHtml(item.excerpt || '')}</small></button>`;
    }).join('')}</section>`;
  }).join('');
  state.globalSearchResults = flat;
  state.globalSearchSelectedIndex = -1;
  container.innerHTML = markup || '<div class="empty">No matching dashboard items.</div>';
  container.hidden = false;
  input.setAttribute('aria-expanded', 'true');
  input.removeAttribute('aria-activedescendant');
}

function closeGlobalSearch() {
  const container = $('#global-search-results');
  const input = $('#global-search');
  if (container) container.hidden = true;
  if (input) {
    input.setAttribute('aria-expanded', 'false');
    input.removeAttribute('aria-activedescendant');
  }
  state.globalSearchSelectedIndex = -1;
}

function selectGlobalSearchIndex(index) {
  if (!state.globalSearchResults.length) return;
  const bounded = Math.max(0, Math.min(index, state.globalSearchResults.length - 1));
  state.globalSearchSelectedIndex = bounded;
  $$('.global-search-result').forEach((item, itemIndex) => item.setAttribute('aria-selected', itemIndex === bounded ? 'true' : 'false'));
  $('#global-search')?.setAttribute('aria-activedescendant', `global-search-result-${bounded}`);
}

async function navigateGlobalSearchResult(result) {
  if (!result) return;
  closeGlobalSearch();
  if (result.kind === 'task') {
    state.projectFilter = result.project || '';
    state.taskStatusFilter = 'all';
    state.taskFilter = '';
    state.selectedTaskId = result.id || '';
    await setView('projects');
    renderProjectScopedViews();
    flashTarget($('#selected-task-panel'));
  } else if (result.kind === 'project') {
    state.projectFilter = result.project || result.label || '';
    await setView('projects');
    renderProjectScopedViews();
  } else if (result.kind === 'session') {
    state.selectedSessionId = result.id || '';
    await setView('agents');
    renderSessions({ sessions: state.sessions });
  } else {
    await setView(result.view || (result.kind === 'note' ? 'notes' : 'calendar'));
  }
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

$('#quick-capture-form')?.addEventListener('submit', async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const title = String(new FormData(form).get('title') || '').trim();
  const project = String(new FormData(form).get('project') || state.projects[0]?.name || '').trim();
  const status = $('#quick-capture-status');
  if (!title || !project) return;
  if (status) status.textContent = 'Adding to today…';
  try {
    const result = await createTask({
      title,
      project,
      status: 'todo',
      priority: 'medium',
      planned_for_today: true,
      manual_rank: state.tasks.filter((task) => task.planned_for_today && isOpenTask(task)).length + 1,
      estimated_minutes: 30,
      planning_state: 'planned',
    });
    form.reset();
    state.tasks = Array.isArray(result.tasks) ? result.tasks : [...state.tasks, result.task];
    renderProjectScopedViews();
    if (status) status.textContent = 'Added to today.';
  } catch (err) {
    if (status) status.textContent = err.message;
  }
});

$('#enable-reminders-button')?.addEventListener('click', async () => {
  const button = $('#enable-reminders-button');
  if (typeof Notification === 'undefined') {
    button.textContent = 'Browser Notifications Unavailable';
    return;
  }
  const permission = await Notification.requestPermission();
  button.textContent = permission === 'granted' ? 'Reminders Enabled' : 'Use In-App Reminders';
  renderAndNotifyReminders(state.tasks);
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
  globalSearch.addEventListener('input', (event) => {
    const query = event.target.value.trim();
    clearTimeout(state.globalSearchTimer);
    state.globalSearchRequestToken += 1;
    if (query.length < 2) {
      closeGlobalSearch();
      return;
    }
    const requestToken = state.globalSearchRequestToken;
    state.globalSearchTimer = window.setTimeout(async () => {
      try {
        const payload = await searchDashboard(query);
        if (requestToken === state.globalSearchRequestToken) renderGlobalSearchResults(payload);
      } catch (err) {
        if (requestToken === state.globalSearchRequestToken) renderGlobalSearchResults({ groups: {} });
      }
    }, 180);
  });
  globalSearch.addEventListener('keydown', async (event) => {
    if (event.key === 'Escape') {
      closeGlobalSearch();
      return;
    }
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      const delta = event.key === 'ArrowDown' ? 1 : -1;
      const start = state.globalSearchSelectedIndex < 0 ? (delta > 0 ? 0 : state.globalSearchResults.length - 1) : state.globalSearchSelectedIndex + delta;
      selectGlobalSearchIndex(start);
      return;
    }
    if (event.key === 'Enter' && state.globalSearchSelectedIndex >= 0) {
      event.preventDefault();
      await navigateGlobalSearchResult(state.globalSearchResults[state.globalSearchSelectedIndex]);
    }
  });
}

$('#global-search-results')?.addEventListener('click', async (event) => {
  const result = event.target.closest('[data-global-search-index]');
  if (!result) return;
  await navigateGlobalSearchResult(state.globalSearchResults[Number(result.dataset.globalSearchIndex)]);
});

$('#notes-search')?.addEventListener('input', (event) => {
  const query = event.target.value.trim();
  state.notesFilter = query;
  clearTimeout(state.notesSearchTimer);
  state.notesSearchTimer = window.setTimeout(async () => {
    try {
      renderNotes(await fetchObsidianNotes(query));
    } catch (err) {
      $('#notes-vault-meta').textContent = err.message;
    }
  }, 180);
});

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

$('#agent-console-attach')?.addEventListener('click', (event) => {
  event.stopPropagation();
  const menu = $('#agent-console-attachment-menu');
  setAgentConsoleAttachmentMenu(Boolean(menu?.hidden));
});

$('#agent-console-attachment-menu')?.addEventListener('click', (event) => {
  const upload = event.target.closest('[data-agent-console-upload]');
  if (upload) {
    setAgentConsoleAttachmentMenu(false);
    $('#agent-console-file-input')?.click();
    return;
  }
  if (event.target.closest('[data-agent-console-workspace]')) {
    openAgentConsoleWorkspacePicker();
    return;
  }
  if (event.target.closest('[data-agent-console-context-packs]')) {
    openAgentConsoleContextPackPicker();
    return;
  }
  if (event.target.closest('[data-agent-console-context-pack-back]')) {
    closeAgentConsoleWorkspacePicker();
    return;
  }
  const contextPack = event.target.closest('[data-apply-context-pack]');
  if (contextPack) {
    void applyContextPackToConsole(contextPack.dataset.applyContextPack || '');
    return;
  }
  if (event.target.closest('[data-agent-console-workspace-back]')) {
    closeAgentConsoleWorkspacePicker();
    return;
  }
  if (event.target.closest('[data-agent-console-workspace-search]')) {
    clearTimeout(state.agentConsoleWorkspaceSearchTimer);
    void searchAgentConsoleWorkspaceFiles($('#agent-console-workspace-query')?.value || '');
    return;
  }
  const workspaceFile = event.target.closest('[data-agent-console-workspace-path]');
  if (workspaceFile) {
    void addAgentConsoleWorkspaceFile(
      workspaceFile.dataset.agentConsoleWorkspaceRoot || '',
      workspaceFile.dataset.agentConsoleWorkspacePath || '',
    );
  }
});

$('#agent-console-workspace-query')?.addEventListener('input', queueAgentConsoleWorkspaceSearch);
$('#agent-console-workspace-query')?.addEventListener('keydown', (event) => {
  if (event.key !== 'Enter' || event.isComposing) return;
  event.preventDefault();
  clearTimeout(state.agentConsoleWorkspaceSearchTimer);
  void searchAgentConsoleWorkspaceFiles(event.currentTarget.value || '');
});

$('#agent-console-file-input')?.addEventListener('change', (event) => {
  void addAgentConsoleFiles(Array.from(event.target.files || []));
});

$('#agent-console-attachment-tray')?.addEventListener('click', (event) => {
  const dismissError = event.target.closest('[data-dismiss-agent-console-attachment-error]');
  if (dismissError) {
    state.agentConsoleAttachmentError = '';
    renderAgentConsoleAttachmentTray();
    return;
  }
  const remove = event.target.closest('[data-remove-agent-console-attachment]');
  if (!remove) return;
  const id = remove.dataset.removeAgentConsoleAttachment || '';
  if ((state.agentConsoleRemoteContext?.attachment_ids || []).includes(id)) {
    clearAgentConsoleRemoteContext({ removeAttachments: true });
  }
  state.agentConsoleAttachments = state.agentConsoleAttachments.filter((attachment) => attachment.id !== id);
  renderAgentConsoleAttachmentTray();
});

document.addEventListener('click', (event) => {
  const copy = event.target.closest('[data-copy-code]');
  if (copy) void copyRenderedCode(copy);
});

document.addEventListener('click', (event) => {
  if (!event.target.closest('#agent-console-attachment-menu, #agent-console-attach')) setAgentConsoleAttachmentMenu(false);
});

$('#agent-console-agent')?.addEventListener('change', async (event) => {
  state.agentConsoleSelectedAgentId = event.target.value || 'default';
  state.agentConsoleSelectedProvider = '';
  state.agentConsoleSelectedModel = '';
  state.agentConsoleProviderInventory = {};
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
$('#agent-console-provider-select')?.addEventListener('change', (event) => {
  state.agentConsoleSelectedProvider = event.target.value || '';
  state.agentConsoleSelectedModel = '';
  renderAgentConsole({ agents: state.agentConsoleAgents, provider_inventory: state.agentConsoleProviderInventory, runs: state.agentConsoleRuns });
});
$('#agent-console-apply-model')?.addEventListener('click', () => void applyAgentConsoleModel());
$('[data-provider-switch-confirm]')?.addEventListener('click', () => void confirmAgentConsoleProviderSwitch());
$$('[data-provider-switch-cancel]').forEach((button) => button.addEventListener('click', () => {
  state.agentConsoleProviderPreview = null;
  $('#provider-switch-dialog')?.close();
  const status = $('#provider-switch-status');
  if (status) status.textContent = '';
}));
document.addEventListener('change', (event) => {
  if (event.target.matches('#managed-agent-provider-select')) {
    state.managedAgentSelectedProvider = event.target.value || '';
    state.managedAgentSelectedModel = '';
    renderHermesProfiles({
      profiles: state.hermesProfiles,
      active_profile: state.activeHermesProfileId,
      capabilities: state.hermesProfileCapabilities,
      status: 'available',
    });
  } else if (event.target.matches('#managed-agent-model-select')) {
    state.managedAgentSelectedModel = event.target.value || '';
  }
});
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
  const weekNavigation = event.target.closest('[data-calendar-week-nav]');
  if (weekNavigation) {
    await navigateCalendarWeek(weekNavigation.dataset.calendarWeekNav || 'today');
    return;
  }
  const calendarEvent = event.target.closest('[data-calendar-event-select]');
  if (calendarEvent) {
    selectCalendarEvent(calendarEvent.dataset.calendarEventSelect || '');
    return;
  }
  if (event.target.closest('#calendar-inspector-close')) {
    selectCalendarEvent('');
    return;
  }
  const triggerCronButton = event.target.closest('[data-trigger-cron]');
  if (triggerCronButton) {
    await openCronTrigger(triggerCronButton.dataset.triggerCron || '');
    return;
  }
  if (event.target.closest('[data-cron-trigger-cancel]')) {
    closeCronTrigger();
    return;
  }
  if (event.target.closest('[data-cron-trigger-confirm]')) {
    await submitCronTrigger();
    return;
  }
  if (event.target.closest('[data-task-delete-cancel]')) {
    closeTaskDeletion();
    return;
  }
  if (event.target.closest('[data-task-delete-confirm]')) {
    await submitTaskDeletion();
    return;
  }
  if (event.target.closest('[data-task-delegation-cancel]')) {
    closeTaskDelegation();
    return;
  }
  if (event.target.closest('[data-task-delegation-preview]')) {
    await reviewTaskDelegation();
    return;
  }
  if (event.target.closest('[data-delegation-action-cancel]')) {
    closeDelegationAction();
    return;
  }
  if (event.target.closest('[data-delegation-action-confirm]')) {
    await submitDelegationAction();
    return;
  }
  const selectProfile = event.target.closest('[data-select-hermes-profile]');
  if (selectProfile) {
    state.selectedHermesProfileId = selectProfile.dataset.selectHermesProfile || '';
    state.managedAgentProviderInventory = {};
    state.managedAgentSelectedProvider = '';
    state.managedAgentSelectedModel = '';
    renderHermesProfiles({
      profiles: state.hermesProfiles,
      active_profile: state.activeHermesProfileId,
      capabilities: state.hermesProfileCapabilities,
      status: 'available',
    });
    await Promise.all([
      loadManagedAgentProviderInventory(state.selectedHermesProfileId),
      loadManagedAgentIdentity(state.selectedHermesProfileId),
    ]);
    return;
  }

  const loadProviders = event.target.closest('[data-load-managed-agent-providers]');
  if (loadProviders) {
    await loadManagedAgentProviderInventory(loadProviders.dataset.loadManagedAgentProviders || state.selectedHermesProfileId);
    return;
  }

  const reviewProvider = event.target.closest('[data-review-managed-agent-provider]');
  if (reviewProvider) {
    await reviewManagedAgentProvider(reviewProvider.dataset.reviewManagedAgentProvider || state.selectedHermesProfileId);
    return;
  }

  const reviewIdentity = event.target.closest('[data-review-agent-identity]');
  if (reviewIdentity) {
    await openAgentIdentityReview(reviewIdentity.dataset.reviewAgentIdentity || state.selectedHermesProfileId);
    return;
  }

  if (event.target.closest('[data-agent-identity-cancel]')) {
    closeAgentIdentityDialog();
    return;
  }

  if (event.target.closest('[data-agent-identity-confirm]')) {
    await submitAgentIdentityUpdate();
    return;
  }

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

  const testProfile = event.target.closest('[data-test-hermes-profile], [data-agent-creator-test]');
  if (testProfile) {
    $('#agent-creator-dialog')?.close();
    await testHermesProfile(testProfile.dataset.testHermesProfile || testProfile.dataset.agentCreatorTest || state.selectedHermesProfileId);
    return;
  }

  const assignProfile = event.target.closest('[data-assign-first-task], [data-agent-creator-assign-first-task]');
  if (assignProfile) {
    $('#agent-creator-dialog')?.close();
    await assignFirstTaskToProfile(assignProfile.dataset.assignFirstTask || assignProfile.dataset.agentCreatorAssignFirstTask || state.selectedHermesProfileId);
    return;
  }

  const useProfile = event.target.closest('[data-use-hermes-profile]');
  if (useProfile) {
    await useHermesProfileInConsole(useProfile.dataset.useHermesProfile || 'default');
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

  const attachNote = event.target.closest('[data-attach-note]');
  if (attachNote) {
    const selected = state.tasks.find((task) => String(task.id || '') === state.selectedTaskId);
    if (!selected?.id) {
      $('#health-label').textContent = 'Select a task in Projects / Tasks before attaching a note.';
      return;
    }
    try {
      const result = await attachNoteToTask(selected.id, attachNote.dataset.attachNote || '');
      state.tasks = Array.isArray(result.tasks) ? result.tasks : state.tasks.map((task) => task.id === result.task?.id ? result.task : task);
      $('#health-label').textContent = `Attached note to ${selected.title}.`;
      renderProjectScopedViews();
    } catch (err) {
      $('#health-label').textContent = `Note attachment failed: ${err.message}`;
    }
    return;
  }

  const detachNote = event.target.closest('[data-detach-note]');
  if (detachNote) {
    const selected = selectedTaskFrom(visibleTasks(state.tasks));
    if (!selected?.id) return;
    try {
      const result = await detachNoteFromTask(selected.id, detachNote.dataset.detachNote || '');
      state.tasks = Array.isArray(result.tasks) ? result.tasks : state.tasks.map((task) => task.id === result.task?.id ? result.task : task);
      renderProjectScopedViews();
    } catch (err) {
      $('#health-label').textContent = `Note detach failed: ${err.message}`;
    }
    return;
  }

  if (event.target.closest('[data-view-task-notes]')) {
    await setView('notes');
    return;
  }

  const createFromCalendar = event.target.closest('[data-calendar-create-task]');
  if (createFromCalendar) {
    const project = state.projectFilter || state.projects[0]?.name || '';
    if (!project) {
      $('#health-label').textContent = 'Create a Mentat project before turning calendar events into tasks.';
      return;
    }
    try {
      const result = await createTaskFromCalendarEvent(
        createFromCalendar.dataset.calendarCreateTask || '',
        project,
        calendarMutationContext(createFromCalendar),
      );
      state.tasks = Array.isArray(result.tasks) ? result.tasks : [...state.tasks, result.task];
      state.selectedTaskId = result.task?.id || '';
      state.projectFilter = result.task?.project || project;
      await setView('projects');
      renderProjectScopedViews();
    } catch (err) {
      $('#health-label').textContent = `Calendar task failed: ${err.message}`;
    }
    return;
  }

  const linkCalendar = event.target.closest('[data-calendar-link-task]');
  if (linkCalendar) {
    const selected = state.tasks.find((task) => String(task.id || '') === state.selectedTaskId);
    if (!selected?.id) {
      $('#health-label').textContent = 'Select a task in Projects / Tasks before linking a calendar event.';
      return;
    }
    try {
      const result = await linkTaskToCalendarEvent(
        selected.id,
        linkCalendar.dataset.calendarLinkTask || '',
        calendarMutationContext(linkCalendar),
      );
      state.tasks = Array.isArray(result.tasks) ? result.tasks : state.tasks.map((task) => task.id === result.task?.id ? result.task : task);
      $('#health-label').textContent = `Linked calendar event to ${selected.title}.`;
      renderProjectScopedViews();
    } catch (err) {
      $('#health-label').textContent = `Calendar link failed: ${err.message}`;
    }
    return;
  }

  const linkedCalendarTask = event.target.closest('[data-calendar-linked-task]');
  if (linkedCalendarTask) {
    const task = state.tasks.find((item) => String(item.id || '') === linkedCalendarTask.dataset.calendarLinkedTask);
    if (!task) return;
    state.selectedTaskId = task.id;
    state.projectFilter = task.project || '';
    state.taskStatusFilter = 'all';
    await setView('projects');
    renderProjectScopedViews();
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

  if (event.target.closest('#selected-task-delete')) {
    const selected = selectedTaskFrom(visibleTasks(state.tasks));
    if (selected?.id) await openTaskDeletion(selected.id);
    return;
  }

  if (event.target.closest('#selected-task-delegate')) {
    const selected = selectedTaskFrom(visibleTasks(state.tasks));
    if (selected) await openTaskDelegation(selected);
    return;
  }

  const refreshDelegation = event.target.closest('[data-delegation-refresh]');
  if (refreshDelegation) {
    await refreshSelectedTaskDelegation(refreshDelegation.dataset.delegationRefresh || '');
    return;
  }

  const delegationAction = event.target.closest('[data-delegation-action]');
  if (delegationAction) {
    await openDelegationAction(delegationAction.dataset.delegationAction || '');
    return;
  }

  const todayMove = event.target.closest('[data-today-move]');
  if (todayMove) {
    const selected = selectedTaskFrom(visibleTasks(state.tasks));
    if (!selected?.id) return;
    try {
      const result = await reorderTodayTask(selected.id, todayMove.dataset.todayMove || '');
      state.tasks = Array.isArray(result.tasks) ? result.tasks : state.tasks;
      renderProjectScopedViews();
      $('#health-label').textContent = `Moved ${selected.title} ${todayMove.dataset.todayMove === 'up' ? 'earlier' : 'later'} in today’s plan.`;
    } catch (err) {
      $('#health-label').textContent = `Today order failed: ${err.message}`;
    }
    return;
  }

  const activityTask = event.target.closest('[data-activity-task-id]');
  if (activityTask) {
    state.projectFilter = activityTask.dataset.activityProject || '';
    state.taskStatusFilter = 'all';
    state.selectedTaskId = activityTask.dataset.activityTaskId || '';
    await setView('projects');
    renderProjectScopedViews();
    flashTarget($('#selected-task-panel'));
    return;
  }

  const reminderTask = event.target.closest('[data-reminder-task]');
  if (reminderTask) {
    state.selectedTaskId = reminderTask.dataset.reminderTask || '';
    state.projectFilter = reminderTask.dataset.reminderProject || '';
    state.taskStatusFilter = 'all';
    await setView('projects');
    renderProjectScopedViews();
    return;
  }

  if (event.target.closest('#selected-task-cancel') || event.target.closest('[data-task-editor-cancel]')) {
    closeTaskEditor();
  }
});

$('#task-delegation-form')?.addEventListener('submit', async (event) => {
  event.preventDefault();
  await submitTaskDelegation();
});

$('#create-context-pack')?.addEventListener('click', () => void openContextPackEditor());
$('#context-pack-form')?.addEventListener('submit', (event) => {
  event.preventDefault();
  void submitContextPackEditor();
});
$$('[data-context-pack-cancel]').forEach((button) => button.addEventListener('click', () => $('#context-pack-dialog')?.close()));
$('[data-context-pack-workspace-search]')?.addEventListener('click', () => void searchContextPackWorkspace());
$('#context-pack-workspace-query')?.addEventListener('keydown', (event) => {
  if (event.key !== 'Enter') return;
  event.preventDefault();
  void searchContextPackWorkspace();
});
$('#context-pack-workspace-results')?.addEventListener('click', (event) => {
  const button = event.target.closest('[data-add-context-pack-file]');
  if (!button || !state.contextPackDraft) return;
  const choice = safeAgentConsoleWorkspaceChoice(button.dataset.addContextPackRoot, button.dataset.addContextPackFile);
  if (!choice) return;
  state.contextPackDraft.workspace_files ||= [];
  if (!state.contextPackDraft.workspace_files.some((item) => item.root_id === choice.root_id && item.relative_path === choice.relative_path)) state.contextPackDraft.workspace_files.push(choice);
  renderContextPackWorkspaceSelected();
  void searchContextPackWorkspace();
});
$('#context-pack-workspace-selected')?.addEventListener('click', (event) => {
  const button = event.target.closest('[data-remove-context-pack-file]');
  if (!button || !state.contextPackDraft) return;
  state.contextPackDraft.workspace_files = (state.contextPackDraft.workspace_files || []).filter((item) => item.relative_path !== button.dataset.removeContextPackFile);
  renderContextPackWorkspaceSelected();
});
$('[data-context-pack-delete]')?.addEventListener('click', async () => {
  const binding = contextPackDeleteBinding(state.contextPackDraft, state.editingContextPackId);
  if (!binding) {
    $('#context-pack-status').textContent = 'Reopen this context pack before deleting it.';
    return;
  }
  if (!window.confirm(`Delete context pack “${binding.name}”?`)) return;
  try {
    const result = await removeContextPack(binding.id, binding.revision, binding.updated_at);
    renderContextPacks(result);
    $('#context-pack-dialog')?.close();
  } catch (err) {
    $('#context-pack-status').textContent = err.message;
  }
});

$('#context-pack-list')?.addEventListener('click', async (event) => {
  const edit = event.target.closest('[data-edit-context-pack]');
  if (edit) return void openContextPackEditor(edit.dataset.editContextPack || '');
  const use = event.target.closest('[data-use-context-pack]');
  if (use) {
    await setView('today');
    await applyContextPackToConsole(use.dataset.useContextPack || '');
  }
});

$('#task-delegation-fields')?.addEventListener('input', () => {
  state.taskDelegationPreview = null;
  $('[data-task-delegation-confirm]').disabled = true;
});

$('#task-delegation-fields')?.addEventListener('change', () => {
  state.taskDelegationPreview = null;
  $('[data-task-delegation-confirm]').disabled = true;
});

$('#selected-task-detail')?.addEventListener('input', (event) => {
  const form = event.target.closest('#task-editor-form');
  if (!form) return;
  state.taskEditorDraft = taskPayloadFromForm(form);
});

$('#selected-task-detail')?.addEventListener('change', async (event) => {
  const subtaskToggle = event.target.closest('[data-subtask-toggle]');
  if (subtaskToggle) {
    const selected = selectedTaskFrom(visibleTasks(state.tasks));
    if (!selected?.id) return;
    const subtasks = (selected.subtasks || []).map((item) => item.id === subtaskToggle.dataset.subtaskToggle ? { ...item, completed: subtaskToggle.checked } : item);
    try {
      const result = await saveTaskEdits(selected.id, { subtasks });
      state.tasks = Array.isArray(result.tasks) ? result.tasks : state.tasks.map((task) => task.id === result.task?.id ? result.task : task);
      renderProjectScopedViews();
    } catch (err) {
      subtaskToggle.checked = !subtaskToggle.checked;
      $('#health-label').textContent = `Checklist update failed: ${err.message}`;
    }
    return;
  }
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
  if (sessionId) loadSessionDetail(sessionId, { messageId: result.dataset.messageId, query: result.dataset.matchText || result.dataset.query || state.sessionFilter });
});



loadDismissedAgentPulseIds();
setView('today');
refresh();
setInterval(refresh, REFRESH_MS);
