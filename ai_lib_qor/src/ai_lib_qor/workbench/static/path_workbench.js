/* Shared client interactions, accessible keyboard navigation, confirm modal, and async job monitor */

/* Reusable Accessible Confirmation Modal (uses native <dialog> when supported) */
var _confirmResolver = null;
function openConfirmDialog(title, message, confirmLabel, tone) {
  var dlg = document.getElementById('confirm-dialog');
  if (!dlg || typeof dlg.showModal !== 'function') {
    return Promise.resolve(window.confirm(message || title));
  }
  var titleEl = document.getElementById('confirm-title');
  var msgEl = document.getElementById('confirm-message');
  var okBtn = document.getElementById('confirm-ok-btn');
  var cancelBtn = document.getElementById('confirm-cancel-btn');
  if (titleEl) titleEl.textContent = title || '确认操作';
  if (msgEl) msgEl.textContent = message || '';
  if (okBtn) {
    okBtn.textContent = confirmLabel || '确认继续';
    okBtn.className = (tone === 'primary' ? 'btn-sm' : 'danger btn-sm');
  }
  return new Promise(function(resolve) {
    _confirmResolver = resolve;
    function finish(accepted) {
      if (dlg.open) dlg.close();
      var r = _confirmResolver;
      _confirmResolver = null;
      if (r) r(accepted);
    }
    okBtn.onclick = function() { finish(true); };
    cancelBtn.onclick = function() { finish(false); };
    dlg.oncancel = function(ev) { ev.preventDefault(); finish(false); };
    dlg.showModal();
  });
}

/* Form submission interceptor: confirmation modal + progressive-enhancement async job runner */
document.addEventListener('submit', function(e) {
  var form = e.target;
  if (!form || !form.method || form.method.toLowerCase() !== 'post') return;

  var confirmMsg = form.getAttribute('data-confirm');
  if (!confirmMsg && form.getAttribute('data-confirm-action') === 'acceptance') {
    var actSel = form.querySelector('select[name="action"]');
    if (actSel && actSel.value === 'rollback') {
      confirmMsg = '确认回退当前库的采纳版本？该操作会写入审计记录并立即生效。';
    }
  }
  if (confirmMsg && form.getAttribute('data-confirmed') !== '1') {
    e.preventDefault();
    var confirmTitle = form.getAttribute('data-confirm-title') || '确认执行操作';
    var confirmLabel = form.getAttribute('data-confirm-label') || '确认执行';
    var confirmTone = form.getAttribute('data-confirm-tone') || 'danger';
    openConfirmDialog(confirmTitle, confirmMsg, confirmLabel, confirmTone).then(function(ok) {
      if (!ok) return;
      form.setAttribute('data-confirmed', '1');
      if (typeof form.requestSubmit === 'function') form.requestSubmit();
      else form.dispatchEvent(new Event('submit', {bubbles: true, cancelable: true}));
      setTimeout(function() { form.removeAttribute('data-confirmed'); }, 50);
    });
    return;
  }

  var asyncUrl = form.getAttribute('data-async-url');
  if (asyncUrl && window.fetch && window.FormData) {
    e.preventDefault();
    runAsyncJobForm(form, asyncUrl);
    return;
  }
  var pending = document.getElementById('pending');
  if (pending) pending.hidden = false;
  form.querySelectorAll('button[type="submit"],button:not([type])').forEach(function(b) { b.disabled = true; });
});

/* Live Async Job Monitor with Real-time Progress Bar & Cooperative Cancellation */
var activeJobId = null;
var activeJobTimer = null;
var activeJobButtons = [];

function _csrfToken() {
  var m = document.querySelector('meta[name="csrf-token"]');
  return m ? m.getAttribute('content') : '';
}

function runAsyncJobForm(form, asyncUrl) {
  activeJobButtons = Array.prototype.slice.call(form.querySelectorAll('button[type="submit"],button:not([type])'));
  activeJobButtons.forEach(function(b) { b.disabled = true; });
  showJobPanel({
    label: '正在提交任务…', status: 'QUEUED', stage: 'QUEUED',
    message: '正在提交任务…', elapsed_seconds: 0, percent: null, events: []
  });
  var body = new FormData(form);
  fetch(asyncUrl, {method: 'POST', body: body, credentials: 'same-origin'})
    .then(function(r) { return r.json().then(function(d) { return {ok: r.ok, status: r.status, data: d}; }); })
    .then(function(res) {
      if (res.status === 409 && res.data && res.data.active_job && res.data.active_job.job_id) {
        activeJobId = res.data.active_job.job_id;
        try { sessionStorage.setItem('ai_lib_active_job', activeJobId); } catch (e) {}
        renderJobState(res.data.active_job);
        scheduleJobPoll();
        return;
      }
      if (!res.ok || !res.data.job_id) {
        renderJobState({
          label: '提交失败', status: 'FAILED', message: (res.data && res.data.error) || '未知错误',
          elapsed_seconds: 0, percent: 0, events: []
        });
        activeJobButtons.forEach(function(b) { b.disabled = false; });
        return;
      }
      activeJobId = res.data.job_id;
      try { sessionStorage.setItem('ai_lib_active_job', activeJobId); } catch (e) {}
      renderJobState(res.data);
      scheduleJobPoll();
    })
    .catch(function(err) {
      renderJobState({label: '网络异常', status: 'FAILED', message: String(err), elapsed_seconds: 0, percent: 0, events: []});
      activeJobButtons.forEach(function(b) { b.disabled = false; });
    });
}

function showJobPanel(job) {
  var panel = document.getElementById('async-job-panel');
  var reopen = document.getElementById('job-reopen-btn');
  if (panel) panel.hidden = false;
  if (reopen) reopen.hidden = true;
  renderJobState(job);
}

function minimizeJobPanel() {
  var panel = document.getElementById('async-job-panel');
  var reopen = document.getElementById('job-reopen-btn');
  if (panel) panel.hidden = true;
  if (reopen) reopen.hidden = false;
}

function reopenJobPanel() {
  var panel = document.getElementById('async-job-panel');
  var reopen = document.getElementById('job-reopen-btn');
  if (panel) panel.hidden = false;
  if (reopen) reopen.hidden = true;
}

function closeJobPanel() {
  var panel = document.getElementById('async-job-panel');
  var reopen = document.getElementById('job-reopen-btn');
  if (panel) panel.hidden = true;
  if (reopen) reopen.hidden = true;
  clearTimeout(activeJobTimer);
  activeJobId = null;
  try { sessionStorage.removeItem('ai_lib_active_job'); } catch (e) {}
}

function renderJobState(job) {
  var panel = document.getElementById('async-job-panel');
  if (!panel) return;
  panel.classList.remove('job-ok', 'job-warn', 'job-err');
  var badge = document.getElementById('job-status-badge');
  var title = document.getElementById('job-title');
  var elapsed = document.getElementById('job-elapsed');
  var bar = document.getElementById('job-progress-bar');
  var pct = document.getElementById('job-progress-pct');
  var msg = document.getElementById('job-message');
  var list = document.getElementById('job-events-list');
  var cancelBtn = document.getElementById('job-cancel-btn');
  var reloadBtn = document.getElementById('job-reload-btn');
  var closeBtn = document.getElementById('job-close-btn');
  var reopen = document.getElementById('job-reopen-btn');

  var st = job.status || 'RUNNING';
  var isActive = (st === 'QUEUED' || st === 'RUNNING' || st === 'CANCELLING');
  panel.classList.remove('job-ok', 'job-warn', 'job-err');
  if (title) title.textContent = job.label || '后台任务';
  if (elapsed) elapsed.textContent = (job.elapsed_seconds != null ? job.elapsed_seconds : 0) + 's';
  if (msg) msg.textContent = job.message || '';

  if (badge) {
    badge.className = 'tag ' + (
      st === 'SUCCEEDED' ? 'tag-new' :
      st === 'FAILED' ? 'tag-failed' :
      (st === 'PARTIAL' || st === 'CANCELLED' || st === 'CANCELLING') ? 'tag-partial' : 'tag-updated'
    );
    var labelMap = {QUEUED: '排队中', RUNNING: '运行中', CANCELLING: '正在终止…', CANCELLED: '已安全终止', SUCCEEDED: '已完成', PARTIAL: '部分失败', FAILED: '执行失败'};
    badge.innerHTML = '<span class="dot" aria-hidden="true"></span>' + (labelMap[st] || st);
  }
  if (st === 'SUCCEEDED') panel.classList.add('job-ok');
  else if (st === 'PARTIAL' || st === 'CANCELLED' || st === 'CANCELLING') panel.classList.add('job-warn');
  else if (st === 'FAILED') panel.classList.add('job-err');

  if (bar && pct) {
    if (job.percent != null) {
      bar.value = job.percent;
      bar.max = 100;
      pct.textContent = (job.total ? (job.completed + '/' + job.total + ' · ') : '') + job.percent + '%';
    } else if (!isActive) {
      bar.value = st === 'SUCCEEDED' ? 100 : 0;
      bar.max = 100;
      pct.textContent = st === 'SUCCEEDED' ? '100%' : '已停止';
    } else {
      bar.removeAttribute('value');
      pct.textContent = (job.stage || '执行中') + '…';
    }
  }

  if (list && Array.isArray(job.events)) {
    var frag = document.createDocumentFragment();
    job.events.forEach(function(ev) {
      var li = document.createElement('li');
      li.textContent = ev;
      frag.appendChild(li);
    });
    if (job.result && job.result.layer === 'ALL') {
      ['l1', 'l2', 'l3'].forEach(function(layer) {
        if (job.result[layer].status === 'SKIPPED') {
          var li = document.createElement('li');
          li.textContent = layer.toUpperCase() + ' 已按同步选项跳过';
          frag.appendChild(li);
        }
      });
    }
    var failures = job.result && (job.result.libraries_failed || []);
    if (job.result && job.result.layer === 'L2') {
      failures = failures.concat(job.result.effective_failures || []);
    }
    if (Array.isArray(failures)) {
      failures.forEach(function(row) {
        var li = document.createElement('li');
        li.textContent = (row.layer ? row.layer + ' · ' : '') + row.vendor + '/' + row.library + ' · ' + row.reason;
        frag.appendChild(li);
      });
    }
    list.textContent = '';
    list.appendChild(frag);
    list.scrollTop = list.scrollHeight;
  }

  if (cancelBtn) {
    cancelBtn.hidden = !isActive;
    cancelBtn.disabled = (st === 'CANCELLING');
    cancelBtn.textContent = (st === 'CANCELLING') ? '正在安全停止…' : '终止任务';
  }
  if (reloadBtn) {
    var scope = document.getElementById('check-scope');
    var reportUrl = st === 'SUCCEEDED' && job.result && job.result.report_url;
    var isAllIps = st === 'SUCCEEDED' && scope && job.kind === 'check_pending' && job.scope_key === scope.dataset.libraryCheckKey;
    reloadBtn.hidden = isActive;
    reloadBtn.textContent = reportUrl || isAllIps ? '查看检查报告' : '刷新结果';
    reloadBtn.onclick = function() {
      closeJobPanel();
      if (reportUrl) {
        location.assign(reportUrl);
        return;
      }
      if (isAllIps) history.replaceState(null, '', '#checks-all-ips');
      location.reload();
    };
  }
  if (closeBtn) closeBtn.hidden = isActive;
  if (reopen && !reopen.hidden) {
    reopen.textContent = isActive ? ('查看运行进度 (' + (job.percent != null ? job.percent + '%' : (job.stage || '运行中')) + ')') : '查看任务结果';
  }
}

function scheduleJobPoll() {
  if (activeJobTimer) clearTimeout(activeJobTimer);
  if (!activeJobId) return;
  activeJobTimer = setTimeout(function() {
    var jid = activeJobId;
    fetch('/api/v1/jobs/' + encodeURIComponent(jid), {credentials: 'same-origin'})
      .then(function(r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
      .then(function(job) {
        if (jid !== activeJobId) return;
        renderJobState(job);
        if (job.status === 'QUEUED' || job.status === 'RUNNING' || job.status === 'CANCELLING') {
          scheduleJobPoll();
        } else {
          activeJobButtons.forEach(function(b) { b.disabled = false; });
          if (!job.result || (!job.result.report_url && job.kind !== 'check_pending')) {
            try { sessionStorage.removeItem('ai_lib_active_job'); } catch (e) {}
          }
        }
      })
      .catch(function() {
        activeJobButtons.forEach(function(b) { b.disabled = false; });
      });
  }, 500);
}

function requestCancelActiveJob() {
  if (!activeJobId) return;
  openConfirmDialog(
    '终止后台任务',
    '将在当前步骤完成后安全停止任务，不影响已归档数据。确认终止？',
    '确认终止',
    'danger'
  ).then(function(ok) {
    if (ok) cancelActiveJob();
  });
}

function cancelActiveJob() {
  if (!activeJobId) return;
  var cancelBtn = document.getElementById('job-cancel-btn');
  if (cancelBtn) { cancelBtn.disabled = true; cancelBtn.textContent = '正在发送终止指令…'; }
  fetch('/api/v1/jobs/' + encodeURIComponent(activeJobId) + '/cancel', {
    method: 'POST',
    headers: {'X-CSRF-Token': _csrfToken()},
    credentials: 'same-origin'
  })
    .then(function(r) { return r.json(); })
    .then(function(job) { renderJobState(job); })
    .catch(function() { if (cancelBtn) cancelBtn.disabled = false; });
}

/* Reconnect to an in-flight background job across page reloads */
(function reconnectActiveJob() {
  var saved = null;
  try { saved = sessionStorage.getItem('ai_lib_active_job'); } catch (e) {}
  if (!saved) return;
  fetch('/api/v1/jobs/' + encodeURIComponent(saved), {credentials: 'same-origin'})
    .then(function(r) { if (!r.ok) throw new Error('missing'); return r.json(); })
    .then(function(job) {
      activeJobId = job.job_id;
      showJobPanel(job);
      if (job.status === 'QUEUED' || job.status === 'RUNNING' || job.status === 'CANCELLING') {
        scheduleJobPoll();
      } else if (!job.result || (!job.result.report_url && job.kind !== 'check_pending')) {
        try { sessionStorage.removeItem('ai_lib_active_job'); } catch (e) {}
      }
    })
    .catch(function() { try { sessionStorage.removeItem('ai_lib_active_job'); } catch (e) {} });
})();

function switchGlobalLibrary(val) {
  if (!val) return;
  var p = val.split('|');
  var target = window.location.pathname.indexOf('/path/index') !== -1 ? '/path/index' : '/path/library';
  window.location.href = target + '?vendor=' + encodeURIComponent(p[0]) + '&library=' + encodeURIComponent(p[1]);
}

function _setSegPressed(btn) {
  if (!btn || !btn.parentNode) return;
  btn.parentNode.querySelectorAll('button').forEach(function(b) {
    b.classList.remove('active');
    b.setAttribute('aria-pressed', 'false');
  });
  btn.classList.add('active');
  btn.setAttribute('aria-pressed', 'true');
}

function _toggleEmptyRow(tableSelector, visibleCount, colSpan, message, resetFn) {
  var tbody = document.querySelector(tableSelector + ' tbody');
  if (!tbody) return;
  var emptyRow = tbody.querySelector('tr.filter-empty-row');
  if (visibleCount === 0) {
    if (!emptyRow) {
      emptyRow = document.createElement('tr');
      emptyRow.className = 'filter-empty-row';
      var td = document.createElement('td');
      td.colSpan = colSpan;
      var span = document.createElement('span');
      span.textContent = message;
      td.appendChild(span);
      if (typeof resetFn === 'function') {
        var btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'ghost btn-xs ml-xs';
        btn.textContent = '重置筛选';
        btn.onclick = resetFn;
        td.appendChild(btn);
      }
      emptyRow.appendChild(td);
      tbody.appendChild(emptyRow);
    }
    emptyRow.style.display = '';
  } else if (emptyRow) {
    emptyRow.style.display = 'none';
  }
}

function resetLibFilters() {
  libState = {status: 'all', vendor: '', ipType: ''};
  var firstBtn = document.querySelector('#lib-status-seg button:first-child');
  if (firstBtn) _setSegPressed(firstBtn);
  var vSel = document.getElementById('lib-vendor-select');
  if (vSel) vSel.value = '';
  var iSel = document.getElementById('lib-iptype-select');
  if (iSel) iSel.value = '';
  var inp = document.getElementById('lib-search-input');
  if (inp) inp.value = '';
  applyLibFilters();
}

/* Level 1 Multi-dimensional Library Filters */
var libState = {status: 'all', vendor: '', ipType: ''};
function setLibFilter(key, val, btn) {
  libState[key] = val;
  if (btn) _setSegPressed(btn);
  applyLibFilters();
}
function applyLibFilters() {
  var q = ((document.getElementById('lib-search-input') || {}).value || '').trim().toLowerCase();
  var visible = 0;
  document.querySelectorAll('#libraries-table tbody tr:not(.filter-empty-row)').forEach(function(tr) {
    var v = tr.getAttribute('data-vendor') || '', lib = tr.getAttribute('data-library') || '';
    var ipType = tr.getAttribute('data-ip-type') || '';
    var searchHay = tr.getAttribute('data-search') || (v.toLowerCase() + ' ' + lib);
    var hasRev = tr.getAttribute('data-has-rev') === '1', issue = tr.getAttribute('data-issue') === '1';
    var ok = true;
    if (libState.vendor && v !== libState.vendor) ok = false;
    if (libState.ipType && ipType !== libState.ipType) ok = false;
    if (libState.status === 'has_rev' && !hasRev) ok = false;
    if (libState.status === 'no_rev' && hasRev) ok = false;
    if (libState.status === 'issue' && !issue) ok = false;
    if (q && searchHay.indexOf(q) === -1) ok = false;
    tr.style.display = ok ? '' : 'none';
    if (ok) visible++;
  });
  var badge = document.getElementById('lib-visible-count');
  if (badge) badge.textContent = '显示 ' + visible + ' 个库';
  _toggleEmptyRow('#libraries-table', visible, 6, '当前筛选条件下没有匹配的来源库。', resetLibFilters);
}

/* Level 2 Accessible Workspace Object Tabs (ARIA + Keyboard Arrow/Home/End) */
function switchLibTab(name, btn, moveFocus, updateHistory) {
  var panel = document.getElementById('tab-' + name);
  if (!panel) return;
  document.querySelectorAll('.tabs-bar .tab-btn').forEach(function(b) {
    b.classList.remove('active');
    b.setAttribute('aria-selected', 'false');
    b.setAttribute('tabindex', '-1');
  });
  document.querySelectorAll('.tab-panel').forEach(function(p) {
    p.classList.remove('active');
    p.hidden = true;
  });
  var activeBtn = btn || document.querySelector('.tabs-bar .tab-btn[data-tab="' + name + '"]');
  if (activeBtn) {
    activeBtn.classList.add('active');
    activeBtn.setAttribute('aria-selected', 'true');
    activeBtn.setAttribute('tabindex', '0');
    if (moveFocus) activeBtn.focus();
  }
  panel.classList.add('active');
  panel.hidden = false;
  document.documentElement.dataset.libraryTab = name;
  document.querySelectorAll('#app-sidebar [data-lib-nav]').forEach(function(el) {
    var active = el.getAttribute('data-lib-nav') === name;
    el.classList.toggle('active', active);
    el.setAttribute('aria-current', active ? 'page' : 'false');
  });
  if (updateHistory !== false) {
    if (name === 'checks') switchCheckSubTab('single', false);
    setLibraryHash(name);
  }
  if (window.innerWidth < 1080) {
    toggleSidebar(false);
  }
}

function setLibraryHash(name) {
  if (location.hash !== '#' + name) history.pushState(null, '', '#' + name);
}

function switchCheckSubTab(name, updateHistory, moveFocus) {
  var panel = document.getElementById('check-pane-' + name);
  if (!panel) return;
  switchLibTab('checks', null, false, false);
  document.querySelectorAll('.check-subtab').forEach(function(btn) {
    var active = btn.dataset.checkSubtab === name;
    btn.classList.toggle('active', active);
    btn.setAttribute('aria-selected', String(active));
    btn.tabIndex = active ? 0 : -1;
    if (active && moveFocus) btn.focus();
  });
  document.querySelectorAll('.check-subpane').forEach(function(pane) {
    pane.classList.toggle('active', pane === panel);
    pane.hidden = pane !== panel;
  });
  if (updateHistory !== false) setLibraryHash(name === 'single' ? 'checks' : 'checks-' + name);
}

function bindArrowTabs(bar, selector, activate) {
  bar.addEventListener('keydown', function(e) {
    var tabs = Array.from(bar.querySelectorAll(selector));
    var idx = tabs.indexOf(document.activeElement);
    if (idx === -1) return;
    var next = null;
    if (e.key === 'ArrowRight') next = (idx + 1) % tabs.length;
    else if (e.key === 'ArrowLeft') next = (idx - 1 + tabs.length) % tabs.length;
    else if (e.key === 'Home') next = 0;
    else if (e.key === 'End') next = tabs.length - 1;
    if (next !== null) {
      e.preventDefault();
      activate(tabs[next]);
    }
  });
}

(function initTabs() {
  var bar = document.querySelector('.tabs-bar[role="tablist"]');
  if (!bar) return;
  bindArrowTabs(bar, '.tab-btn', function(btn) { switchLibTab(btn.dataset.tab, btn, true); });
  var subBar = document.querySelector('.check-subtabs[role="tablist"]');
  if (subBar) bindArrowTabs(subBar, '.check-subtab', function(btn) { switchCheckSubTab(btn.dataset.checkSubtab, true, true); });

  function restoreTab() {
    var hash = location.hash.slice(1);
    if (hash === 'checks' || hash === 'check-scope') switchCheckSubTab('single', false);
    else if (hash === 'checks-overall') switchCheckSubTab('overall', false);
    else if (hash === 'checks-all-ips' && document.getElementById('check-pane-all-ips')) switchCheckSubTab('all-ips', false);
    else if (hash === 'checks-all-ips') switchCheckSubTab('single', false);
    else switchLibTab(['members', 'deliveries', 'ops'].includes(hash) ? hash : 'members', null, false, false);
  }
  window.addEventListener('hashchange', restoreTab);
  window.addEventListener('popstate', restoreTab);
  restoreTab();
})();

/* Level 2 Member Filters */
var memState = {diff: 'all', view: ''};
function setMemberFilter(key, val, btn) {
  memState[key] = val;
  if (btn) _setSegPressed(btn);
  applyMemberFilters();
}
function applyMemberFilters() {
  var q = ((document.getElementById('member-search-input') || {}).value || '').trim().toLowerCase();
  var visible = 0;
  document.querySelectorAll('#members-table tbody tr:not(.filter-empty-row)').forEach(function(tr) {
    var v = tr.getAttribute('data-view'), d = tr.getAttribute('data-diff'), txt = tr.getAttribute('data-text') || '';
    var ok = true;
    if (memState.view && v !== memState.view) ok = false;
    if (memState.diff === 'changed' && !(d === 'NEW' || d === 'UPDATED' || d === 'REMOVED')) ok = false;
    else if (memState.diff !== 'all' && memState.diff !== 'changed' && d !== memState.diff) ok = false;
    if (q && txt.indexOf(q) === -1) ok = false;
    tr.style.display = ok ? '' : 'none';
    if (ok) visible++;
  });
  _toggleEmptyRow('#members-table', visible, 6, '当前筛选条件下没有匹配的有效版本成员。');
}

/* Level 2 Artifact Filters */
var artState = {kind: 'all', quality: ''};
function setArtFilter(key, val, btn) {
  artState[key] = val;
  if (btn) _setSegPressed(btn);
  applyArtFilters();
}
function applyArtFilters() {
  var onlyCurr = !!(document.getElementById('filter-current-rev-only') || {}).checked;
  var visible = 0;
  document.querySelectorAll('#artifacts-table tbody tr:not(.filter-empty-row)').forEach(function(tr) {
    var k = tr.getAttribute('data-kind'), q = tr.getAttribute('data-quality'), curr = tr.getAttribute('data-current') === '1';
    var ok = true;
    if (artState.kind !== 'all' && k !== artState.kind) ok = false;
    if (artState.quality && q !== artState.quality) ok = false;
    if (onlyCurr && !curr) ok = false;
    tr.style.display = ok ? '' : 'none';
    if (ok) visible++;
  });
  _toggleEmptyRow('#artifacts-table', visible, 4, '当前筛选条件下没有匹配的检查报告。');
}

/* Level 2 Delivery Filter */
function filterDeliveries(q) {
  q = (q || '').trim().toLowerCase();
  var visible = 0;
  var ths = document.querySelectorAll('#deliveries-table thead th');
  var cols = ths.length || 5;
  document.querySelectorAll('#deliveries-table tbody tr:not(.filter-empty-row)').forEach(function(tr) {
    var txt = tr.getAttribute('data-text') || '';
    var ok = (!q || txt.indexOf(q) !== -1);
    tr.style.display = ok ? '' : 'none';
    if (ok) visible++;
  });
  _toggleEmptyRow('#deliveries-table', visible, cols, '当前关键字没有匹配的供应商交付记录。');
}

/* Check View Filter */
var cvState = {src: 'all', view: ''};
function setCvFilter(key, val, btn) {
  cvState[key] = val;
  if (btn) _setSegPressed(btn);
  applyCvFilters();
}
function applyCvFilters() {
  var q = ((document.getElementById('cv-q') || {}).value || '').trim().toLowerCase();
  var visible = 0;
  document.querySelectorAll('#cv-files-table tbody tr:not(.filter-empty-row)').forEach(function(tr) {
    var v = tr.getAttribute('data-view'), s = tr.getAttribute('data-src'), c = tr.getAttribute('data-content'), txt = tr.getAttribute('data-text') || '';
    var ok = true;
    if (cvState.view && v !== cvState.view) ok = false;
    if (cvState.src === 'changed' && !(s === 'NEW' || s === 'UPDATED' || s === 'REMOVED')) ok = false;
    if (cvState.src === 'diff' && !(c === 'CURRENT_CONTENT_DIFF' || c === 'PARTIAL_DIFF')) ok = false;
    if (q && txt.indexOf(q) === -1) ok = false;
    tr.style.display = ok ? '' : 'none';
    if (ok) visible++;
  });
  _toggleEmptyRow('#cv-files-table', visible, 6, '当前筛选条件下没有匹配的文件记录。');
}

/* Collapsible Left Navigation Sidebar (persisted, keyboard '[' shortcut, mobile drawer) */
function _syncSidebarAria() {
  var collapsed = document.documentElement.getAttribute('data-sidebar') === 'collapsed';
  var btn = document.getElementById('sidebar-toggle-btn');
  if (btn) {
    btn.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
    btn.setAttribute('aria-label', collapsed ? '展开左侧导航栏' : '收起左侧导航栏');
    btn.setAttribute('title', (collapsed ? '展开左侧导航栏' : '收起左侧导航栏') + ' ([)');
  }
}

function toggleSidebar(forceOpen) {
  var curCollapsed = document.documentElement.getAttribute('data-sidebar') === 'collapsed';
  var nextCollapsed = (typeof forceOpen === 'boolean') ? !forceOpen : !curCollapsed;
  if (nextCollapsed) {
    document.documentElement.setAttribute('data-sidebar', 'collapsed');
  } else {
    document.documentElement.removeAttribute('data-sidebar');
  }
  try { localStorage.setItem('ai_lib_sidebar_collapsed', nextCollapsed ? '1' : '0'); } catch (e) {}
  _syncSidebarAria();
}

var _sidebarSearchTimer = null;
function filterSidebarLibraries(q) {
  var inp = document.getElementById('sidebar-lib-filter');
  q = (q || '').trim();
  if (inp && inp.getAttribute('data-remote-search') === '1') {
    if (_sidebarSearchTimer) clearTimeout(_sidebarSearchTimer);
    _sidebarSearchTimer = setTimeout(function() {
      fetch('/api/v1/libraries?limit=30&q=' + encodeURIComponent(q))
        .then(function(r) { return r.ok ? r.json() : null; })
        .then(function(data) {
          if (!data || !Array.isArray(data.items)) return;
          var list = document.getElementById('sidebar-lib-list');
          if (!list) return;
          list.innerHTML = '';
          data.items.forEach(function(item) {
            var li = document.createElement('li');
            li.setAttribute('data-search', (item.vendor + ' ' + item.library).toLowerCase());
            var a = document.createElement('a');
            a.className = 'sidebar-lib-item';
            a.href = '/path/library?vendor=' + encodeURIComponent(item.vendor) + '&library=' + encodeURIComponent(item.library);
            a.title = item.vendor + ' / ' + item.library;
            var s1 = document.createElement('span');
            s1.className = 'sidebar-lib-name';
            s1.setAttribute('translate', 'no');
            s1.textContent = item.library;
            var s2 = document.createElement('span');
            s2.className = 'sidebar-lib-vendor';
            s2.setAttribute('translate', 'no');
            s2.textContent = item.vendor;
            a.appendChild(s1);
            a.appendChild(s2);
            li.appendChild(a);
            list.appendChild(li);
          });
        })
        .catch(function() {});
    }, 150);
    return;
  }
  var ql = q.toLowerCase();
  document.querySelectorAll('#sidebar-lib-list li').forEach(function(li) {
    var hay = li.getAttribute('data-search') || '';
    li.style.display = (!ql || hay.indexOf(ql) !== -1) ? '' : 'none';
  });
}

(function initSidebar() {
  _syncSidebarAria();
  document.addEventListener('keydown', function(e) {
    var tag = (e.target && e.target.tagName) ? e.target.tagName.toLowerCase() : '';
    var editable = tag === 'input' || tag === 'textarea' || tag === 'select' || (e.target && e.target.isContentEditable);
    if (e.key === '[' && !e.ctrlKey && !e.metaKey && !e.altKey && !editable) {
      e.preventDefault();
      toggleSidebar();
    } else if (e.key === 'Escape' && window.innerWidth < 1080) {
      if (document.documentElement.getAttribute('data-sidebar') !== 'collapsed') {
        toggleSidebar(false);
      }
    }
  });
})();

/* Overview Focused View Switcher (Left Sidebar + Collapsed Fallback Bar + URL Sync) */
var _OVERVIEW_META = {
  activity: ['数据源就绪与近期变动', '核查数据源是否就绪，对比当前时间展示近期新增库、RAW 交付与 Formal (NL) 快照变动。'],
  layers:   ['三层同步健康状态', '按来源归档（L1）、有效版本（L2）与文件索引（L3）逐层核对规模并按需单独刷新。'],
  json:     ['JSON 产物与更新时间明细', '切换下方筛选项自动生效，快速定位各层 JSON 状态与更新时间。'],
  history:  ['同步批次记录明细', '按时间倒序留存每次 L1 / L2 / L3 同步批次的变更与异常明细。'],
  config:   ['来源目录与检查策略', '修改后可「仅保存配置」即时生效，或选择「保存并立即同步」执行刷新。']
};
var _currentPipelineTab = 'layers';

function switchPipelineTab(tabName, btn, moveFocus) {
  if (tabName !== 'layers' && tabName !== 'json' && tabName !== 'history') tabName = 'layers';
  var targetPane = document.getElementById('sync-pane-' + tabName);
  if (targetPane && targetPane.getAttribute('data-lazy-url')) {
    window.location.href = targetPane.getAttribute('data-lazy-url');
    return;
  }
  _currentPipelineTab = tabName;
  document.querySelectorAll('.sync-pane').forEach(function(pane) {
    pane.hidden = (pane.id !== 'sync-pane-' + tabName);
  });
  var meta = _OVERVIEW_META[tabName];
  if (meta) {
    var titleEl = document.getElementById('sync-center-title');
    var descEl = document.getElementById('sync-center-desc');
    if (titleEl) titleEl.textContent = meta[0];
    if (descEl) descEl.textContent = meta[1];
  }
  var seg = document.getElementById('pipeline-sub-seg');
  if (seg) {
    seg.querySelectorAll('button[data-pipe-tab]').forEach(function(b) {
      var active = b.getAttribute('data-pipe-tab') === tabName;
      b.classList.toggle('active', active);
      b.setAttribute('aria-selected', active ? 'true' : 'false');
      b.setAttribute('tabindex', active ? '0' : '-1');
      if (active && moveFocus && b === btn) b.focus();
    });
  }
  try {
    var url = new URL(window.location.href);
    url.searchParams.set('view', tabName);
    history.replaceState(null, '', url.pathname + url.search);
  } catch (e) {}
}

function switchOverviewView(name, btn, moveFocus) {
  var syncSec = document.getElementById('sync-center-section');
  var libSec = document.getElementById('libraries-section');
  if (!syncSec && !libSec) return;

  var domain = name;
  var pipeTab = null;
  if (name === 'layers' || name === 'json' || name === 'history') {
    domain = 'pipeline';
    pipeTab = name;
  } else if (name === 'pipeline') {
    domain = 'pipeline';
    pipeTab = _currentPipelineTab || 'layers';
  }
  if (domain === 'libraries' && libSec && libSec.getAttribute('data-lazy-url')) {
    window.location.href = libSec.getAttribute('data-lazy-url');
    return;
  }
  if (domain === 'activity') {
    var actPane = document.getElementById('sync-pane-activity');
    if (actPane && actPane.getAttribute('data-lazy-url')) {
      window.location.href = actPane.getAttribute('data-lazy-url');
      return;
    }
  }
  if (domain === 'pipeline' && pipeTab === 'json') {
    var jsonPane = document.getElementById('sync-pane-json');
    if (jsonPane && jsonPane.getAttribute('data-lazy-url')) {
      window.location.href = jsonPane.getAttribute('data-lazy-url');
      return;
    }
  }

  // Switch domain-scoped page heads (KPI only in 'activity', clean settings head in 'config')
  ['activity', 'libraries', 'catalog', 'pipeline', 'config'].forEach(function(d) {
    var h = document.getElementById('domain-head-' + d);
    if (h) h.hidden = (d !== domain);
  });

  var catSec = document.getElementById('catalog-section');
  var isLibs = (domain === 'libraries');
  var isCat = (domain === 'catalog');
  if (syncSec) syncSec.hidden = (isLibs || isCat);
  if (libSec) libSec.hidden = !isLibs;
  if (catSec) catSec.hidden = !isCat;
  if (isCat && typeof window.initCatalogSearchPanel === 'function') {
    window.initCatalogSearchPanel();
  }

  var pipeSeg = document.getElementById('pipeline-sub-seg');
  if (pipeSeg) pipeSeg.hidden = (domain !== 'pipeline');
  var toLibsBtn = document.getElementById('overview-to-libs-btn');
  if (toLibsBtn) toLibsBtn.hidden = (domain !== 'activity');

  if (!isLibs && !isCat) {
    var paneName = (domain === 'pipeline') ? pipeTab : domain;
    if (domain === 'pipeline') {
      switchPipelineTab(pipeTab);
    } else {
      document.querySelectorAll('.sync-pane').forEach(function(pane) {
        pane.hidden = (pane.id !== 'sync-pane-' + paneName);
      });
      var meta = _OVERVIEW_META[paneName];
      if (meta) {
        var titleEl = document.getElementById('sync-center-title');
        var descEl = document.getElementById('sync-center-desc');
        if (titleEl) titleEl.textContent = meta[0];
        if (descEl) descEl.textContent = meta[1];
      }
    }
  }

  document.querySelectorAll('[data-overview-nav]').forEach(function(el) {
    var active = el.getAttribute('data-overview-nav') === domain;
    el.classList.toggle('active', active);
    if (el.getAttribute('role') === 'tab') {
      el.setAttribute('aria-selected', active ? 'true' : 'false');
      el.setAttribute('tabindex', active ? '0' : '-1');
    } else {
      el.setAttribute('aria-current', active ? 'page' : 'false');
    }
    if (active && moveFocus && el === btn) el.focus();
  });

  try {
    var url = new URL(window.location.href);
    if (domain === 'activity') url.searchParams.delete('view');
    else if (domain === 'pipeline') url.searchParams.set('view', pipeTab);
    else url.searchParams.set('view', domain);
    history.replaceState(null, '', url.pathname + url.search);
  } catch (e) {}
  var crumbEl = document.getElementById('topbar-crumb-curr');
  if (crumbEl) {
    var _crumbMap = {activity: '总览与动态', libraries: '来源库资产', catalog: '跨库检索', pipeline: '同步与数据链', config: '工作区设置'};
    if (_crumbMap[domain]) crumbEl.textContent = _crumbMap[domain];
  }

  if (window.innerWidth < 1080) {
    toggleSidebar(false);
  }
}

function switchSyncTab(name, btn, moveFocus) {
  switchOverviewView(name, btn, moveFocus);
}

function jumpToIssueLibraries() {
  switchOverviewView('libraries');
  var issueBtn = document.querySelector('#lib-status-seg button:last-child');
  if (issueBtn) issueBtn.click();
  var sec = document.getElementById('libraries-section');
  if (sec && typeof sec.scrollIntoView === 'function') {
    sec.scrollIntoView({behavior: 'smooth', block: 'start'});
  }
}

(function initOverviewCollapsedTabs() {
  var seg = document.getElementById('overview-collapsed-seg');
  if (!seg) return;
  seg.addEventListener('keydown', function(e) {
    var tabs = Array.prototype.slice.call(seg.querySelectorAll('button[role="tab"]'));
    var idx = tabs.indexOf(document.activeElement);
    if (idx === -1) return;
    var next = null;
    if (e.key === 'ArrowRight') next = (idx + 1) % tabs.length;
    else if (e.key === 'ArrowLeft') next = (idx - 1 + tabs.length) % tabs.length;
    else if (e.key === 'Home') next = 0;
    else if (e.key === 'End') next = tabs.length - 1;
    if (next !== null) {
      e.preventDefault();
      var target = tabs[next];
      switchOverviewView(target.getAttribute('data-overview-nav'), target, true);
    }
  });
})();

/* Overview Activity Tables: Instant Zero-Click Filters (#recent-raw-table & #recent-nl-table) */
function formatLocalUtcString(raw, fmt, prefix) {
  if (!raw) return '';
  var norm = String(raw).trim();
  if (/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}(:\d{2})?$/.test(norm)) {
    norm = norm.replace(' ', 'T') + 'Z';
  }
  if (norm.indexOf('T') === -1) return '';
  var d = new Date(norm);
  if (isNaN(d.getTime())) return '';
  function pad2(n) { return n < 10 ? ('0' + n) : String(n); }
  function tzLabel(dt) {
    var offMin = -dt.getTimezoneOffset();
    var sign = offMin >= 0 ? '+' : '-';
    var absMin = Math.abs(offMin);
    var hh = Math.floor(absMin / 60);
    var mm = absMin % 60;
    return 'UTC' + sign + hh + (mm ? (':' + pad2(mm)) : '');
  }
  var pfx = prefix || '';
  if (fmt === 'full') {
    return pfx + d.getFullYear() + '-' + pad2(d.getMonth() + 1) + '-' + pad2(d.getDate())
      + ' ' + pad2(d.getHours()) + ':' + pad2(d.getMinutes()) + ' (' + tzLabel(d) + ')';
  }
  if (fmt === 'datetime-sec') {
    return pfx + d.getFullYear() + '-' + pad2(d.getMonth() + 1) + '-' + pad2(d.getDate())
      + ' ' + pad2(d.getHours()) + ':' + pad2(d.getMinutes()) + ':' + pad2(d.getSeconds());
  }
  if (fmt === 'datetime') {
    return pfx + d.getFullYear() + '-' + pad2(d.getMonth() + 1) + '-' + pad2(d.getDate())
      + ' ' + pad2(d.getHours()) + ':' + pad2(d.getMinutes());
  }
  return pfx + pad2(d.getMonth() + 1) + '-' + pad2(d.getDate())
    + ' ' + pad2(d.getHours()) + ':' + pad2(d.getMinutes());
}
(function hydrateLocalTimestamps() {
  var nodes = document.querySelectorAll('.js-local-ts[data-utc-iso]');
  if (!nodes.length) return;
  nodes.forEach(function(el) {
    var raw = el.getAttribute('data-utc-iso') || '';
    var fmt = el.getAttribute('data-fmt') || 'short';
    var prefix = el.getAttribute('data-prefix') || '';
    var out = formatLocalUtcString(raw, fmt, prefix);
    if (!out) return;
    el.textContent = out;
    if (!el.getAttribute('title')) {
      el.setAttribute('title', 'UTC: ' + raw);
    }
  });
})();

var rawActState = {kind: 'all'};
function setRawActFilter(kind, btn) {
  rawActState.kind = kind;
  if (btn) _setSegPressed(btn);
  applyRawActFilters();
}
function resetRawActFilters() {
  rawActState.kind = 'all';
  var firstBtn = document.querySelector('#raw-act-seg button:first-child');
  if (firstBtn) _setSegPressed(firstBtn);
  var inp = document.getElementById('raw-act-search');
  if (inp) inp.value = '';
  applyRawActFilters();
}
function applyRawActFilters() {
  var q = ((document.getElementById('raw-act-search') || {}).value || '').trim().toLowerCase();
  var rows = document.querySelectorAll('#recent-raw-table tbody tr:not(.filter-empty-row)');
  var total = rows.length, visible = 0;
  rows.forEach(function(tr) {
    var k = tr.getAttribute('data-kind') || '';
    var hay = tr.getAttribute('data-search') || '';
    var ok = true;
    if (rawActState.kind !== 'all' && k !== rawActState.kind) ok = false;
    if (q && hay.indexOf(q) === -1) ok = false;
    tr.style.display = ok ? '' : 'none';
    if (ok) visible++;
  });
  var badge = document.getElementById('raw-act-count');
  if (badge) badge.textContent = (visible === total) ? ('共 ' + total + ' 条') : ('显示 ' + visible + ' / ' + total + ' 条');
  _toggleEmptyRow('#recent-raw-table', visible, 6, '当前筛选条件下没有匹配的 RAW 交付变动。', resetRawActFilters);
}

var nlActState = {kind: 'all'};
function setNlActFilter(kind, btn) {
  nlActState.kind = kind;
  if (btn) _setSegPressed(btn);
  applyNlActFilters();
}
function resetNlActFilters() {
  nlActState.kind = 'all';
  var firstBtn = document.querySelector('#nl-act-seg button:first-child');
  if (firstBtn) _setSegPressed(firstBtn);
  var inp = document.getElementById('nl-act-search');
  if (inp) inp.value = '';
  applyNlActFilters();
}
function applyNlActFilters() {
  var q = ((document.getElementById('nl-act-search') || {}).value || '').trim().toLowerCase();
  var rows = document.querySelectorAll('#recent-nl-table tbody tr:not(.filter-empty-row)');
  var total = rows.length, visible = 0;
  rows.forEach(function(tr) {
    var k = tr.getAttribute('data-kind') || '';
    var hay = tr.getAttribute('data-search') || '';
    var ok = true;
    if (nlActState.kind !== 'all' && k !== nlActState.kind) ok = false;
    if (q && hay.indexOf(q) === -1) ok = false;
    tr.style.display = ok ? '' : 'none';
    if (ok) visible++;
  });
  var badge = document.getElementById('nl-act-count');
  if (badge) badge.textContent = (visible === total) ? ('共 ' + total + ' 条') : ('显示 ' + visible + ' / ' + total + ' 条');
  _toggleEmptyRow('#recent-nl-table', visible, 5, '当前筛选条件下没有匹配的 Formal (NL) 快照变动。', resetNlActFilters);
}

/* Declarative Zero-Click Auto-Filter Engine for GET Server Tables (IME-safe debounce + focus restore) */
(function initAutoFilterForms() {
  try {
    var refocusName = sessionStorage.getItem('ai_lib_refocus_search');
    if (refocusName) {
      sessionStorage.removeItem('ai_lib_refocus_search');
      var targetInput = document.querySelector('form[data-auto-filter="1"] input[type="search"][name="' + refocusName + '"]');
      if (targetInput && !targetInput.closest('[hidden]')) {
        targetInput.focus();
        var len = targetInput.value.length;
        try { targetInput.setSelectionRange(len, len); } catch (e) {}
      }
    }
  } catch (e) {}

  document.querySelectorAll('form[data-auto-filter="1"]').forEach(function(form) {
    var submitNow = function(rememberSearchName) {
      if (rememberSearchName) {
        try { sessionStorage.setItem('ai_lib_refocus_search', rememberSearchName); } catch (e) {}
      }
      var pageInputs = form.querySelectorAll('input[name="page"], input[name="json_page"]');
      pageInputs.forEach(function(pi) { pi.value = '1'; });
      form.submit();
    };

    form.querySelectorAll('select, input[type="checkbox"], input[type="radio"]').forEach(function(ctrl) {
      ctrl.addEventListener('change', function() { submitNow(null); });
    });

    form.querySelectorAll('input[type="search"]').forEach(function(inp) {
      var timer = null;
      var composing = false;
      var lastVal = inp.value;
      inp.addEventListener('compositionstart', function() { composing = true; });
      inp.addEventListener('compositionend', function() {
        composing = false;
        if (inp.value !== lastVal) {
          clearTimeout(timer);
          timer = setTimeout(function() {
            if (inp.value !== lastVal) submitNow(inp.name);
          }, 320);
        }
      });
      inp.addEventListener('input', function() {
        if (composing) return;
        clearTimeout(timer);
        timer = setTimeout(function() {
          if (inp.value !== lastVal) submitNow(inp.name);
        }, 320);
      });
      inp.addEventListener('search', function() {
        clearTimeout(timer);
        if (inp.value !== lastVal) submitNow(inp.name);
      });
    });
  });
})();

/* Level 3 Timeline Toggle & Copy */
function toggleTimeline(id, btn) {
  var row = document.getElementById(id);
  if (!row) return;
  var show = (row.style.display === 'none' || !row.style.display);
  row.style.display = show ? 'table-row' : 'none';
  btn.setAttribute('aria-expanded', show ? 'true' : 'false');
  btn.textContent = show ? '收起' : '展开';
}

var _COPY_OK_SVG = '<svg class="ico ico-sm" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="20 6 9 17 4 12"/></svg>';

function copyPath(btn, text) {
  var done = function() {
    if (btn.classList.contains('copy-icon-btn')) {
      var origHtml = btn.getAttribute('data-orig-html') || btn.innerHTML;
      btn.setAttribute('data-orig-html', origHtml);
      btn.innerHTML = _COPY_OK_SVG;
      btn.classList.add('copied');
      setTimeout(function() {
        btn.innerHTML = origHtml;
        btn.classList.remove('copied');
      }, 1200);
      return;
    }
    var orig = btn.getAttribute('data-orig-label') || btn.textContent;
    btn.setAttribute('data-orig-label', orig);
    btn.textContent = '已复制';
    btn.classList.add('copied');
    setTimeout(function() {
      btn.textContent = orig;
      btn.classList.remove('copied');
    }, 1200);
  };
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text).then(done).catch(function() {});
  } else {
    var i = document.createElement('input');
    i.value = text;
    document.body.appendChild(i);
    i.select();
    document.execCommand('copy');
    document.body.removeChild(i);
    done();
  }
}

/* ============================================================================
 * Per-Library Configuration Slide-Over Drawer (pure /api/v1/config driven)
 * ============================================================================ */
(function() {
  var _state = { data: null, editing: false, saving: false, opener: null };

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function sourceBadge(overridden, labelOverride) {
    if (overridden) {
      return '<span class="tag tag-accent tag-sm">' + esc(labelOverride || '单库覆盖') + '</span>';
    }
    return '<span class="tag tag-inherited tag-sm">继承全局</span>';
  }

  function renderReadOnly(d) {
    var ov = d.overrides || {};
    var eff = d.effective || {};
    var lf = eff.liberty_parse_filter || {};
    var lfDesc = lf.enabled
      ? ('阈值 > ' + lf.threshold + ' 抽样'
        + (lf.keywords && lf.keywords.length ? ' · 优先: ' + lf.keywords.join(', ') : '')
        + (lf.exclude_keywords && lf.exclude_keywords.length ? ' · 排除: ' + lf.exclude_keywords.join(', ') : '')
        + (lf.max_selected ? ' · 上限 ' + lf.max_selected : '')
        + ' · 回退 ' + (lf.fallback || 'first_n'))
      : '关闭（全量解析 .lib）';
    var spvDesc = (eff.skip_parse_views && eff.skip_parse_views.length)
      ? eff.skip_parse_views.join(' / ')
      : '无（全部支持视图均解析）';
    var tailDesc = (eff.initial_delivery_tail === null || eff.initial_delivery_tail === 0)
      ? '不折叠（全历史逐版演进）'
      : ('最近 ' + eff.initial_delivery_tail + ' 版逐版演进（早期折叠为 rev_0001）');
    var ipListHtml = (d.ip_list && d.ip_list.length)
      ? d.ip_list.map(function(ip) { return '<span class="chip" translate="no">' + esc(ip) + '</span>'; }).join(' ')
      : '<span class="muted">未配置（单轨库）</span>';
    var effPlugins = new Set(eff.check_plugins || []);
    var pluginsHtml = (d.available_plugins || []).map(function(p) {
      var on = effPlugins.has(p.name);
      return '<div class="lib-cfg-plugin-row">'
        + '<span class="tag ' + (on ? 'tag-new' : 'tag-inherited') + ' tag-sm">' + (on ? '启用' : '停用') + '</span>'
        + '<div><div class="mono text-xs" translate="no"><strong>' + esc(p.name) + '</strong> <span class="muted">v' + esc(p.version) + '</span></div>'
        + '<div class="muted text-xs">' + esc(p.description || '') + '</div></div>'
        + '</div>';
    }).join('');

    return ''
      + '<div class="org-drawer-section">'
      + '  <div class="lib-cfg-sec-head"><span class="org-drawer-sec-title">业务身份与多轨 IP</span></div>'
      + '  <div class="lib-cfg-kv"><span>IP 类型 (ip_type)</span><strong translate="no">' + esc(d.ip_type || '未设置') + '</strong></div>'
      + '  <div class="lib-cfg-kv"><span>业务 IP 列表</span><div class="lib-cfg-chips">' + ipListHtml + '</div></div>'
      + '</div>'
      + '<div class="org-drawer-section">'
      + '  <div class="lib-cfg-sec-head"><span class="org-drawer-sec-title">解析视图与折叠策略</span>' + sourceBadge(ov.has_skip_parse_views || ov.has_initial_delivery_tail) + '</div>'
      + '  <div class="lib-cfg-kv"><span>跳过解析视图 ' + sourceBadge(ov.has_skip_parse_views) + '</span><span class="mono text-xs">' + esc(spvDesc) + '</span></div>'
      + '  <div class="lib-cfg-kv"><span>A+ 初始折叠窗口 ' + sourceBadge(ov.has_initial_delivery_tail) + '</span><span class="text-xs">' + esc(tailDesc) + '</span></div>'
      + '</div>'
      + '<div class="org-drawer-section">'
      + '  <div class="lib-cfg-sec-head"><span class="org-drawer-sec-title">Liberty (.lib) 抽样规则</span>' + sourceBadge(ov.has_liberty_parse_filter) + '</div>'
      + '  <div class="text-xs">' + esc(lfDesc) + '</div>'
      + '</div>'
      + '<div class="org-drawer-section">'
      + '  <div class="lib-cfg-sec-head"><span class="org-drawer-sec-title">检查插件生效清单（' + (eff.check_plugins || []).length + '/' + (d.available_plugins || []).length + '）</span>' + sourceBadge(ov.has_check_plugins) + '</div>'
      + '  <div class="lib-cfg-plugins">' + pluginsHtml + '</div>'
      + '</div>';
  }

  function renderEditForm(d) {
    var ov = d.overrides || {};
    var eff = d.effective || {};
    var ws = d.workspace_defaults || {};
    var curSpv = new Set(ov.has_skip_parse_views ? (ov.skip_parse_views || []) : (ws.skip_parse_views || []));
    var viewChoices = ['CDL', 'SPICE', 'VERILOG', 'LEF', 'LIBERTY'];
    (d.supported_views || []).forEach(function(v) {
      if (viewChoices.indexOf(v) < 0) viewChoices.push(v);
    });

    var lfMode = 'inherit';
    if (ov.has_liberty_parse_filter) {
      lfMode = ov.liberty_parse_filter === null ? 'disable' : 'override';
    }
    var lfVal = (lfMode === 'override' && ov.liberty_parse_filter) ? ov.liberty_parse_filter : (eff.liberty_parse_filter || {});
    var effPlugins = new Set(eff.check_plugins || []);

    var viewsHtml = viewChoices.map(function(v) {
      return '<label class="check-inline"><input type="checkbox" name="cfg_spv" value="' + esc(v) + '" ' + (curSpv.has(v) ? 'checked' : '') + '> ' + esc(v) + '</label>';
    }).join('');

    var pluginsHtml = (d.available_plugins || []).map(function(p) {
      var checked = effPlugins.has(p.name) ? 'checked' : '';
      return '<label class="lib-cfg-plugin-check">'
        + '<input type="checkbox" name="cfg_plugin" value="' + esc(p.name) + '" ' + checked + '>'
        + '<div><div class="mono text-xs" translate="no"><strong>' + esc(p.name) + '</strong> <span class="muted">v' + esc(p.version) + '</span></div>'
        + '<div class="muted text-xs">' + esc(p.description || '') + '</div></div>'
        + '</label>';
    }).join('');

    return ''
      + '<form id="lib-cfg-form" onsubmit="event.preventDefault(); saveLibraryConfigDrawer();">'
      + '  <div class="org-drawer-section">'
      + '    <div class="lib-cfg-sec-head"><span class="org-drawer-sec-title">1. 业务身份与多轨分轨</span></div>'
      + '    <div class="field mb-sm">'
      + '      <label for="lcfg-ip-type">IP 类型（如 SRAM / STDCELL / PHY / IO）</label>'
      + '      <input id="lcfg-ip-type" type="text" value="' + esc(d.ip_type || '') + '" placeholder="留空表示未分类" autocomplete="off">'
      + '    </div>'
      + '    <div class="field">'
      + '      <label for="lcfg-ip-list">多业务 IP 列表（每行或逗号分隔；留空为单轨库）</label>'
      + '      <textarea id="lcfg-ip-list" rows="3" placeholder="例如：&#10;sram22_256x16m8w8&#10;sram22_512x32m4w8" spellcheck="false">' + esc((d.ip_list || []).join('\n')) + '</textarea>'
      + '      <span class="muted text-xs">修改 IP 列表后，请在库页点击「重新分轨」使新轨道生效。</span>'
      + '    </div>'
      + '  </div>'
      + '  <div class="org-drawer-section">'
      + '    <div class="lib-cfg-sec-head">'
      + '      <span class="org-drawer-sec-title">2. 跳过解析视图 &amp; A+ 折叠窗口</span>'
      + '    </div>'
      + '    <label class="check-inline mb-xs"><input id="lcfg-spv-inherit" type="checkbox" ' + (!ov.has_skip_parse_views ? 'checked' : '') + ' onchange="document.getElementById(\'lcfg-spv-box\').hidden = this.checked"> 继承工作区默认（' + esc((ws.skip_parse_views || []).join('/') || '无') + '）</label>'
      + '    <div id="lcfg-spv-box" class="toolbar-group mb-sm" ' + (!ov.has_skip_parse_views ? 'hidden' : '') + '>' + viewsHtml + '</div>'
      + '    <label class="check-inline mb-xs"><input id="lcfg-tail-inherit" type="checkbox" ' + (!ov.has_initial_delivery_tail ? 'checked' : '') + ' onchange="document.getElementById(\'lcfg-tail-box\').hidden = this.checked"> 继承工作区默认折叠窗口（' + esc(ws.initial_delivery_tail == null ? '不折叠' : ws.initial_delivery_tail + ' 版') + '）</label>'
      + '    <div id="lcfg-tail-box" class="field" ' + (!ov.has_initial_delivery_tail ? 'hidden' : '') + '>'
      + '      <label for="lcfg-tail-val">单库初始尾部演进窗口（0 为不折叠）</label>'
      + '      <input id="lcfg-tail-val" type="number" min="0" step="1" value="' + esc(ov.has_initial_delivery_tail ? (ov.initial_delivery_tail == null ? 0 : ov.initial_delivery_tail) : (ws.initial_delivery_tail == null ? 0 : ws.initial_delivery_tail)) + '">'
      + '    </div>'
      + '  </div>'
      + '  <div class="org-drawer-section">'
      + '    <div class="lib-cfg-sec-head"><span class="org-drawer-sec-title">3. Liberty 文件选择</span></div>'
      + '    <div class="field mb-xs">'
      + '      <label for="lcfg-lf-mode">策略模式</label>'
      + '      <select id="lcfg-lf-mode" onchange="document.getElementById(\'lcfg-lf-box\').hidden = (this.value !== \'override\')">'
      + '        <option value="inherit" ' + (lfMode === 'inherit' ? 'selected' : '') + '>继承工作区默认</option>'
      + '        <option value="override" ' + (lfMode === 'override' ? 'selected' : '') + '>单库单独覆盖</option>'
      + '        <option value="disable" ' + (lfMode === 'disable' ? 'selected' : '') + '>本库关闭抽样（全量解析）</option>'
      + '      </select>'
      + '    </div>'
      + '    <div id="lcfg-lf-box" ' + (lfMode !== 'override' ? 'hidden' : '') + '>'
      + '      <div class="form-grid-2">'
      + '        <div class="field"><label for="lcfg-lf-threshold">文件数超过此值才抽样</label><input id="lcfg-lf-threshold" type="number" min="0" step="1" value="' + esc(lfVal.threshold || '') + '" placeholder="例如 6"></div>'
      + '        <div class="field"><label for="lcfg-lf-max">最多解析数</label><input id="lcfg-lf-max" type="number" min="0" step="1" value="' + esc(lfVal.max_selected || '') + '" placeholder="留空不限"></div>'
      + '      </div>'
      + '      <div class="field mt-xs"><label for="lcfg-lf-kw">优先关键词（逗号分隔）</label><input id="lcfg-lf-kw" type="text" value="' + esc((lfVal.keywords || []).join(', ')) + '" placeholder="tt, ss, ff"></div>'
      + '      <div class="field mt-xs"><label for="lcfg-lf-excl">排除关键词（逗号分隔）</label><input id="lcfg-lf-excl" type="text" value="' + esc((lfVal.exclude_keywords || []).join(', ')) + '" placeholder="ccs, lvf"></div>'
      + '      <div class="field mt-xs"><label for="lcfg-lf-fb">未命中回退</label><select id="lcfg-lf-fb"><option value="first_n" ' + ((lfVal.fallback || 'first_n') === 'first_n' ? 'selected' : '') + '>first_n（取前 N 个）</option><option value="skip" ' + (lfVal.fallback === 'skip' ? 'selected' : '') + '>skip（全部跳过）</option></select></div>'
      + '    </div>'
      + '  </div>'
      + '  <div class="org-drawer-section">'
      + '    <div class="lib-cfg-sec-head"><span class="org-drawer-sec-title">4. 检查插件启停策略</span></div>'
      + '    <label class="check-inline mb-xs"><input id="lcfg-plg-inherit" type="checkbox" ' + (!ov.has_check_plugins ? 'checked' : '') + ' onchange="document.getElementById(\'lcfg-plg-box\').hidden = this.checked"> 继承工作区 / IP 类型默认（' + (ws.check_plugins || []).length + ' 项）</label>'
      + '    <div id="lcfg-plg-box" class="lib-cfg-plugins" ' + (!ov.has_check_plugins ? 'hidden' : '') + '>' + pluginsHtml + '</div>'
      + '  </div>'
      + '</form>';
  }

  function renderDrawer() {
    var body = document.getElementById('lib-cfg-body');
    var title = document.getElementById('lib-cfg-title');
    var modeBtn = document.getElementById('lib-cfg-mode-btn');
    var footer = document.getElementById('lib-cfg-footer');
    if (!body || !_state.data) return;
    if (_state.editing) {
      title.textContent = '编辑单库配置';
      modeBtn.textContent = '返回只读';
      body.innerHTML = renderEditForm(_state.data);
      footer.hidden = false;
    } else {
      title.textContent = '单库配置概览';
      modeBtn.textContent = '编辑配置';
      body.innerHTML = renderReadOnly(_state.data);
      footer.hidden = true;
    }
  }

  function parseTokens(text) {
    return String(text || '').split(/[\r\n,，;]+/).map(function(s) { return s.trim(); }).filter(Boolean);
  }

  window.openLibraryConfigDrawer = function(vendor, library, section) {
    var drawer = document.getElementById('lib-config-drawer');
    var body = document.getElementById('lib-cfg-body');
    var status = document.getElementById('lib-cfg-status');
    if (!drawer || drawer.open) return;
    _state.opener = document.activeElement;
    _state.data = null;
    _state.editing = section === 'liberty';
    if (status) { status.textContent = ''; status.className = 'text-xs'; }
    body.innerHTML = '<p class="muted text-xs">正在加载单库配置…</p>';
    drawer.showModal();
    fetch('/api/v1/config?vendor=' + encodeURIComponent(vendor) + '&library=' + encodeURIComponent(library), { credentials: 'same-origin' })
      .then(function(r) { return r.json().then(function(j) { return { ok: r.ok, data: j }; }); })
      .then(function(res) {
        if (!res.ok) {
          body.innerHTML = '<div class="notice bad"><strong>加载失败</strong><span>' + esc(res.data && res.data.error || '未知错误') + '</span></div>';
          return;
        }
        _state.data = res.data;
        renderDrawer();
        if (_state.editing && drawer.open) {
          document.getElementById('lcfg-lf-mode').focus();
        }
      })
      .catch(function(err) {
        body.innerHTML = '<div class="notice bad"><strong>网络错误</strong><span>' + esc(err.message || err) + '</span></div>';
      });
  };

  window.closeLibraryConfigDrawer = function() {
    var drawer = document.getElementById('lib-config-drawer');
    if (drawer && drawer.open) drawer.close();
  };

  window.toggleLibraryConfigEdit = function(forceEdit) {
    if (!_state.data) return;
    _state.editing = (typeof forceEdit === 'boolean') ? forceEdit : !_state.editing;
    var status = document.getElementById('lib-cfg-status');
    if (status) { status.textContent = ''; status.className = 'text-xs'; }
    renderDrawer();
    document.getElementById('lib-cfg-mode-btn').focus();
  };

  window.saveLibraryConfigDrawer = function() {
    if (_state.saving || !_state.data) return;
    var drawer = document.getElementById('lib-config-drawer');
    var status = document.getElementById('lib-cfg-status');
    var saveBtn = document.getElementById('lib-cfg-save-btn');
    var vendor = drawer.getAttribute('data-vendor');
    var library = drawer.getAttribute('data-library');
    var csrf = drawer.getAttribute('data-csrf');

    var updates = {
      ip_type: (document.getElementById('lcfg-ip-type').value || '').trim() || null,
      ip_list: parseTokens(document.getElementById('lcfg-ip-list').value)
    };
    if (document.getElementById('lcfg-spv-inherit').checked) {
      updates.inherit_skip_parse_views = true;
    } else {
      updates.skip_parse_views = Array.prototype.slice.call(document.querySelectorAll('#lcfg-spv-box input[name="cfg_spv"]:checked')).map(function(el) { return el.value; });
    }
    if (document.getElementById('lcfg-tail-inherit').checked) {
      updates.inherit_initial_delivery_tail = true;
    } else {
      var tRaw = (document.getElementById('lcfg-tail-val').value || '').trim();
      updates.initial_delivery_tail = tRaw === '' ? 0 : parseInt(tRaw, 10);
    }
    var lfMode = document.getElementById('lcfg-lf-mode').value;
    if (lfMode === 'inherit') {
      updates.inherit_liberty_parse_filter = true;
    } else if (lfMode === 'disable') {
      updates.liberty_parse_filter = null;
    } else {
      var thRaw = (document.getElementById('lcfg-lf-threshold').value || '').trim();
      var mxRaw = (document.getElementById('lcfg-lf-max').value || '').trim();
      var thVal = thRaw ? parseInt(thRaw, 10) : null;
      updates.liberty_parse_filter = {
        enabled: thVal !== null && thVal > 0,
        threshold: thVal,
        keywords: parseTokens(document.getElementById('lcfg-lf-kw').value),
        exclude_keywords: parseTokens(document.getElementById('lcfg-lf-excl').value),
        max_selected: mxRaw ? parseInt(mxRaw, 10) : null,
        fallback: document.getElementById('lcfg-lf-fb').value || 'first_n'
      };
    }
    if (document.getElementById('lcfg-plg-inherit').checked) {
      updates.inherit_check_plugins = true;
    } else {
      var enabledPlugins = Array.prototype.slice.call(document.querySelectorAll('#lcfg-plg-box input[name="cfg_plugin"]:checked')).map(function(el) { return el.value; });
      updates.check_plugins = { enabled: enabledPlugins, disabled: [] };
    }

    _state.saving = true;
    saveBtn.disabled = true;
    status.textContent = '正在校验并保存…';
    status.className = 'text-xs muted';

    fetch('/api/v1/config', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf },
      body: JSON.stringify({ vendor: vendor, library: library, updates: updates })
    })
      .then(function(r) { return r.json().then(function(j) { return { ok: r.ok, data: j }; }); })
      .then(function(res) {
        _state.saving = false;
        saveBtn.disabled = false;
        if (!res.ok) {
          status.textContent = '保存失败：' + (res.data && res.data.error || '校验未通过');
          status.className = 'text-xs bad-text';
          return;
        }
        var ipChanged = (JSON.stringify(_state.data.ip_list) !== JSON.stringify(res.data.ip_list))
          || (_state.data.ip_type !== res.data.ip_type);
        var before = _state.data.effective || {};
        var after = res.data.effective || {};
        var previewChanged = JSON.stringify(before.liberty_parse_filter) !== JSON.stringify(after.liberty_parse_filter)
          || JSON.stringify(before.skip_parse_views) !== JSON.stringify(after.skip_parse_views)
          || JSON.stringify(before.check_plugins) !== JSON.stringify(after.check_plugins);
        _state.data = res.data;
        _state.editing = false;
        renderDrawer();
        var body = document.getElementById('lib-cfg-body');
        if (body) {
          var banner = document.createElement('div');
          banner.className = 'notice ok mb-sm';
          banner.innerHTML = '<strong>单库配置已通过 Schema 校验并保存</strong>'
            + '<span>' + (ipChanged || previewChanged ? '正在刷新检查范围及候选文件…' : '已写入 work/path_sources.json，后续检查与刷新即刻生效。') + '</span>';
          body.insertBefore(banner, body.firstChild);
        }
        if (ipChanged || previewChanged) {
          setTimeout(function() { location.reload(); }, 900);
        }
      })
      .catch(function(err) {
        _state.saving = false;
        saveBtn.disabled = false;
        status.textContent = '网络错误：' + (err.message || err);
        status.className = 'text-xs bad-text';
      });
  };

  var configDrawer = document.getElementById('lib-config-drawer');
  if (configDrawer) {
    configDrawer.addEventListener('close', function() {
      if (_state.opener) _state.opener.focus();
    });
    configDrawer.addEventListener('click', function(e) {
      if (e.target === configDrawer && e.clientX < configDrawer.getBoundingClientRect().left) configDrawer.close();
    });
    configDrawer.addEventListener('keydown', function(e) {
      if (e.key !== 'Tab') return;
      var controls = Array.from(configDrawer.querySelectorAll('button, select, input, textarea, a[href]'))
        .filter(function(el) { return !el.disabled && el.tabIndex >= 0 && el.getClientRects().length; });
      var first = controls[0], last = controls[controls.length - 1];
      if (e.shiftKey ? document.activeElement === first : document.activeElement === last) {
        e.preventDefault();
        (e.shiftKey ? last : first).focus();
      }
    });
  }
})();

/* ============================================================================
 * Check Rules Filter / Search / Collapse & Candidate .lib Preview Widget
 * ============================================================================ */
(function() {
  function initRuleWidget(widget) {
    if (!widget || widget.dataset.bound === '1') return;
    widget.dataset.bound = '1';
    var activeCat = 'all';
    var activeStatus = 'all';
    var totalRules = parseInt(widget.getAttribute('data-total-rules') || '0', 10);
    var totalEntries = parseInt(widget.getAttribute('data-total-entries') || '0', 10);
    var summaryEl = widget.querySelector('[data-rule-summary]');
    var emptyEl = widget.querySelector('[data-rule-empty]');
    var rules = Array.prototype.slice.call(widget.querySelectorAll('.check-rule'));

    function applyRuleInner(ruleEl) {
      var listEl = ruleEl.querySelector('.check-rule-evidence');
      if (!listEl) return { matched: 0, shown: 0 };
      var limit = parseInt(listEl.getAttribute('data-page-limit') || '20', 10);
      var searchInput = ruleEl.querySelector('[data-rule-inner-search]');
      var q = searchInput ? (searchInput.value || '').trim().toLowerCase() : '';
      var toggleBtn = ruleEl.querySelector('[data-rule-toggle-more]');
      var moreBar = ruleEl.querySelector('[data-rule-more-bar]');
      var countEl = ruleEl.querySelector('[data-rule-inner-count]');
      var innerEmpty = ruleEl.querySelector('[data-rule-inner-empty]');
      var expanded = toggleBtn && toggleBtn.getAttribute('data-expanded') === '1';
      var bypassCap = expanded || q !== '' || activeStatus !== 'all';

      var items = Array.prototype.slice.call(listEl.children);
      var matched = 0;
      var shown = 0;
      items.forEach(function(li) {
        var res = li.getAttribute('data-result') || '';
        var hay = li.getAttribute('data-search') || '';
        var statusOk = (activeStatus === 'all' || res === activeStatus);
        var queryOk = (!q || hay.indexOf(q) !== -1);
        if (statusOk && queryOk) {
          matched += 1;
          if (bypassCap || shown < limit) {
            li.hidden = false;
            shown += 1;
          } else {
            li.hidden = true;
          }
        } else {
          li.hidden = true;
        }
      });

      if (moreBar && toggleBtn) {
        if (!q && activeStatus === 'all' && matched > limit) {
          moreBar.hidden = false;
          toggleBtn.textContent = expanded
            ? ('收起至前 ' + limit + ' 条')
            : ('展开其余 ' + (matched - limit) + ' 条结论');
        } else {
          moreBar.hidden = true;
        }
      }
      if (countEl) {
        if (q || activeStatus !== 'all') {
          countEl.textContent = '匹配 ' + matched + ' / ' + items.length + ' 条';
        } else if (!expanded && matched > limit) {
          countEl.textContent = '显示前 ' + limit + ' / ' + matched + ' 条';
        } else {
          countEl.textContent = '共 ' + matched + ' 条';
        }
      }
      if (innerEmpty) {
        innerEmpty.hidden = !(q && matched === 0);
      }
      return { matched: matched, shown: shown };
    }

    function applyAll() {
      var visibleRules = 0;
      var visibleEntries = 0;
      rules.forEach(function(ruleEl) {
        var cat = ruleEl.getAttribute('data-rule-cat') || 'FACTS';
        var catOk = (activeCat === 'all' || cat === activeCat);
        if (!catOk) {
          ruleEl.hidden = true;
          return;
        }
        var stat = applyRuleInner(ruleEl);
        var searchInput = ruleEl.querySelector('[data-rule-inner-search]');
        var hasInnerQ = searchInput && (searchInput.value || '').trim() !== '';
        // Hide rules with 0 entries matching top-level status filter (unless user only typed inner search)
        if (activeStatus !== 'all' && stat.matched === 0 && !hasInnerQ) {
          ruleEl.hidden = true;
          return;
        }
        ruleEl.hidden = false;
        visibleRules += 1;
        visibleEntries += stat.matched;
      });
      if (summaryEl) {
        if (activeCat === 'all' && activeStatus === 'all') {
          summaryEl.textContent = '共 ' + totalRules + ' 项规则 · ' + totalEntries + ' 条结论';
        } else {
          summaryEl.textContent = '匹配 ' + visibleRules + ' / ' + totalRules + ' 项规则 · ' + visibleEntries + ' / ' + totalEntries + ' 条结论';
        }
      }
      if (emptyEl) {
        emptyEl.hidden = visibleRules > 0;
      }
    }

    var catSeg = widget.querySelector('[data-rule-cat-seg]');
    if (catSeg) {
      catSeg.addEventListener('click', function(e) {
        var btn = e.target.closest('button[data-cat]');
        if (!btn) return;
        activeCat = btn.getAttribute('data-cat') || 'all';
        catSeg.querySelectorAll('button[data-cat]').forEach(function(b) {
          var on = b === btn;
          b.classList.toggle('active', on);
          b.setAttribute('aria-pressed', on ? 'true' : 'false');
        });
        applyAll();
      });
    }

    var statusSeg = widget.querySelector('[data-rule-status-seg]');
    if (statusSeg) {
      statusSeg.addEventListener('click', function(e) {
        var btn = e.target.closest('button[data-status]');
        if (!btn) return;
        activeStatus = btn.getAttribute('data-status') || 'all';
        statusSeg.querySelectorAll('button[data-status]').forEach(function(b) {
          var on = b === btn;
          b.classList.toggle('active', on);
          b.setAttribute('aria-pressed', on ? 'true' : 'false');
        });
        applyAll();
      });
    }

    rules.forEach(function(ruleEl) {
      var searchInput = ruleEl.querySelector('[data-rule-inner-search]');
      if (searchInput) {
        searchInput.addEventListener('input', function() { applyRuleInner(ruleEl); });
      }
      var toggleBtn = ruleEl.querySelector('[data-rule-toggle-more]');
      if (toggleBtn) {
        toggleBtn.addEventListener('click', function() {
          var cur = toggleBtn.getAttribute('data-expanded') === '1';
          toggleBtn.setAttribute('data-expanded', cur ? '0' : '1');
          applyRuleInner(ruleEl);
        });
      }
    });

    var resetBtn = widget.querySelector('[data-rule-reset]');
    if (resetBtn) {
      resetBtn.addEventListener('click', function() {
        activeCat = 'all';
        activeStatus = 'all';
        if (catSeg) {
          catSeg.querySelectorAll('button[data-cat]').forEach(function(b) {
            var on = b.getAttribute('data-cat') === 'all';
            b.classList.toggle('active', on);
            b.setAttribute('aria-pressed', on ? 'true' : 'false');
          });
        }
        if (statusSeg) {
          statusSeg.querySelectorAll('button[data-status]').forEach(function(b) {
            var on = b.getAttribute('data-status') === 'all';
            b.classList.toggle('active', on);
            b.setAttribute('aria-pressed', on ? 'true' : 'false');
          });
        }
        rules.forEach(function(r) {
          var inp = r.querySelector('[data-rule-inner-search]');
          if (inp) inp.value = '';
        });
        applyAll();
      });
    }
  }

  function initLibertyPreview(widget) {
    if (!widget || widget.dataset.bound === '1') return;
    widget.dataset.bound = '1';
    var listEl = widget.querySelector('[data-lib-preview-list]');
    if (!listEl) return;
    var limit = parseInt(listEl.getAttribute('data-page-limit') || '20', 10);
    var searchInput = widget.querySelector('[data-lib-preview-search]');
    var countEl = widget.querySelector('[data-lib-preview-count]');
    var moreWrap = widget.querySelector('[data-lib-preview-more]');
    var toggleBtn = widget.querySelector('[data-lib-preview-toggle]');
    var emptyEl = widget.querySelector('[data-lib-preview-empty]');
    var items = Array.prototype.slice.call(listEl.children);

    function applyPreview() {
      var q = searchInput ? (searchInput.value || '').trim().toLowerCase() : '';
      var expanded = toggleBtn && toggleBtn.getAttribute('data-expanded') === '1';
      var bypassCap = expanded || q !== '';
      var matched = 0;
      var shown = 0;
      items.forEach(function(li) {
        var hay = li.getAttribute('data-search') || '';
        if (!q || hay.indexOf(q) !== -1) {
          matched += 1;
          if (bypassCap || shown < limit) {
            li.hidden = false;
            shown += 1;
          } else {
            li.hidden = true;
          }
        } else {
          li.hidden = true;
        }
      });
      if (moreWrap && toggleBtn) {
        if (!q && matched > limit) {
          moreWrap.hidden = false;
          toggleBtn.textContent = expanded
            ? ('收起至前 ' + limit + ' 个')
            : ('展开其余 ' + (matched - limit) + ' 个 .lib');
        } else {
          moreWrap.hidden = true;
        }
      }
      if (countEl) {
        if (q) {
          countEl.textContent = '匹配 ' + matched + ' / ' + items.length + ' 个';
        } else if (!expanded && matched > limit) {
          countEl.textContent = '显示前 ' + limit + ' / ' + matched + ' 个';
        } else {
          countEl.textContent = '共 ' + matched + ' 个';
        }
      }
      if (emptyEl) {
        emptyEl.hidden = matched > 0;
      }
    }

    if (searchInput) {
      searchInput.addEventListener('input', applyPreview);
    }
    if (toggleBtn) {
      toggleBtn.addEventListener('click', function() {
        var cur = toggleBtn.getAttribute('data-expanded') === '1';
        toggleBtn.setAttribute('data-expanded', cur ? '0' : '1');
        applyPreview();
      });
    }
  }

  function initCheckConsole() {
    var scope = document.getElementById('check-scope');
    var targetSel = document.getElementById('check-target-rev');
    var baseSel = document.getElementById('check-baseline-rev');
    if (scope && targetSel && baseSel && scope.dataset.consoleBound !== '1') {
      scope.dataset.consoleBound = '1';
      var revisions = JSON.parse(scope.dataset.revisions);
      var preview = document.getElementById('liberty-check-preview');
      var previewKey = 'ai_lib_open_liberty_preview';
      try {
        if (sessionStorage.getItem(previewKey) === location.pathname + location.search) {
          sessionStorage.removeItem(previewKey);
          preview.open = true;
        }
      } catch (e) {}

      function navigateCheckScope() {
        var revision = targetSel.value;
        var baseline = baseSel.value;
        var baselineIndex = revisions.indexOf(baseline);
        if (baselineIndex >= revisions.indexOf(revision)) baseline = '__prev_file__';
        var url = new URL(location.href);
        url.searchParams.set('revision', revision);
        url.searchParams.set('baseline', baseline);
        url.hash = 'checks';
        if (preview.open) {
          try { sessionStorage.setItem(previewKey, url.pathname + url.search); } catch (e) {}
        }
        document.getElementById('check-single-submit-btn').disabled = true;
        location.assign(url);
      }

      targetSel.addEventListener('change', navigateCheckScope);
      baseSel.addEventListener('change', navigateCheckScope);
      window.addEventListener('pageshow', function(event) {
        if (!event.persisted) return;
        [targetSel, baseSel].forEach(function(select) {
          var initialOption = select.querySelector('option[selected]');
          if (initialOption) select.value = initialOption.value;
        });
        document.getElementById('check-single-submit-btn').disabled = false;
      });
    }

    // All-IP matrix filters (multi-track libraries)
    var ipSeg = document.getElementById('all-ips-status-seg');
    var ipSearch = document.getElementById('all-ips-search');
    var ipTable = document.getElementById('all-ips-matrix-table');
    if (ipTable && ipTable.dataset.bound !== '1') {
      ipTable.dataset.bound = '1';
      var activeIpStatus = 'all';
      function applyIpMatrixFilter() {
        var q = ipSearch ? (ipSearch.value || '').trim().toLowerCase() : '';
        ipTable.querySelectorAll('tbody tr').forEach(function(tr) {
          var st = tr.getAttribute('data-ip-status') || '';
          var hay = tr.getAttribute('data-search') || '';
          var ok = (activeIpStatus === 'all' || st === activeIpStatus) && (!q || hay.indexOf(q) !== -1);
          tr.hidden = !ok;
        });
      }
      if (ipSeg) {
        ipSeg.addEventListener('click', function(e) {
          var btn = e.target.closest('button[data-ip-status]');
          if (!btn) return;
          activeIpStatus = btn.getAttribute('data-ip-status') || 'all';
          ipSeg.querySelectorAll('button[data-ip-status]').forEach(function(b) {
            var on = b === btn;
            b.classList.toggle('active', on);
            b.setAttribute('aria-pressed', on ? 'true' : 'false');
          });
          applyIpMatrixFilter();
        });
      }
      if (ipSearch) ipSearch.addEventListener('input', applyIpMatrixFilter);
    }
  }

  window.initCheckWidgets = function() {
    document.querySelectorAll('[data-check-rules-widget]').forEach(initRuleWidget);
    document.querySelectorAll('[data-liberty-preview-widget]').forEach(initLibertyPreview);
    initCheckConsole();
    var catSec = document.getElementById('catalog-section');
    if (catSec && !catSec.hidden && typeof window.initCatalogSearchPanel === 'function') {
      window.initCatalogSearchPanel();
    }
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', window.initCheckWidgets);
  } else {
    window.initCheckWidgets();
  }
})();

/* ============================================================================
 * Cross-Library SQL Catalog Search Panel (Layer-1 + Layer-2 SQLite Projection)
 * ========================================================================== */
(function() {
  var _state = {
    initialized: false,
    tab: 'check-items',
    offset: 0,
    limit: 50,
    total: 0,
    timer: null,
    reqSeq: 0,
    summary: null
  };

  var _PLACEHOLDERS = {
    'check-items': '规则 ID / 库名 / 摘要…',
    'changes': '对象名（Cell / Macro）…',
    'objects': 'Cell / Macro / 库名…',
    'corners': 'Corner 词（如 slow+125c）'
  };

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function secEl() {
    return document.getElementById('catalog-section');
  }

  function libHref(vendor, library, businessIp, revision, hash) {
    var sec = secEl();
    var base = (sec && sec.getAttribute('data-library-url')) || '/path/library';
    var q = new URLSearchParams();
    q.set('vendor', vendor || '');
    q.set('library', library || '');
    if (businessIp) q.set('ip', businessIp);
    if (revision) q.set('revision', revision);
    return base + '?' + q.toString() + (hash || '');
  }

  function checkViewHref(vendor, library, checkName) {
    var sec = secEl();
    var base = (sec && sec.getAttribute('data-check-view-url')) || '/path/check/view';
    var q = new URLSearchParams();
    q.set('vendor', vendor || '');
    q.set('library', library || '');
    q.set('name', checkName || '');
    return base + '?' + q.toString() + '#check-rules';
  }

  function renderLibLink(r, hash) {
    var href = libHref(r.vendor, r.library, r.business_ip, r.revision, hash || '');
    var label = esc(r.vendor) + ' / <strong>' + esc(r.library) + '</strong>';
    var ipPill = r.business_ip ? ' <span class="chip mono" translate="no">' + esc(r.business_ip) + '</span>' : '';
    var typeSub = r.ip_type ? '<div class="sub-text">' + esc(r.ip_type) + '</div>' : '';
    return '<a href="' + esc(href) + '" translate="no">' + label + '</a>' + ipPill + typeSub;
  }

  function resultBadge(res) {
    var u = String(res || '').toUpperCase();
    if (u === 'FAIL') return '<span class="tag tag-failed tag-sm"><span class="dot" aria-hidden="true"></span>FAIL</span>';
    if (u === 'PASS') return '<span class="tag tag-new tag-sm"><span class="dot" aria-hidden="true"></span>PASS</span>';
    return '<span class="tag tag-partial tag-sm"><span class="dot" aria-hidden="true"></span>' + esc(u || 'INCONCLUSIVE') + '</span>';
  }

  function showNotice(msg) {
    var el = document.getElementById('catalog-notice');
    if (!el) return;
    if (!msg) {
      el.hidden = true;
      el.textContent = '';
    } else {
      el.hidden = false;
      el.textContent = msg;
    }
  }

  function updateFilterVisibility(tab) {
    document.querySelectorAll('[data-cat-filter]').forEach(function(el) {
      var list = (el.getAttribute('data-cat-filter') || '').split(',');
      el.hidden = list.indexOf(tab) === -1;
    });
    var qEl = document.getElementById('cat-q');
    if (qEl) qEl.placeholder = _PLACEHOLDERS[tab] || '输入关键词搜索…';
    var latestLbl = document.querySelector('.catalog-latest-toggle span');
    if (latestLbl) {
      latestLbl.textContent = (tab === 'changes') ? '仅每次版本最新检查' : '仅最新有效版';
    }
  }

  function syncCheckIdSelect(byCheckId) {
    var sel = document.getElementById('cat-check-id');
    if (!sel || !Array.isArray(byCheckId)) return;
    var cur = sel.value;
    var seen = {};
    var opts = '<option value="">全部规则 ID</option>';
    byCheckId.forEach(function(row) {
      var cid = row.check_id || '';
      if (!cid || seen[cid]) return;
      seen[cid] = true;
      opts += '<option value="' + esc(cid) + '"' + (cid === cur ? ' selected' : '') + '>'
        + esc(cid) + ' (FAIL ' + Number(row.fail_count || 0) + ' / 总 ' + Number(row.total || 0) + ')</option>';
    });
    sel.innerHTML = opts;
    if (cur && !seen[cur]) sel.value = '';
  }

  function loadCatalogSummary() {
    var sec = secEl();
    if (!sec) return Promise.resolve(null);
    var url = sec.getAttribute('data-api-summary');
    return fetch(url, { credentials: 'same-origin' })
      .then(function(r) { return r.json(); })
      .then(function(data) {
        _state.summary = data;
        if (!data || data.backend === 'disabled') {
          showNotice('当前工作区已关闭 SQLite 投影（AI_LIB_QOR_CATALOG_SQLITE=0），跨库 SQL 检索不可用；原有纯文件视图不受影响。');
          return data;
        }
        showNotice('');
        var tot = data.totals || {};
        var setTxt = function(id, v) {
          var e = document.getElementById(id);
          if (e) e.textContent = v;
        };
        setTxt('cat-count-check-items', Number(tot.check_items || 0));
        setTxt('cat-count-changes', Number(tot.object_change_events || 0));
        setTxt('cat-count-objects', Number(tot.effective_objects || 0));
        setTxt('cat-count-corners', Number(tot.effective_views || 0));

        var failTotal = 0;
        (data.by_check_id || []).forEach(function(x) { failTotal += Number(x.fail_count || 0); });
        setTxt('cat-sub-check-items', failTotal > 0 ? ('当前最新存在 ' + failTotal + ' 项 FAIL') : '按 check_id 聚合最新结果');

        var metaEl = document.getElementById('catalog-meta-line');
        if (metaEl) {
          var ver = data.projection_version ? ('v' + data.projection_version) : 'v2';
          var rebuilt = data.last_rebuild_at
            ? (formatLocalUtcString(data.last_rebuild_at, 'full') || (data.last_rebuild_at.slice(0, 19).replace('T', ' ') + ' UTC'))
            : '—';
          metaEl.textContent = 'SQLite 投影 ' + ver + ' · 覆盖 ' + Number(tot.libraries || 0) + ' 库 / '
            + Number(tot.revisions || 0) + ' 有效版 · 最近全量重建 ' + rebuilt + '（只读查询，不扫 RAW）';
        }
        syncCheckIdSelect(data.by_check_id || []);
        return data;
      })
      .catch(function(err) {
        showNotice('加载跨库投影汇总失败：' + (err && err.message ? err.message : '网络异常'));
        return null;
      });
  }

  function renderSummaryStrip(tab, data) {
    var strip = document.getElementById('catalog-summary-strip');
    if (!strip) return;
    var html = '';
    if (tab === 'check-items') {
      var curCid = (document.getElementById('cat-check-id') || {}).value || '';
      var rows = data.by_check_id || [];
      rows.forEach(function(r) {
        var active = curCid === r.check_id;
        html += '<button type="button" class="catalog-rule-card' + (active ? ' active' : '') + '" '
          + 'onclick="toggleCatalogQuickFilter(\'check-id\',\'' + esc(r.check_id) + '\')">'
          + '<span class="mono">' + esc(r.check_id) + '</span>'
          + (Number(r.fail_count) > 0 ? '<span class="tag tag-failed tag-sm num">FAIL ' + Number(r.fail_count) + '</span>' : '')
          + (Number(r.inconclusive_count) > 0 ? '<span class="tag tag-partial tag-sm num">无结论 ' + Number(r.inconclusive_count) + '</span>' : '')
          + (Number(r.pass_count) > 0 ? '<span class="tag tag-new tag-sm num">PASS ' + Number(r.pass_count) + '</span>' : '')
          + '</button>';
      });
    } else if (tab === 'changes') {
      var curKind = ((document.getElementById('cat-change-kind') || {}).value || '').trim().toUpperCase();
      var byKind = data.counts_by_kind || {};
      Object.keys(byKind).sort().forEach(function(k) {
        var active = curKind === k.toUpperCase();
        html += '<button type="button" class="catalog-rule-card' + (active ? ' active' : '') + '" '
          + 'onclick="toggleCatalogQuickFilter(\'change-kind\',\'' + esc(k) + '\')">'
          + '<span class="mono">' + esc(k) + '</span>'
          + '<span class="chip num">' + Number(byKind[k]) + '</span>'
          + '</button>';
      });
    } else if (tab === 'objects') {
      var curType = ((document.getElementById('cat-object-type') || {}).value || '').trim().toUpperCase();
      var byType = data.counts_by_type || {};
      Object.keys(byType).sort().forEach(function(t) {
        var active = curType === t.toUpperCase();
        html += '<button type="button" class="catalog-rule-card' + (active ? ' active' : '') + '" '
          + 'onclick="toggleCatalogQuickFilter(\'object-type\',\'' + esc(t) + '\')">'
          + '<span class="mono">' + esc(t) + '</span>'
          + '<span class="chip num">' + Number(byType[t]) + '</span>'
          + '</button>';
      });
    } else if (tab === 'corners') {
      var curView = ((document.getElementById('cat-view') || {}).value || '').trim().toUpperCase();
      var byView = data.counts_by_view || {};
      Object.keys(byView).sort().forEach(function(v) {
        var active = curView === v.toUpperCase();
        html += '<button type="button" class="catalog-rule-card' + (active ? ' active' : '') + '" '
          + 'onclick="toggleCatalogQuickFilter(\'view\',\'' + esc(v) + '\')">'
          + '<span class="mono">' + esc(v) + '</span>'
          + '<span class="chip num">' + Number(byView[v]) + '</span>'
          + '</button>';
      });
    }
    strip.innerHTML = html;
  }

  function renderTable(tab, data) {
    var thead = document.getElementById('catalog-thead');
    var tbody = document.getElementById('catalog-tbody');
    if (!thead || !tbody) return;
    var items = data.items || [];

    if (tab === 'check-items') {
      thead.innerHTML = '<tr><th>规则 ID</th><th>来源库 / 轨道</th><th>版本</th><th>结论 / 覆盖</th><th>发现</th><th>摘要说明</th></tr>';
      if (!items.length) {
        tbody.innerHTML = '<tr><td colspan="6" class="muted">当前筛选条件下暂无匹配的规则检查项。</td></tr>';
        return;
      }
      tbody.innerHTML = items.map(function(r) {
        var detailRaw = r.detail || '—';
        var findTxt = Number(r.findings_count || 0) > 0 ? String(Number(r.findings_count)) : '—';
        var ruleHtml = r.check_name
          ? '<a href="' + esc(checkViewHref(r.vendor, r.library, r.check_name)) + '" class="mono" translate="no"><strong>' + esc(r.check_id) + '</strong></a>'
          : '<strong class="mono" translate="no">' + esc(r.check_id) + '</strong>';
        return '<tr>'
          + '<td>' + ruleHtml + '</td>'
          + '<td>' + renderLibLink(r, '#checks') + '</td>'
          + '<td class="mono nowrap" translate="no">' + esc(r.revision || '—') + '</td>'
          + '<td class="nowrap">' + resultBadge(r.result)
          + '<div class="sub-text mono">' + esc(r.coverage || '—') + '</div></td>'
          + '<td class="num muted">' + esc(findTxt) + '</td>'
          + '<td class="catalog-detail-cell" title="' + esc(detailRaw) + '"><div class="catalog-detail-clamp">' + esc(detailRaw) + '</div></td>'
          + '</tr>';
      }).join('');
    } else if (tab === 'changes') {
      thead.innerHTML = '<tr><th>对象名称</th><th>来源库 / 版本对比</th><th>变更类型</th><th>变化值（旧 → 新）</th><th>文件路径</th></tr>';
      if (!items.length) {
        tbody.innerHTML = '<tr><td colspan="5" class="muted">当前筛选条件下暂无跨版本对象变更记录。</td></tr>';
        return;
      }
      tbody.innerHTML = items.map(function(r) {
        var deltaHtml = '<span class="catalog-delta-val">';
        if (r.old_value) deltaHtml += '<span class="catalog-delta-old">' + esc(r.old_value) + '</span><span>→</span>';
        deltaHtml += '<span class="catalog-delta-new">' + esc(r.new_value || '—') + '</span>';
        if (r.unit) deltaHtml += '<span class="muted">' + esc(r.unit) + '</span>';
        deltaHtml += '</span>';
        var revPair = (r.baseline ? (esc(r.baseline) + ' → ') : '') + esc(r.revision || '—');
        return '<tr>'
          + '<td class="mono" translate="no"><strong>' + esc(r.object_name) + '</strong>'
          + '<div class="sub-text"><span class="chip mono">' + esc(r.object_type) + '</span> <span class="muted">' + esc(r.view) + '</span></div></td>'
          + '<td>' + renderLibLink(r, '#checks') + '<div class="sub-text mono" translate="no">' + revPair + '</div></td>'
          + '<td class="mono nowrap"><span class="tag tag-partial tag-sm">' + esc(r.change_kind) + '</span></td>'
          + '<td>' + deltaHtml + '</td>'
          + '<td class="mono text-xs catalog-path-cell" translate="no">' + esc(r.file_path || '—') + '</td>'
          + '</tr>';
      }).join('');
    } else if (tab === 'objects') {
      thead.innerHTML = '<tr><th>对象名称 / 类型</th><th>来源库 / 轨道</th><th>Pin 数</th><th>尺寸 / 面积 (um / um²)</th><th>覆盖文件</th><th>版本状态</th></tr>';
      if (!items.length) {
        tbody.innerHTML = '<tr><td colspan="6" class="muted">当前筛选条件下暂无去重对象目录（需先对库执行过检查并落盘 FileFacts 共享池）。</td></tr>';
        return;
      }
      tbody.innerHTML = items.map(function(r) {
        var dimText = '—';
        if (r.width_um != null && r.height_um != null) {
          dimText = esc(r.width_um) + ' × ' + esc(r.height_um);
          if (r.area_um2 != null) dimText += ' (' + esc(r.area_um2) + ')';
        }
        var revMeta = [];
        if (r.is_latest) revMeta.push('最新');
        if (r.is_accepted) revMeta.push('已采纳');
        var revSub = revMeta.length ? ' <span class="muted text-xs">· ' + esc(revMeta.join(' / ')) + '</span>' : '';
        return '<tr>'
          + '<td class="mono" translate="no"><strong>' + esc(r.object_name) + '</strong>'
          + '<div class="sub-text"><span class="chip mono">' + esc(r.object_type) + '</span> <span class="muted mono">' + esc(r.view) + '</span></div></td>'
          + '<td>' + renderLibLink(r, '#members') + '</td>'
          + '<td class="num">' + Number(r.pin_count || 0) + '</td>'
          + '<td class="mono num text-xs">' + dimText + '</td>'
          + '<td class="num">' + Number(r.corner_file_count || 1) + '</td>'
          + '<td class="nowrap"><span class="mono text-xs" translate="no">' + esc(r.revision) + '</span>' + revSub + '</td>'
          + '</tr>';
      }).join('');
    } else {
      thead.innerHTML = '<tr><th>View</th><th>Corner 提示 / 路径</th><th>来源库 / 轨道</th><th>来源交付版</th><th>版本状态</th></tr>';
      if (!items.length) {
        tbody.innerHTML = '<tr><td colspan="5" class="muted">当前筛选条件下暂无匹配的 Corner / View 文件。</td></tr>';
        return;
      }
      tbody.innerHTML = items.map(function(r) {
        var badges = '';
        if (r.is_latest) badges += '<span class="chip">最新</span> ';
        if (r.is_accepted) badges += '<span class="tag tag-new tag-sm">已采纳</span>';
        return '<tr>'
          + '<td><span class="chip mono">' + esc(r.view) + '</span></td>'
          + '<td class="mono catalog-path-cell" translate="no"><strong>' + esc(r.filename) + '</strong>'
          + '<div class="sub-text mono">' + esc(r.file_path) + '</div></td>'
          + '<td>' + renderLibLink(r, '#members') + '</td>'
          + '<td class="mono text-xs nowrap" translate="no">' + esc(r.source_version || '—') + '</td>'
          + '<td class="nowrap"><span class="mono text-xs" translate="no">' + esc(r.revision) + '</span> ' + badges + '</td>'
          + '</tr>';
      }).join('');
    }
  }

  function updatePager(total, offset, limit) {
    var pager = document.getElementById('catalog-pager');
    var info = document.getElementById('catalog-page-info');
    var prev = document.getElementById('cat-prev-btn');
    var next = document.getElementById('cat-next-btn');
    var matchEl = document.getElementById('catalog-match-count');
    if (matchEl) {
      var extraNote = '';
      var lo = document.getElementById('cat-latest-only');
      var sumTot = _state.summary && _state.summary.totals ? Number(_state.summary.totals.effective_objects || 0) : 0;
      if (_state.tab === 'objects' && lo && lo.checked && sumTot > Number(total || 0) && !((document.getElementById('cat-q') || {}).value || '').trim()) {
        extraNote = '（仅最新 · 含已采纳共 ' + sumTot + '）';
      }
      matchEl.textContent = '命中 ' + Number(total || 0) + ' 条' + extraNote;
    }
    if (!pager) return;
    if (total <= limit) {
      pager.hidden = true;
      return;
    }
    pager.hidden = false;
    var curPage = Math.floor(offset / limit) + 1;
    var pages = Math.max(1, Math.ceil(total / limit));
    if (info) info.textContent = '第 ' + curPage + ' / ' + pages + ' 页 · 共 ' + total + ' 条';
    if (prev) prev.disabled = (offset <= 0);
    if (next) next.disabled = (offset + limit >= total);
  }

  window.runCatalogQuery = function(newOffset) {
    var sec = secEl();
    if (!sec) return;
    if (typeof newOffset === 'number') _state.offset = Math.max(0, newOffset);
    var tab = _state.tab;
    var attrMap = {
      'check-items': 'data-api-check-items',
      'changes': 'data-api-changes',
      'objects': 'data-api-objects',
      'corners': 'data-api-corners'
    };
    var baseUrl = sec.getAttribute(attrMap[tab]);
    if (!baseUrl) return;

    var params = new URLSearchParams();
    params.set('limit', String(_state.limit));
    params.set('offset', String(_state.offset));
    var latestOnly = document.getElementById('cat-latest-only');
    params.set('latest_only', (latestOnly && !latestOnly.checked) ? '0' : '1');

    var q = ((document.getElementById('cat-q') || {}).value || '').trim();
    var vendor = ((document.getElementById('cat-vendor') || {}).value || '').trim();
    if (vendor) params.set('vendor', vendor);
    if (tab === 'check-items') {
      if (q) params.set('q', q);
      var res = ((document.getElementById('cat-result') || {}).value || '').trim();
      var cid = ((document.getElementById('cat-check-id') || {}).value || '').trim();
      if (res) params.set('result', res);
      if (cid) params.set('check_id', cid);
    } else if (tab === 'changes') {
      if (q) params.set('object_name', q);
      var ck = ((document.getElementById('cat-change-kind') || {}).value || '').trim();
      var vw = ((document.getElementById('cat-view') || {}).value || '').trim();
      if (ck) params.set('change_kind', ck);
      if (vw) params.set('view', vw);
    } else if (tab === 'objects') {
      if (q) params.set('q', q);
      var ot = ((document.getElementById('cat-object-type') || {}).value || '').trim();
      var vw2 = ((document.getElementById('cat-view') || {}).value || '').trim();
      if (ot) params.set('object_type', ot);
      if (vw2) params.set('view', vw2);
    } else if (tab === 'corners') {
      if (q) params.set('q', q);
      var vw3 = ((document.getElementById('cat-view') || {}).value || '').trim();
      if (vw3) params.set('view', vw3);
    }

    var seq = ++_state.reqSeq;
    var t0 = performance.now();
    var badge = document.getElementById('catalog-timing-badge');
    if (badge) badge.textContent = '查询中…';

    fetch(baseUrl + '?' + params.toString(), { credentials: 'same-origin' })
      .then(function(r) { return r.json(); })
      .then(function(data) {
        if (seq !== _state.reqSeq) return;
        var dt = Math.max(0.1, performance.now() - t0);
        if (badge) badge.textContent = (data.backend === 'sqlite' ? 'SQLite · ' : '') + dt.toFixed(1) + ' ms';
        if (data.backend === 'disabled') {
          showNotice('当前工作区已关闭 SQLite 投影（AI_LIB_QOR_CATALOG_SQLITE=0），无法执行跨库 SQL 检索。');
        }
        _state.total = Number(data.total || 0);
        renderSummaryStrip(tab, data);
        renderTable(tab, data);
        updatePager(_state.total, _state.offset, _state.limit);
      })
      .catch(function(err) {
        if (seq !== _state.reqSeq) return;
        if (badge) badge.textContent = '查询失败';
        showNotice('跨库查询失败：' + (err && err.message ? err.message : '网络异常'));
      });
  };

  window.scheduleCatalogQuery = function() {
    if (_state.timer) clearTimeout(_state.timer);
    _state.timer = setTimeout(function() { window.runCatalogQuery(0); }, 200);
  };

  window.switchCatalogTab = function(tab, btn) {
    if (['check-items', 'changes', 'objects', 'corners'].indexOf(tab) === -1) tab = 'check-items';
    _state.tab = tab;
    _state.offset = 0;
    document.querySelectorAll('.catalog-kpi-btn[data-cat-tab]').forEach(function(b) {
      var active = b.getAttribute('data-cat-tab') === tab;
      b.classList.toggle('active', active);
      b.setAttribute('aria-selected', active ? 'true' : 'false');
      b.setAttribute('tabindex', active ? '0' : '-1');
    });
    updateFilterVisibility(tab);
    window.runCatalogQuery(0);
  };

  window.toggleCatalogQuickFilter = function(kind, val) {
    var map = {
      'check-id': 'cat-check-id',
      'change-kind': 'cat-change-kind',
      'object-type': 'cat-object-type',
      'view': 'cat-view'
    };
    var el = document.getElementById(map[kind]);
    if (!el) return;
    el.value = (el.value === val) ? '' : val;
    window.runCatalogQuery(0);
  };

  window.resetCatalogFilters = function() {
    if (_state.timer) {
      clearTimeout(_state.timer);
      _state.timer = null;
    }
    ['cat-q', 'cat-result', 'cat-check-id', 'cat-view', 'cat-object-type', 'cat-change-kind', 'cat-vendor'].forEach(function(id) {
      var el = document.getElementById(id);
      if (el) el.value = '';
    });
    var lo = document.getElementById('cat-latest-only');
    if (lo) lo.checked = true;
    _state.offset = 0;
    window.runCatalogQuery(0);
  };

  window.stepCatalogPage = function(dir) {
    var nextOffset = _state.offset + (dir * _state.limit);
    if (nextOffset < 0 || nextOffset >= _state.total) return;
    window.runCatalogQuery(nextOffset);
  };

  window.rebuildCatalogProjection = function(btn) {
    var sec = secEl();
    if (!sec) return;
    var url = sec.getAttribute('data-api-rebuild');
    var csrf = sec.getAttribute('data-csrf') || '';
    if (btn) {
      btn.disabled = true;
      btn.setAttribute('data-orig-text', btn.textContent);
      btn.textContent = '重建中…';
    }
    var fd = new FormData();
    fd.append('csrf', csrf);
    fetch(url, { method: 'POST', body: fd, credentials: 'same-origin' })
      .then(function(r) { return r.json().then(function(j) { return { ok: r.ok, body: j }; }); })
      .then(function(res) {
        if (!res.ok) throw new Error((res.body && res.body.error) || '重建失败');
        return loadCatalogSummary().then(function() { window.runCatalogQuery(0); });
      })
      .catch(function(err) {
        showNotice('重建 SQLite 投影失败：' + (err && err.message ? err.message : '未知错误'));
      })
      .finally(function() {
        if (btn) {
          btn.disabled = false;
          btn.textContent = btn.getAttribute('data-orig-text') || '重建投影';
        }
      });
  };

  window.initCatalogSearchPanel = function() {
    if (_state.initialized) return;
    _state.initialized = true;
    updateFilterVisibility(_state.tab);
    loadCatalogSummary().then(function() {
      window.runCatalogQuery(0);
    });
  };
})();
