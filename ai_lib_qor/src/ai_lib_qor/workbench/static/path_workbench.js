/* Shared client interactions + progressive-enhancement async job runner */
document.addEventListener('submit', function(e) {
  var form = e.target;
  if (form.method.toLowerCase() !== 'post') return;
  var asyncUrl = form.getAttribute('data-async-url');
  if (asyncUrl && window.fetch && window.FormData) {
    e.preventDefault();
    runAsyncJobForm(form, asyncUrl);
    return;
  }
  var pending = document.getElementById('pending');
  if (pending) pending.hidden = false;
  form.querySelectorAll('button[type="submit"],button:not([type])').forEach(function(b){ b.disabled = true; });
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
  activeJobButtons.forEach(function(b){ b.disabled = true; });
  showJobPanel({
    label: '后台任务提交中…', status: 'QUEUED', stage: 'QUEUED',
    message: '正在向本地服务提交后台任务…', elapsed_seconds: 0, percent: null, events: []
  });
  var body = new FormData(form);
  fetch(asyncUrl, {method: 'POST', body: body, credentials: 'same-origin'})
    .then(function(r){ return r.json().then(function(d){ return {ok: r.ok, data: d}; }); })
    .then(function(res){
      if (!res.ok || !res.data.job_id) {
        renderJobState({
          label: '提交失败', status: 'FAILED', message: (res.data && res.data.error) || '未知错误',
          elapsed_seconds: 0, percent: 0, events: []
        });
        activeJobButtons.forEach(function(b){ b.disabled = false; });
        return;
      }
      activeJobId = res.data.job_id;
      try { sessionStorage.setItem('ai_lib_active_job', activeJobId); } catch (e) {}
      renderJobState(res.data);
      scheduleJobPoll();
    })
    .catch(function(err){
      renderJobState({label: '网络异常', status: 'FAILED', message: String(err), elapsed_seconds: 0, percent: 0, events: []});
      activeJobButtons.forEach(function(b){ b.disabled = false; });
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
  if (title) title.textContent = job.label || '后台任务';
  if (elapsed) elapsed.textContent = (job.elapsed_seconds != null ? job.elapsed_seconds : 0) + 's';
  if (msg) msg.textContent = job.message || '';

  if (badge) {
    badge.className = 'tag ' + (
      st === 'SUCCEEDED' ? 'tag-new' :
      st === 'FAILED' ? 'tag-failed' :
      (st === 'CANCELLED' || st === 'CANCELLING') ? 'tag-partial' : 'tag-updated'
    );
    var labelMap = {QUEUED:'排队中', RUNNING:'运行中', CANCELLING:'正在终止…', CANCELLED:'已安全终止', SUCCEEDED:'已完成', FAILED:'执行失败'};
    badge.innerHTML = '<span class="dot"></span>' + (labelMap[st] || st);
  }
  if (st === 'SUCCEEDED') panel.classList.add('job-ok');
  else if (st === 'CANCELLED' || st === 'CANCELLING') panel.classList.add('job-warn');
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
    list.innerHTML = '';
    job.events.forEach(function(ev) {
      var li = document.createElement('li');
      li.textContent = ev;
      list.appendChild(li);
    });
    list.scrollTop = list.scrollHeight;
  }

  if (cancelBtn) {
    cancelBtn.hidden = !isActive;
    cancelBtn.disabled = (st === 'CANCELLING');
    cancelBtn.textContent = (st === 'CANCELLING') ? '正在安全停止…' : '终止任务';
  }
  if (reloadBtn) reloadBtn.hidden = (st !== 'SUCCEEDED' && st !== 'CANCELLED');
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
      .then(function(r){ if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
      .then(function(job){
        renderJobState(job);
        if (job.status === 'QUEUED' || job.status === 'RUNNING' || job.status === 'CANCELLING') {
          scheduleJobPoll();
        } else {
          activeJobButtons.forEach(function(b){ b.disabled = false; });
          try { sessionStorage.removeItem('ai_lib_active_job'); } catch (e) {}
        }
      })
      .catch(function(){
        activeJobButtons.forEach(function(b){ b.disabled = false; });
      });
  }, 500);
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
    .then(function(r){ return r.json(); })
    .then(function(job){ renderJobState(job); })
    .catch(function(){ if (cancelBtn) cancelBtn.disabled = false; });
}

/* Reconnect to an in-flight background job across page reloads */
(function reconnectActiveJob() {
  var saved = null;
  try { saved = sessionStorage.getItem('ai_lib_active_job'); } catch (e) {}
  if (!saved) return;
  fetch('/api/v1/jobs/' + encodeURIComponent(saved), {credentials: 'same-origin'})
    .then(function(r){ if (!r.ok) throw new Error('missing'); return r.json(); })
    .then(function(job){
      activeJobId = job.job_id;
      showJobPanel(job);
      if (job.status === 'QUEUED' || job.status === 'RUNNING' || job.status === 'CANCELLING') {
        scheduleJobPoll();
      } else {
        try { sessionStorage.removeItem('ai_lib_active_job'); } catch (e) {}
      }
    })
    .catch(function(){ try { sessionStorage.removeItem('ai_lib_active_job'); } catch (e) {} });
})();

function switchGlobalLibrary(val) {
  if (!val) return;
  var p = val.split('|'), target = window.location.pathname.indexOf('/path/index') !== -1 ? '/path/index' : '/path/library';
  window.location.href = target + '?vendor=' + encodeURIComponent(p[0]) + '&library=' + encodeURIComponent(p[1]);
}

/* Level 1 Multi-dimensional Library Filters */
var libState = {status: 'all', vendor: ''};
function setLibFilter(key, val, btn) {
  libState[key] = val;
  if (btn) {
    btn.parentNode.querySelectorAll('button').forEach(function(b){ b.classList.remove('active'); });
    btn.classList.add('active');
  }
  applyLibFilters();
}
function applyLibFilters() {
  var q = (document.getElementById('lib-search-input') || {}).value || '';
  q = q.trim().toLowerCase();
  var hideSim = !!(document.getElementById('hide-sim-cb') || {}).checked;
  var visible = 0;
  document.querySelectorAll('#libraries-table tbody tr').forEach(function(tr) {
    var v = tr.getAttribute('data-vendor'), lib = tr.getAttribute('data-library');
    var hasRev = tr.getAttribute('data-has-rev') === '1', issue = tr.getAttribute('data-issue') === '1';
    var sim = tr.getAttribute('data-sim') === '1';
    var ok = true;
    if (libState.vendor && v !== libState.vendor) ok = false;
    if (libState.status === 'has_rev' && !hasRev) ok = false;
    if (libState.status === 'no_rev' && hasRev) ok = false;
    if (libState.status === 'issue' && !issue) ok = false;
    if (hideSim && sim) ok = false;
    if (q && (v.toLowerCase() + ' ' + lib).indexOf(q) === -1) ok = false;
    tr.style.display = ok ? '' : 'none';
    if (ok) visible++;
  });
  var badge = document.getElementById('lib-visible-count');
  if (badge) badge.innerText = '显示 ' + visible + ' 个库';
}

/* Level 2 Workspace Object Tabs */
function switchLibTab(name, btn) {
  document.querySelectorAll('.tabs-bar .tab-btn').forEach(function(b){ b.classList.remove('active'); });
  document.querySelectorAll('.tab-panel').forEach(function(p){ p.classList.remove('active'); });
  if (btn) btn.classList.add('active');
  var panel = document.getElementById('tab-' + name);
  if (panel) panel.classList.add('active');
  try { history.replaceState(null, '', '#' + name); } catch (e) {}
}
(function restoreTab() {
  var hash = (window.location.hash || '').replace('#', '');
  if (!hash) return;
  var btn = document.querySelector('.tabs-bar .tab-btn[data-tab="' + hash + '"]');
  if (btn) switchLibTab(hash, btn);
})();

/* Level 2 Member Filters */
var memState = {diff: 'all', view: ''};
function setMemberFilter(key, val, btn) {
  memState[key] = val;
  if (btn) {
    btn.parentNode.querySelectorAll('button').forEach(function(b){ b.classList.remove('active'); });
    btn.classList.add('active');
  }
  applyMemberFilters();
}
function applyMemberFilters() {
  var q = (document.getElementById('member-search-input') || {}).value || '';
  q = q.trim().toLowerCase();
  document.querySelectorAll('#members-table tbody tr').forEach(function(tr) {
    var v = tr.getAttribute('data-view'), d = tr.getAttribute('data-diff'), txt = tr.getAttribute('data-text') || '';
    var ok = true;
    if (memState.view && v !== memState.view) ok = false;
    if (memState.diff === 'changed' && !(d === 'NEW' || d === 'UPDATED' || d === 'REMOVED')) ok = false;
    else if (memState.diff !== 'all' && memState.diff !== 'changed' && d !== memState.diff) ok = false;
    if (q && txt.indexOf(q) === -1) ok = false;
    tr.style.display = ok ? '' : 'none';
  });
}

/* Level 2 Artifact Filters */
var artState = {kind: 'all', quality: ''};
function setArtFilter(key, val, btn) {
  artState[key] = val;
  if (btn) {
    btn.parentNode.querySelectorAll('button').forEach(function(b){ b.classList.remove('active'); });
    btn.classList.add('active');
  }
  applyArtFilters();
}
function applyArtFilters() {
  var onlyCurr = !!(document.getElementById('filter-current-rev-only') || {}).checked;
  document.querySelectorAll('#artifacts-table tbody tr').forEach(function(tr) {
    var k = tr.getAttribute('data-kind'), q = tr.getAttribute('data-quality'), curr = tr.getAttribute('data-current') === '1';
    var ok = true;
    if (artState.kind !== 'all' && k !== artState.kind) ok = false;
    if (artState.quality && q !== artState.quality) ok = false;
    if (onlyCurr && !curr) ok = false;
    tr.style.display = ok ? '' : 'none';
  });
}

/* Level 2 Delivery Filter */
function filterDeliveries(q) {
  q = (q || '').trim().toLowerCase();
  document.querySelectorAll('#deliveries-table tbody tr').forEach(function(tr) {
    var txt = tr.getAttribute('data-text') || '';
    tr.style.display = (!q || txt.indexOf(q) !== -1) ? '' : 'none';
  });
}

/* Check View Filter */
var cvState = {src: 'all', view: ''};
function setCvFilter(key, val, btn) {
  cvState[key] = val;
  if (btn) {
    btn.parentNode.querySelectorAll('button').forEach(function(b){ b.classList.remove('active'); });
    btn.classList.add('active');
  }
  applyCvFilters();
}
function applyCvFilters() {
  var q = ((document.getElementById('cv-q') || {}).value || '').trim().toLowerCase();
  document.querySelectorAll('#cv-files-table tbody tr').forEach(function(tr) {
    var v = tr.getAttribute('data-view'), s = tr.getAttribute('data-src'), c = tr.getAttribute('data-content'), txt = tr.getAttribute('data-text') || '';
    var ok = true;
    if (cvState.view && v !== cvState.view) ok = false;
    if (cvState.src === 'changed' && !(s === 'NEW' || s === 'UPDATED' || s === 'REMOVED')) ok = false;
    if (cvState.src === 'diff' && !(c === 'CURRENT_CONTENT_DIFF' || c === 'PARTIAL_DIFF')) ok = false;
    if (q && txt.indexOf(q) === -1) ok = false;
    tr.style.display = ok ? '' : 'none';
  });
}

/* Level 3 Timeline Toggle & Copy */
function toggleTimeline(id, btn) {
  var row = document.getElementById(id);
  if (!row) return;
  var show = (row.style.display === 'none' || !row.style.display);
  row.style.display = show ? 'table-row' : 'none';
  btn.innerText = show ? '收起 ▴' : '展开 ▾';
}
function copyPath(btn, text) {
  var done = function() {
    var o = btn.innerText; btn.innerText = '已复制'; btn.classList.add('copied');
    setTimeout(function(){ btn.innerText = o; btn.classList.remove('copied'); }, 1200);
  };
  if (navigator.clipboard) navigator.clipboard.writeText(text).then(done);
  else { var i = document.createElement('input'); i.value = text; document.body.appendChild(i); i.select(); document.execCommand('copy'); document.body.removeChild(i); done(); }
}
