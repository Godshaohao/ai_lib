(() => {
  const tabs = [...document.querySelectorAll("[data-workbench-tab]")];
  const panels = [...document.querySelectorAll("[data-workbench-panel]")];

  function selectTab(name) {
    tabs.forEach((tab) => {
      const selected = tab.dataset.workbenchTab === name;
      tab.setAttribute("aria-selected", String(selected));
      tab.tabIndex = selected ? 0 : -1;
    });
    panels.forEach((panel) => {
      panel.hidden = panel.dataset.workbenchPanel !== name;
    });
  }

  tabs.forEach((tab, index) => {
    tab.addEventListener("click", () => selectTab(tab.dataset.workbenchTab));
    tab.addEventListener("keydown", (event) => {
      if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
      event.preventDefault();
      const nextIndex = event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1 :
        (index + (event.key === "ArrowRight" ? 1 : tabs.length - 1)) % tabs.length;
      tabs[nextIndex].focus();
      selectTab(tabs[nextIndex].dataset.workbenchTab);
    });
  });

  document.querySelectorAll("[data-check-card]").forEach((card) => {
    const checkbox = card.querySelector('summary input[type="checkbox"]');
    checkbox.addEventListener("change", () => {
      if (checkbox.checked) card.open = true;
    });
  });

  document.querySelector("[data-ip-search]")?.addEventListener("input", (event) => {
    const query = event.target.value.trim().toLocaleLowerCase();
    document.querySelectorAll("[data-ip-name]").forEach((item) => {
      item.hidden = !item.dataset.ipName.includes(query);
    });
  });

  document.querySelector("[data-open-config]")?.addEventListener("click", () => selectTab("config"));
  selectTab("config");
})();
