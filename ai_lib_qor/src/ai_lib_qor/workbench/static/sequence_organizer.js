/* Interactive Draft-First Sequence & Business-IP Track Organizer (Inline + Drag & Drop + Batch + Row Context Menu) */
(function initSequenceOrganizer() {
  var dataEl = document.getElementById('organizer-initial-data');
  var boardEl = document.getElementById('org-board');
  if (!dataEl || !boardEl) return;

  var initial = null;
  try { initial = JSON.parse(dataEl.textContent || '{}'); } catch (e) { return; }
  if (!initial || !initial.mode) return;

  var isMulti = initial.mode === 'multi_track';
  var ipList = Array.isArray(initial.ip_list) ? initial.ip_list.slice() : [];
  var trackStatuses = initial.track_statuses || {};

  // Master metadata map by version string
  var metaByVer = {};
  function _registerItems(list) {
    (list || []).forEach(function(item) {
      if (item && item.version) metaByVer[item.version] = item;
    });
  }
  if (isMulti) {
    Object.keys(initial.tracks || {}).forEach(function(ip) { _registerItems(initial.tracks[ip]); });
    _registerItems(initial.needs_review);
    _registerItems(initial.excluded);
  } else {
    _registerItems(initial.order);
    _registerItems(initial.excluded);
  }

  function _cloneSavedGroups() {
    var g = {};
    if (isMulti) {
      g.__review__ = (initial.needs_review || []).map(function(x) { return x.version; });
      ipList.forEach(function(ip) {
        g[ip] = ((initial.tracks || {})[ip] || []).map(function(x) { return x.version; });
      });
      g.__excluded__ = (initial.excluded || []).map(function(x) { return x.version; });
    } else {
      g.__active__ = (initial.order || []).map(function(x) { return x.version; });
      g.__excluded__ = (initial.excluded || []).map(function(x) { return x.version; });
    }
    return g;
  }

  var savedGroups = _cloneSavedGroups();
  var draftGroups = _cloneSavedGroups();
  var selectedSet = {};
  var searchQuery = '';
  var dragState = null; // {ver, fromGroup}
  var ctxTarget = null; // {ver, group}

  var toastEl = document.getElementById('org-inline-toast');
  var batchBar = document.getElementById('org-batch-bar');
  var batchCountEl = document.getElementById('org-batch-count');
  var batchTargetSel = document.getElementById('org-batch-target');
  var draftBar = document.getElementById('org-draft-bar');
  var draftSummaryEl = document.getElementById('org-draft-summary');
  var draftImpactEl = document.getElementById('org-draft-impact');
  var rebuildWrapEl = document.getElementById('org-rebuild-wrap');
  var rebuildCheckEl = document.getElementById('org-rebuild-checkbox');
  var rebuildLabelEl = document.getElementById('org-rebuild-label');
  var applyBtn = document.getElementById('org-apply-btn');
  var ctxMenu = document.getElementById('org-context-menu');

  var toastTimer = null;
  function showToast(msg, tone) {
    if (!toastEl) return;
    toastEl.textContent = msg;
    toastEl.className = 'org-toast ' + (tone === 'bad' ? 'org-toast-bad' : (tone === 'ok' ? 'org-toast-ok' : 'org-toast-warn'));
    toastEl.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function() { toastEl.hidden = true; }, 4800);
  }

  function _csrf() {
    var m = document.querySelector('meta[name="csrf-token"]');
    return m ? m.getAttribute('content') : '';
  }

  function _validateSingleTrackOrder(orderList) {
    var lastDay = null, lastVer = null;
    for (var i = 0; i < orderList.length; i++) {
      var v = orderList[i];
      var vd = (metaByVer[v] || {}).version_date;
      if (vd) {
        if (lastDay && vd < lastDay) {
          return '目录日期优先规则不允许跨日期倒排：' + v + ' (' + vd + ') 不能排在 ' + lastVer + ' (' + lastDay + ') 之后；如需停用请标记排除。';
        }
        lastDay = vd;
        lastVer = v;
      }
    }
    return null;
  }

  function _findGroup(ver) {
    var keys = Object.keys(draftGroups);
    for (var i = 0; i < keys.length; i++) {
      if (draftGroups[keys[i]].indexOf(ver) !== -1) return keys[i];
    }
    return null;
  }

  function _moveVersion(ver, toGroup, targetIndex) {
    var fromGroup = _findGroup(ver);
    if (!fromGroup || !draftGroups[toGroup]) return false;

    var nextFrom = draftGroups[fromGroup].filter(function(x) { return x !== ver; });
    var nextTo = (fromGroup === toGroup) ? nextFrom.slice() : draftGroups[toGroup].slice();
    var idx = (typeof targetIndex === 'number' && targetIndex >= 0 && targetIndex <= nextTo.length) ? targetIndex : nextTo.length;
    nextTo.splice(idx, 0, ver);

    if (!isMulti && toGroup === '__active__') {
      var err = _validateSingleTrackOrder(nextTo);
      if (err) {
        showToast(err, 'bad');
        return false;
      }
    }

    if (fromGroup === toGroup) {
      draftGroups[toGroup] = nextTo;
    } else {
      draftGroups[fromGroup] = nextFrom;
      draftGroups[toGroup] = nextTo;
    }
    return true;
  }

  function _stepVersion(ver, delta) {
    var g = _findGroup(ver);
    if (!g) return;
    var arr = draftGroups[g];
    var idx = arr.indexOf(ver);
    if (idx === -1) return;
    var nextIdx = idx + delta;
    if (nextIdx < 0 || nextIdx >= arr.length) return;
    if (_moveVersion(ver, g, nextIdx)) {
      render();
    }
  }

  function _computeDiffAndImpact() {
    var assignedChanges = 0;
    var excludedChanges = 0;
    var reorderedGroups = [];
    var touchedEvolved = [];
    var rebuildable = [];
    var protectedTracks = [];

    var savedPos = {};
    Object.keys(savedGroups).forEach(function(g) {
      savedGroups[g].forEach(function(v) { savedPos[v] = g; });
    });

    Object.keys(draftGroups).forEach(function(g) {
      draftGroups[g].forEach(function(v) {
        var oldG = savedPos[v];
        if (oldG !== g) {
          if (g === '__excluded__' || oldG === '__excluded__') excludedChanges++;
          else assignedChanges++;
        }
      });
    });

    var checkKeys = isMulti ? ipList : ['__active__'];
    checkKeys.forEach(function(key) {
      var oldArr = savedGroups[key] || [];
      var newArr = draftGroups[key] || [];
      var same = (oldArr.length === newArr.length) && oldArr.every(function(v, i) { return v === newArr[i]; });
      if (!same) {
        var newSet = {};
        newArr.forEach(function(v) { newSet[v] = true; });
        var oldCommon = oldArr.filter(function(v) { return newSet[v]; });
        var oldSet = {};
        oldArr.forEach(function(v) { oldSet[v] = true; });
        var newCommon = newArr.filter(function(v) { return oldSet[v]; });
        if (oldCommon.length > 1 && oldCommon.some(function(v, i) { return v !== newCommon[i]; })) {
          reorderedGroups.push(key);
        }
      }
      var stKey = isMulti ? key : '__single__';
      var st = trackStatuses[stKey];
      if (!st || !st.has_history) return;
      var evolvedSet = {};
      (st.processed_versions || []).forEach(function(v) { evolvedSet[v] = true; });
      var oldEv = oldArr.filter(function(v) { return evolvedSet[v]; });
      var newEv = newArr.filter(function(v) { return evolvedSet[v]; });
      var historyChanged = (oldEv.length !== newEv.length) || oldEv.some(function(v, i) { return v !== newEv[i]; });
      if (!historyChanged && oldEv.length > 0) {
        var lastIdx = -1;
        oldEv.forEach(function(v) {
          var pos = newArr.indexOf(v);
          if (pos > lastIdx) lastIdx = pos;
        });
        for (var p = 0; p < lastIdx; p++) {
          if (!evolvedSet[newArr[p]]) { historyChanged = true; break; }
        }
      }
      if (historyChanged) {
        touchedEvolved.push(stKey);
        if (st.is_accepted) protectedTracks.push({key: stKey, label: isMulti ? key : initial.library, rev: st.accepted_revision});
        else rebuildable.push({key: stKey, label: isMulti ? key : initial.library});
      }
    });

    var hasAnyChange = assignedChanges > 0 || excludedChanges > 0 || reorderedGroups.length > 0;
    if (!hasAnyChange) {
      // Fallback exact check across all groups
      hasAnyChange = Object.keys(draftGroups).some(function(k) {
        var a = savedGroups[k] || [], b = draftGroups[k] || [];
        return a.length !== b.length || a.some(function(v, i) { return v !== b[i]; });
      });
    }
    return {
      hasAnyChange: hasAnyChange,
      assignedChanges: assignedChanges,
      excludedChanges: excludedChanges,
      reorderedCount: reorderedGroups.length,
      touchedEvolved: touchedEvolved,
      rebuildable: rebuildable,
      protectedTracks: protectedTracks
    };
  }

  function _groupTitle(gKey) {
    if (gKey === '__review__') return '待复核队列（冲突 / 未归类）';
    if (gKey === '__active__') return '正常纳入版本（按演进先后排列）';
    if (gKey === '__excluded__') return '已排除版本（不参与演进）';
    return gKey;
  }

  function _targetOptions() {
    var opts = [];
    if (isMulti) {
      ipList.forEach(function(ip) { opts.push({value: ip, label: ip}); });
      opts.push({value: '__review__', label: '移至待复核'});
      opts.push({value: '__excluded__', label: '排除此版本'});
    } else {
      opts.push({value: '__active__', label: '正常纳入'});
      opts.push({value: '__excluded__', label: '排除此版本'});
    }
    return opts;
  }

  function _indexUrl(ver, groupKey) {
    var base = '/path/index?vendor=' + encodeURIComponent(initial.vendor) +
      '&library=' + encodeURIComponent(initial.library) +
      '&delivery=' + encodeURIComponent(ver);
    if (isMulti && groupKey && groupKey !== '__review__' && groupKey !== '__excluded__') {
      base += '&ip=' + encodeURIComponent(groupKey);
    }
    return base;
  }

  function _buildRow(ver, groupKey, idx, total) {
    var m = metaByVer[ver] || {version: ver, file_count: 0, view_counts: {}};
    var q = searchQuery;
    var hay = (ver + ' ' + groupKey + ' ' + (m.version_date || '') + ' ' + Object.keys(m.view_counts || {}).join(' ') + ' ' + (m.reason || '')).toLowerCase();
    var matchesSearch = (!q || hay.indexOf(q) !== -1);

    var row = document.createElement('div');
    row.className = 'org-row' + (selectedSet[ver] ? ' is-selected' : '');
    if (!matchesSearch) row.hidden = true;
    row.setAttribute('draggable', 'true');
    row.setAttribute('data-ver', ver);
    row.setAttribute('data-group', groupKey);

    var isChanged = (savedGroups[groupKey] || []).indexOf(ver) !== idx;
    if (isChanged) row.classList.add('is-dirty');

    // Drag events
    row.addEventListener('dragstart', function(e) {
      dragState = {ver: ver, fromGroup: groupKey};
      row.classList.add('is-dragging');
      try { e.dataTransfer.setData('text/plain', ver); e.dataTransfer.effectAllowed = 'move'; } catch (err) {}
    });
    row.addEventListener('dragend', function() {
      dragState = null;
      row.classList.remove('is-dragging');
      boardEl.querySelectorAll('.drop-before,.drop-after,.drop-group-over').forEach(function(el) {
        el.classList.remove('drop-before', 'drop-after', 'drop-group-over');
      });
    });
    row.addEventListener('dragover', function(e) {
      if (!dragState || dragState.ver === ver) return;
      e.preventDefault();
      var rect = row.getBoundingClientRect();
      var before = (e.clientY - rect.top) < (rect.height / 2);
      row.classList.toggle('drop-before', before);
      row.classList.toggle('drop-after', !before);
    });
    row.addEventListener('dragleave', function() {
      row.classList.remove('drop-before', 'drop-after');
    });
    row.addEventListener('drop', function(e) {
      if (!dragState || dragState.ver === ver) return;
      e.preventDefault();
      e.stopPropagation();
      var rect = row.getBoundingClientRect();
      var before = (e.clientY - rect.top) < (rect.height / 2);
      row.classList.remove('drop-before', 'drop-after');
      var list = draftGroups[groupKey] || [];
      var targetIdx = list.indexOf(ver);
      if (targetIdx < 0) return;
      var srcIdx = (dragState.fromGroup === groupKey) ? list.indexOf(dragState.ver) : -1;
      var insertAt = before ? targetIdx : targetIdx + 1;
      if (srcIdx !== -1 && srcIdx < insertAt) insertAt--;
      if (_moveVersion(dragState.ver, groupKey, insertAt)) {
        render();
      }
    });

    // Right-click smart context menu (only when no text selected)
    row.addEventListener('contextmenu', function(e) {
      var selText = window.getSelection ? String(window.getSelection()) : '';
      if (selText && selText.trim()) return;
      e.preventDefault();
      openContextMenu(e.clientX, e.clientY, ver, groupKey, idx, total);
    });

    // 1. Checkbox + Drag Handle + Order Index
    var lead = document.createElement('div');
    lead.className = 'org-row-lead';
    var cb = document.createElement('input');
    cb.type = 'checkbox';
    cb.className = 'org-row-cb';
    cb.checked = !!selectedSet[ver];
    cb.setAttribute('aria-label', '选择版本 ' + ver);
    cb.addEventListener('change', function() {
      if (cb.checked) selectedSet[ver] = true;
      else delete selectedSet[ver];
      row.classList.toggle('is-selected', cb.checked);
      updateBatchBar();
    });
    lead.appendChild(cb);

    var grip = document.createElement('span');
    grip.className = 'org-grip';
    grip.setAttribute('aria-hidden', 'true');
    grip.title = '按住拖动可调序或跨轨道移动';
    grip.textContent = '⋮⋮';
    lead.appendChild(grip);

    var seq = document.createElement('span');
    seq.className = 'org-seq num';
    seq.textContent = (groupKey === '__review__' || groupKey === '__excluded__') ? '—' : ('#' + (idx + 1));
    lead.appendChild(seq);
    row.appendChild(lead);

    // 2. Main Info (Version, Date/mtime, Status Tags, Review Candidates)
    var main = document.createElement('div');
    main.className = 'org-row-main';

    var topLine = document.createElement('div');
    topLine.className = 'org-row-head';
    var verEl = document.createElement('strong');
    verEl.className = 'mono org-ver';
    verEl.setAttribute('translate', 'no');
    verEl.textContent = ver;
    topLine.appendChild(verEl);

    if (m.in_revisions && m.in_revisions.length > 0) {
      var revTag = document.createElement('span');
      revTag.className = 'tag tag-new tag-sm';
      revTag.setAttribute('translate', 'no');
      revTag.textContent = '已入 ' + m.in_revisions[m.in_revisions.length - 1];
      topLine.appendChild(revTag);
    } else if (m.is_evolved) {
      var procTag = document.createElement('span');
      procTag.className = 'tag tag-inherited tag-sm';
      procTag.textContent = '已处理';
      topLine.appendChild(procTag);
    } else if (groupKey === '__review__') {
      var rvTag = document.createElement('span');
      rvTag.className = 'tag tag-partial tag-sm';
      rvTag.textContent = (m.review_kind === 'CONFLICT') ? '多命中冲突' : '待归类';
      topLine.appendChild(rvTag);
    } else if (groupKey !== '__excluded__') {
      var pendTag = document.createElement('span');
      pendTag.className = 'tag tag-updated tag-sm';
      pendTag.textContent = '未入版';
      topLine.appendChild(pendTag);
    }

    if (isChanged) {
      var dirtyTag = document.createElement('span');
      dirtyTag.className = 'tag tag-accent tag-sm';
      dirtyTag.textContent = '待保存';
      topLine.appendChild(dirtyTag);
    }
    main.appendChild(topLine);

    // Sub-meta: date, mtime, views
    var sub = document.createElement('div');
    sub.className = 'org-row-sub num';
    var parts = [];
    parts.push(m.version_date ? ('目录日期 ' + m.version_date) : '无日期目录');
    if (m.registration_time) parts.push('登记 ' + m.registration_time.slice(0, 16).replace('T', ' '));
    else if (m.directory_mtime) parts.push('mtime ' + m.directory_mtime.slice(0, 10));
    var viewText = Object.keys(m.view_counts || {}).slice(0, 4).map(function(k) { return k + ' ' + m.view_counts[k]; }).join(' · ');
    parts.push((m.file_count || 0) + ' 文件' + (viewText ? ' (' + viewText + ')' : ''));
    sub.textContent = parts.join(' · ');
    main.appendChild(sub);

    // Conflict / unassigned quick-assign candidates
    if (groupKey === '__review__' && (m.reason || (m.candidates && m.candidates.length))) {
      var rvMeta = document.createElement('div');
      rvMeta.className = 'org-review-line';
      if (m.candidates && m.candidates.length) {
        var lbl = document.createElement('span');
        lbl.className = 'muted text-xs';
        lbl.textContent = '快捷归入：';
        rvMeta.appendChild(lbl);
        m.candidates.forEach(function(candIp) {
          if (!draftGroups[candIp]) return;
          var qBtn = document.createElement('button');
          qBtn.type = 'button';
          qBtn.className = 'secondary btn-xs';
          qBtn.setAttribute('translate', 'no');
          qBtn.textContent = '→ ' + candIp;
          qBtn.addEventListener('click', function() {
            if (_moveVersion(ver, candIp)) render();
          });
          rvMeta.appendChild(qBtn);
        });
      } else if (m.reason) {
        var rSpan = document.createElement('span');
        rSpan.className = 'muted text-xs';
        rSpan.textContent = m.reason;
        rvMeta.appendChild(rSpan);
      }
      main.appendChild(rvMeta);
    }
    row.appendChild(main);

    // 3. Explicit Inline Controls (Track Select + Up/Down + Index Link)
    var actions = document.createElement('div');
    actions.className = 'org-row-actions';

    var sel = document.createElement('select');
    sel.className = 'ctrl-sm org-track-select';
    sel.setAttribute('aria-label', '调整版本 ' + ver + ' 的归属');
    _targetOptions().forEach(function(opt) {
      var o = document.createElement('option');
      o.value = opt.value;
      o.textContent = opt.label;
      if (opt.value === groupKey) o.selected = true;
      sel.appendChild(o);
    });
    sel.addEventListener('change', function() {
      if (_moveVersion(ver, sel.value)) {
        render();
      } else {
        sel.value = groupKey;
      }
    });
    actions.appendChild(sel);

    if (groupKey !== '__review__' && groupKey !== '__excluded__') {
      var upBtn = document.createElement('button');
      upBtn.type = 'button';
      upBtn.className = 'ghost btn-xs org-step-btn';
      upBtn.setAttribute('aria-label', '上移版本 ' + ver);
      upBtn.title = '上移一位';
      upBtn.textContent = '↑';
      upBtn.disabled = (idx === 0);
      upBtn.addEventListener('click', function() { _stepVersion(ver, -1); });
      actions.appendChild(upBtn);

      var dnBtn = document.createElement('button');
      dnBtn.type = 'button';
      dnBtn.className = 'ghost btn-xs org-step-btn';
      dnBtn.setAttribute('aria-label', '下移版本 ' + ver);
      dnBtn.title = '下移一位';
      dnBtn.textContent = '↓';
      dnBtn.disabled = (idx === total - 1);
      dnBtn.addEventListener('click', function() { _stepVersion(ver, 1); });
      actions.appendChild(dnBtn);
    }

    var inspectBtn = document.createElement('button');
    inspectBtn.type = 'button';
    inspectBtn.className = 'ghost btn-xs';
    inspectBtn.textContent = (groupKey === '__review__') ? '看证据' : '文件';
    inspectBtn.title = '原地预览该版本文件清单与冲突命中证据（不打断当前草稿）';
    inspectBtn.addEventListener('click', function() { openInspector(ver); });
    actions.appendChild(inspectBtn);

    row.appendChild(actions);
    return row;
  }

  function _buildGroupCard(gKey) {
    var list = draftGroups[gKey] || [];
    var card = document.createElement('div');
    card.className = 'org-group' + (gKey === '__review__' && list.length ? ' org-group-warn' : '') + (gKey === '__excluded__' ? ' org-group-muted' : '');
    card.setAttribute('data-group-card', gKey);

    // Group drop target (for dropping into empty group or appending to end)
    card.addEventListener('dragover', function(e) {
      if (!dragState) return;
      e.preventDefault();
      card.classList.add('drop-group-over');
    });
    card.addEventListener('dragleave', function(e) {
      if (!card.contains(e.relatedTarget)) card.classList.remove('drop-group-over');
    });
    card.addEventListener('drop', function(e) {
      if (!dragState) return;
      e.preventDefault();
      card.classList.remove('drop-group-over');
      if (_moveVersion(dragState.ver, gKey)) {
        render();
      }
    });

    var head = document.createElement('div');
    head.className = 'org-group-head';
    var left = document.createElement('div');
    left.className = 'toolbar-group';

    var h3 = document.createElement('h3');
    h3.className = 'org-group-title';
    if (gKey !== '__review__' && gKey !== '__active__' && gKey !== '__excluded__') {
      h3.setAttribute('translate', 'no');
    }
    h3.textContent = _groupTitle(gKey);
    left.appendChild(h3);

    var cnt = document.createElement('span');
    cnt.className = 'chip num';
    cnt.textContent = list.length + ' 版';
    left.appendChild(cnt);

    // Runtime track status badge (Policy A visibility!)
    var stKey = (isMulti && gKey !== '__review__' && gKey !== '__excluded__') ? gKey : (gKey === '__active__' ? '__single__' : null);
    if (stKey && trackStatuses[stKey]) {
      var st = trackStatuses[stKey];
      var stTag = document.createElement('span');
      if (st.is_accepted) {
        stTag.className = 'tag tag-new tag-sm';
        stTag.textContent = '已采纳 ' + st.accepted_revision + ' · 受保护';
      } else if (st.has_history) {
        stTag.className = 'tag tag-updated tag-sm';
        stTag.textContent = '已建 ' + st.revision_count + ' 版 · 可归档重建';
      } else {
        stTag.className = 'tag tag-inherited tag-sm';
        stTag.textContent = '未建版';
      }
      left.appendChild(stTag);
    }
    head.appendChild(left);

    var rightHint = document.createElement('span');
    rightHint.className = 'muted text-xs';
    rightHint.textContent = (gKey === '__review__') ? '拖出或快捷归入目标轨道' : (gKey === '__excluded__' ? '拖入此处可排除' : '可拖拽 / ↑↓ 调整先后顺序');
    head.appendChild(rightHint);
    card.appendChild(head);

    var body = document.createElement('div');
    body.className = 'org-group-list';
    if (list.length === 0) {
      var empty = document.createElement('div');
      empty.className = 'org-group-empty';
      empty.textContent = (gKey === '__review__') ? '无待复核项，所有版本均已归类。' : '暂无版本（可拖拽版本行至此区域）。';
      body.appendChild(empty);
    } else {
      list.forEach(function(ver, idx) {
        body.appendChild(_buildRow(ver, gKey, idx, list.length));
      });
    }
    card.appendChild(body);
    return card;
  }

  function updateBatchBar() {
    var picked = Object.keys(selectedSet);
    if (!batchBar) return;
    if (picked.length === 0) {
      batchBar.hidden = true;
      return;
    }
    batchBar.hidden = false;
    if (batchCountEl) batchCountEl.textContent = '已选 ' + picked.length + ' 个版本';
    if (batchTargetSel && batchTargetSel.options.length === 0) {
      _targetOptions().forEach(function(opt) {
        var o = document.createElement('option');
        o.value = opt.value;
        o.textContent = opt.label;
        batchTargetSel.appendChild(o);
      });
    }
  }

  function updateDraftBar() {
    if (!draftBar) return;
    var diff = _computeDiffAndImpact();
    if (!diff.hasAnyChange) {
      draftBar.hidden = true;
      return;
    }
    draftBar.hidden = false;

    var parts = [];
    if (diff.assignedChanges) parts.push('归属变动 ' + diff.assignedChanges + ' 项');
    if (diff.reorderedCount) parts.push('顺序调整 ' + diff.reorderedCount + ' 组');
    if (diff.excludedChanges) parts.push('排除状态 ' + diff.excludedChanges + ' 项');
    if (!parts.length) parts.push('顺序或分组已调整');
    if (draftSummaryEl) draftSummaryEl.textContent = '待保存草稿：' + parts.join(' · ');

    if (draftImpactEl) {
      if (diff.protectedTracks.length > 0) {
        draftImpactEl.className = 'org-draft-impact impact-bad';
        draftImpactEl.textContent = '受保护提醒：' + diff.protectedTracks.map(function(x) { return x.label + ' (已采纳 ' + x.rev + ')'; }).join('、') + ' 禁止归档重建；如需重算请先回退人工采纳。';
      } else if (diff.rebuildable.length > 0) {
        draftImpactEl.className = 'org-draft-impact impact-warn';
        draftImpactEl.textContent = '触及已入版但未采纳轨道：' + diff.rebuildable.map(function(x) { return x.label; }).join('、') + '。可勾选右侧「归档重建」以按新顺序重算 L2/L3。';
      } else {
        draftImpactEl.className = 'org-draft-impact impact-ok';
        draftImpactEl.textContent = '仅涉及未入版/新增归属项，保存后自动执行安全 L2 + L3 增量刷新。';
      }
    }

    if (rebuildWrapEl && rebuildCheckEl) {
      if (diff.rebuildable.length > 0) {
        rebuildWrapEl.hidden = false;
        if (rebuildLabelEl) {
          rebuildLabelEl.textContent = '归档旧版并按新顺序重建 L2/L3（无损移入 archive/：' + diff.rebuildable.map(function(x) { return x.label; }).join('、') + '）';
        }
      } else {
        rebuildWrapEl.hidden = true;
        rebuildCheckEl.checked = false;
      }
    }
  }

  function closeContextMenu() {
    if (ctxMenu) ctxMenu.hidden = true;
    ctxTarget = null;
  }

  function openContextMenu(x, y, ver, groupKey, idx, total) {
    if (!ctxMenu) return;
    ctxTarget = {ver: ver, group: groupKey};
    ctxMenu.innerHTML = '';

    var title = document.createElement('div');
    title.className = 'org-ctx-head mono';
    title.setAttribute('translate', 'no');
    title.textContent = ver;
    ctxMenu.appendChild(title);

    _targetOptions().forEach(function(opt) {
      if (opt.value === groupKey) return;
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'org-ctx-item';
      btn.setAttribute('role', 'menuitem');
      btn.textContent = '移动到 → ' + opt.label;
      btn.addEventListener('click', function() {
        closeContextMenu();
        if (_moveVersion(ver, opt.value)) render();
      });
      ctxMenu.appendChild(btn);
    });

    if (groupKey !== '__review__' && groupKey !== '__excluded__') {
      var sep = document.createElement('div');
      sep.className = 'org-ctx-sep';
      ctxMenu.appendChild(sep);

      var up = document.createElement('button');
      up.type = 'button';
      up.className = 'org-ctx-item';
      up.setAttribute('role', 'menuitem');
      up.textContent = '上移一位 ↑';
      up.disabled = (idx === 0);
      up.addEventListener('click', function() { closeContextMenu(); _stepVersion(ver, -1); });
      ctxMenu.appendChild(up);

      var dn = document.createElement('button');
      dn.type = 'button';
      dn.className = 'org-ctx-item';
      dn.setAttribute('role', 'menuitem');
      dn.textContent = '下移一位 ↓';
      dn.disabled = (idx === total - 1);
      dn.addEventListener('click', function() { closeContextMenu(); _stepVersion(ver, 1); });
      ctxMenu.appendChild(dn);
    }

    var sep2 = document.createElement('div');
    sep2.className = 'org-ctx-sep';
    ctxMenu.appendChild(sep2);

    var prevBtn = document.createElement('button');
    prevBtn.type = 'button';
    prevBtn.className = 'org-ctx-item';
    prevBtn.setAttribute('role', 'menuitem');
    prevBtn.textContent = '原地预览文件与证据';
    prevBtn.addEventListener('click', function() { closeContextMenu(); openInspector(ver); });
    ctxMenu.appendChild(prevBtn);

    var link = document.createElement('a');
    link.className = 'org-ctx-item';
    link.setAttribute('role', 'menuitem');
    link.href = _indexUrl(ver, groupKey);
    link.textContent = '在新页打开文件索引 →';
    ctxMenu.appendChild(link);

    ctxMenu.hidden = false;
    var vw = window.innerWidth, vh = window.innerHeight;
    var mw = ctxMenu.offsetWidth || 220, mh = ctxMenu.offsetHeight || 220;
    ctxMenu.style.left = Math.max(8, Math.min(x, vw - mw - 12)) + 'px';
    ctxMenu.style.top = Math.max(8, Math.min(y, vh - mh - 12)) + 'px';
  }

  /* In-Place Slide-Over Evidence Inspector Drawer (Zero page reload, keeps draft alive!) */
  var drawerEl = document.getElementById('org-inspector-drawer');
  var drawerBackdrop = document.getElementById('org-inspector-backdrop');
  var drawerTitle = document.getElementById('org-drawer-title');
  var drawerBody = document.getElementById('org-drawer-body');
  var drawerCloseBtn = document.getElementById('org-drawer-close');
  var activeInspectorVer = null;

  function closeInspector() {
    if (drawerEl) drawerEl.hidden = true;
    if (drawerBackdrop) drawerBackdrop.hidden = true;
    activeInspectorVer = null;
  }

  var filesCacheLoaded = false;
  var filesCacheLoading = null;

  function _ensureFilesLoaded() {
    if (filesCacheLoaded) return Promise.resolve();
    if (filesCacheLoading) return filesCacheLoading;
    var url = '/api/v1/organizer?vendor=' + encodeURIComponent(initial.vendor) +
      '&library=' + encodeURIComponent(initial.library) + '&include_files=1';
    filesCacheLoading = fetch(url, {credentials: 'same-origin'})
      .then(function(r) { return r.ok ? r.json() : null; })
      .then(function(d) {
        if (!d) return;
        function _merge(list) {
          (list || []).forEach(function(item) {
            if (item && item.version && metaByVer[item.version]) {
              metaByVer[item.version].files_by_view = item.files_by_view || {};
              metaByVer[item.version].files_truncated = item.files_truncated || 0;
              if (item.evidence) metaByVer[item.version].evidence = item.evidence;
              if (item.trace) metaByVer[item.version].trace = item.trace;
            }
          });
        }
        if (d.mode === 'multi_track') {
          Object.keys(d.tracks || {}).forEach(function(ip) { _merge(d.tracks[ip]); });
          _merge(d.needs_review);
          _merge(d.excluded);
        } else {
          _merge(d.order);
          _merge(d.excluded);
        }
        filesCacheLoaded = true;
      })
      .catch(function() {})
      .finally(function() { filesCacheLoading = null; });
    return filesCacheLoading;
  }

  function openInspector(ver) {
    if (!drawerEl || !drawerBody) return;
    activeInspectorVer = ver;
    if (!filesCacheLoaded) {
      if (drawerTitle) drawerTitle.textContent = ver;
      drawerBody.innerHTML = '<div class="muted text-xs">正在加载交付文件清单与命中依据…</div>';
      drawerEl.hidden = false;
      if (drawerBackdrop) drawerBackdrop.hidden = false;
      _ensureFilesLoaded().then(function() {
        if (activeInspectorVer === ver) openInspector(ver);
      });
      return;
    }
    var m = metaByVer[ver] || {version: ver, file_count: 0, view_counts: {}, files_by_view: {}};
    var curGroup = _findGroup(ver) || '';
    if (drawerTitle) drawerTitle.textContent = ver;
    drawerBody.innerHTML = '';

    // 1. Status & Quick Assign Section
    var metaCard = document.createElement('div');
    metaCard.className = 'org-drawer-section';
    var metaLine = document.createElement('div');
    metaLine.className = 'toolbar-group';
    var gChip = document.createElement('span');
    gChip.className = 'chip chip-accent';
    gChip.textContent = '当前草稿分组：' + _groupTitle(curGroup);
    metaLine.appendChild(gChip);
    if (m.version_date) {
      var dChip = document.createElement('span');
      dChip.className = 'chip num';
      dChip.textContent = '目录日期 ' + m.version_date;
      metaLine.appendChild(dChip);
    }
    metaCard.appendChild(metaLine);

    if (m.root) {
      var pathRow = document.createElement('div');
      pathRow.className = 'org-drawer-path mono';
      pathRow.setAttribute('translate', 'no');
      pathRow.title = m.root;
      pathRow.textContent = m.root;
      metaCard.appendChild(pathRow);
    }

    var quickRow = document.createElement('div');
    quickRow.className = 'org-drawer-actions';
    var qLabel = document.createElement('span');
    qLabel.className = 'muted text-xs';
    qLabel.textContent = '快捷归入草稿：';
    quickRow.appendChild(qLabel);
    _targetOptions().forEach(function(opt) {
      var b = document.createElement('button');
      b.type = 'button';
      b.className = (opt.value === curGroup) ? 'btn-xs' : 'secondary btn-xs';
      b.textContent = opt.label;
      b.disabled = (opt.value === curGroup);
      b.addEventListener('click', function() {
        if (_moveVersion(ver, opt.value)) {
          render();
          openInspector(ver);
        }
      });
      quickRow.appendChild(b);
    });
    metaCard.appendChild(quickRow);
    drawerBody.appendChild(metaCard);

    // 2. Conflict / Auto-Trace Evidence Section
    if (m.reason || m.evidence || m.trace) {
      var evSec = document.createElement('div');
      evSec.className = 'org-drawer-section org-drawer-evidence';
      var evHead = document.createElement('div');
      evHead.className = 'org-drawer-sec-title';
      evHead.textContent = (m.review_kind === 'CONFLICT') ? '多命中冲突依据' : (m.trace ? '自动匹配依据' : '待复核说明');
      evSec.appendChild(evHead);

      if (m.reason) {
        var rP = document.createElement('p');
        rP.className = 'text-xs';
        rP.textContent = m.reason;
        evSec.appendChild(rP);
      }
      if (m.evidence && typeof m.evidence === 'object' && !Array.isArray(m.evidence)) {
        Object.keys(m.evidence).forEach(function(hitIp) {
          var box = document.createElement('div');
          box.className = 'org-ev-group';
          var strong = document.createElement('strong');
          strong.className = 'mono text-xs';
          strong.setAttribute('translate', 'no');
          strong.textContent = '命中 ' + hitIp + '：';
          box.appendChild(strong);
          var ul = document.createElement('ul');
          ul.className = 'org-ev-list mono';
          (m.evidence[hitIp] || []).forEach(function(fp) {
            var li = document.createElement('li');
            li.setAttribute('translate', 'no');
            li.textContent = fp;
            ul.appendChild(li);
          });
          box.appendChild(ul);
          evSec.appendChild(box);
        });
      } else if (m.trace && Array.isArray(m.trace.matched_by) && m.trace.matched_by.length) {
        var tUl = document.createElement('ul');
        tUl.className = 'org-ev-list mono';
        m.trace.matched_by.forEach(function(fp) {
          var li = document.createElement('li');
          li.setAttribute('translate', 'no');
          li.textContent = fp;
          tUl.appendChild(li);
        });
        evSec.appendChild(tUl);
      }
      drawerBody.appendChild(evSec);
    }

    // 3. View-Grouped File List with Instant Search
    var fileSec = document.createElement('div');
    fileSec.className = 'org-drawer-section';
    var fHead = document.createElement('div');
    fHead.className = 'org-drawer-file-head';
    var fTitle = document.createElement('span');
    fTitle.className = 'org-drawer-sec-title num';
    fTitle.textContent = '交付文件清单（共 ' + (m.file_count || 0) + ' 个）';
    fHead.appendChild(fTitle);
    var fullLink = document.createElement('a');
    fullLink.className = 'text-xs';
    fullLink.href = _indexUrl(ver, curGroup);
    fullLink.textContent = '完整索引页 →';
    fHead.appendChild(fullLink);
    fileSec.appendChild(fHead);

    var fSearch = document.createElement('input');
    fSearch.type = 'search';
    fSearch.className = 'ctrl-sm org-drawer-search';
    fSearch.placeholder = '过滤此版本内的文件名…';
    fSearch.setAttribute('aria-label', '过滤版本内文件');
    fileSec.appendChild(fSearch);

    var fListWrap = document.createElement('div');
    fListWrap.className = 'org-drawer-files';
    var fbv = m.files_by_view || {};
    var viewKeys = Object.keys(fbv);

    function renderFiles(qText) {
      fListWrap.innerHTML = '';
      var q = (qText || '').trim().toLowerCase();
      var shown = 0;
      viewKeys.forEach(function(vk) {
        var matches = (fbv[vk] || []).filter(function(fp) {
          return !q || fp.toLowerCase().indexOf(q) !== -1 || vk.toLowerCase().indexOf(q) !== -1;
        });
        if (!matches.length) return;
        shown += matches.length;
        var grp = document.createElement('div');
        grp.className = 'org-drawer-view-group';
        var vh = document.createElement('div');
        vh.className = 'org-drawer-view-head';
        vh.innerHTML = '<span class="chip" translate="no">' + vk + '</span><span class="muted text-xs num">' + matches.length + ' 项</span>';
        grp.appendChild(vh);
        var ul = document.createElement('ul');
        ul.className = 'org-ev-list mono';
        matches.forEach(function(fp) {
          var li = document.createElement('li');
          li.setAttribute('translate', 'no');
          li.textContent = fp;
          ul.appendChild(li);
        });
        grp.appendChild(ul);
        fListWrap.appendChild(grp);
      });
      if (shown === 0) {
        var empty = document.createElement('div');
        empty.className = 'muted text-xs';
        empty.textContent = '没有匹配的文件。';
        fListWrap.appendChild(empty);
      } else if (m.files_truncated > 0 && !q) {
        var more = document.createElement('div');
        more.className = 'muted text-xs mt-xs';
        more.textContent = '另有 ' + m.files_truncated + ' 个文件未完全展开，可点击右上角「完整索引页」查看全部。';
        fListWrap.appendChild(more);
      }
    }
    fSearch.addEventListener('input', function() { renderFiles(fSearch.value); });
    renderFiles('');
    fileSec.appendChild(fListWrap);
    drawerBody.appendChild(fileSec);

    drawerEl.hidden = false;
    if (drawerBackdrop) drawerBackdrop.hidden = false;
  }

  if (drawerCloseBtn) drawerCloseBtn.addEventListener('click', closeInspector);
  if (drawerBackdrop) drawerBackdrop.addEventListener('click', closeInspector);

  document.addEventListener('click', function(e) {
    if (ctxMenu && !ctxMenu.hidden && !ctxMenu.contains(e.target)) closeContextMenu();
  });
  document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') {
      closeContextMenu();
      closeInspector();
    }
  });
  window.addEventListener('scroll', closeContextMenu, true);

  function render() {
    boardEl.innerHTML = '';
    var keys = isMulti ? ['__review__'].concat(ipList, ['__excluded__']) : ['__active__', '__excluded__'];
    keys.forEach(function(k) {
      if (k === '__review__' && (draftGroups.__review__ || []).length === 0 && (savedGroups.__review__ || []).length === 0) {
        return;
      }
      if (k === '__excluded__' && (draftGroups.__excluded__ || []).length === 0 && (savedGroups.__excluded__ || []).length === 0) {
        // Still show compact dropzone if user drags, or show empty card so exclusion is discoverable
      }
      boardEl.appendChild(_buildGroupCard(k));
    });
    updateBatchBar();
    updateDraftBar();
  }

  // Bind toolbar controls
  var searchInp = document.getElementById('org-search-input');
  if (searchInp) {
    searchInp.addEventListener('input', function() {
      searchQuery = (searchInp.value || '').trim().toLowerCase();
      render();
    });
  }

  var batchApplyBtn = document.getElementById('org-batch-apply');
  if (batchApplyBtn) {
    batchApplyBtn.addEventListener('click', function() {
      var target = batchTargetSel ? batchTargetSel.value : '';
      if (!target) return;
      var moved = 0;
      Object.keys(selectedSet).forEach(function(ver) {
        if (_moveVersion(ver, target)) moved++;
      });
      selectedSet = {};
      if (moved > 0) showToast('已将 ' + moved + ' 个版本移入草稿「' + _groupTitle(target) + '」。', 'ok');
      render();
    });
  }

  var batchClearBtn = document.getElementById('org-batch-clear');
  if (batchClearBtn) {
    batchClearBtn.addEventListener('click', function() {
      selectedSet = {};
      render();
    });
  }

  var resetBtn = document.getElementById('org-reset-btn');
  if (resetBtn) {
    resetBtn.addEventListener('click', function() {
      draftGroups = _cloneSavedGroups();
      selectedSet = {};
      if (rebuildCheckEl) rebuildCheckEl.checked = false;
      render();
      showToast('已撤销全部未保存草稿。', 'ok');
    });
  }

  if (applyBtn) {
    applyBtn.addEventListener('click', function() {
      var diff = _computeDiffAndImpact();
      if (!diff.hasAnyChange) return;
      var rebuildList = [];
      if (rebuildCheckEl && rebuildCheckEl.checked && diff.rebuildable.length > 0) {
        rebuildList = diff.rebuildable.map(function(x) { return x.key; });
      }
      var body = {
        vendor: initial.vendor,
        library: initial.library,
        excluded: draftGroups.__excluded__ || [],
        rebuild_tracks: rebuildList,
        refresh: true
      };
      if (isMulti) {
        var tracksMap = {};
        ipList.forEach(function(ip) { tracksMap[ip] = draftGroups[ip] || []; });
        body.tracks = tracksMap;
      } else {
        body.order = draftGroups.__active__ || [];
      }

      applyBtn.disabled = true;
      var origLabel = applyBtn.textContent;
      applyBtn.textContent = '正在保存并刷新 L2/L3…';

      fetch('/api/v1/organizer/apply', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRF-Token': _csrf()
        },
        credentials: 'same-origin',
        body: JSON.stringify(body)
      })
        .then(function(r) { return r.json().then(function(d) { return {ok: r.ok, data: d}; }); })
        .then(function(res) {
          if (!res.ok) {
            applyBtn.disabled = false;
            applyBtn.textContent = origLabel;
            showToast((res.data && res.data.error) || '保存失败，请检查配置', 'bad');
            return;
          }
          var archCount = (res.data && res.data.archived_tracks) ? res.data.archived_tracks.length : 0;
          var msg = '已保存编排并完成 L2/L3 刷新' + (archCount ? ('（已无损归档重建 ' + archCount + ' 条轨道）') : '') + '，正在更新视图…';
          showToast(msg, 'ok');
          setTimeout(function() {
            window.location.hash = '#deliveries';
            window.location.reload();
          }, 550);
        })
        .catch(function(err) {
          applyBtn.disabled = false;
          applyBtn.textContent = origLabel;
          showToast('网络请求异常：' + String(err), 'bad');
        });
    });
  }

  render();
})();
