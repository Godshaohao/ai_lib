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
  document.querySelector("[data-select-all]")?.addEventListener("change", (event) => {
    document.querySelectorAll("[data-candidate]").forEach((checkbox) => {
      checkbox.checked = event.currentTarget.checked;
    });
  });
  selectTab(document.body.dataset.activeTab || "catalog", "main");
  selectTab("config", "review");
})();
