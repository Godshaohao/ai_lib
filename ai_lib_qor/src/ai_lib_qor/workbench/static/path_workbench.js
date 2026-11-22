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

function runAsyncJobForm(form, asyncUrl) {
  var banner = document.getElementById('async-job-banner');
  var statusEl = document.getElementById('async-job-status');
  var buttons = form.querySelectorAll('button[type="submit"],button:not([type])');
  buttons.forEach(function(b){ b.disabled = true; });
  if (banner) {
    banner.hidden = false;
    statusEl.textContent = '已提交后台任务，正在排队执行…';
  }
  var body = new FormData(form);
  fetch(asyncUrl, {method: 'POST', body: body, credentials: 'same-origin'})
    .then(function(r){ return r.json().then(function(d){ return {ok: r.ok, data: d}; }); })
    .then(function(res){
      if (!res.ok || !res.data.job_id) {
        if (statusEl) statusEl.textContent = '后台任务提交失败：' + (res.data && res.data.error || '未知错误');
        buttons.forEach(function(b){ b.disabled = false; });
        return;
      }
      pollAsyncJob(res.data.job_id, buttons);
    })
    .catch(function(err){
      if (statusEl) statusEl.textContent = '网络请求失败：' + err;
      buttons.forEach(function(b){ b.disabled = false; });
    });
}

function pollAsyncJob(jobId, buttons) {
  var statusEl = document.getElementById('async-job-status');
  fetch('/api/v1/jobs/' + encodeURIComponent(jobId), {credentials: 'same-origin'})
    .then(function(r){ return r.json(); })
    .then(function(job){
      if (job.status === 'QUEUED' || job.status === 'RUNNING') {
        if (statusEl) statusEl.textContent = job.label + ' · 状态 ' + job.status + ' · 已耗时 ' + job.elapsed_seconds + 's';
        setTimeout(function(){ pollAsyncJob(jobId, buttons); }, 700);
      } else if (job.status === 'SUCCEEDED') {
        if (statusEl) statusEl.textContent = job.label + ' 已完成（' + job.elapsed_seconds + 's），正在刷新页面…';
        setTimeout(function(){ window.location.reload(); }, 400);
      } else {
        if (statusEl) statusEl.textContent = job.label + ' 失败：' + (job.error || '未知错误');
        buttons.forEach(function(b){ b.disabled = false; });
      }
    })
    .catch(function(){
      setTimeout(function(){ pollAsyncJob(jobId, buttons); }, 1200);
    });
}

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
