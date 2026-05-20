const $ = (id) => document.getElementById(id);
const { call, normalizeBridgeUrl, storageGet } = jdBrowser;

// Survives across re-renders triggered by the 5s refresh tick.
let expandedJobId = null;
let lastJobs = [];
let refreshPromise = null;

async function send(msg) {
  return await call('runtime.sendMessage', msg);
}

async function getBridgeUrl() {
  const { config } = await storageGet('config');
  return normalizeBridgeUrl(config?.bridgeUrl);
}

async function openPdf(jobId) {
  const base = await getBridgeUrl();
  await call('tabs.create', { url: `${base}/pdf/${encodeURIComponent(jobId)}` });
}

async function openCoverLetter(jobId) {
  const base = await getBridgeUrl();
  await call('tabs.create', { url: `${base}/cover-letter/${encodeURIComponent(jobId)}` });
}

async function setApplied(jobId, applied) {
  try {
    await send({ type: 'mark-applied', id: jobId, applied });
  } finally {
    await refresh();
  }
}

async function requestGenerate(jobId, includeCoverLetter) {
  try {
    await send({ type: 'generate-job', id: jobId, include_cover_letter: includeCoverLetter });
    setMessage(includeCoverLetter ? 'Generating resume + cover letter...' : 'Generating resume...', 'success');
  } catch (e) {
    setMessage(e?.message || 'Failed to start generation', 'error');
  } finally {
    await refresh();
  }
}

async function skipJob(jobId) {
  try {
    await send({ type: 'skip-job', id: jobId });
    setMessage('Skipped job', 'success');
  } catch (e) {
    setMessage(e?.message || 'Failed to skip job', 'error');
  } finally {
    await refresh();
  }
}

function timeAgo(ms) {
  if (!ms) return '';
  const s = Math.floor((Date.now() - ms) / 1000);
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

function focusToken(root) {
  const active = document.activeElement;
  if (!active || !root.contains(active)) return null;
  const item = active.closest('[data-job-id]');
  const key = active.dataset.focusKey;
  return item && key ? { jobId: item.dataset.jobId, key } : null;
}

function restoreFocus(root, token) {
  if (!token) return;
  for (const el of root.querySelectorAll('[data-focus-key]')) {
    if (el.dataset.focusKey === token.key && el.closest('[data-job-id]')?.dataset.jobId === token.jobId) {
      el.focus({ preventScroll: true });
      return;
    }
  }
}

function setMessage(text, tone = 'muted') {
  const message = $('message');
  message.hidden = !text;
  message.textContent = text || '';
  message.className = `message ${tone}`;
}

function statusLabel(status) {
  return ({
    pending: 'Pending',
    running: 'Running',
    evaluated: 'Evaluated',
    done: 'Done',
    failed: 'Failed',
    skipped: 'Skipped',
  })[status] || String(status || 'Pending');
}

function recommendationLabel(recommendation) {
  return ({
    apply: 'Apply',
    'long-shot': 'Long shot',
    skip: 'Skip',
  })[recommendation] || String(recommendation || '');
}

function makeEl(tag, className, text) {
  const el = document.createElement(tag);
  if (className) el.className = className;
  if (text != null) el.textContent = text;
  return el;
}

function makeChip(text, className = '') {
  const chip = makeEl('span', `chip ${className}`.trim(), text);
  chip.title = text;
  return chip;
}

function makeActionButton(label, focusKey, onClick, className = '') {
  const button = makeEl('button', `action-button ${className}`.trim(), label);
  button.type = 'button';
  button.dataset.focusKey = focusKey;
  button.addEventListener('click', onClick);
  return button;
}

function variantLabel(job) {
  if (!job.variant_used) return '';
  if (job.variant_used === 'tailored') return 'Tailored';
  return `Via ${job.variant_used}`;
}

function fitText(job) {
  const parts = [];
  if (job.compatibility_score != null && job.consideration_score != null) {
    parts.push(`${job.compatibility_score}/${job.consideration_score}`);
  }
  if (job.grade) parts.push(job.grade);
  if (job.recommendation) parts.push(recommendationLabel(job.recommendation));
  return parts.join(' ');
}

function statusTone(job) {
  if (job.applied_at) return 'applied';
  return job.status || 'pending';
}

function statusText(job) {
  if (job.applied_at) return 'Applied';
  if (job.status === 'running' && job.phase === 'generate') return 'Generating';
  return statusLabel(job.status);
}

function renderEmpty(text) {
  const li = makeEl('li', 'empty-state', text);
  return li;
}

function renderJobSummary(job, isExpanded) {
  const summary = makeEl('button', 'job-summary');
  summary.type = 'button';
  summary.dataset.focusKey = 'summary';
  summary.setAttribute('aria-expanded', String(isExpanded));
  summary.addEventListener('click', () => {
    expandedJobId = isExpanded ? null : job.id;
    renderJobs(lastJobs);
  });

  const main = makeEl('div', 'job-main');
  const title = makeEl('div', 'job-title');
  const company = makeEl('span', 'company', job.company || 'Unknown');
  const separator = makeEl('span', 'title-separator', '-');
  const role = makeEl('span', 'role', job.title || 'Untitled job');
  title.title = `${job.company || 'Unknown'} - ${job.title || 'Untitled job'}`;
  title.appendChild(company);
  title.appendChild(separator);
  title.appendChild(role);

  const meta = makeEl('div', 'job-meta');
  const fit = fitText(job);
  if (fit) meta.appendChild(makeChip(fit, `fit-${job.recommendation || 'score'}`));
  const variant = variantLabel(job);
  if (variant) meta.appendChild(makeChip(variant, job.variant_used === 'tailored' ? 'tailored' : ''));
  const age = timeAgo(job.applied_at || job.created_at);
  if (age) meta.appendChild(makeChip(job.applied_at ? `Applied ${age}` : age));
  if (!meta.childElementCount) meta.appendChild(makeChip(statusLabel(job.status)));

  main.appendChild(title);
  main.appendChild(meta);

  const side = makeEl('div', 'job-side');
  side.appendChild(makeEl('span', `job-status job-status-${statusTone(job)}`, statusText(job)));
  side.appendChild(makeEl('span', 'chevron'));

  summary.appendChild(main);
  summary.appendChild(side);
  return summary;
}

function renderJobDetails(job) {
  const details = makeEl('div', 'job-details');
  const actions = makeEl('div', 'job-actions');

  if (job.status === 'evaluated' || (job.status === 'failed' && job.phase === 'generate')) {
    actions.appendChild(makeActionButton(
      'Generate resume',
      'generate-resume',
      () => requestGenerate(job.id, false),
      'primary-action',
    ));
    actions.appendChild(makeActionButton(
      'Resume + cover',
      'generate-cover',
      () => requestGenerate(job.id, true),
    ));
  }

  if (job.status === 'evaluated' || job.status === 'failed') {
    actions.appendChild(makeActionButton('Skip', 'skip', () => skipJob(job.id), 'danger-action'));
  }

  if (job.status === 'done' && job.pdf_path) {
    actions.appendChild(makeActionButton('Resume', 'pdf', () => openPdf(job.id), 'primary-action'));
    if (job.cover_letter_pdf_path) {
      actions.appendChild(makeActionButton('Cover', 'cover-letter', () => openCoverLetter(job.id)));
    }
  }

  if (job.url) {
    actions.appendChild(makeActionButton('JD', 'jd', () => call('tabs.create', { url: job.url })));
  }

  actions.appendChild(makeActionButton(
    job.applied_at ? 'Undo applied' : 'Mark applied',
    'applied',
    () => setApplied(job.id, !job.applied_at),
    'applied-action',
  ));

  if (actions.childElementCount) details.appendChild(actions);

  if (job.rationale) {
    const block = makeEl('div', 'detail-block');
    block.appendChild(makeEl('div', 'detail-label', 'Why'));
    block.appendChild(makeEl('p', 'detail-text', job.rationale));
    details.appendChild(block);
  }

  if (job.status === 'evaluated' || job.status === 'done' || job.status === 'skipped') {
    const block = makeEl('div', 'detail-block');
    block.appendChild(makeEl('div', 'detail-label', 'Evaluation'));
    const evalText = [];
    if (job.compatibility_score != null) evalText.push(`Compatibility ${job.compatibility_score}/100`);
    if (job.consideration_score != null) evalText.push(`Consideration ${job.consideration_score}/100`);
    if (job.grade) evalText.push(`Grade ${job.grade}`);
    if (job.work_authorization) evalText.push(`Work auth ${job.work_authorization.replace('_', ' ')}`);
    if (evalText.length) block.appendChild(makeEl('p', 'detail-text', evalText.join(' - ')));
    if (Array.isArray(job.blockers) && job.blockers.length) {
      const blockers = makeEl('ul', 'blocker-list');
      for (const blocker of job.blockers.slice(0, 4)) {
        blockers.appendChild(makeEl('li', '', blocker));
      }
      block.appendChild(blockers);
    }
    if (block.childElementCount > 1) details.appendChild(block);
  }

  if (job.status === 'failed' && job.error) {
    const block = makeEl('div', 'detail-block error-block');
    const pre = makeEl('pre', '', job.error);
    pre.dataset.focusKey = 'error';
    block.appendChild(pre);
    details.appendChild(block);
  }

  return details;
}

function renderJob(job) {
  const isExpanded = expandedJobId === job.id;
  const li = makeEl('li', `job-card job-card-${job.status}${isExpanded ? ' expanded' : ''}${job.applied_at ? ' applied' : ''}`);
  li.dataset.jobId = job.id;
  li.appendChild(renderJobSummary(job, isExpanded));
  if (isExpanded) li.appendChild(renderJobDetails(job));
  return li;
}

function renderJobs(jobs) {
  const ul = $('jobs');
  const scrollTop = ul.scrollTop;
  const focused = focusToken(ul);

  ul.innerHTML = '';
  if (!jobs.length) {
    ul.appendChild(renderEmpty('No jobs yet. Queue a LinkedIn job to start.'));
    return;
  }

  if (expandedJobId && !jobs.some((job) => job.id === expandedJobId)) {
    expandedJobId = null;
  }

  for (const job of jobs.slice(0, 15)) {
    ul.appendChild(renderJob(job));
  }

  restoreFocus(ul, focused);
  ul.scrollTop = scrollTop;
}

async function refresh() {
  if (refreshPromise) return await refreshPromise;
  refreshPromise = refreshOnce().finally(() => {
    refreshPromise = null;
  });
  return await refreshPromise;
}

async function refreshOnce() {
  let res;
  try {
    res = await send({ type: 'list-jobs' });
  } catch (e) {
    res = { error: e?.message ?? String(e) };
  }
  if (res?.error) {
    $('status').textContent = 'Bridge unreachable';
    $('status').className = 'bridge-status error';
    $('inflight').textContent = '';
    lastJobs = [];
    expandedJobId = null;
    const ul = $('jobs');
    ul.innerHTML = '';
    ul.appendChild(renderEmpty('Start jd-bridge, then check Settings if URL or token changed.'));
    return;
  }
  const jobs = res.jobs || [];
  const inflight = jobs.filter((j) => j.status === 'pending' || j.status === 'running').length;
  $('status').textContent = `${jobs.length} job${jobs.length === 1 ? '' : 's'}`;
  $('status').className = 'bridge-status';
  $('inflight').textContent = inflight ? `${inflight} active` : '';
  lastJobs = jobs;
  renderJobs(jobs);
}

$('queue').addEventListener('click', async () => {
  $('queue').disabled = true;
  setMessage('Extracting current tab...', 'muted');
  try {
    const res = await send({ type: 'queue-current-tab' });
    if (res?.ok) {
      setMessage(`Queued evaluation for ${res.company || 'job'} - ${res.title || res.id}`, 'success');
    } else {
      setMessage(res?.error || 'Failed to queue job', 'error');
    }
  } catch (e) {
    setMessage(e?.message || 'Failed to queue job', 'error');
  } finally {
    $('queue').disabled = false;
    await refresh();
  }
});

$('open-options').addEventListener('click', (e) => {
  e.preventDefault();
  call('runtime.openOptionsPage').catch(() => {});
});

refresh();
const refresher = setInterval(refresh, 5000);
window.addEventListener('unload', () => clearInterval(refresher));
