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
    var failures = job.result && job.result.libraries_failed;
    if (Array.isArray(failures)) {
      failures.forEach(function(row) {
        var li = document.createElement('li');
        li.textContent = row.vendor + '/' + row.library + ' · ' + row.reason;
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
  if (reloadBtn) reloadBtn.hidden = isActive;
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
        renderJobState(job);
        if (job.status === 'QUEUED' || job.status === 'RUNNING' || job.status === 'CANCELLING') {
          scheduleJobPoll();
        } else {
          activeJobButtons.forEach(function(b) { b.disabled = false; });
          try { sessionStorage.removeItem('ai_lib_active_job'); } catch (e) {}
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
      } else {
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

function _toggleEmptyRow(tableSelector, visibleCount, colSpan, message) {
  var tbody = document.querySelector(tableSelector + ' tbody');
  if (!tbody) return;
  var emptyRow = tbody.querySelector('tr.filter-empty-row');
  if (visibleCount === 0) {
    if (!emptyRow) {
      emptyRow = document.createElement('tr');
      emptyRow.className = 'filter-empty-row';
      var td = document.createElement('td');
      td.colSpan = colSpan;
      td.textContent = message;
      emptyRow.appendChild(td);
      tbody.appendChild(emptyRow);
    }
    emptyRow.style.display = '';
  } else if (emptyRow) {
    emptyRow.style.display = 'none';
  }
}

/* Level 1 Multi-dimensional Library Filters */
var libState = {status: 'all', vendor: ''};
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
    var hasRev = tr.getAttribute('data-has-rev') === '1', issue = tr.getAttribute('data-issue') === '1';
    var ok = true;
    if (libState.vendor && v !== libState.vendor) ok = false;
    if (libState.status === 'has_rev' && !hasRev) ok = false;
    if (libState.status === 'no_rev' && hasRev) ok = false;
    if (libState.status === 'issue' && !issue) ok = false;
    if (q && (v.toLowerCase() + ' ' + lib).indexOf(q) === -1) ok = false;
    tr.style.display = ok ? '' : 'none';
    if (ok) visible++;
  });
  var badge = document.getElementById('lib-visible-count');
  if (badge) badge.textContent = '显示 ' + visible + ' 个库';
  _toggleEmptyRow('#libraries-table', visible, 6, '当前筛选条件下没有匹配的来源库。');
}

/* Level 2 Accessible Workspace Object Tabs (ARIA + Keyboard Arrow/Home/End) */
function switchLibTab(name, btn, moveFocus) {
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
  var panel = document.getElementById('tab-' + name);
  if (panel) {
    panel.classList.add('active');
    panel.hidden = false;
  }
  try { history.replaceState(null, '', '#' + name); } catch (e) {}
}

(function initTabs() {
  var bar = document.querySelector('.tabs-bar[role="tablist"]');
  if (!bar) return;
  bar.addEventListener('keydown', function(e) {
    var tabs = Array.prototype.slice.call(bar.querySelectorAll('.tab-btn[role="tab"]'));
    var idx = tabs.indexOf(document.activeElement);
    if (idx === -1) return;
    var next = null;
    if (e.key === 'ArrowRight') next = (idx + 1) % tabs.length;
    else if (e.key === 'ArrowLeft') next = (idx - 1 + tabs.length) % tabs.length;
    else if (e.key === 'Home') next = 0;
    else if (e.key === 'End') next = tabs.length - 1;
    if (next !== null) {
      e.preventDefault();
      var targetBtn = tabs[next];
      switchLibTab(targetBtn.getAttribute('data-tab'), targetBtn, true);
    }
  });
  var hash = (window.location.hash || '').replace('#', '');
  if (hash) {
    var btn = document.querySelector('.tabs-bar .tab-btn[data-tab="' + hash + '"]');
    if (btn) switchLibTab(hash, btn, false);
  }
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
  document.querySelectorAll('#deliveries-table tbody tr:not(.filter-empty-row)').forEach(function(tr) {
    var txt = tr.getAttribute('data-text') || '';
    var ok = (!q || txt.indexOf(q) !== -1);
    tr.style.display = ok ? '' : 'none';
    if (ok) visible++;
  });
  _toggleEmptyRow('#deliveries-table', visible, 5, '当前关键字没有匹配的供应商交付记录。');
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

/* Overview Sync Center Inner Tabs (Layers & JSON / History / Config) with ARIA Keyboard Nav */
function switchSyncTab(name, btn, moveFocus) {
  var seg = document.getElementById('sync-center-seg');
  if (seg) {
    seg.querySelectorAll('button[role="tab"]').forEach(function(b) {
      var active = (b === btn || b.getAttribute('data-sync-tab') === name);
      b.classList.toggle('active', active);
      b.setAttribute('aria-selected', active ? 'true' : 'false');
      b.setAttribute('tabindex', active ? '0' : '-1');
      if (active && moveFocus) b.focus();
    });
  }
  document.querySelectorAll('.sync-pane').forEach(function(pane) {
    var active = (pane.id === 'sync-pane-' + name);
    pane.hidden = !active;
  });
}

(function initSyncTabs() {
  var seg = document.getElementById('sync-center-seg');
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
      switchSyncTab(target.getAttribute('data-sync-tab'), target, true);
    }
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
