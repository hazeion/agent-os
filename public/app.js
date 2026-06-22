function humanDate(value) {
  if (!value) return '—';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return String(value);
  return fmt.format(d);
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
  if (state.hasBootstrapped && viewChanged && refreshOnChange) return refresh();
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

function renderProjectScopedViews() {
  renderTaskList(state.tasks);
  renderFocusTasks(state.tasks);
  renderProjects(state.projects);
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
  $('#attention-list').innerHTML = open.length ? open.map((item) => {
    const isTaskAttention = item.source === 'task' || item.task_id;
    const severityClass = item.severity === 'high' ? 'danger' : 'warn';
    return `
      <article class="item ${isTaskAttention ? 'attention-task-item' : ''}">
        <div class="item-title">
          <span>${escapeHtml(item.title)}</span>
          <span class="pill ${severityClass}">${escapeHtml(item.severity || 'medium')}</span>
        </div>
        <div class="item-desc">${escapeHtml(item.description || '')}</div>
        <div class="item-meta mono">${escapeHtml(item.type || 'manual')} · ${escapeHtml(item.project || 'General')} · ${humanDate(item.created_at)}</div>
        <div class="item-actions">
          ${isTaskAttention
            ? `<button class="action-button open-task-source" type="button" data-project-name="${escapeHtml(item.project || '')}" data-task-id="${escapeHtml(item.task_id || '')}">Open task</button>`
            : `<button class="action-button resolve-attention" type="button" data-attention-id="${escapeHtml(item.id)}">Resolve</button>`}
        </div>
      </article>
    `;
  }).join('') : `<div class="empty clear-skies">No open attention items. Clear skies.</div>`;
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

function selectedTaskFrom(tasks = []) {
  if (!tasks.length) return null;
  let selected = tasks.find((task, index) => taskId(task, index) === state.selectedTaskId);
  if (!selected) {
    selected = tasks[0];
    state.selectedTaskId = taskId(selected, 0);
  }
  return selected;
}

function renderSelectedTaskInspector(tasks = visibleTasks(state.tasks)) {
  const container = $('#selected-task-detail');
  const context = $('#selected-task-context');
  if (!container) return;
  const selected = selectedTaskFrom(tasks);
  if (!selected) {
    if (context) context.textContent = 'detail rail';
    container.innerHTML = `<div class="empty">No tasks match ${escapeHtml(filterSummary())}. Adjust the project, status, or search filter to inspect a task.</div>`;
    return;
  }

  const area = taskArea(selected);
  const statusLabel = taskStatusLabels[area] || area;
  const tags = Array.isArray(selected.tags) ? selected.tags : [];
  const updated = selected.updated_at || selected.created_at || selected.completed_at;
  if (context) context.textContent = area === 'completed' ? 'history detail' : 'selected detail';
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
  const label = $('#task-status-label');
  const button = $('#task-status-button');
  const menu = $('#task-status-menu');

  if (label) label.textContent = taskStatusLabels[value] || value;
  if (button) button.dataset.value = value;
  menu?.querySelectorAll('[data-status-value]').forEach((option) => {
    option.setAttribute('aria-selected', option.dataset.statusValue === value ? 'true' : 'false');
  });
}

function setStatusDropdownOpen(open) {
  const shell = $('#task-status-select-shell');
  const button = $('#task-status-button');
  const menu = $('#task-status-menu');
  if (!shell || !button || !menu) return;

  shell.classList.toggle('is-open', open);
  button.setAttribute('aria-expanded', open ? 'true' : 'false');
  menu.hidden = !open;
}

function applyTaskStatusFilter(value = 'open') {
  state.taskStatusFilter = taskStatusLabels[value] ? value : 'open';
  syncTaskStatusControl();
  renderTaskList(state.tasks);
  setStatusDropdownOpen(false);
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

  const canScroll = rail.scrollWidth > rail.clientWidth + 4;
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
  const focus = open.slice(0, 4);

  const scopeLabel = state.projectFilter || (state.projects.length === 1 ? state.projects[0].name : 'All Projects');
  const completed = scoped.filter((task) => taskArea(task) === 'completed').length;
  const inProgress = open.filter((task) => taskArea(task) === 'in progress').length;
  const needsAttention = open.filter((task) => taskArea(task) === 'needs attention').length;
  const waiting = open.filter((task) => taskArea(task) === 'waiting').length;
  const nextTask = open[0];
  const statusLine = nextTask
    ? `Next: ${escapeHtml(nextTask.title)} · ${escapeHtml(taskArea(nextTask))}`
    : 'Queue clear — no open next moves in this scope.';
  const queueMeta = `${open.length} open · ${completed} done`;

  const header = `
    <section class="focus-queue-shell ${open.length ? '' : 'clear'}">
      <header class="focus-queue-header">
        <div class="focus-queue-copy">
          <div class="focus-kicker mono">Current queue</div>
          <h3>${escapeHtml(scopeLabel)} queue</h3>
          <p>${statusLine}</p>
        </div>
        <div class="focus-queue-head-meta detail-context-label mono">${escapeHtml(queueMeta)}</div>
        <div class="focus-stat-row" aria-label="Queue status summary">
          <span><strong>${inProgress}</strong> in progress</span>
          <span><strong>${needsAttention}</strong> attention</span>
          <span><strong>${waiting}</strong> waiting</span>
          <span><strong>${completed}</strong> completed</span>
        </div>
      </header>
      <div class="focus-task-rail">
  `;

  const taskCards = focus.length ? focus.map((task, index) => {
    const area = taskArea(task);
    return `
      <button class="item focus-task-item focus-task-button" type="button" data-focus-task-id="${escapeHtml(String(task.id || ''))}" data-focus-task-title="${escapeHtml(task.title || '')}" data-focus-project-name="${escapeHtml(task.project || '')}">
        <span class="focus-task-rank mono">${String(index + 1).padStart(2, '0')}</span>
        <div class="focus-task-body">
          <div class="item-title"><span>${escapeHtml(task.title)}</span><span class="task-state-text ${taskTone(area)}">${escapeHtml(area)}</span></div>
          <div class="item-desc">${escapeHtml(task.description || '')}</div>
          <div class="item-meta mono">${escapeHtml(task.project || 'General')} · due ${escapeHtml(task.due_date || 'none')}</div>
        </div>
      </button>
    `;
  }).join('') : `
      <div class="empty clear-skies">No open next moves in this scope.</div>
  `;

  $('#focus-task-list').innerHTML = `${header}${taskCards}</div></section>`;
}

function renderTaskList(tasks = []) {
  state.tasks = tasks;
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

function projectStats(projectName = '', tasks = state.tasks) {
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

function renderProjects(projects = []) {
  state.projects = projects;
  const projectCount = $('#project-count');
  if (projectCount) projectCount.textContent = `${projects.length} project${projects.length === 1 ? '' : 's'}`;

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
        <div class="progress-track mini" aria-hidden="true"><span style="width: ${stats.progress}%"></span></div>
      </button>
    `;
  }).join('') : `<div class="empty">No projects found. For now, ask Hermes to add one to <code>data/projects.json</code>.</div>`;
  requestAnimationFrame(updateProjectRailButtons);
  renderProjectStatus(projects, state.tasks);
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
  renderCalendarInto('#calendar-list', payload, { limit: 4 });
  renderCalendarInto('#calendar-full-list', payload, { limit: Infinity });
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
            <div class="message-content markdown-body">${renderMarkdown(message.content || '', query)}</div>
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
  $('#agent-pulse-pill').textContent = 'read-only now';
  $('#agent-pulse').innerHTML = `
    <div class="agent-orb"><span>${recentCount}</span><small>sessions</small></div>
    <div>
      <div class="item-title"><span>Historical pulse now · live heartbeat later</span></div>
      <div class="item-desc">Right now this only counts recent Hermes sessions from state.db. In Phase 4, Agent Pulse should become an active heartbeat/status panel where agents self-report running, blocked, done, failed, and needs-user-input states.</div>
      <div class="item-meta mono">Latest: ${latest ? `${escapeHtml(latest.title || 'Untitled')} · ${humanDate(latest.ended_at || latest.started_at)}` : 'No session data yet'}</div>
    </div>
  `;
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
    attention: api(endpoints.attention),
    health: api(endpoints.health),
  };

  if (activeView === 'today' || activeView === 'calendar') requests.calendar = api(endpoints.calendar);
  if (activeView === 'today' || activeView === 'agents') requests.sessions = api(endpoints.sessions);
  if (activeView === 'projects') requests.projects = api(endpoints.projects);
  if (activeView === 'agents') requests.crons = api(endpoints.crons);
  if (activeView === 'notes') requests.notes = api(endpoints.notes);
  if (activeView === 'settings') requests.config = api(endpoints.config);

  try {
    const entries = await Promise.all(Object.entries(requests).map(async ([key, promise]) => [key, await promise]));
    const data = Object.fromEntries(entries);

    renderGreeting(data.overview.identity || {});
    renderCards(data.overview.cards);
    if (data.projects) {
      state.projects = data.projects.projects || [];
      state.projectsLoaded = true;
    }
    renderTaskList(data.tasks.tasks);
    if (data.projects) renderProjects(state.projects);
    renderFocusTasks(data.tasks.tasks);
    renderAttention(data.attention.attention);
    if (data.calendar) renderCalendar(data.calendar);
    if (data.crons) renderCrons(data.crons);
    if (data.sessions) {
      renderSessions(data.sessions);
      renderSessionStats(data.sessions);
      renderAgentPulse(data.sessions);
    }
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

$('#focus-task-list').addEventListener('click', async (event) => {
  const taskButton = event.target.closest('.focus-task-button');
  if (!taskButton) return;

  state.projectFilter = taskButton.dataset.focusProjectName || '';
  state.taskStatusFilter = 'open';
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

const taskStatusButton = $('#task-status-button');
const taskStatusMenu = $('#task-status-menu');
const taskStatusShell = $('#task-status-select-shell');

if (taskStatusButton && taskStatusMenu && taskStatusShell) {
  taskStatusButton.addEventListener('click', (event) => {
    event.stopPropagation();
    setStatusDropdownOpen(!taskStatusShell.classList.contains('is-open'));
  });

  taskStatusMenu.addEventListener('click', (event) => {
    event.stopPropagation();
    const option = event.target.closest('[data-status-value]');
    if (!option) return;
    applyTaskStatusFilter(option.dataset.statusValue);
  });

  taskStatusShell.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') {
      setStatusDropdownOpen(false);
      taskStatusButton.focus();
      return;
    }
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      setStatusDropdownOpen(true);
      taskStatusMenu.querySelector('[aria-selected="true"]')?.focus();
    }
  });

  taskStatusMenu.addEventListener('keydown', (event) => {
    const options = Array.from(taskStatusMenu.querySelectorAll('[data-status-value]'));
    const index = options.indexOf(document.activeElement);
    if (event.key === 'Escape') {
      setStatusDropdownOpen(false);
      taskStatusButton.focus();
    } else if (event.key === 'ArrowDown') {
      event.preventDefault();
      options[Math.min(options.length - 1, index + 1)]?.focus();
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      options[Math.max(0, index - 1)]?.focus();
    }
  });

  document.addEventListener('pointerdown', (event) => {
    if (!taskStatusShell.contains(event.target)) setStatusDropdownOpen(false);
  });
}

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
  const taskButton = event.target.closest('.open-task-source');
  if (taskButton) {
    state.projectFilter = taskButton.dataset.projectName || '';
    state.taskStatusFilter = 'open';
    await setView('projects');
    renderProjectScopedViews();
    const tasksPanel = $('#tasks-panel');
    tasksPanel?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    flashTarget(tasksPanel);
    return;
  }

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

setView('projects');
refresh();
setInterval(refresh, REFRESH_MS);
