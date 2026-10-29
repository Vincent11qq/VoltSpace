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
    toast(`請填「${label}」（${hint}）`, true);
    return undefined;
  }
  let value = parseNumber(raw);
  if (value === null) {
    toast(`「${label}」請填數字，例如 ${hint}`, true);
    return undefined;
  }
  if (integer) value = Math.round(value);
  if (min !== undefined && value < min) {
    toast(`「${label}」必須大於等於 ${min}`, true);
    return undefined;
  }
  if (max !== undefined && value > max) {
    toast(`「${label}」必須小於等於 ${max}`, true);
    return undefined;
  }
  return value;
}

/* -------------------------------------------------------------------- setup */

async function boot() {
  try {
    const health = await api("/health");
    $("conn").textContent = `後端 v${health.version}`;
    $("conn").className = "pill ok";
  } catch (error) {
    $("conn").textContent = "後端未連線";
    $("conn").className = "pill bad";
    toast("連不到後端，請確認伺服器是否啟動", true);
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
  renderPresets();
  await loadSaved();
  bindEvents();
}

function buildPlanSelect(tariffs) {
  const select = $("plan");
  select.innerHTML = "";
  for (const plan of tariffs.plans) {
    const option = el("option", null, plan.name_zh || plan.name_en || plan.id);
    option.value = plan.id;
    if (plan.id === tariffs.default_plan_id) option.selected = true;
    select.append(option);
  }
}

function buildMonthSelect() {
  const select = $("month");
  select.innerHTML = "";
  const any = el("option", null, "依目前季節");
  any.value = "";
  select.append(any);
  const now = new Date().getMonth() + 1;
  for (let month = 1; month <= 12; month += 1) {
    const option = el("option", null, `${month} 月`);
    option.value = String(month);
    if (month === now) option.selected = true;
    select.append(option);
  }
  state.month = now;
}

function buildCircuitSelect(presets) {
  const select = $("circuit");
  select.innerHTML = "";
  for (const circuit of presets.circuits) {
    const option = el(
      "option",
      null,
      `${circuit.label_zh}（${circuit.amps}A × ${circuit.voltage}V = ${circuit.max_watts}W）`
    );
    option.value = String(circuit.amps);
    if (circuit.amps === presets.default_circuit_amps) option.selected = true;
    select.append(option);
  }
  $("ampsLimit").value = String(presets.default_circuit_amps);
  $("margin").value = "0.8";
}

/* ------------------------------------------------------------------ presets */

function renderPresets() {
  const list = $("presets");
  list.innerHTML = "";
  for (const preset of state.presets) {
    const button = el("button", "preset");
    button.type = "button";
    button.title = `加入 ${preset.name_zh}`;

    const left = el("div");
    const name = el("div", "preset-name", preset.name_zh);
    if (preset.is_high_power) name.append(el("span", "high-power", " ⚡"));
    left.append(name);
    left.append(
      el(
        "div",
        "preset-meta",
        `${preset.power_watts}W · ${preset.voltage}V · ${preset.hours_per_day}h/日`
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
    name: preset.name_zh,
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
    ? `已儲存 ${listing.count} 台家電（每月約 ${fmt(listing.total_monthly_kwh)} 度）`
    : "目前沒有已儲存的家電，加入後按「儲存我的家電」。";
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
    toast(`已儲存 ${listing.count} 台家電`);
    await loadSaved();
  } catch (error) {
    toast(`儲存失敗：${error.message}`, true);
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
    toast(`計算失敗：${error.message}`, true);
  } finally {
    state.busy = false;
  }
}

function applyEmpty() {
  const outlet = $("outlet");
  outlet.className = "card outlet";
  $("status").textContent = "尚未接上電器";
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
    no_limit: "未設定迴路上限",
  }[summary.load_verdict] || "—";
  $("status").textContent = verdictText;
  $("status").className = `status ${severity}`.trim();

  const totalWatts = data.load ? data.load.total_power_watts : 0;
  $("watts").textContent = `${Math.round(totalWatts)} W` +
    (state.limitAmps ? ` / ${Math.round(state.limitAmps * 110)} W` : "");
  $("amps").textContent = data.load
    ? `${fmt(summary.estimated_total_current_amps, 2)} A（上限 ${fmt(state.limitAmps, 1)} A）`
    : "—";

  const ratio = state.limitAmps
    ? Math.min((summary.estimated_total_current_amps || 0) / state.limitAmps, 1)
    : 0;
  const bar = $("bar");
  bar.style.width = `${(ratio * 100).toFixed(1)}%`;
  bar.style.background = ratio >= 1 ? "var(--danger)" : ratio > state.margin ? "var(--warn)" : "var(--ok)";

  $("cost").textContent = `預估 ${fmt(summary.estimated_monthly_cost_twd, 0)} 元 / 月`;

  $("sKwh").textContent = `${fmt(summary.total_monthly_kwh, 1)} 度`;
  $("sCost").textContent = `${fmt(summary.estimated_monthly_cost_twd, 0)} 元`;
  $("sRate").textContent = `${fmt(summary.effective_rate_per_kwh, 2)} 元/度`;
  $("sSeason").textContent = summary.season_label_zh || "—";

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
    head.append(el("span", "muted", `${fmt(appliance.monthly_kwh, 1)} 度 · ${fmt(appliance.share_of_total_percent, 1)}%`));
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
    note.textContent = "目前沒有可提供的建議。";
    return;
  }
  note.textContent =
    `每月約可省 ${fmt(recommendations.total_potential_monthly_saving_kwh, 1)} 度` +
    `（${fmt(recommendations.total_potential_monthly_saving_twd, 0)} 元，` +
    `約 ${fmt(recommendations.potential_saving_percent_of_usage, 0)}% 用電）。`;

  for (const item of recommendations.recommendations) {
    const box = el("li", "rec");
    const head = el("div", "rec-head");
    head.append(el("span", `rec-sev ${item.severity}`, item.severity.toUpperCase()));
    head.append(el("span", "rec-title", item.title_zh));
    box.append(head);
    box.append(el("p", "muted", item.reason_zh));
    box.append(el("p", null, item.suggestion_zh));
    if (item.estimated_monthly_saving_kwh > 0) {
      box.append(
        el("p", "rec-saving",
          `預估每月省 ${fmt(item.estimated_monthly_saving_kwh, 1)} 度 / ` +
          `${fmt(item.estimated_monthly_saving_twd, 0)} 元`)
      );
    } else if (item.advice_only) {
      box.append(el("p", "muted small", "此為用電安全建議，未估算節省度數。"));
    }
    box.append(el("p", "small muted", `假設：${item.assumption_zh}`));
    list.append(box);
  }
}

function renderDisclaimer(data) {
  const list = $("disclaimer");
  list.innerHTML = "";
  const notes = new Set();
  if (data.load) {
    notes.add(data.load.disclaimer_zh);
    for (const warning of data.load.warnings) {
      if (warning.message_zh) notes.add(warning.message_zh);
    }
  }
  if (data.bill) {
    for (const warning of data.bill.warnings) {
      if (warning.message_zh) notes.add(warning.message_zh);
    }
  }
  if (data.recommendations) notes.add(data.recommendations.disclaimer_zh);
  for (const note of notes) list.append(el("li", null, note));
}

function renderPlugged() {
  const list = $("plugged");
  list.innerHTML = "";
  if (state.items.length === 0) {
    list.append(el("li", "empty", "點選左側家電或使用「自訂家電」加入"));
    return;
  }
  state.items.forEach((item, index) => {
    const li = el("li");
    li.append(el("span", null, `${item.name}（${item.power_watts}W · ${item.hours_per_day}h/日${item.quantity > 1 ? ` ×${item.quantity}` : ""}）`));
    const remove = el("button", "unplug", "✕");
    remove.type = "button";
    remove.title = "移除";
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
      toast("請填「名稱」，例如 除濕機", true);
      $("cName").focus();
      return;
    }

    const watts = readField("cWatts", { label: "功率", hint: "150 或 150W", min: 0.1, max: 100000 });
    if (watts === undefined) return describeFieldError("cWatts");

    const volts = readField("cVolts", { label: "電壓", hint: "110 或 110V", min: 1, max: 1000, fallback: 110 });
    if (volts === undefined) return describeFieldError("cVolts");

    const hours = readField("cHours", { label: "每日小時", hint: "0 到 24，例 6", min: 0, max: 24 });
    if (hours === undefined) return describeFieldError("cHours");

    const days = readField("cDays", {
      label: "每月天數", hint: "0 到 31", min: 0, max: 31, integer: true, fallback: 30,
    });
    if (days === undefined) return describeFieldError("cDays");

    const qty = readField("cQty", {
      label: "數量", hint: "1 到 999", min: 1, max: 999, integer: true, fallback: 1,
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
    $("saveNote").textContent = "已清除儲存的家電。";
    toast("已清除");
  } catch (error) {
    toast(`清除失敗：${error.message}`, true);
  }
}

document.addEventListener("DOMContentLoaded", () => {
  boot().catch((error) => {
    console.error(error);
    toast(`啟動失敗：${error.message}`, true);
  });
});
