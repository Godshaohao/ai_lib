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
    checkbox.addEventListener("change", () => {
      if (checkbox.checked) card.open = true;
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

      entry.querySelectorAll("[data-source-kind]").forEach((group) => {
        group.hidden = sidebarScope !== "all" && group.dataset.sourceKind !== sidebarScope;
      });
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
      if (input && choice.value) input.value = choice.value;
    });
  });
  const libertyInput = document.querySelector('[name="ll_liberty_files"]');
  const libertyRows = [...document.querySelectorAll("[data-lib-row]")];
  const libertySearch = document.querySelector("[data-lib-search]");
  const libertyCount = document.querySelector("[data-lib-count]");
  function syncLibertyInput() {
    if (libertyInput) libertyInput.value = [...document.querySelectorAll("[data-lib-file]:checked")]
      .map((item) => item.value).join("\n");
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
    });
  });
  const taskBanner = document.querySelector("[data-review-task]");
  if (taskBanner && ["QUEUED", "RUNNING"].includes(taskBanner.querySelector("[data-task-status]")?.textContent.trim())) {
    const statusNode = taskBanner.querySelector("[data-task-status]");
    const detailNode = taskBanner.querySelector("[data-task-detail]");
    const poll = async () => {
      try {
        const response = await fetch(taskBanner.dataset.taskUrl, { headers: { Accept: "application/json" } });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const task = await response.json();
        statusNode.textContent = task.status;
        detailNode.textContent = task.error || (task.execution_status ? `检查结论：${task.execution_status}` : "正在等待运行结果");
        if (["COMPLETE", "FAILED"].includes(task.status)) {
          window.setTimeout(() => window.location.reload(), 700);
          return;
        }
      } catch (error) {
        detailNode.textContent = `状态暂不可用，稍后重试（${error.message}）`;
      }
      window.setTimeout(poll, 1500);
    };
    window.setTimeout(poll, 700);
  }
  selectTab(document.body.dataset.activeTab || "catalog", "main");
  selectTab("config", "review");
})();
