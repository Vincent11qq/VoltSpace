/* VoltSpace UI logic.
 *
 * Design rule: this file contains NO physics and NO tariffs. Every number shown comes
 * from the backend:
 *   GET  /appliances/presets   -> appliance library, circuit ceilings, reference rate
 *   GET  /household/appliances -> the saved household
 *   POST /household/dashboard  -> consumption + bill + load + recommendations
 *   PUT  /household/appliances -> save all
 * The original Flet prototype did the arithmetic in the client (a fixed circuit ceiling,
 * a guessed per-kWh rate and a bare watts/volts division). That is what this replaces:
 * the ceiling comes from the chosen circuit preset and the rate from the tariff table.
 */

const API = ""; // same origin
const state = {
  presets: [],
  circuits: [],
  plans: [],
  items: [],        // working list (unsaved edits included)
  savedIds: new Set(),
  limitAmps: 15,
  margin: 0.8,
  planId: null,
  month: null,
  busy: false,
  lastSummary: null,
};

const $ = (id) => document.getElementById(id);
const el = (tag, cls, text) => {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined && text !== null) node.textContent = text;
  return node;
};
const fmt = (value, digits = 1) =>
  value === null || value === undefined ? "—" : Number(value).toFixed(digits);

/* ------------------------------------------------------------------ language */
/*
 * Two languages, chosen on the client and remembered in localStorage.
 *
 * Static markup carries data-i18n / data-i18n-ph / data-i18n-title attributes; dynamic
 * text calls t(). Anything the backend supplies in both languages (appliance names,
 * circuit labels, plan names, recommendations, warnings, disclaimers) is read through
 * pick(), which never returns an empty string.
 */

const LANG_KEY = "voltspace.lang";

const I18N = {
  zh: {
    "brand.tagline": "租屋用電估算與迴路安全檢查",
    "label.plan": "電價方案",
    "label.month": "月份",
    "conn.checking": "連線中…",
    "conn.ok": "後端 v{v}",
    "conn.bad": "後端未連線",
    "conn.title": "後端連線狀態",
    "toast.noBackend": "連不到後端，請確認伺服器是否啟動",
    "drawer.title": "家電庫",
    "drawer.hint": "點選即可加入，數字來自後端參考資料。",
    "drawer.custom": "＋ 自訂家電",
    "form.name": "名稱（例如 除濕機）",
    "form.watts": "功率 150 或 150W 都可",
    "form.volts": "電壓 110 或 110V 都可",
    "form.hours": "每日小時（例 6）",
    "form.days": "每月天數",
    "form.qty": "數量",
    "form.hint": "只要填數字，單位（W／V／小時）可以省略。",
    "form.add": "加入",
    "form.cancel": "取消",
    "centre.title": "主要迴路插座",
    "outlet.plugged": "已接上的電器",
    "outlet.empty": "點選左側家電或使用「自訂家電」加入",
    "circuit.label": "迴路上限",
    "circuit.custom": "自訂上限 (A)",
    "circuit.margin": "安全裕度",
    "margin.80": "80%（建議）",
    "margin.70": "70%（保守）",
    "margin.100": "100%（只看是否超限）",
    "actions.save": "儲存我的家電",
    "actions.reload": "重新載入已存清單",
    "actions.clear": "全部清除",
    "results.title": "本月估算",
    "stat.kwh": "每月用電",
    "stat.cost": "預估電費",
    "stat.rate": "平均每度",
    "stat.season": "季節",
    "breakdown.title": "用電等級",
    "recs.title": "節電建議",
    "recs.none": "目前沒有可提供的建議。",
    "recs.saving": "每月約可省 {kwh} 度（{twd} 元，約 {pct}% 用電）。",
    "recs.perMonth": "預估每月省 {kwh} 度 / {twd} 元",
    "recs.adviceOnly": "此為用電安全建議，未估算節省度數。",
    "recs.assumption": "假設：{text}",
    "notes.summary": "計算假設與限制",
    "footer.text": "VoltSpace · Group 9 · 計算與電價皆由後端提供，",
    "footer.api": "API 文件",
    "month.any": "依目前季節",
    "preset.add": "加入 {name}",
    "preset.meta": "{w}W · {v}V · {h}h/日",
    "unit.kwh": "度",
    "unit.twd": "元",
    "unit.perKwh": "元/度",
    "saved.count": "已儲存 {n} 台家電（每月約 {kwh} 度）",
    "saved.empty": "目前沒有已儲存的家電，加入後按「儲存我的家電」。",
    "toast.saved": "已儲存 {n} 台家電",
    "toast.saveFailed": "儲存失敗：{msg}",
    "toast.calcFailed": "計算失敗：{msg}",
    "toast.cleared": "已清除",
    "toast.clearFailed": "清除失敗：{msg}",
    "toast.bootFailed": "啟動失敗：{msg}",
    "empty.status": "尚未接上電器",
    "verdict.noLimit": "未設定迴路上限",
    "outlet.cost": "預估 {twd} 元 / 月",
    "amps.withLimit": "{a} A（上限 {limit} A）",
    "plug.line": "{name}（{w}W · {h}h/日{qty}）",
    "plug.qty": " ×{n}",
    "field.name": "名稱",
    "field.watts": "功率",
    "field.volts": "電壓",
    "field.hours": "每日小時",
    "field.days": "每月天數",
    "field.qty": "數量",
    "hint.watts": "150 或 150W",
    "hint.volts": "110 或 110V",
    "hint.hours": "0 到 24，例 6",
    "hint.days": "0 到 31",
    "hint.qty": "1 到 999",
    "err.missing": "請填「{label}」（{hint}）",
    "err.notNumber": "「{label}」請填數字，例如 {hint}",
    "err.min": "「{label}」必須大於等於 {min}",
    "err.max": "「{label}」必須小於等於 {max}",
    "err.name": "請填「名稱」，例如 除濕機",
    "title.remove": "移除",
    "lang.button": "EN",
    "lang.title": "Switch to English",
  },
  en: {
    "brand.tagline": "Electricity estimates and circuit safety for rented rooms",
    "label.plan": "Tariff plan",
    "label.month": "Month",
    "conn.checking": "Connecting…",
    "conn.ok": "Backend v{v}",
    "conn.bad": "Backend offline",
    "conn.title": "Backend connection status",
    "toast.noBackend": "Cannot reach the backend. Is the server running?",
    "drawer.title": "Appliance library",
    "drawer.hint": "Click one to add it. The numbers come from the backend.",
    "drawer.custom": "+ Custom appliance",
    "form.name": "Name (e.g. dehumidifier)",
    "form.watts": "Power: 150 or 150W",
    "form.volts": "Voltage: 110 or 110V",
    "form.hours": "Hours per day (e.g. 6)",
    "form.days": "Days per month",
    "form.qty": "Quantity",
    "form.hint": "Numbers only; units (W / V / hours) are optional.",
    "form.add": "Add",
    "form.cancel": "Cancel",
    "centre.title": "Main circuit outlet",
    "outlet.plugged": "Plugged in",
    "outlet.empty": "Pick an appliance on the left, or use \"Custom appliance\"",
    "circuit.label": "Circuit limit",
    "circuit.custom": "Custom limit (A)",
    "circuit.margin": "Safety margin",
    "margin.80": "80% (recommended)",
    "margin.70": "70% (conservative)",
    "margin.100": "100% (overload only)",
    "actions.save": "Save my appliances",
    "actions.reload": "Reload saved list",
    "actions.clear": "Clear all",
    "results.title": "This month",
    "stat.kwh": "Monthly use",
    "stat.cost": "Estimated bill",
    "stat.rate": "Average rate",
    "stat.season": "Season",
    "breakdown.title": "Usage breakdown",
    "recs.title": "Saving tips",
    "recs.none": "No suggestions right now.",
    "recs.saving": "Saves about {kwh} kWh a month ({twd} TWD, roughly {pct}% of usage).",
    "recs.perMonth": "Estimated saving {kwh} kWh / {twd} TWD per month",
    "recs.adviceOnly": "Safety advice; no kWh saving is estimated.",
    "recs.assumption": "Assumption: {text}",
    "notes.summary": "Assumptions and limits",
    "footer.text": "VoltSpace · Group 9 · all calculations and tariffs come from the backend.",
    "footer.api": "API docs",
    "month.any": "Current season",
    "preset.add": "Add {name}",
    "preset.meta": "{w}W · {v}V · {h}h/day",
    "unit.kwh": "kWh",
    "unit.twd": "TWD",
    "unit.perKwh": "TWD/kWh",
    "saved.count": "{n} appliance(s) saved (about {kwh} kWh a month)",
    "saved.empty": "No saved appliances yet. Add some, then press \"Save my appliances\".",
    "toast.saved": "Saved {n} appliance(s)",
    "toast.saveFailed": "Save failed: {msg}",
    "toast.calcFailed": "Calculation failed: {msg}",
    "toast.cleared": "Cleared",
    "toast.clearFailed": "Clear failed: {msg}",
    "toast.bootFailed": "Startup failed: {msg}",
    "empty.status": "Nothing plugged in",
    "verdict.noLimit": "No circuit limit set",
    "outlet.cost": "About {twd} TWD / month",
    "amps.withLimit": "{a} A (limit {limit} A)",
    "plug.line": "{name} ({w}W · {h}h/day{qty})",
    "plug.qty": " ×{n}",
    "field.name": "Name",
    "field.watts": "Power",
    "field.volts": "Voltage",
    "field.hours": "Hours per day",
    "field.days": "Days per month",
    "field.qty": "Quantity",
    "hint.watts": "150 or 150W",
    "hint.volts": "110 or 110V",
    "hint.hours": "0 to 24, e.g. 6",
    "hint.days": "0 to 31",
    "hint.qty": "1 to 999",
    "err.missing": "Please fill in \"{label}\" ({hint})",
    "err.notNumber": "\"{label}\" must be a number, e.g. {hint}",
    "err.min": "\"{label}\" must be at least {min}",
    "err.max": "\"{label}\" must be at most {max}",
    "err.name": "Please enter a name, e.g. dehumidifier",
    "title.remove": "Remove",
    "lang.button": "中文",
    "lang.title": "切換成中文",
  },
};

const MONTHS_EN = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

let LANG = (() => {
  try {
    const stored = localStorage.getItem(LANG_KEY);
    if (stored === "zh" || stored === "en") return stored;
  } catch (error) {
    /* localStorage can be blocked; fall through to the default. */
  }
  return "zh";
})();

/** Translate a UI key, substituting {placeholders}. Missing keys fall back to Chinese. */
function t(key, vars) {
  const table = I18N[LANG] || I18N.zh;
  let text = table[key];
  if (text === undefined) text = I18N.zh[key];
  if (text === undefined) return key;
  if (vars) {
    for (const [name, value] of Object.entries(vars)) {
      text = text.split(`{${name}}`).join(String(value));
    }
  }
  return text;
}

/** Choose the text the backend supplied in both languages. */
function pick(zh, en) {
  return LANG === "en" ? en || zh : zh || en;
}

/*
 * Month labels are language-specific rather than a template: Chinese says "7 月" while
 * English names the month. Keeping this in one function avoids a dictionary key whose
 * placeholder would differ between the two languages.
 */
const monthLabel = (month) =>
  LANG === "en" ? MONTHS_EN[month - 1] : `${month} 月`;

/** "3 度" / "3 kWh" */
const unitKwh = (value, digits = 1) =>
  LANG === "en"
    ? `${fmt(value, digits)} ${t("unit.kwh")}`
    : `${fmt(value, digits)} ${t("unit.kwh")}`;

/** "120 元" / "120 TWD" */
const unitTwd = (value, digits = 0) => `${fmt(value, digits)} ${t("unit.twd")}`;

const unitRate = (value) =>
  LANG === "en"
    ? `${fmt(value, 2)} ${t("unit.perKwh")}`
    : `${fmt(value, 2)} ${t("unit.perKwh")}`;

/** Update every element that carries a translation attribute. */
function applyStatic() {
  document.documentElement.lang = LANG === "en" ? "en" : "zh-Hant";
  document.title =
    LANG === "en"
      ? "VoltSpace — Electricity and circuit safety for renters"
      : "VoltSpace — 租屋用電與迴路安全";

  for (const node of document.querySelectorAll("[data-i18n]")) {
    node.textContent = t(node.dataset.i18n);
  }
  for (const node of document.querySelectorAll("[data-i18n-ph]")) {
    node.placeholder = t(node.dataset.i18nPh);
  }
  for (const node of document.querySelectorAll("[data-i18n-title]")) {
    node.title = t(node.dataset.i18nTitle);
  }

  const toggle = $("langToggle");
  if (toggle) {
    toggle.textContent = t("lang.button");
    toggle.title = t("lang.title");
    toggle.setAttribute("aria-label", t("lang.title"));
  }
}

/** Switch language, remember it, and redraw everything the user can see. */
function setLanguage(next) {
  LANG = next === "en" ? "en" : "zh";
  try {
    localStorage.setItem(LANG_KEY, LANG);
  } catch (error) {
    /* not fatal - the choice just will not persist */
  }
  applyStatic();
  if (state.plans.length) {
    buildPlanSelect({ plans: state.plans, default_plan_id: state.planId });
    buildMonthSelect(state.month);
    buildCircuitSelect({ circuits: state.circuits, default_circuit_amps: state.limitAmps });
    renderPresets();
    if (state.items.length) refresh();
    else applyEmpty();
  }
}

/* ------------------------------------------------------------------ network */

async function api(path, { method = "GET", body } = {}) {
  const options = { method, headers: {} };
  if (body !== undefined) {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }
  const response = await fetch(API + path, options);
  const text = await response.text();
  let payload = null;
  try {
    payload = text ? JSON.parse(text) : null;
  } catch {
    payload = { message: text };
  }
  if (!response.ok) {
    const error = new Error(
      (payload && (payload.message || payload.code)) || `HTTP ${response.status}`
    );
    error.status = response.status;
    error.payload = payload;
    throw error;
  }
  return payload;
}

function toast(message, isError = false) {
  const node = $("toast");
  node.textContent = message;
  node.classList.toggle("error", !!isError);
  node.hidden = false;
  clearTimeout(toast._timer);
  toast._timer = setTimeout(() => (node.hidden = true), 3800);
}

/* ------------------------------------------------------- number input parsing */

/* Users type units. "150W", "150 W", "1,200" and "150" all mean 150 watts, and a
 * <input type="number"> refuses the first three with the browser's own
 * "請輸入有效的值" tooltip, which says nothing about which field is wrong.
 * So the fields are plain text and parsed here, with a message that names the field. */

function parseNumber(raw) {
  if (raw === null || raw === undefined) return null;
  // Keep digits, a decimal point and a leading minus; drop units, spaces and commas.
  const cleaned = String(raw)
    .replace(/[,，\s]/g, "")
    // A trailing unit ("150W", "150 瓦", "6小時", "110V") is ignored; anything after it is
    // not part of the number either.
    .replace(/(?:瓦|小時|度|時|天|日|台|個|w|v|h|a).*$/i, "")
    .replace(/[^0-9.\-]/g, "");
  if (cleaned === "" || cleaned === "-" || cleaned === ".") return null;
  const value = Number(cleaned);
  return Number.isFinite(value) ? value : null;
}

/**
 * Read a field, returning a value or showing a message that names the field.
 * `label` is what the user sees; `hint` is the range, e.g. "0.1 到 100000".
 */
function readField(id, { label, hint, min, max, integer = false, fallback = null }) {
  const raw = $(id).value;
  if (String(raw).trim() === "") {
    if (fallback !== null) return fallback;
    toast(t("err.missing", { label, hint }), true);
    return undefined;
  }
  let value = parseNumber(raw);
  if (value === null) {
    toast(t("err.notNumber", { label, hint }), true);
    return undefined;
  }
  if (integer) value = Math.round(value);
  if (min !== undefined && value < min) {
    toast(t("err.min", { label, min }), true);
    return undefined;
  }
  if (max !== undefined && value > max) {
    toast(t("err.max", { label, max }), true);
    return undefined;
  }
  return value;
}

/* -------------------------------------------------------------------- setup */

async function boot() {
  applyStatic();
  try {
    const health = await api("/health");
    $("conn").textContent = t("conn.ok", { v: health.version });
    $("conn").className = "pill ok";
  } catch (error) {
    $("conn").textContent = t("conn.bad");
    $("conn").className = "pill bad";
    toast(t("toast.noBackend"), true);
    return;
  }

  const [presets, tariffs] = await Promise.all([api("/appliances/presets"), api("/tariffs")]);
  state.presets = presets.presets;
  state.circuits = presets.circuits;
  state.plans = tariffs.plans;
  state.planId = tariffs.default_plan_id;
  state.limitAmps = presets.default_circuit_amps;

  buildPlanSelect(tariffs);
  buildMonthSelect();
  buildCircuitSelect(presets);
  // Set once at startup. buildCircuitSelect is also called when the language changes, and
  // must not reset a margin the user already picked.
  $("margin").value = String(state.margin);
  renderPresets();
  await loadSaved();
  bindEvents();
}

function buildPlanSelect(tariffs) {
  const select = $("plan");
  select.innerHTML = "";
  for (const plan of tariffs.plans) {
    const option = el("option", null, pick(plan.name_zh, plan.name_en) || plan.id);
    option.value = plan.id;
    if (plan.id === (tariffs.default_plan_id || state.planId)) option.selected = true;
    select.append(option);
  }
}

function buildMonthSelect(preselect) {
  const select = $("month");
  select.innerHTML = "";
  const any = el("option", null, t("month.any"));
  any.value = "";
  select.append(any);

  const chosen = preselect === undefined ? new Date().getMonth() + 1 : preselect;
  for (let month = 1; month <= 12; month += 1) {
    const option = el("option", null, monthLabel(month));
    option.value = String(month);
    if (month === chosen) option.selected = true;
    select.append(option);
  }
  state.month = chosen || null;
}

function buildCircuitSelect(presets) {
  const select = $("circuit");
  select.innerHTML = "";
  for (const circuit of presets.circuits) {
    const label = pick(circuit.label_zh, circuit.label_en);
    const option = el(
      "option",
      null,
      `${label} (${circuit.amps}A × ${circuit.voltage}V = ${circuit.max_watts}W)`
    );
    option.value = String(circuit.amps);
    if (circuit.amps === (presets.default_circuit_amps || state.limitAmps)) {
      option.selected = true;
    }
    select.append(option);
  }
  $("ampsLimit").value = String(state.limitAmps ?? presets.default_circuit_amps);
}

/* ------------------------------------------------------------------ presets */

function renderPresets() {
  const list = $("presets");
  list.innerHTML = "";
  for (const preset of state.presets) {
    const name = pick(preset.name_zh, preset.name_en);
    const button = el("button", "preset");
    button.type = "button";
    button.title = t("preset.add", { name });

    const left = el("div");
    const label = el("div", "preset-name", name);
    if (preset.is_high_power) label.append(el("span", "high-power", " ⚡"));
    left.append(label);
    left.append(
      el(
        "div",
        "preset-meta",
        t("preset.meta", {
          w: preset.power_watts,
          v: preset.voltage,
          h: preset.hours_per_day,
        })
      )
    );

    const plus = el("span", "preset-add", "＋");
    button.append(left, plus);
    button.addEventListener("click", () => addPreset(preset));
    list.append(button);
  }
}

function addPreset(preset) {
  state.items.push({
    name: pick(preset.name_zh, preset.name_en),
    category: preset.category,
    power_watts: preset.power_watts,
    hours_per_day: preset.hours_per_day,
    days_per_month: preset.days_per_month,
    quantity: 1,
    voltage: preset.voltage,
    savedId: null,
  });
  refresh();
}

/* ------------------------------------------------------------------ load/save */

async function loadSaved() {
  const listing = await api("/household/appliances");
  state.items = listing.appliances.map((row) => ({
    name: row.name,
    category: row.category,
    power_watts: row.power_watts,
    hours_per_day: row.hours_per_day,
    days_per_month: row.days_per_month,
    quantity: row.quantity,
    voltage: row.voltage,
    savedId: row.id,
  }));
  state.savedIds = new Set(listing.appliances.map((row) => row.id));
  $("saveNote").textContent = listing.count
    ? t("saved.count", { n: listing.count, kwh: fmt(listing.total_monthly_kwh) })
    : t("saved.empty");
  refresh();
}

function toPayload(item) {
  return {
    name: item.name,
    category: item.category || null,
    power_watts: Number(item.power_watts),
    hours_per_day: Number(item.hours_per_day),
    days_per_month: Number(item.days_per_month ?? 30),
    quantity: Number(item.quantity ?? 1),
    voltage: item.voltage === null || item.voltage === undefined ? null : Number(item.voltage),
  };
}

async function saveAll() {
  try {
    const body = { appliances: state.items.map(toPayload) };
    const listing = await api("/household/appliances", { method: "PUT", body });
    state.items = listing.appliances.map((row) => ({
      name: row.name,
      category: row.category,
      power_watts: row.power_watts,
      hours_per_day: row.hours_per_day,
      days_per_month: row.days_per_month,
      quantity: row.quantity,
      voltage: row.voltage,
      savedId: row.id,
    }));
    state.savedIds = new Set(listing.appliances.map((row) => row.id));
    toast(t("toast.saved", { n: listing.count }));
    await loadSaved();
  } catch (error) {
    toast(t("toast.saveFailed", { msg: error.message }), true);
  }
}

/* ------------------------------------------------------------------ dashboard */

async function refresh() {
  renderPlugged();
  if (state.items.length === 0) {
    applyEmpty();
    return;
  }
  if (state.busy) return;
  state.busy = true;
  try {
    const body = {
      appliances: state.items.map(toPayload),
      load_limit_amps: state.limitAmps,
      safety_margin: state.margin,
      include_recommendations: true,
      max_recommendations: 6,
    };
    if (state.planId) body.plan_id = state.planId;
    if (state.month) body.month = state.month;

    const data = await api("/household/dashboard", { method: "POST", body });
    state.lastSummary = data.summary;
    renderDashboard(data);
  } catch (error) {
    toast(t("toast.calcFailed", { msg: error.message }), true);
  } finally {
    state.busy = false;
  }
}

function applyEmpty() {
  const outlet = $("outlet");
  outlet.className = "card outlet";
  $("status").textContent = t("empty.status");
  $("status").className = "status";
  $("watts").textContent = "0 W";
  $("amps").textContent = "0 A";
  $("cost").textContent = "—";
  $("bar").style.width = "0%";
  $("sKwh").textContent = "—";
  $("sCost").textContent = "—";
  $("sRate").textContent = "—";
  $("sSeason").textContent = "—";
  $("breakdown").innerHTML = "";
  $("recs").innerHTML = "";
  $("saving").textContent = "";
}

function renderDashboard(data) {
  const summary = data.summary;
  const outlet = $("outlet");
  const severity = summary.load_severity === "danger" ? "danger"
    : summary.load_severity === "warning" ? "warn" : "";
  outlet.className = `card outlet ${severity}`.trim();

  const verdictText = {
    safe: "STATUS: SAFE",
    near_limit: "WARNING: HIGH LOAD",
    over_limit: "DANGER: CIRCUIT OVERLOADED",
    no_limit: t("verdict.noLimit"),
  }[summary.load_verdict] || "—";
  $("status").textContent = verdictText;
  $("status").className = `status ${severity}`.trim();

  const totalWatts = data.load ? data.load.total_power_watts : 0;
  $("watts").textContent = `${Math.round(totalWatts)} W` +
    (state.limitAmps ? ` / ${Math.round(state.limitAmps * 110)} W` : "");
  $("amps").textContent = data.load
    ? t("amps.withLimit", {
        a: fmt(summary.estimated_total_current_amps, 2),
        limit: fmt(state.limitAmps, 1),
      })
    : "—";

  const ratio = state.limitAmps
    ? Math.min((summary.estimated_total_current_amps || 0) / state.limitAmps, 1)
    : 0;
  const bar = $("bar");
  bar.style.width = `${(ratio * 100).toFixed(1)}%`;
  bar.style.background = ratio >= 1 ? "var(--danger)" : ratio > state.margin ? "var(--warn)" : "var(--ok)";

  $("cost").textContent = t("outlet.cost", {
    twd: fmt(summary.estimated_monthly_cost_twd, 0),
  });

  $("sKwh").textContent = unitKwh(summary.total_monthly_kwh, 1);
  $("sCost").textContent = unitTwd(summary.estimated_monthly_cost_twd, 0);
  $("sRate").textContent = unitRate(summary.effective_rate_per_kwh);
  $("sSeason").textContent =
    pick(summary.season_label_zh, summary.season_label_en) || "—";

  renderBreakdown(data.consumption.appliances);
  renderRecommendations(data.recommendations);
  renderDisclaimer(data);
}

function renderBreakdown(appliances) {
  const list = $("breakdown");
  list.innerHTML = "";
  const sorted = [...appliances].sort((a, b) => b.monthly_kwh - a.monthly_kwh);
  for (const appliance of sorted) {
    const li = el("li");
    const head = el("div", "bd-head");
    head.append(el("span", null, appliance.name));
    head.append(
      el(
        "span",
        "muted",
        `${unitKwh(appliance.monthly_kwh, 1)} · ${fmt(appliance.share_of_total_percent, 1)}%`
      )
    );
    const track = el("div", "bd-track");
    const fill = el("div", "bd-fill");
    fill.style.width = `${Math.min(appliance.share_of_total_percent || 0, 100)}%`;
    track.append(fill);
    li.append(head, track);
    list.append(li);
  }
}

function renderRecommendations(recommendations) {
  const list = $("recs");
  list.innerHTML = "";
  const note = $("saving");
  if (!recommendations || recommendations.recommendations.length === 0) {
    note.textContent = t("recs.none");
    return;
  }
  note.textContent = t("recs.saving", {
    kwh: fmt(recommendations.total_potential_monthly_saving_kwh, 1),
    twd: fmt(recommendations.total_potential_monthly_saving_twd, 0),
    pct: fmt(recommendations.potential_saving_percent_of_usage, 0),
  });

  for (const item of recommendations.recommendations) {
    const box = el("li", "rec");
    const head = el("div", "rec-head");
    head.append(el("span", `rec-sev ${item.severity}`, item.severity.toUpperCase()));
    head.append(el("span", "rec-title", pick(item.title_zh, item.title_en)));
    box.append(head);
    box.append(el("p", "muted", pick(item.reason_zh, item.reason_en)));
    box.append(el("p", null, pick(item.suggestion_zh, item.suggestion_en)));
    if (item.estimated_monthly_saving_kwh > 0) {
      box.append(
        el(
          "p",
          "rec-saving",
          t("recs.perMonth", {
            kwh: fmt(item.estimated_monthly_saving_kwh, 1),
            twd: fmt(item.estimated_monthly_saving_twd, 0),
          })
        )
      );
    } else if (item.advice_only) {
      box.append(el("p", "muted small", t("recs.adviceOnly")));
    }
    box.append(
      el("p", "small muted", t("recs.assumption", {
        text: pick(item.assumption_zh, item.assumption_en),
      }))
    );
    list.append(box);
  }
}

function renderDisclaimer(data) {
  const list = $("disclaimer");
  list.innerHTML = "";
  const notes = new Set();
  if (data.load) {
    notes.add(pick(data.load.disclaimer_zh, data.load.disclaimer_en));
    for (const warning of data.load.warnings) {
      const text = pick(warning.message_zh, warning.message_en);
      if (text) notes.add(text);
    }
  }
  if (data.bill) {
    for (const warning of data.bill.warnings) {
      const text = pick(warning.message_zh, warning.message_en);
      if (text) notes.add(text);
    }
  }
  if (data.recommendations) {
    notes.add(pick(data.recommendations.disclaimer_zh, data.recommendations.disclaimer_en));
  }
  for (const note of notes) {
    if (note) list.append(el("li", null, note));
  }
}

function renderPlugged() {
  const list = $("plugged");
  list.innerHTML = "";
  if (state.items.length === 0) {
    list.append(el("li", "empty", t("outlet.empty")));
    return;
  }
  state.items.forEach((item, index) => {
    const li = el("li");
    li.append(
      el(
        "span",
        null,
        t("plug.line", {
          name: item.name,
          w: item.power_watts,
          h: item.hours_per_day,
          qty: item.quantity > 1 ? t("plug.qty", { n: item.quantity }) : "",
        })
      )
    );
    const remove = el("button", "unplug", "✕");
    remove.type = "button";
    remove.title = t("title.remove");
    remove.addEventListener("click", () => {
      state.items.splice(index, 1);
      refresh();
    });
    li.append(remove);
    list.append(li);
  });
}

/* -------------------------------------------------------------------- events */

function bindEvents() {
  $("langToggle").addEventListener("click", () => {
    setLanguage(LANG === "en" ? "zh" : "en");
  });

  $("plan").addEventListener("change", (event) => {
    state.planId = event.target.value;
    refresh();
  });
  $("month").addEventListener("change", (event) => {
    state.month = event.target.value ? Number(event.target.value) : null;
    refresh();
  });
  $("circuit").addEventListener("change", (event) => {
    state.limitAmps = Number(event.target.value);
    $("ampsLimit").value = String(state.limitAmps);
    refresh();
  });
  $("ampsLimit").addEventListener("change", (event) => {
    const value = Number(event.target.value);
    if (value > 0) {
      state.limitAmps = value;
      refresh();
    }
  });
  $("margin").addEventListener("change", (event) => {
    state.margin = Number(event.target.value);
    refresh();
  });

  $("saveAll").addEventListener("click", saveAll);
  $("reload").addEventListener("click", () => loadSaved().catch((e) => toast(e.message, true)));
  $("clearAll").addEventListener("click", async () => {
    state.items = [];
    andThenClearSaved();
    refresh();
  });

  $("customToggle").addEventListener("click", () => {
    $("customForm").hidden = !$("customForm").hidden;
  });
  $("customCancel").addEventListener("click", () => {
    $("customForm").hidden = true;
  });
  $("customForm").addEventListener("submit", (event) => {
    event.preventDefault();

    const name = $("cName").value.trim();
    if (!name) {
      toast(t("err.name"), true);
      $("cName").focus();
      return;
    }

    const watts = readField("cWatts", {
      label: t("field.watts"), hint: t("hint.watts"), min: 0.1, max: 100000,
    });
    if (watts === undefined) return describeFieldError("cWatts");

    const volts = readField("cVolts", {
      label: t("field.volts"), hint: t("hint.volts"), min: 1, max: 1000, fallback: 110,
    });
    if (volts === undefined) return describeFieldError("cVolts");

    const hours = readField("cHours", {
      label: t("field.hours"), hint: t("hint.hours"), min: 0, max: 24,
    });
    if (hours === undefined) return describeFieldError("cHours");

    const days = readField("cDays", {
      label: t("field.days"), hint: t("hint.days"),
      min: 0, max: 31, integer: true, fallback: 30,
    });
    if (days === undefined) return describeFieldError("cDays");

    const qty = readField("cQty", {
      label: t("field.qty"), hint: t("hint.qty"),
      min: 1, max: 999, integer: true, fallback: 1,
    });
    if (qty === undefined) return describeFieldError("cQty");

    const item = {
      name,
      category: null,
      power_watts: watts,
      hours_per_day: hours,
      days_per_month: days,
      quantity: qty,
      voltage: volts,
      savedId: null,
    };
    state.items.push(item);
    $("customForm").reset();
    $("cVolts").value = "110";
    $("cDays").value = "30";
    $("cQty").value = "1";
    $("customForm").hidden = true;
    refresh();
  });
}

/** Highlight the field that failed so the message is easy to act on. */
function describeFieldError(id) {
  const node = $(id);
  if (!node) return;
  node.classList.add("field-error");
  node.focus();
  node.select?.();
  setTimeout(() => node.classList.remove("field-error"), 2000);
}

async function andThenClearSaved() {
  try {
    await api("/household/appliances", { method: "PUT", body: { appliances: [] } });
    $("saveNote").textContent = t("toast.cleared");
    toast(t("toast.cleared"));
  } catch (error) {
    toast(t("toast.clearFailed", { msg: error.message }), true);
  }
}

document.addEventListener("DOMContentLoaded", () => {
  boot().catch((error) => {
    console.error(error);
    toast(t("toast.bootFailed", { msg: error.message }), true);
  });
});
