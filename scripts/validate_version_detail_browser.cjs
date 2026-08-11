#!/usr/bin/env node

/* Repeatable desktop smoke test for generated Version Detail HTML. */
const fs = require("fs");
const os = require("os");
const path = require("path");

function usage(message) {
  if (message) console.error(`ERROR: ${message}`);
  console.error("用法: node scripts/validate_version_detail_browser.cjs <index.html> [<index.html> ...] [--out <目录>]");
  process.exit(2);
}

function parseArgs(argv) {
  const pages = [];
  let outDir = path.resolve("work/browser_validation");
  for (let i = 0; i < argv.length; i += 1) {
    if (argv[i] === "--out") {
      if (!argv[i + 1]) usage("--out 缺少目录");
      outDir = path.resolve(argv[++i]);
    } else if (argv[i].startsWith("-")) {
      usage(`未知参数: ${argv[i]}`);
    } else {
      pages.push(path.resolve(argv[i]));
    }
  }
  if (!pages.length) usage("至少指定一个 Version Detail index.html");
  return { pages, outDir };
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

async function runPage(browser, pagePath, outDir) {
  if (!fs.existsSync(pagePath)) throw new Error(`页面不存在: ${pagePath}`);
  const context = await browser.newContext({ viewport: { width: 1440, height: 1100 }, deviceScaleFactor: 1 });
  const page = await context.newPage();
  await page.goto(`file://${pagePath}`, { waitUntil: "load" });
  await page.waitForTimeout(200);

  const result = {
    page: pagePath,
    title: await page.title(),
    tables: await page.locator("table").count(),
    headings: await page.locator("h1,h2,h3").allTextContents(),
    screenshot: path.join(outDir, `${pageKey(pagePath)}.png`),
  };
  result.hasDecision = (await page.locator("text=判断摘要").count()) > 0;
  result.hasFileTree = (await page.locator("[data-file-tree], .file-tree").count()) > 0;
  result.hasViewMatrix = (await page.locator(".view-delta-table").count()) > 0;
  await page.screenshot({ path: result.screenshot, fullPage: true });

  const checks = [result.hasDecision, result.hasFileTree, result.hasViewMatrix];
  if (result.hasFileTree) {
    result.treeFiles = await page.locator(".tree-file").count();
    result.treeAllVisible = await visibleTreeFiles(page);
    await page.locator('[data-tree-filter="added"]').click();
    result.treeAddedVisible = await visibleTreeFiles(page);
    result.treeAddedStatusCount = await page.locator('.tree-file[data-tree-status="added"]').count();
    result.treeVisibleLabelAfterAdded = (await page.locator("#file-tree-visible").textContent()).trim();
    await page.locator('[data-tree-filter="all"]').click();
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
      result.treeAllVisible === result.treeFiles,
      result.treeAddedVisible === result.treeAddedStatusCount,
      result.treeSearchVisible > 0,
      result.openDetailsAfterCollapse === 0,
      result.openDetailsAfterExpand > 0,
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
    result.tableSearchQuery = cellText.split(/\s+/)[0].slice(0, 12);
    await tableSearch.fill(result.tableSearchQuery);
    await page.waitForTimeout(50);
    result.tableRowsBefore = rowsBefore;
    result.tableRowsAfter = await page.evaluate(() => [...document.querySelectorAll("#tbl-focus-change-scroll tbody tr")]
      .filter((item) => !item.classList.contains("is-hidden-by-filter") && !item.hidden && item.offsetParent !== null).length);
    checks.push(result.focusInitiallyOpen === null, result.tableSearchVisible, result.tableRowsAfter > 0 && result.tableRowsAfter <= rowsBefore);
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
  checks.push(result.horizontalScroll.exists && result.horizontalScroll.overflow && result.horizontalScroll.afterScrollLeft > 0);
  result.assertions = { passed: checks.filter(Boolean).length, total: checks.length, allPassed: checks.every(Boolean) };
  await context.close();
  return result;
}

(async () => {
  const { pages, outDir } = parseArgs(process.argv.slice(2));
  fs.mkdirSync(outDir, { recursive: true });
  process.env.HOME = process.env.LG_BROWSER_HOME || path.join(os.tmpdir(), `lib_guard_chrome_home_${process.pid}`);
  process.env.XDG_RUNTIME_DIR = process.env.XDG_RUNTIME_DIR || path.join(os.tmpdir(), `lib_guard_xdg_${process.pid}`);
  fs.mkdirSync(process.env.HOME, { recursive: true });
  fs.mkdirSync(process.env.XDG_RUNTIME_DIR, { recursive: true });
  const { chromium } = loadPlaywright();
  const browser = await chromium.launch({
    executablePath: browserPath(),
    headless: true,
    args: ["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
  });
  const results = [];
  try {
    for (const pagePath of pages) results.push(await runPage(browser, pagePath, outDir));
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
