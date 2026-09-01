#!/usr/bin/env node

/* Repeatable desktop smoke test for generated Version Detail HTML. */
const fs = require("fs");
const os = require("os");
const path = require("path");

function usage(message) {
  if (message) console.error(`ERROR: ${message}`);
  console.error("用法: node scripts/validate_version_detail_browser.cjs <index.html> [<index.html> ...] [--scenario 名称=路径 ...] [--out <目录>]");
  process.exit(2);
}

function parseArgs(argv) {
  const pages = [];
  const scenarios = [];
  let outDir = path.resolve("work/browser_validation");
  for (let i = 0; i < argv.length; i += 1) {
    if (argv[i] === "--out") {
      if (!argv[i + 1]) usage("--out 缺少目录");
      outDir = path.resolve(argv[++i]);
    } else if (argv[i] === "--scenario") {
      const value = argv[++i];
      if (!value || !value.includes("=")) usage("--scenario 格式应为 名称=页面路径");
      const separator = value.indexOf("=");
      const name = value.slice(0, separator).trim();
      const page = value.slice(separator + 1).trim();
      if (!name || !page) usage("--scenario 缺少名称或页面路径");
      scenarios.push({ name, page: path.resolve(page) });
    } else if (argv[i].startsWith("-")) {
      usage(`未知参数: ${argv[i]}`);
    } else {
      pages.push(path.resolve(argv[i]));
    }
  }
  const entries = [
    ...pages.map((page) => ({ name: "", page })),
    ...scenarios,
  ];
  if (!entries.length) usage("至少指定一个 Version Detail index.html 或 --scenario");
  return { entries, outDir };
}

function loadPlaywright() {
  const candidates = [
    process.env.LG_PLAYWRIGHT_CORE,
    "/tmp/lib_guard_playwright/node_modules/playwright-core",
    "playwright-core",
  ].filter(Boolean);
  for (const candidate of candidates) {
    try {
      return require(candidate);
    } catch (_error) {
      // Try the next configured location.
    }
  }
  usage("找不到 playwright-core；先执行 npm install --prefix /tmp/lib_guard_playwright playwright-core@latest");
}

function browserPath() {
  const candidates = [
    process.env.LG_CHROME_PATH,
    "/opt/google/chrome/chrome",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
  ].filter(Boolean);
  const executable = candidates.find((item) => fs.existsSync(item));
  if (!executable) usage("找不到 Chrome/Chromium；设置 LG_CHROME_PATH 指向浏览器可执行文件");
  return executable;
}

function pageKey(pagePath) {
  const parts = pagePath.split(path.sep);
  const version = parts[parts.length - 2] === "index.html" ? parts[parts.length - 3] : path.basename(path.dirname(pagePath));
  const libraryIndex = parts.lastIndexOf("libraries");
  const library = libraryIndex >= 0 ? parts[libraryIndex + 1] : "version-detail";
  return `${library}__${version}`.replace(/[^A-Za-z0-9_.-]+/g, "_");
}

async function visibleTreeFiles(page) {
  return page.evaluate(() => [...document.querySelectorAll(".tree-file")]
    .filter((item) => !item.classList.contains("tree-hidden") && item.offsetParent !== null).length);
}

function businessExpectation(name, text) {
  const checks = {
    first_version: [/首版/, /首版交付|自身/],
    normal_full_update: [/视图变化矩阵/, /有变化|有更新/],
    missing_required_view: [/必需视图|必需 View/, /不可接入|缺失/],
    missing_diff: [/尚未生成对比|对比证据尚未完成/, /生成可信对比|下一步/],
    adjacent_fallback: [/相邻上一版回退|相邻上一版|相邻版本/],
    unknown_package: [/未知/, /待分类|包类型/],
    full_fix_doc: [/FULL/, /FIX|DOC|组合/],
    stale_evidence: [/过期/, /证据|扫描/],
  }[name];
  if (!checks) return { required: false, passed: true, details: [] };
  const details = checks.map((pattern) => ({ pattern: pattern.source, passed: pattern.test(text) }));
  return { required: true, passed: details.every((item) => item.passed), details };
}

async function runPage(browser, pagePath, outDir, scenarioName = "") {
  if (!fs.existsSync(pagePath)) throw new Error(`页面不存在: ${pagePath}`);
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 });
  const page = await context.newPage();
  await page.goto(`file://${pagePath}`, { waitUntil: "load" });
  await page.waitForTimeout(200);

  const result = {
    page: pagePath,
    scenario: scenarioName || undefined,
    title: await page.title(),
    tables: await page.locator("table").count(),
    headings: await page.locator("h1,h2,h3").allTextContents(),
    screenshot: path.join(outDir, `${pageKey(pagePath)}.png`),
  };
  result.hasDecision = (await page.locator("text=判断摘要").count()) > 0;
  result.hasNextAction = (await page.locator("[data-next-action='true']").count()) > 0;
  result.hasFileTree = (await page.locator("[data-file-tree], .file-tree").count()) > 0;
  result.hasViewMatrix = (await page.locator(".view-delta-table").count()) > 0;
  result.hasViewDeltaFilters = (await page.locator("[data-view-delta-filter]").count()) > 0;
  const semanticSections = [
    "decision-summary", "comparison-context", "impact-summary", "view-delta",
    "focus-files", "file-structure", "review-report", "evidence-status",
  ];
  result.semanticSections = {};
  for (const section of semanticSections) {
    result.semanticSections[section] = (await page.locator(`[data-section="${section}"]`).count()) > 0;
  }
  result.hasReviewReport = result.semanticSections["review-report"];
  result.reviewReportInitiallyClosed = result.hasReviewReport
    ? (await page.locator('[data-section="review-report"]').getAttribute("open")) === null
    : false;
  if (result.hasReviewReport) {
    await page.locator('[data-section="review-report"] summary').click();
    result.reviewReportOpens = (await page.locator('[data-section="review-report"]').getAttribute("open")) !== null;
    await page.locator('[data-section="review-report"] summary').click();
    result.reviewReportCloses = (await page.locator('[data-section="review-report"]').getAttribute("open")) === null;
  } else {
    result.reviewReportOpens = false;
    result.reviewReportCloses = false;
  }
  await page.screenshot({ path: result.screenshot, fullPage: true });

  const checks = [
    result.hasDecision, result.hasNextAction, result.hasFileTree, result.hasViewMatrix,
    !result.hasViewMatrix || result.hasViewDeltaFilters,
    ...Object.values(result.semanticSections),
    result.reviewReportInitiallyClosed, result.reviewReportOpens, result.reviewReportCloses,
  ];
  if (result.hasFileTree) {
    result.treeFiles = await page.locator(".tree-file").count();
    result.treeChangeStatusCount = await page.locator('.tree-file[data-tree-status="added"], .tree-file[data-tree-status="removed"], .tree-file[data-tree-status="changed"]').count();
    result.treeDefaultFilter = await page.locator("[data-file-tree]").getAttribute("data-tree-filter");
    result.treeInitialVisible = await visibleTreeFiles(page);
    await page.locator('.tree-filter-chip[data-tree-filter="all"]').click();
    result.treeAllVisible = await visibleTreeFiles(page);
    const treeViewFilter = page.locator("#file-tree-view-filter");
    const treeAreaFilter = page.locator("#file-tree-area-filter");
    const treeChangeFilter = page.locator("#file-tree-change-filter");
    result.treeViewOptionCount = await treeViewFilter.locator("option").count();
    result.treeAreaOptionCount = await treeAreaFilter.locator("option").count();
    result.treeChangeOptionCount = await treeChangeFilter.locator("option").count();
    if (result.treeViewOptionCount > 1) {
      await treeViewFilter.selectOption({ index: 1 });
      await page.waitForTimeout(50);
      result.treeViewVisible = await visibleTreeFiles(page);
    } else {
      result.treeViewVisible = result.treeAllVisible;
    }
    if (result.treeAreaOptionCount > 1) {
      await treeAreaFilter.selectOption({ index: 1 });
      await page.waitForTimeout(50);
      result.treeAreaVisible = await visibleTreeFiles(page);
    } else {
      result.treeAreaVisible = result.treeViewVisible;
    }
    if (result.treeChangeOptionCount > 1) {
      await treeChangeFilter.selectOption({ index: 1 });
      await page.waitForTimeout(50);
      result.treeChangeVisible = await visibleTreeFiles(page);
    } else {
      result.treeChangeVisible = result.treeAreaVisible;
    }
    await page.locator("[data-tree-reset]").click();
    await page.waitForTimeout(50);
    result.treeAfterResetVisible = await visibleTreeFiles(page);
    await page.locator('.tree-filter-chip[data-tree-filter="current"]').click();
    result.treeCurrentVisible = await visibleTreeFiles(page);
    result.treeCurrentStatusCount = await page.locator('.tree-file:not([data-tree-status="removed"])').count();
    await page.locator('.tree-filter-chip[data-tree-filter="changes"]').click();
    result.treeVisibleLabelAfterChanges = (await page.locator("#file-tree-visible").textContent()).trim();
    await page.locator('.tree-filter-chip[data-tree-filter="all"]').click();
    const treeSearch = page.locator("#file-tree-search");
    const firstTitle = await page.locator(".tree-file code").first().getAttribute("title");
    result.treeSearchQuery = firstTitle ? firstTitle.split("/").pop().slice(0, 8) : "lef";
    await treeSearch.fill(result.treeSearchQuery);
    await page.waitForTimeout(50);
    result.treeSearchVisible = await visibleTreeFiles(page);
    await treeSearch.fill("");
    const collapse = page.getByRole("button", { name: "全部收起" });
    const expand = page.getByRole("button", { name: "全部展开" });
    await collapse.click();
    result.openDetailsAfterCollapse = await page.locator("[data-file-tree] details[open]").count();
    await expand.click();
    result.openDetailsAfterExpand = await page.locator("[data-file-tree] details[open]").count();
    checks.push(
      result.treeInitialVisible === (result.treeDefaultFilter === "current" ? result.treeCurrentStatusCount : result.treeChangeStatusCount),
      result.treeAllVisible === result.treeFiles,
      result.treeViewOptionCount >= 1,
      result.treeAreaOptionCount >= 1,
      result.treeChangeOptionCount >= 1,
      result.treeViewVisible >= 0 && result.treeViewVisible <= result.treeAllVisible,
      result.treeAreaVisible >= 0 && result.treeAreaVisible <= result.treeViewVisible,
      result.treeChangeVisible >= 0 && result.treeChangeVisible <= result.treeAllVisible,
      result.treeAfterResetVisible === result.treeAllVisible,
      result.treeCurrentVisible === result.treeCurrentStatusCount,
      result.treeSearchVisible > 0,
      result.openDetailsAfterCollapse === 0,
      result.openDetailsAfterExpand > 0,
    );
  }

  if (result.hasViewDeltaFilters) {
    const filterRoot = page.locator("[data-view-delta-filter]").first();
    const viewRows = page.locator(".view-delta-table tbody tr[data-view-type]");
    result.viewDeltaRows = await viewRows.count();
    result.viewDeltaInitialCount = (await filterRoot.locator("[data-view-delta-count]").textContent()).trim();
    const addedFilter = filterRoot.locator("[data-change-filter]");
    await addedFilter.selectOption("added");
    await page.waitForTimeout(50);
    result.viewDeltaAddedRows = await page.locator(".view-delta-table tbody tr[data-view-type]:not([hidden])").count();
    result.viewDeltaAddedCount = (await filterRoot.locator("[data-view-delta-count]").textContent()).trim();
    const search = filterRoot.locator("[data-view-search]");
    await addedFilter.selectOption("all");
    await search.fill("LEF");
    await page.waitForTimeout(50);
    result.viewDeltaSearchRows = await page.locator(".view-delta-table tbody tr[data-view-type]:not([hidden])").count();
    await filterRoot.locator("[data-reset-view-delta]").click();
    await page.waitForTimeout(50);
    result.viewDeltaResetRows = await page.locator(".view-delta-table tbody tr[data-view-type]:not([hidden])").count();
    result.viewDeltaCanBeEmpty = result.viewDeltaRows === 0
      ? (await page.locator("text=对比证据尚未完成").count()) > 0
      : true;
    checks.push(
      result.viewDeltaCanBeEmpty,
      result.viewDeltaAddedRows >= 0 && result.viewDeltaAddedRows <= result.viewDeltaRows,
      result.viewDeltaAddedCount.includes("显示"),
      result.viewDeltaSearchRows >= 0 && result.viewDeltaSearchRows <= result.viewDeltaRows,
      result.viewDeltaResetRows === result.viewDeltaRows,
    );
  }

  const focusDetails = page.locator("details.detail-fold.review-fold").first();
  if (await focusDetails.count()) {
    result.focusInitiallyOpen = await focusDetails.getAttribute("open");
    await focusDetails.locator("summary").click();
    const tableSearch = page.locator("#tbl-focus-change-scroll-search");
    result.tableSearchVisible = await tableSearch.isVisible();
    const rowsBefore = await page.locator("#tbl-focus-change-scroll tbody tr").count();
    const cellText = ((await page.locator("#tbl-focus-change-scroll tbody tr td").first().textContent()) || "新增").trim();
    const focusHasDataRows = rowsBefore > 0 && !cellText.includes("暂无重点变化文件");
    result.tableSearchQuery = cellText.split(/\s+/)[0].slice(0, 12);
    await tableSearch.fill(result.tableSearchQuery);
    await page.waitForTimeout(50);
    result.tableRowsBefore = rowsBefore;
    result.tableRowsAfter = await page.evaluate(() => [...document.querySelectorAll("#tbl-focus-change-scroll tbody tr")]
      .filter((item) => !item.classList.contains("is-hidden-by-filter") && !item.hidden && item.offsetParent !== null).length);
    checks.push(
      result.focusInitiallyOpen === null,
      result.tableSearchVisible,
      focusHasDataRows ? result.tableRowsAfter > 0 && result.tableRowsAfter <= rowsBefore : result.tableRowsAfter === 0,
    );
  }

  const collapsible = page.locator("details.panel.collapsible").first();
  if (await collapsible.count()) {
    result.collapsibleInitiallyOpen = await collapsible.getAttribute("open");
    await collapsible.locator("summary").click();
    result.collapsibleOpenAfterClick = await collapsible.getAttribute("open");
    await collapsible.locator("summary").click();
    result.collapsibleOpenAfterSecondClick = await collapsible.getAttribute("open");
    checks.push(result.collapsibleInitiallyOpen === null, result.collapsibleOpenAfterClick !== null, result.collapsibleOpenAfterSecondClick === null);
  }

  result.horizontalScroll = await page.evaluate(() => {
    const item = document.querySelector(".view-delta-scroll");
    if (!item) return { exists: false };
    const before = { scrollWidth: item.scrollWidth, clientWidth: item.clientWidth };
    item.scrollLeft = item.scrollWidth;
    return { exists: true, ...before, afterScrollLeft: item.scrollLeft, overflow: item.scrollWidth > item.clientWidth };
  });
  // The compact matrix should fit in the primary column. If unusually long
  // labels force overflow, the container must still provide usable scrolling.
  checks.push(
    result.horizontalScroll.exists
      && (!result.horizontalScroll.overflow || result.horizontalScroll.afterScrollLeft > 0),
  );
  if (scenarioName && result.hasReviewReport && result.reviewReportInitiallyClosed) {
    await page.locator('[data-section="review-report"] summary').click();
    await page.waitForTimeout(50);
  }
  const reportFocusScroll = page.locator("[data-focus-scroll='true']").first();
  if (await reportFocusScroll.count()) {
    result.reportFocusScroll = await reportFocusScroll.evaluate((item) => {
      const style = window.getComputedStyle(item);
      return {
        maxHeight: style.maxHeight,
        overflowY: style.overflowY,
        scrollable: item.scrollHeight >= item.clientHeight,
      };
    });
    checks.push(
      result.reportFocusScroll.maxHeight !== "none",
      ["auto", "scroll"].includes(result.reportFocusScroll.overflowY),
    );
  }
  result.business = businessExpectation(scenarioName, await page.locator("body").innerText());
  if (result.business.required) checks.push(result.business.passed);
  result.assertions = { passed: checks.filter(Boolean).length, total: checks.length, allPassed: checks.every(Boolean) };
  await context.close();
  return result;
}

(async () => {
  const { entries, outDir } = parseArgs(process.argv.slice(2));
  fs.mkdirSync(outDir, { recursive: true });
  process.env.HOME = process.env.LG_BROWSER_HOME || path.join(os.tmpdir(), `lib_guard_chrome_home_${process.pid}`);
  process.env.XDG_RUNTIME_DIR = process.env.XDG_RUNTIME_DIR || path.join(os.tmpdir(), `lib_guard_xdg_${process.pid}`);
  fs.mkdirSync(process.env.HOME, { recursive: true });
  fs.mkdirSync(process.env.XDG_RUNTIME_DIR, { recursive: true });
  const { chromium } = loadPlaywright();
  const browser = await chromium.launch({
    executablePath: browserPath(),
    headless: true,
    args: [
      "--no-sandbox",
      "--disable-setuid-sandbox",
      "--disable-dev-shm-usage",
      "--disable-gpu",
      "--disable-crashpad",
      "--disable-crash-reporter",
      "--disable-breakpad",
    ],
  });
  const results = [];
  try {
    for (const entry of entries) results.push(await runPage(browser, entry.page, outDir, entry.name));
  } finally {
    await browser.close();
  }
  const report = { status: results.every((item) => item.assertions.allPassed), results };
  fs.writeFileSync(path.join(outDir, "browser_validation.json"), JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report, null, 2));
  process.exit(report.status ? 0 : 1);
})().catch((error) => {
  console.error(`浏览器验收失败: ${error.stack || error}`);
  process.exit(1);
});
