const state = {
  config: null,
  locale: window.__APP_BOOTSTRAP__.defaultLocale,
  sort: window.__APP_BOOTSTRAP__.defaultSort,
  ui: {},
  dashboard: null,
  scan: null,
  previousScanStatus: null,
  activeCoser: "",
  activeCharacter: "",
  i18nLocale: window.__APP_BOOTSTRAP__.defaultLocale,
  i18nEntity: "cosers",
};

const SORT_HEADERS = [
  ["th-sets-coser", "sets"],
  ["th-images-coser", "images"],
  ["th-size-coser", "size"],
  ["th-sets-character", "sets"],
  ["th-images-character", "images"],
  ["th-size-character", "size"],
];

function $(id) {
  return document.getElementById(id);
}

function t(key) {
  return state.ui[key] || key;
}

function formatTemplate(template, values = {}) {
  return template.replace(/\{(\w+)\}/g, (_, name) => values[name] ?? "");
}

function formatNumber(value) {
  return new Intl.NumberFormat(state.locale).format(value || 0);
}

function formatBytes(bytes) {
  const value = Number(bytes || 0);
  if (!Number.isFinite(value) || value <= 0) {
    return "0 B";
  }
  const units = ["B", "KB", "MB", "GB", "TB", "PB"];
  let current = value;
  let index = 0;
  while (current >= 1024 && index < units.length - 1) {
    current /= 1024;
    index += 1;
  }
  const digits = current >= 100 || index === 0 ? 0 : 2;
  return `${current.toLocaleString(state.locale, { maximumFractionDigits: digits, minimumFractionDigits: digits === 0 ? 0 : 2 })} ${units[index]}`;
}

function formatDate(value) {
  if (!value) {
    return t("not_available");
  }
  return new Intl.DateTimeFormat(state.locale, {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(new Date(value));
}

function metricValue(item) {
  if (state.sort === "images") return item.image_count;
  if (state.sort === "sets") return item.set_count;
  return item.total_size;
}

function metricValueLabel(item) {
  if (state.sort === "images") return formatNumber(item.image_count);
  if (state.sort === "sets") return formatNumber(item.set_count);
  return formatBytes(item.total_size);
}

async function fetchJson(url, options) {
  const response = await fetch(url, options);
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.detail || response.statusText);
  }
  return response.json();
}

function renderStaticText() {
  $("app-title").textContent = t("title");
  $("app-subtitle").textContent = t("subtitle");
  $("label-locale").textContent = t("locale_label");
  $("scan-kicker").textContent = t("scan_kicker");
  $("scan-title").textContent = t("scan_title");
  $("scan-current-folder-label").textContent = t("scan_current_folder");
  $("scan-current-set-label").textContent = t("scan_current_set");
  $("scan-counts-label").textContent = t("scan_counts");
  $("scan-last-finished-label").textContent = t("scan_last_finished");
  $("sort-kicker").textContent = t("sort_kicker");
  $("sort-title").textContent = t("sort_title");
  $("sort-current-label").textContent = t("sort_current_label");
  $("coser-chart-kicker").textContent = t("coser_chart_kicker");
  $("coser-chart-title").textContent = t("coser_chart_title");
  $("character-chart-kicker").textContent = t("character_chart_kicker");
  $("character-chart-title").textContent = t("character_chart_title");
  $("coser-table-kicker").textContent = t("coser_table_kicker");
  $("coser-table-title").textContent = t("coser_table_title");
  $("character-table-kicker").textContent = t("character_table_kicker");
  $("character-table-title").textContent = t("character_table_title");
  $("th-coser-name").textContent = t("coser_name");
  $("th-character-name").textContent = t("character_name");
  $("coser-detail-kicker").textContent = t("coser_detail_kicker");
  $("coser-detail-title").textContent = t("coser_detail_title");
  $("character-detail-kicker").textContent = t("character_detail_kicker");
  $("character-detail-title").textContent = t("character_detail_title");
  $("coser-filter-label").textContent = t("coser_filter");
  $("character-filter-label").textContent = t("character_filter");
  $("i18n-kicker").textContent = t("i18n_kicker");
  $("i18n-title").textContent = t("i18n_title");
  $("i18n-locale-label").textContent = t("i18n_locale");
  $("i18n-entity-label").textContent = t("i18n_entity");
  $("export-button").textContent = t("export_csv");
  $("import-button-label").textContent = t("import_csv");
  $("i18n-hint").textContent = t("i18n_hint");
}

function renderLocaleSelects() {
  const localeOptions = state.config.supportedLocales;
  for (const select of [$("locale-select"), $("i18n-locale-select")]) {
    select.innerHTML = "";
    localeOptions.forEach((item) => {
      const option = document.createElement("option");
      option.value = item.code;
      option.textContent = item.label;
      select.append(option);
    });
  }
  $("locale-select").value = state.locale;
  $("i18n-locale-select").value = state.i18nLocale;

  $("i18n-entity-select").innerHTML = "";
  [
    ["cosers", t("i18n_entity_cosers")],
    ["characters", t("i18n_entity_characters")],
  ].forEach(([value, label]) => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    $("i18n-entity-select").append(option);
  });
  $("i18n-entity-select").value = state.i18nEntity;
}

function renderSortStatus() {
  $("sort-current-value").textContent = t(`sort_${state.sort}`);
  SORT_HEADERS.forEach(([id, value]) => {
    const cell = $(id);
    cell.setAttribute("aria-sort", value === state.sort ? "descending" : "none");
    const button = document.createElement("button");
    button.type = "button";
    button.className = `table-sort-button${value === state.sort ? " active" : ""}`;
    button.setAttribute("aria-label", t("sort_by_column").replace("{label}", t(value)));
    button.setAttribute("aria-pressed", value === state.sort ? "true" : "false");
    button.innerHTML = `
      <span>${escapeHtml(t(value))}</span>
      <span class="table-sort-indicator" aria-hidden="true">${value === state.sort ? "↓" : ""}</span>
    `;
    button.addEventListener("click", () => {
      void applySort(value);
    });
    cell.innerHTML = "";
    cell.append(button);
  });
}

async function applySort(value) {
  if (state.sort === value) {
    return;
  }
  state.sort = value;
  renderSortStatus();
  await loadDashboard();
  await refreshActiveDetails();
}

function renderSummary() {
  const container = $("summary-grid");
  container.innerHTML = "";
  const summary = state.dashboard?.summary;
  const template = $("summary-card-template");
  if (!summary) {
    return;
  }
  const cards = [
    ["summary_total_cosers", formatNumber(summary.totalCosers)],
    ["summary_total_sets", formatNumber(summary.totalSets)],
    ["summary_total_characters", formatNumber(summary.totalCharacters)],
    ["summary_total_images", formatNumber(summary.totalImages)],
    ["summary_total_size", formatBytes(summary.totalSize)],
  ];
  cards.forEach(([labelKey, value]) => {
    const fragment = template.content.cloneNode(true);
    fragment.querySelector(".summary-label").textContent = t(labelKey);
    fragment.querySelector(".summary-value").textContent = value;
    container.append(fragment);
  });
}

function renderBarList(containerId, items) {
  const container = $(containerId);
  container.innerHTML = "";
  if (!items.length) {
    container.innerHTML = `<div class="empty-state">${t("empty_library")}</div>`;
    return;
  }
  const topItems = items.slice(0, 15);
  const maxValue = Math.max(...topItems.map((item) => metricValue(item)), 1);
  topItems.forEach((item) => {
    const row = document.createElement("div");
    row.className = "bar-row";
    const percentage = (metricValue(item) / maxValue) * 100;
    row.innerHTML = `
      <div class="bar-meta">
        <span class="bar-label">${escapeHtml(item.display_name)}</span>
        <div class="bar-track"><div class="bar-fill" style="width:${percentage.toFixed(2)}%"></div></div>
      </div>
      <span class="bar-value">${escapeHtml(metricValueLabel(item))}</span>
    `;
    container.append(row);
  });
}

function renderTable(bodyId, items, entityType) {
  const body = $(bodyId);
  body.innerHTML = "";
  if (!items.length) {
    body.innerHTML = `<tr><td colspan="5"><div class="empty-state">${t("empty_library")}</div></td></tr>`;
    return;
  }
  items.forEach((item, index) => {
    const row = document.createElement("tr");
    row.innerHTML = `
      <td>${index + 1}</td>
      <td>${escapeHtml(item.display_name)}</td>
      <td class="${state.sort === "sets" ? "active-sort-cell" : ""}">${formatNumber(item.set_count)}</td>
      <td class="${state.sort === "images" ? "active-sort-cell" : ""}">${formatNumber(item.image_count)}</td>
      <td class="${state.sort === "size" ? "active-sort-cell" : ""}">${escapeHtml(formatBytes(item.total_size))}</td>
    `;
    row.addEventListener("click", async () => {
      if (entityType === "coser") {
        state.activeCoser = item.key;
        $("coser-select").value = item.key;
        await loadCoserDetail();
      } else {
        state.activeCharacter = item.key;
        $("character-select").value = item.key;
        await loadCharacterDetail();
      }
      window.scrollTo({ top: document.body.scrollHeight * 0.45, behavior: "smooth" });
    });
    body.append(row);
  });
}

function fillEntitySelect(selectId, items, activeValue) {
  const select = $(selectId);
  const previousValue = activeValue || select.value;
  select.innerHTML = "";
  const placeholder = document.createElement("option");
  placeholder.value = "";
  placeholder.textContent = t("select_placeholder");
  select.append(placeholder);
  items.forEach((item) => {
    const option = document.createElement("option");
    option.value = item.key;
    option.textContent = item.display_name;
    select.append(option);
  });
  select.value = items.some((item) => item.key === previousValue) ? previousValue : "";
}

function renderScanStatus() {
  const scan = state.scan;
  const scanDetails = $("scan-details");
  const running = scan?.status === "running";
  const completed = scan?.status === "completed";
  const failed = scan?.status === "failed";
  const labelKey = running ? "scan_running" : failed ? "scan_failed" : completed ? "scan_completed" : "scan_idle";
  $("scan-state-pill").textContent = t(labelKey);
  $("scan-summary-text").textContent = running
    ? formatTemplate(t("count_progress"), {
        processed: formatNumber(scan?.processed_cosers || 0),
        total: formatNumber(scan?.total_cosers || 0),
      })
    : scan?.finished_at
      ? formatTemplate(t("last_scan_prefix"), { time: formatDate(scan.finished_at) })
      : t("scan_summary_idle");
  $("scan-progress-fill").style.width = `${Math.max(0, Math.min((scan?.progress || 0) * 100, 100)).toFixed(2)}%`;
  $("scan-progress-text").textContent = formatTemplate(t("count_progress"), {
    processed: formatNumber(scan?.processed_cosers || 0),
    total: formatNumber(scan?.total_cosers || 0),
  });
  $("scan-current-folder").textContent = scan?.current_path || t("not_available");
  $("scan-current-set").textContent = scan?.current_set || t("not_available");
  $("scan-counts").textContent = formatTemplate(t("discovered_counts"), {
    sets: formatNumber(scan?.discovered_sets || 0),
    images: formatNumber(scan?.discovered_images || 0),
    size: formatBytes(scan?.discovered_size || 0),
  });
  $("scan-last-finished").textContent = scan?.finished_at
    ? formatTemplate(t("last_scan_prefix"), { time: formatDate(scan.finished_at) })
    : t("not_available");
  $("scan-note").textContent = failed ? t("scan_note_failed") : running ? t("scan_note_running") : t("scan_note_idle");

  const hasData = Boolean(state.dashboard?.summary?.totalSets || scan?.hasData);
  $("scan-button").textContent = hasData ? t("rescan") : t("start_scan");
  $("scan-button").disabled = running;
  if (running && !scanDetails.open && state.previousScanStatus !== "running") {
    scanDetails.open = true;
  }
}

function detailSummary(entity) {
  return formatTemplate(t("detail_summary"), {
    sets: formatNumber(entity.setCount),
    images: formatNumber(entity.imageCount),
    size: formatBytes(entity.totalSize),
  });
}

function renderCards(containerId, summaryId, payload) {
  const container = $(containerId);
  const summary = $(summaryId);
  container.innerHTML = "";
  if (!payload) {
    summary.textContent = t("detail_empty");
    container.innerHTML = `<div class="empty-state">${t("detail_empty")}</div>`;
    return;
  }
  summary.textContent = `${payload.entity.displayName} - ${detailSummary(payload.entity)}`;
  payload.sets.forEach((item) => {
    const article = document.createElement("article");
    article.className = "cover-card";
    const characters = item.characters.map((character) => character.displayName).join(", ");
    article.innerHTML = `
      <img loading="lazy" src="${item.coverUrl}?size=420" alt="${escapeHtml(item.setName)}" />
      <div>
        <p class="cover-title">${escapeHtml(item.setName)}</p>
        <p class="cover-meta">${escapeHtml(characters || t("not_available"))}</p>
        <p class="cover-meta">${formatNumber(item.imageCount)} ${escapeHtml(t("images"))} · ${escapeHtml(formatBytes(item.totalSize))}</p>
        <p class="cover-path">${escapeHtml(t("relative_path"))}: ${escapeHtml(item.relativePath)}</p>
      </div>
    `;
    container.append(article);
  });
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

async function loadDashboard() {
  state.dashboard = await fetchJson(`/api/dashboard?locale=${encodeURIComponent(state.locale)}&sort=${encodeURIComponent(state.sort)}`);
  renderSummary();
  renderBarList("coser-bar-list", state.dashboard.cosers);
  renderBarList("character-bar-list", state.dashboard.characters);
  renderTable("coser-table-body", state.dashboard.cosers, "coser");
  renderTable("character-table-body", state.dashboard.characters, "character");
  fillEntitySelect("coser-select", state.dashboard.cosers, state.activeCoser);
  fillEntitySelect("character-select", state.dashboard.characters, state.activeCharacter);
}

async function refreshActiveDetails() {
  await Promise.all([loadCoserDetail(), loadCharacterDetail()]);
}

async function loadCoserDetail() {
  const key = $("coser-select").value || state.activeCoser;
  state.activeCoser = key;
  if (!key) {
    renderCards("coser-card-grid", "coser-detail-summary", null);
    return;
  }
  const payload = await fetchJson(`/api/cosers/${encodeURIComponent(key)}?locale=${encodeURIComponent(state.locale)}&sort=${encodeURIComponent(state.sort)}`);
  renderCards("coser-card-grid", "coser-detail-summary", payload);
}

async function loadCharacterDetail() {
  const key = $("character-select").value || state.activeCharacter;
  state.activeCharacter = key;
  if (!key) {
    renderCards("character-card-grid", "character-detail-summary", null);
    return;
  }
  const payload = await fetchJson(`/api/characters/${encodeURIComponent(key)}?locale=${encodeURIComponent(state.locale)}&sort=${encodeURIComponent(state.sort)}`);
  renderCards("character-card-grid", "character-detail-summary", payload);
}

async function refreshScan() {
  try {
    state.scan = await fetchJson("/api/scan/status");
    renderScanStatus();
    const previous = state.previousScanStatus;
    state.previousScanStatus = state.scan.status;
    const shouldReload = previous === "running" && state.scan.status === "completed";
    if (shouldReload || (!state.dashboard && state.scan.hasData)) {
      await loadDashboard();
      await refreshActiveDetails();
    }
  } catch (error) {
    $("scan-note").textContent = error.message;
  }
}

async function switchLocale(locale) {
  state.locale = locale;
  state.ui = await fetchJson(`/api/ui-translations/${encodeURIComponent(locale)}`);
  renderStaticText();
  renderLocaleSelects();
  renderSortStatus();
  await loadDashboard();
  await refreshScan();
  await refreshActiveDetails();
}

async function startScan() {
  try {
    await fetchJson("/api/scan/start", { method: "POST" });
    await refreshScan();
  } catch (error) {
    $("scan-note").textContent = error.message;
  }
}

async function importTranslations(file) {
  const formData = new FormData();
  formData.append("file", file);
  const url = `/api/i18n/import?entity=${encodeURIComponent(state.i18nEntity)}&locale=${encodeURIComponent(state.i18nLocale)}`;
  const response = await fetch(url, { method: "POST", body: formData });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.detail || response.statusText);
  }
  $("i18n-status").textContent = formatTemplate(t("i18n_import_success"), { count: formatNumber(payload.updated) });
  if (state.i18nLocale === state.locale) {
    await loadDashboard();
    await refreshActiveDetails();
  }
}

function bindEvents() {
  $("locale-select").addEventListener("change", async (event) => {
    await switchLocale(event.target.value);
  });
  $("scan-button").addEventListener("click", startScan);
  $("coser-select").addEventListener("change", loadCoserDetail);
  $("character-select").addEventListener("change", loadCharacterDetail);
  $("i18n-locale-select").addEventListener("change", (event) => {
    state.i18nLocale = event.target.value;
  });
  $("i18n-entity-select").addEventListener("change", (event) => {
    state.i18nEntity = event.target.value;
  });
  $("export-button").addEventListener("click", () => {
    const url = `/api/i18n/export?entity=${encodeURIComponent(state.i18nEntity)}&locale=${encodeURIComponent(state.i18nLocale)}`;
    window.open(url, "_blank", "noopener");
  });
  $("import-file").addEventListener("change", async (event) => {
    const [file] = event.target.files || [];
    if (!file) return;
    try {
      await importTranslations(file);
    } catch (error) {
      $("i18n-status").textContent = error.message;
    } finally {
      event.target.value = "";
    }
  });
}

async function init() {
  state.config = await fetchJson("/api/config");
  state.locale = state.config.defaultLocale;
  state.i18nLocale = state.config.defaultLocale;
  state.ui = await fetchJson(`/api/ui-translations/${encodeURIComponent(state.locale)}`);
  renderStaticText();
  renderLocaleSelects();
  renderSortStatus();
  bindEvents();
  await loadDashboard();
  await refreshScan();
  renderCards("coser-card-grid", "coser-detail-summary", null);
  renderCards("character-card-grid", "character-detail-summary", null);
  window.setInterval(refreshScan, 2000);
}

window.addEventListener("DOMContentLoaded", () => {
  init().catch((error) => {
    console.error(error);
    $("scan-note").textContent = error.message;
  });
});
