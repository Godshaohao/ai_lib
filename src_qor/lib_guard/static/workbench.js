(() => {
  const tabs = [...document.querySelectorAll("[data-workbench-tab]")];
  const panels = [...document.querySelectorAll("[data-workbench-panel]")];

  function selectTab(name, group = "main") {
    tabs.filter((tab) => (tab.dataset.tabGroup || "main") === group).forEach((tab) => {
      const selected = tab.dataset.workbenchTab === name;
      tab.setAttribute("aria-selected", String(selected));
      tab.tabIndex = selected ? 0 : -1;
    });
    panels.filter((panel) => (panel.dataset.tabGroup || "main") === group).forEach((panel) => {
      panel.hidden = panel.dataset.workbenchPanel !== name;
    });
  }

  tabs.forEach((tab) => {
    const group = tab.dataset.tabGroup || "main";
    tab.addEventListener("click", () => selectTab(tab.dataset.workbenchTab, group));
    tab.addEventListener("keydown", (event) => {
      if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
      event.preventDefault();
      const groupTabs = tabs.filter((item) => (item.dataset.tabGroup || "main") === group);
      const index = groupTabs.indexOf(tab);
      const nextIndex = event.key === "Home" ? 0 : event.key === "End" ? groupTabs.length - 1 :
        (index + (event.key === "ArrowRight" ? 1 : groupTabs.length - 1)) % groupTabs.length;
      groupTabs[nextIndex].focus();
      selectTab(groupTabs[nextIndex].dataset.workbenchTab, group);
    });
  });

  document.querySelectorAll("[data-check-card]").forEach((card) => {
    const checkbox = card.querySelector('summary input[type="checkbox"]');
    checkbox.addEventListener("click", (event) => event.stopPropagation());
    checkbox.addEventListener("change", () => {
      card.open = checkbox.checked;
    });
  });

  const sidebarEntries = [...document.querySelectorAll("[data-ip-entry]")];
  const sidebarSearch = document.querySelector("[data-ip-search]");
  const vendorFilter = document.querySelector("[data-vendor-filter]");
  const sidebarCount = document.querySelector("[data-sidebar-count]");
  let sidebarScope = "all";

  function applySidebarFilters() {
    const query = (sidebarSearch?.value || "").trim().toLocaleLowerCase();
    const vendor = (vendorFilter?.value || "").toLocaleLowerCase();
    let visibleCount = 0;

    sidebarEntries.forEach((entry) => {
      const scopeMatches = sidebarScope === "all" ||
        (sidebarScope === "raw" && entry.dataset.hasRaw === "true") ||
        (sidebarScope === "formal" && entry.dataset.hasFormal === "true");
      const matches = scopeMatches && entry.dataset.ipName.includes(query) &&
        (!vendor || entry.dataset.ipVendor === vendor);
      entry.hidden = !matches;
      if (matches) visibleCount += 1;
    });

    document.querySelectorAll("[data-vendor-heading]").forEach((heading) => {
      const headingVendor = heading.dataset.vendorName;
      const hasVisibleEntry = sidebarEntries.some((entry) =>
        entry.dataset.ipVendor === headingVendor && !entry.hidden);
      heading.hidden = !hasVisibleEntry;
    });
    if (sidebarCount) sidebarCount.textContent = `显示 ${visibleCount} / ${sidebarEntries.length} 个库`;
  }

  sidebarSearch?.addEventListener("input", applySidebarFilters);
  vendorFilter?.addEventListener("change", applySidebarFilters);
  document.querySelectorAll("[data-sidebar-scope]").forEach((button) => {
    button.addEventListener("click", () => {
      sidebarScope = button.dataset.sidebarScope;
      document.querySelectorAll("[data-sidebar-scope]").forEach((item) => {
        item.setAttribute("aria-pressed", String(item === button));
      });
      applySidebarFilters();
    });
  });
  applySidebarFilters();

  document.querySelector("[data-open-config]")?.addEventListener("click", () => {
    selectTab("review", "main");
    selectTab("config", "review");
  });
  document.querySelector("[data-main-tab]")?.addEventListener("click", (event) => {
    selectTab(event.currentTarget.dataset.mainTab, "main");
  });
  const discoveryRows = [...document.querySelectorAll("[data-discovery-row]")];
  const discoverySearch = document.querySelector("[data-discovery-search]");
  const discoveryVendor = document.querySelector("[data-discovery-vendor]");
  const discoveryView = document.querySelector("[data-discovery-view]");
  const discoveryState = document.querySelector("[data-discovery-state]");
  const discoveryCount = document.querySelector("[data-discovery-count]");
  function applyDiscoveryFilters() {
    const query = (discoverySearch?.value || "").trim().toLocaleLowerCase();
    const vendor = (discoveryVendor?.value || "").toLocaleLowerCase();
    const view = (discoveryView?.value || "").toLocaleLowerCase();
    const state = discoveryState?.value || "";
    let visible = 0;
    discoveryRows.forEach((row) => {
      const show = row.dataset.search.includes(query) && (!vendor || row.dataset.vendor === vendor) &&
        (!view || row.dataset.views.split(",").includes(view)) && (!state || row.dataset.state === state);
      row.hidden = !show;
      if (show) visible += 1;
    });
    if (discoveryCount) discoveryCount.textContent = `显示 ${visible} / ${discoveryRows.length} 个库`;
  }
  [discoverySearch, discoveryVendor, discoveryView, discoveryState].forEach((control) => {
    control?.addEventListener(control.tagName === "INPUT" ? "input" : "change", applyDiscoveryFilters);
  });
  applyDiscoveryFilters();

  function setVisibleChecks(selector, checked) {
    document.querySelectorAll(selector).forEach((checkbox) => {
      if (!checkbox.disabled && !checkbox.closest("tr")?.hidden && !checkbox.closest("[data-lib-row]")?.hidden) {
        checkbox.checked = checked;
        checkbox.dispatchEvent(new Event("change", { bubbles: true }));
      }
    });
  }
  document.querySelector("[data-select-visible]")?.addEventListener("click", () =>
    setVisibleChecks("[data-candidate]", true));
  document.querySelector("[data-clear-visible]")?.addEventListener("click", () =>
    setVisibleChecks("[data-candidate]", false));
  document.querySelector("[data-check-select-all]")?.addEventListener("click", () =>
    document.querySelectorAll('[data-review-form] input[name="checks"]').forEach((item) => {
      item.checked = true;
      item.dispatchEvent(new Event("change", { bubbles: true }));
    }));
  document.querySelector("[data-check-clear]")?.addEventListener("click", () =>
    document.querySelectorAll('[data-review-form] input[name="checks"]').forEach((item) => {
      item.checked = false;
      item.dispatchEvent(new Event("change", { bubbles: true }));
    }));
  document.querySelectorAll("[data-fill-input]").forEach((choice) => {
    choice.addEventListener("change", () => {
      const input = document.querySelector(`[name="${choice.dataset.fillInput}"]`);
      if (input && choice.value) {
        input.value = choice.value;
        input.dataset.inputSource = "从版本文件列表选择";
        input.dispatchEvent(new Event("input", { bubbles: true }));
      }
    });
  });
  const libertyInput = document.querySelector('[name="ll_liberty_files"]');
  const libertyRows = [...document.querySelectorAll("[data-lib-row]")];
  const libertySearch = document.querySelector("[data-lib-search]");
  const libertyCount = document.querySelector("[data-lib-count]");
  function syncLibertyInput(source = "从当前 RAW 文件列表勾选") {
    if (libertyInput) libertyInput.value = [...document.querySelectorAll("[data-lib-file]:checked")]
      .map((item) => item.value).join("\n");
    if (libertyInput) libertyInput.dataset.inputSource = source;
  }
  function applyLibertyFilter() {
    const query = (libertySearch?.value || "").trim().toLocaleLowerCase();
    let visible = 0;
    libertyRows.forEach((row) => {
      row.hidden = !row.dataset.libPath.includes(query);
      if (!row.hidden) visible += 1;
    });
    if (libertyCount) libertyCount.textContent = `显示 ${visible} / ${libertyRows.length} 个文件`;
  }
  libertySearch?.addEventListener("input", applyLibertyFilter);
  applyLibertyFilter();
  document.querySelector("[data-lib-select-visible]")?.addEventListener("click", () =>
    setVisibleChecks("[data-lib-file]", true));
  document.querySelector("[data-lib-clear-visible]")?.addEventListener("click", () =>
    setVisibleChecks("[data-lib-file]", false));
  document.querySelectorAll("[data-lib-file]").forEach((choice) => {
    choice.addEventListener("change", () => {
      syncLibertyInput();
      updateScopeSummary();
    });
  });
  libertyInput?.addEventListener("input", (event) => {
    document.querySelectorAll("[data-lib-file]").forEach((choice) => { choice.checked = false; });
    if (event.isTrusted) libertyInput.dataset.inputSource = "手工指定";
    updateScopeSummary();
  });

  const reviewForm = document.querySelector("[data-review-form]");
  const suggestedButton = document.querySelector("[data-apply-suggested-checks]");
  const suggestedPayload = document.querySelector("[data-suggested-checks]");
  const suggestionFeedback = document.querySelector("[data-suggestion-feedback]");
  const suggestedFields = {
    macro_index: { root: "macro_root", version: "macro_version", library_id: "macro_library_id" },
    lef_review: { old_file: "lef_old_file", new_file: "lef_new_file" },
    lef_liberty_check: { lef_file: "ll_lef_file" },
  };
  suggestedButton?.addEventListener("click", () => {
    let suggestions = {};
    try { suggestions = JSON.parse(suggestedPayload?.textContent || "{}"); } catch { suggestions = {}; }
    const applied = [];
    Object.entries(suggestions).forEach(([checkName, values]) => {
      const check = reviewForm?.querySelector(`input[name="checks"][value="${checkName}"]`);
      if (!check || !values) return;
      check.checked = true;
      check.dispatchEvent(new Event("change", { bubbles: true }));
      applied.push(check.closest("details")?.querySelector(".check-card-title strong")?.textContent || checkName);
      Object.entries(suggestedFields[checkName] || {}).forEach(([key, fieldName]) => {
        const input = reviewForm.querySelector(`[name="${fieldName}"]`);
        if (input && values[key]) {
          input.value = values[key];
          input.dataset.inputSource = "自动建议";
          input.dispatchEvent(new Event("input", { bubbles: true }));
        }
      });
      if (checkName === "lef_liberty_check" && Array.isArray(values.liberty_files)) {
        const choices = [...document.querySelectorAll("[data-lib-file]")];
        choices.forEach((choice) => { choice.checked = values.liberty_files.includes(choice.value); });
        if (choices.length && values.liberty_files.every((path) => choices.some((choice) => choice.value === path))) {
          syncLibertyInput("自动建议");
        } else if (libertyInput) {
          libertyInput.value = values.liberty_files.join("\n");
          libertyInput.dataset.inputSource = "自动建议";
        }
      }
    });
    if (suggestionFeedback) suggestionFeedback.textContent = applied.length
      ? `已填入并勾选：${applied.join("、")}。请核对范围后运行。`
      : "没有可填入的自动建议，请手动选择检查项。";
    updateScopeSummary();
  });

  const checkLabels = {
    formal_nl: "正式目录盘点", macro_index: "Macro / View 索引",
    lef_review: "LEF 双文件核查", lef_liberty_check: "LEF–Liberty 接口核查",
  };
  const scopeTarget = document.querySelector("[data-scope-target]");
  const scopeBase = document.querySelector("[data-scope-base]");
  const scopeSummary = document.querySelector("[data-run-scope-summary]");
  function addScopeFile(container, label, path, source = "") {
    const row = document.createElement("div");
    const title = document.createElement("span");
    const value = document.createElement("code");
    const normalized = String(path || "").trim();
    const names = normalized.split(/\r?\n/).map((item) => item.trim()).filter(Boolean)
      .map((item) => item.split(/[\\/]/).filter(Boolean).pop());
    title.textContent = label;
    value.textContent = names.length ? names.join("、") : "未指定";
    if (normalized) value.title = normalized;
    row.append(title, value);
    if (source) {
      const origin = document.createElement("small");
      origin.className = "scope-source";
      origin.textContent = `来源：${source}`;
      row.append(origin);
    }
    container.append(row);
  }
  function updateScopeSummary() {
    if (!scopeSummary) return;
    const selectedChecks = [...(reviewForm?.querySelectorAll('input[name="checks"]:checked') || [])];
    const target = scopeTarget?.value
      ? scopeTarget.selectedOptions[0]?.textContent
      : (reviewForm?.querySelector('[name="raw_version"]')?.value || "未选择");
    const base = scopeBase?.selectedOptions[0]?.textContent || "不比较版本差异";
    const targetNode = scopeSummary.querySelector("[data-scope-target-label]");
    const baseNode = scopeSummary.querySelector("[data-scope-base-label]");
    const checksNode = scopeSummary.querySelector("[data-scope-checks]");
    const filesNode = scopeSummary.querySelector("[data-scope-files]");
    if (targetNode) targetNode.textContent = target || "未选择";
    if (baseNode) baseNode.textContent = base || "不比较版本差异";
    if (checksNode) checksNode.textContent = selectedChecks.length
      ? selectedChecks.map((item) => checkLabels[item.value] || item.value).join("、") : "尚未选择";
    if (!filesNode) return;
    filesNode.replaceChildren();
    if (!selectedChecks.length) {
      filesNode.textContent = "选择检查项后显示文件范围。";
      return;
    }
    const append = (label, field, fallbackSource = "手工指定") => {
      const input = reviewForm?.querySelector(`[name="${field}"]`);
      if (input?.value.trim()) addScopeFile(filesNode, label, input.value.trim(), input.dataset.inputSource || fallbackSource);
    };
    selectedChecks.forEach((item) => {
      if (item.value === "formal_nl") append("正式目录配置", "formal_config");
      if (item.value === "macro_index") append("RAW 根目录", "macro_root", "所选 RAW 版本");
      if (item.value === "lef_review") {
        append("基准 LEF", "lef_old_file");
        append("目标 LEF", "lef_new_file");
      }
      if (item.value === "lef_liberty_check") {
        if (selectedChecks.some((selected) => selected.value === "lef_review")) {
          append("LEF（复用目标 LEF）", "lef_new_file");
        } else {
          append("LEF", "ll_lef_file", "所选 RAW 版本");
        }
        const paths = (libertyInput?.value || "").split(/\r?\n/).map((path) => path.trim()).filter(Boolean);
        if (paths.length) addScopeFile(filesNode, `Liberty（${paths.length} 个）`, paths.join("\n"), libertyInput?.dataset.inputSource || "所选 RAW 版本");
        else addScopeFile(filesNode, "Liberty", "", "尚未选择");
      }
    });
    if (!filesNode.childElementCount) filesNode.textContent = "部分文件尚未选择；展开对应检查项补齐。";
  }
  scopeTarget?.addEventListener("change", updateScopeSummary);
  scopeBase?.addEventListener("change", updateScopeSummary);
  reviewForm?.addEventListener("input", updateScopeSummary);
  reviewForm?.addEventListener("change", updateScopeSummary);
  reviewForm?.querySelectorAll("[data-scope-source-input]").forEach((input) => {
    input.addEventListener("input", (event) => {
      if (event.isTrusted) input.dataset.inputSource = "手工指定";
      updateScopeSummary();
    });
  });
  updateScopeSummary();
  const formalLibrarySearch = document.querySelector("[data-formal-library-search]");
  const formalLibraryRows = [...document.querySelectorAll("[data-formal-library-row]")];
  const formalLibraryCount = document.querySelector("[data-formal-library-count]");
  const formalFileSearch = document.querySelector("[data-formal-file-search]");
  const formalViewFilter = document.querySelector("[data-formal-view-filter]");
  const formalFilesDisclosure = document.querySelector("[data-formal-files]");
  const formalFileContent = document.querySelector("[data-formal-file-content]");
  const formalFileCount = document.querySelector("[data-formal-file-count]");
  let formalFileRows = [...document.querySelectorAll("[data-formal-file-row]")];
  let formalFilesLoaded = formalFileRows.length > 0;
  function filterFormalInventory() {
    const libraryQuery = (formalLibrarySearch?.value || "").trim().toLocaleLowerCase();
    let visibleLibraries = 0;
    formalLibraryRows.forEach((row) => {
      row.hidden = !row.dataset.search.includes(libraryQuery);
      if (!row.hidden) visibleLibraries += 1;
    });
    if (formalLibraryCount) formalLibraryCount.textContent = `${visibleLibraries} 个来源 IP`;

    const fileQuery = (formalFileSearch?.value || "").trim().toLocaleLowerCase();
    const view = formalViewFilter?.value || "";
    let visibleFiles = 0;
    formalFileRows.forEach((row) => {
      row.hidden = !row.dataset.search.includes(fileQuery) || (view && row.dataset.view !== view);
      if (!row.hidden) visibleFiles += 1;
    });
    if (formalFileCount) formalFileCount.textContent = `${visibleFiles} 条`;
  }
  function textCell(row, value, className = "") {
    const cell = document.createElement("td");
    if (className) cell.className = className;
    const text = document.createElement(className === "path-cell" ? "code" : "span");
    text.textContent = value || "—";
    cell.append(text);
    return cell;
  }
  function renderFormalFiles(files) {
    const wrapper = document.createElement("div");
    wrapper.className = "table-wrap formal-overview-file-wrap";
    const table = document.createElement("table");
    const head = document.createElement("thead");
    const heading = document.createElement("tr");
    ["阶段", "来源 IP", "RAW 版本", "View", "正式路径", "RAW 来源路径"].forEach((value) => {
      const cell = document.createElement("th");
      cell.textContent = value;
      heading.append(cell);
    });
    head.append(heading);
    const body = document.createElement("tbody");
    files.forEach((file) => {
      const row = document.createElement("tr");
      row.dataset.formalFileRow = "";
      row.dataset.view = file.view || "other";
      row.dataset.search = [file.stage, file.vendor, file.middle_path, file.library_name,
        file.raw_version, file.relative_path, file.published_path, file.source_path]
        .join(" ").toLocaleLowerCase();
      row.append(
        textCell(row, file.stage),
        textCell(row, [file.vendor, file.middle_path, file.library_name].filter(Boolean).join(" / ")),
        textCell(row, file.raw_version),
        textCell(row, String(file.view || "other").toUpperCase()),
        textCell(row, file.published_path, "path-cell"),
        textCell(row, file.source_path, "path-cell"),
      );
      body.append(row);
    });
    table.append(head, body);
    wrapper.append(table);
    formalFileContent.replaceChildren(wrapper);
    formalFileRows = [...formalFileContent.querySelectorAll("[data-formal-file-row]")];
    formalFilesLoaded = true;
    filterFormalInventory();
  }
  formalFilesDisclosure?.addEventListener("toggle", async () => {
    if (!formalFilesDisclosure.open || formalFilesLoaded) return;
    formalFileContent.textContent = "正在读取已保存的正式目录快照…";
    try {
      const response = await fetch(formalFilesDisclosure.dataset.filesUrl, { headers: { Accept: "application/json" } });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || `读取失败 (${response.status})`);
      renderFormalFiles(payload.files || []);
    } catch (error) {
      formalFileContent.textContent = `${error.message} 请刷新正式目录后重试。`;
    }
  });
  formalLibrarySearch?.addEventListener("input", filterFormalInventory);
  formalFileSearch?.addEventListener("input", filterFormalInventory);
  formalViewFilter?.addEventListener("change", filterFormalInventory);
  const taskBanner = document.querySelector("[data-review-task]");
  if (taskBanner) {
    const statusNode = taskBanner.querySelector("[data-task-status]");
    const messageNode = taskBanner.querySelector("[data-task-message]");
    const stageNode = taskBanner.querySelector("[data-task-stage]");
    const elapsedNode = taskBanner.querySelector("[data-task-elapsed]");
    const progressNode = taskBanner.querySelector("[data-task-progress]");
    const eventList = taskBanner.querySelector("[data-task-events]");
    const eventCount = taskBanner.querySelector("[data-task-event-count]");
    const statusLabels = { QUEUED: "排队中", RUNNING: "运行中", COMPLETE: "已完成", FAILED: "失败", INTERRUPTED: "已中断" };
    const renderElapsed = (task) => {
      const start = Date.parse(task.started_at || taskBanner.dataset.taskStartedAt || task.submitted_at || taskBanner.dataset.taskSubmittedAt);
      const end = Date.parse(task.finished_at || taskBanner.dataset.taskFinishedAt) || Date.now();
      if (elapsedNode && Number.isFinite(start)) elapsedNode.textContent = `用时：${Math.max(0, (end - start) / 1000).toFixed(1)} 秒`;
    };
  reviewForm?.querySelectorAll("[data-scope-source-input]").forEach((input) => {
    input.addEventListener("input", (event) => {
      if (event.isTrusted) input.dataset.inputSource = "手工指定";
    });
  });
    const renderEvents = (events = []) => {
      if (!eventList) return;
      const rows = events.slice(-12);
      eventList.replaceChildren();
      rows.forEach((event) => {
        const row = document.createElement("li");
        const time = document.createElement("time");
        const text = document.createElement("span");
        const parsed = Date.parse(event.at || "");
        time.textContent = Number.isFinite(parsed) ? new Date(parsed).toLocaleTimeString() : "";
        text.textContent = event.message || "";
        row.append(time, text);
        eventList.append(row);
      });
      if (eventCount) eventCount.textContent = `${rows.length} 条`;
    };
    const renderTask = (task) => {
      const status = String(task.status || "");
      statusNode.textContent = statusLabels[status] || status;
      messageNode.textContent = task.error || task.progress_message ||
        (task.execution_status && task.execution_status !== "PENDING" ? `检查结论：${task.execution_status}` : "等待任务状态");
      stageNode.textContent = `阶段：${task.phase || (status === "QUEUED" ? "排队中" : "状态待更新")}`;
      taskBanner.classList.toggle("is-running", ["QUEUED", "RUNNING"].includes(status));
      taskBanner.classList.toggle("is-failed", ["FAILED", "INTERRUPTED"].includes(status));
      taskBanner.classList.toggle("is-finished", status === "COMPLETE");
      progressNode?.classList.toggle("is-indeterminate", status === "RUNNING");
      renderElapsed(task);
      renderEvents(task.events || []);
    };
    renderElapsed({});
    const initiallyActive = ["排队中", "运行中", "QUEUED", "RUNNING"].includes(statusNode.textContent.trim());
    if (initiallyActive) window.setInterval(() => renderElapsed({}), 1000);
    if (!initiallyActive) {
      renderEvents([...eventList.querySelectorAll("li")].map((row) => ({
        at: row.querySelector("time")?.textContent,
        message: row.querySelector("span")?.textContent,
      })));
    } else {
    const poll = async () => {
      try {
        const response = await fetch(taskBanner.dataset.taskUrl, { headers: { Accept: "application/json" } });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const task = await response.json();
        renderTask(task);
        if (["COMPLETE", "FAILED"].includes(task.status)) {
          window.setTimeout(() => window.location.reload(), 700);
          return;
        }
      } catch (error) {
        messageNode.textContent = `状态暂不可用，稍后重试（${error.message}）`;
      }
      window.setTimeout(poll, 1500);
    };
    window.setTimeout(poll, 700);
    }
  }
  selectTab(document.body.dataset.activeTab || "catalog", "main");
  selectTab("config", "review");
})();
