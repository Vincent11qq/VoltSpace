"""
VoltSpace - Desktop frontend (Flet)   See the unseen power.

Member A's design; the numbers come from the FastAPI backend, not from this file.

    1) start the server    ->  run_app.bat   (from the repo root)
    2) start the desktop   ->  run_app.bat --flet

Every figure on screen is produced by the backend:

  appliances   /household/appliances      (stored in SQLite or Supabase)
  usage, bill  /household/dashboard       (consumption + bill + recommendations)
  circuit load /calculate/load            (only the appliances marked "used at the same time")
  catalogue    /appliances/presets
  tariff       /tariffs                   (read-only: rates live in the backend)

So the desktop window, the web page and the API docs always show the same numbers.

Only two things are local: the icon of each appliance and the "used at the same time"
switch. Those are interface preferences, not data. They live in desktop_prefs.json.

Backend location: VOLTSPACE_API (default http://127.0.0.1:8000).

Optional assets (used when present):
  assets/fonts/CormorantGaramond-Bold.ttf, assets/fonts/RozhaOne-Regular.ttf
  assets/plug_safe.png, plug_moderate.png, plug_danger.png, assets/profile.png
"""
import json
import os
import time
import urllib.error
import urllib.request

import flet as ft

W, H = 414, 896

YELLOW = "#FFC61A"
NAVY = "#0A0047"
CARD = "#0A0047"       # colour block
DARK = "#0A0B0E"       # background
WHITE = "#FFF4EA"
GREEN = "#2ECC71"
ORANGE = "#F39C12"
RED = "#E74C3C"

BODY_FONT_FILE = "assets/fonts/CormorantGaramond-Bold.ttf"
LOGO_FONT_FILE = "assets/fonts/RozhaOne-Regular.ttf"
FONTS = {}
if os.path.exists(BODY_FONT_FILE):
    FONTS["Cormorant"] = "fonts/CormorantGaramond-Bold.ttf"
if os.path.exists(LOGO_FONT_FILE):
    FONTS["Logo"] = "fonts/RozhaOne-Regular.ttf"
BODY = "Cormorant" if "Cormorant" in FONTS else None
LOGO = "Logo" if "Logo" in FONTS else None

ICONS = getattr(ft, "Icons", None) or getattr(ft, "icons")

# ==================================================================
# 資料層：所有數字都來自後端（這一層原本是前端自己算）
# ==================================================================
API = os.environ.get("VOLTSPACE_API", "http://127.0.0.1:8000").rstrip("/")

# 圖示與「是否同時使用」是介面偏好，不是資料，所以留在本機。
PREFS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "desktop_prefs.json")


class ApiError(RuntimeError):
    """The backend refused the request or could not be reached."""


def request(path, *, method="GET", payload=None, timeout=25):
    """Minimal JSON client. urllib keeps Flet dependency-free."""
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{API}{path}",
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        raw = error.read().decode("utf-8", "replace")
        try:
            detail = json.loads(raw)
        except ValueError:
            raise ApiError(f"HTTP {error.code} from {path}") from error
        message = detail.get("message") or f"HTTP {error.code}"
        field = detail.get("field")
        raise ApiError(f"{message}" + (f" ({field})" if field else "")) from error
    except urllib.error.URLError as error:
        raise ApiError(f"cannot reach {API} - start the backend first ({error.reason})") from error
    return json.loads(body) if body else None


# 圖示：用後端家電庫的 key 對應。查不到的一律用 POWER，不會因缺少圖示而崩潰。
def _icon(name):
    return getattr(ICONS, name, ICONS.POWER)


ICON_MAP = {
    "air_conditioner": _icon("AC_UNIT"),
    "refrigerator": _icon("KITCHEN"),
    "washing_machine": _icon("LOCAL_LAUNDRY_SERVICE"),
    "microwave": _icon("MICROWAVE"),
    "hair_dryer": _icon("AIR"),
    "tv": _icon("TV"),
    "electric_fan": _icon("TOYS"),
    "desktop_computer": _icon("POWER"),
    "lighting": _icon("LIGHTBULB_OUTLINE"),
    "rice_cooker": _icon("KITCHEN"),
    "electric_water_heater": _icon("POWER"),
    "electric_heater": _icon("POWER"),
    "custom": ICONS.POWER,
}

# 後端 verdict -> 這個介面使用的三種顏色 / 中性用語（不寫「安全」）
VERDICT_UI = {
    "safe": "safe",
    "near_limit": "near",
    "over_limit": "over",
    "no_limit": "none",
}
STATUS_LABEL = {
    "safe": "WITHIN MARGIN",
    "near": "NEAR LIMIT",
    "over": "OVER LIMIT",
    "none": "NO LIMIT SET",
}
STATUS_COLOR = {"safe": GREEN, "near": ORANGE, "over": RED, "none": "#888888"}

# 由 Store.reload() 從 /appliances/presets 填入：(顯示名稱, key, 瓦數, 每日時數)
PRESETS = []
# 由 Store.reload() 填入：名稱（中英）-> preset key，用來決定圖示
NAME_INDEX = {}


def guess_icon(name):
    return NAME_INDEX.get(str(name).strip().lower(), "custom")


def icon_of(a):
    return ICON_MAP.get(a.get("icon") or "custom", ICONS.POWER)


# ------------------------------------------------------------------ 純呈現輔助
def kwh_of(a):
    """Per-appliance monthly kWh, as computed by the backend."""
    return a.get("kwh") or 0.0


def total_kwh(st):
    return st.get("total_kwh") or 0.0


def bill_of(st, kwh=None):
    return st.get("bill") or 0.0


def cost_breakdown(st):
    """(bill, total kWh, [(appliance, kWh, cost)]) - cost is the bill's share."""
    tk = total_kwh(st)
    bill = bill_of(st)
    rows = []
    for a in st["appliances"]:
        k = kwh_of(a)
        rows.append((a, k, bill * k / tk if tk else 0.0))
    return bill, tk, rows


def safety_of(st):
    """(percent of limit used, ui key, watts in use, limit watts) from /calculate/load."""
    load = st.get("load") or {}
    key = VERDICT_UI.get(load.get("verdict") or "no_limit", "none")
    used = load.get("total_power_watts") or 0.0
    limit = load.get("limit_watts") or 0.0
    pct = (used / limit * 100.0) if limit else 0.0
    return pct, key, used, limit


def load_line(used, limit):
    if not limit:
        return f"{used:,.0f} W (no circuit limit set)"
    return f"{used:,.0f} W / {limit:,.0f} W  ({used / limit * 100:.0f}% of limit)"


def record_safety(st):
    """Log a line when the backend's verdict changes. Never claims safety."""
    load = st.get("load") or {}
    key = VERDICT_UI.get(load.get("verdict") or "no_limit", "none")
    if st.get("last_status") is None:
        st["last_status"] = key
        return
    if key != st["last_status"]:
        used = load.get("total_power_watts") or 0.0
        limit = load.get("limit_watts") or 0.0
        st["logs"].insert(0, {
            "time": time.strftime("%Y-%m-%d %H:%M"),
            "status": key,
            "pct": round(used / limit * 100) if limit else None,
            "detail": load_line(used, limit),
        })
        st["logs"] = st["logs"][:50]
    st["last_status"] = key


def make_suggestions(st):
    if st.get("error"):
        return [f"Backend unreachable: {st['error']}"]
    if not st["appliances"]:
        return ["Add your appliances first, then VoltSpace can give you suggestions."]
    recs = st.get("recs") or []
    if not recs:
        return ["No suggestions right now - your usage looks typical for these appliances."]
    tips = []
    for r in recs[:6]:
        title = r.get("title_en") or r.get("title_zh") or ""
        body = r.get("suggestion_en") or r.get("suggestion_zh") or ""
        line = f"{title}\n{body}"
        saving = r.get("estimated_monthly_saving_twd") or 0
        if saving:
            line += f"\nSave about NT$ {saving:,.0f} / month"
        tips.append(line)
    return tips


def product_tips(st):
    """Product advice from /product-recommendations, one line per product."""

    rows = st.get("products") or []
    if not rows:
        return []
    lines = []
    for item in rows[:4]:
        name = " ".join(
            part for part in (item.get("brand"), item.get("product_name")) if part
        ).strip() or "Suggested product"
        saving = item.get("estimated_savings_cost")
        money = f"Save about NT$ {saving:,.0f} / month" if saving else "Lower power draw"
        price = item.get("price")
        price_line = f"NT$ {price:,.0f}" if price else ""
        lines.append(f"{name}\nFor your {item.get('appliance') or 'appliance'}: {money}"
                     + (f"\n{price_line}" if price_line else ""))
    return lines


def default_state():
    return {
        "appliances": [],
        "amps": 15.0,
        "volts": 110.0,
        "plan_id": None,
        "plan_name": "",
        "season": "",
        "rate": None,
        "bill": 0.0,
        "total_kwh": 0.0,
        "load": {},
        "recs": [],
        "products": [],
        "error": None,
        "logs": [],
        "last_status": None,
    }


def to_api(a):
    """UI appliance -> ApplianceIn (no icon / on: those are local only)."""
    return {
        "name": a["name"],
        "power_watts": a["watts"],
        "hours_per_day": a["hours"],
        "days_per_month": a["days"],
        "quantity": 1,
    }


class Store:
    """The backend's saved household, plus the local interface preferences."""

    def __init__(self, prefs_path=PREFS_FILE):
        self.path = prefs_path
        self.prefs = {}
        self.st = default_state()
        self._read_prefs()
        self.reload()

    # --- local preferences -------------------------------------------------
    def _read_prefs(self):
        try:
            with open(self.path, encoding="utf-8") as handle:
                loaded = json.load(handle)
            if isinstance(loaded, dict):
                self.prefs = loaded
        except Exception:
            self.prefs = {}

    def _write_prefs(self):
        try:
            with open(self.path, "w", encoding="utf-8") as handle:
                json.dump(self.prefs, handle, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def remember(self, name, icon=None, on=None):
        entry = self.prefs.setdefault(str(name).strip().lower(), {})
        if icon:
            entry["icon"] = icon
        if on is not None:
            entry["on"] = bool(on)
        self._write_prefs()

    # --- backend ----------------------------------------------------------
    def reload(self):
        st = self.st
        st["error"] = None
        try:
            presets = request("/appliances/presets")
            tariffs = request("/tariffs")
            saved = request("/household/appliances")
        except ApiError as error:
            st["error"] = str(error)
            st["products"] = []
            return

        # Product advice is optional: an empty catalogue or no Supabase simply means
        # nothing to show, never an error banner.
        try:
            products = request(
                "/product-recommendations",
                method="POST",
                payload={
                    "appliances": [to_api(a) for a in st["appliances"]],
                    **({"plan_id": st["plan_id"]} if st.get("plan_id") else {}),
                },
            )
            st["products"] = products.get("recommendations") or []
        except ApiError:
            st["products"] = []
            return

        PRESETS[:] = [
            (p["name_en"], p["key"], p["power_watts"], p["hours_per_day"])
            for p in presets["presets"]
        ]
        NAME_INDEX.clear()
        for p in presets["presets"]:
            NAME_INDEX[str(p["name_en"]).lower()] = p["key"]
            NAME_INDEX[str(p["name_zh"]).lower()] = p["key"]

        if not st.get("amps"):
            st["amps"] = float(presets["default_circuit_amps"])
        if not st.get("volts"):
            st["volts"] = float(presets["default_voltage"])
        if not st.get("plan_id"):
            st["plan_id"] = tariffs["default_plan_id"]
        st["plan_name"] = next(
            (p["name_en"] for p in tariffs["plans"] if p["id"] == st["plan_id"]), st["plan_id"]
        )

        st["appliances"] = [
            {
                "id": row["id"],
                "name": row["name"],
                "icon": self.prefs.get(str(row["name"]).lower(), {}).get("icon")
                or guess_icon(row["name"]),
                "watts": row["power_watts"],
                "hours": row["hours_per_day"],
                "days": row["days_per_month"],
                "on": self.prefs.get(str(row["name"]).lower(), {}).get("on", True),
                "kwh": 0.0,
            }
            for row in saved["appliances"]
        ]
        self._recalculate()

    def _recalculate(self):
        """One dashboard call for usage/bill/advice, one load call for the circuit."""
        st = self.st
        if not st["appliances"]:
            st["bill"], st["total_kwh"], st["load"], st["recs"], st["rate"] = 0.0, 0.0, {}, [], None
            st["products"] = []
            return
        payload = {
            "appliances": [to_api(a) for a in st["appliances"]],
            "load_limit_amps": st["amps"],
            "voltage": st["volts"],
            "safety_margin": 0.8,
            "include_recommendations": True,
            "max_recommendations": 6,
        }
        if st.get("plan_id"):
            payload["plan_id"] = st["plan_id"]
        try:
            dash = request("/household/dashboard", method="POST", payload=payload)
            marked = [to_api(a) for a in st["appliances"] if a.get("on")]
            load = request(
                "/calculate/load",
                method="POST",
                payload={
                    "appliances": marked or [to_api(a) for a in st["appliances"]],
                    "voltage": st["volts"],
                    "load_limit_amps": st["amps"],
                    "safety_margin": 0.8,
                },
            )
        except ApiError as error:
            st["error"] = str(error)
            return

        st["bill"] = dash["bill"]["total_amount"]
        st["total_kwh"] = dash["consumption"]["total_monthly_kwh"]
        st["season"] = dash["bill"].get("season_label_en") or ""
        st["rate"] = dash["summary"].get("effective_rate_per_kwh")
        for appliance, row in zip(st["appliances"], dash["consumption"]["appliances"]):
            appliance["kwh"] = row["monthly_kwh"]
        st["load"] = load
        st["recs"] = (dash.get("recommendations") or {}).get("recommendations") or []
        record_safety(st)

    # --- actions ----------------------------------------------------------
    def save(self):
        """Replace the stored list with what the UI currently holds."""
        try:
            request(
                "/household/appliances",
                method="PUT",
                payload={"appliances": [to_api(a) for a in self.st["appliances"]]},
            )
        except ApiError as error:
            self.st["error"] = str(error)
            return False
        self.reload()
        return True

    def load_sample(self):
        self.st["appliances"] = []
        for name, key, watts, hours in PRESETS[:5]:
            self.st["appliances"].append(
                {"name": name, "icon": key, "watts": watts, "hours": hours,
                 "days": 30, "on": True, "kwh": 0.0}
            )
        self.save()

    def clear(self):
        self.st["appliances"] = []
        self.save()
        self.st["logs"] = []
        self.st["last_status"] = None


# ==================================================================
# UI 小工具
# ==================================================================
def viewport(page, fallback_w=None, fallback_h=None):
    """The frame to draw in: the design size, shrunk to the real viewport.

    A phone browser is narrower and shorter than the 414x896 design frame (an iPhone
    reports about 390x700 CSS pixels once the browser chrome is subtracted). Drawing a
    fixed larger frame clipped the right-hand column and pushed the bottom navigation
    off-screen, so every screen is built into this instead.
    """

    width = getattr(page, "width", None) or fallback_w or W
    height = getattr(page, "height", None) or fallback_h or H
    # Never grow beyond the design frame; a wide desktop window gets the phone layout.
    return int(min(width, W)), int(min(height, H))


def radius(tl=0, tr=0, bl=0, br=0):
    return ft.BorderRadius(top_left=tl, top_right=tr, bottom_left=bl, bottom_right=br)


def pad(left=0, top=0, right=0, bottom=0):
    return ft.Padding(left=left, top=top, right=right, bottom=bottom)


def center():
    return ft.Alignment(0, 0)


def txt(value, size=16, color=WHITE, bold=False, font=BODY, italic=False, align=None):
    return ft.Text(
        value, size=size, color=color,
        weight=ft.FontWeight.BOLD if bold else ft.FontWeight.NORMAL,
        font_family=font, italic=italic, text_align=align,
    )


def circle(icon, size, bg, fg, icon_size):
    return ft.Container(
        content=ft.Icon(icon, color=fg, size=icon_size),
        width=size, height=size, border_radius=size / 2, bgcolor=bg, alignment=center(),
    )


def logo(color=WHITE):
    return ft.Column(
        [txt("Volt", 20, color, True, LOGO, True), txt("Space", 20, color, True, LOGO, True)],
        spacing=0, tight=True,
    )


def button(label, on_click, bg=YELLOW, fg=NAVY, height=50):
    return ft.Container(
        content=txt(label, 20, fg, True), alignment=center(),
        height=height, bgcolor=bg, border_radius=height / 2, on_click=on_click,
    )


def field(label, value="", number=False, disabled=False, width=None):
    return ft.TextField(
        label=label,
        value="" if value is None else str(value),
        keyboard_type=ft.KeyboardType.NUMBER if number else ft.KeyboardType.TEXT,
        bgcolor=WHITE, filled=True, border=ft.InputBorder.NONE, border_radius=14,
        color=NAVY, cursor_color=NAVY, disabled=disabled, width=width,
        label_style=ft.TextStyle(color=NAVY, size=14, font_family=BODY, weight=ft.FontWeight.BOLD),
        text_style=ft.TextStyle(color=NAVY, size=18, font_family=BODY, weight=ft.FontWeight.BOLD),
    )


def parse_num(s, lo, hi):
    try:
        v = float(str(s).strip())
    except Exception:
        return None
    return v if lo <= v <= hi else None


def fmt_hours(h):
    return f"{h:g}"


# ==================================================================
# 共用版面
# ==================================================================
def bottom_nav(app):
    items = []
    for key, label, icon in [
        ("home", "Home", ICONS.HOME),
        ("logs", "Safety Logs", ICONS.VERIFIED_USER),
        ("appliances", "My appliances", ICONS.BOLT),
        ("settings", "Settings", ICONS.SETTINGS),
    ]:
        items.append(ft.Container(
            content=ft.Column([ft.Icon(icon, color=NAVY, size=38), txt(label, 15, NAVY, True)],
                              spacing=0, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
            on_click=lambda e, k=key: app.go(k),
        ))
    return ft.Container(
        content=ft.Row(items, alignment=ft.MainAxisAlignment.SPACE_AROUND),
        height=100, bgcolor=YELLOW, border_radius=radius(tl=30, tr=30), padding=pad(left=5, right=5, top=8),
    )


def yellow_header(app, title, size=40, back=None):
    if back:
        left = ft.Container(
            ft.Icon(ICONS.ARROW_BACK, color=NAVY, size=32), left=20, top=45,
            on_click=lambda e: app.go(back),
        )
    else:
        left = ft.Container(logo(NAVY), left=22, top=40)
    return ft.Container(
        content=ft.Stack([
            left,
            ft.Container(txt(title, size, NAVY, True, align=ft.TextAlign.CENTER),
                         alignment=center(), left=0, right=0, top=0, bottom=0),
        ]),
        height=125, bgcolor=YELLOW, border_radius=radius(bl=30, br=30),
    )


def scroll_body(controls, left=42, right=42, top=30, spacing=14):
    return ft.Container(
        content=ft.Column(controls, spacing=spacing, scroll=ft.ScrollMode.AUTO),
        padding=pad(left=left, right=right, top=top, bottom=10), expand=True,
    )


# ==================================================================
# Home
# ==================================================================
SEARCH_INDEX = {
    "cost": ["cost", "estimation", "bill", "price", "電費"],
    "load": ["load", "24", "profile"],
    "suggest": ["suggest", "tip", "建議"],
    "guide": ["guide", "help", "說明"],
    "appliances": ["appliance", "device", "家電"],
    "logs": ["safety", "log", "安全"],
    "settings": ["setting", "tariff", "breaker", "設定"],
}


def home_header(app):
    def do_search(e):
        q = (e.control.value or "").strip().lower()
        for target, words in SEARCH_INDEX.items():
            if q and any(w in q or q in w for w in words):
                app.go(target)
                return
        e.control.value = ""
        e.control.hint_text = "No match, try 'cost'"
        app.page.update()

    sf = ft.TextField(
        hint_text="Search functions...",
        hint_style=ft.TextStyle(color=NAVY, size=16, font_family=BODY, weight=ft.FontWeight.BOLD),
        text_style=ft.TextStyle(color=NAVY, size=16, font_family=BODY, weight=ft.FontWeight.BOLD),
        border=ft.InputBorder.NONE, expand=True,
        content_padding=pad(), cursor_color=NAVY, on_submit=do_search,
    )
    search = ft.Container(
        content=ft.Row([sf, ft.Icon(ICONS.SEARCH, color=NAVY, size=24)],
                       vertical_alignment=ft.CrossAxisAlignment.CENTER),
        width=228, height=42, bgcolor=YELLOW, border_radius=21, padding=pad(left=22, right=14),
    )
    if os.path.exists("assets/profile.png"):
        avatar = ft.Container(ft.Image(src="profile.png", width=40, height=40),
                              width=40, height=40, border_radius=20, clip_behavior=ft.ClipBehavior.ANTI_ALIAS)
    else:
        avatar = circle(ICONS.PERSON, 40, "#E6E6E6", "#888888", 26)
    profile = ft.Column([avatar, txt("Profile", 12, WHITE, True)], spacing=2,
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER, tight=True)
    return ft.Container(
        content=ft.Row([logo(WHITE), search, profile], alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                       vertical_alignment=ft.CrossAxisAlignment.CENTER),
        height=125, bgcolor=NAVY, border_radius=radius(bl=40, br=40), padding=pad(left=20, right=22, top=18),
    )


def plug_graphic(key, color):
    path = f"assets/plug_{key}.png"
    if os.path.exists(path):
        return ft.Image(src=f"plug_{key}.png", width=250, height=200)
    return ft.Stack([
        ft.Icon(ICONS.POWER_OUTLINED, color=color, size=110, left=0, top=20),
        ft.Icon(ICONS.BOLT, color=color, size=200, left=60, top=0),
        ft.Icon(ICONS.POWER_OUTLINED, color=color, size=110, left=140, top=70),
    ], width=260, height=200)


def home_screen(app, p):
    st = app.store.st
    score, key, load, cap = safety_of(st)
    color = STATUS_COLOR[key]

    def action(icon, label, target):
        return ft.Container(
            content=ft.Row([circle(icon, 36, YELLOW, NAVY, 26), txt(label, 17, WHITE, True)], spacing=10),
            on_click=lambda e: app.go(target, **({"mode": "add"} if target == "form" else {})),
        )

    quick = ft.Container(
        content=ft.Row([action(ICONS.ADD, "Add appliance", "form"), action(ICONS.CHECK, "Safety logs", "logs")],
                       alignment=ft.MainAxisAlignment.SPACE_AROUND,
                       vertical_alignment=ft.CrossAxisAlignment.CENTER),
        height=75, bgcolor=CARD, border_radius=20,
    )

    # Four fixed 88px cells do not fit a 390px phone (they were clipped on the right),
    # so the cell width follows the frame and the row is allowed to wrap.
    gaps = 8
    cell_w = max(68, int((app.size[0] - 84 - 3 * gaps) / 4))
    cells = []
    for target, label, icon in [
        ("cost", "Cost\nEstimation", ICONS.PAYMENTS_OUTLINED),
        ("load", "24-hour\nload profile", ICONS.INSIGHTS),
        ("suggest", "Suggestion", ICONS.LIGHTBULB_OUTLINE),
        ("guide", "App guide", ICONS.SEARCH),
    ]:
        cells.append(ft.Container(
            content=ft.Column([
                ft.Container(ft.Icon(icon, color=YELLOW, size=28), width=44, height=44,
                             bgcolor=CARD, border_radius=4, alignment=center()),
                txt(label, 11, WHITE, True, align=ft.TextAlign.CENTER),
            ], spacing=4, horizontal_alignment=ft.CrossAxisAlignment.CENTER, tight=True),
            width=cell_w, on_click=lambda e, t=target: app.go(t),
        ))

    banner = []
    if st.get("error"):
        banner = [ft.Container(
            txt(f"Backend unreachable: {st['error']}", 13, RED, True),
            bgcolor=CARD, border_radius=16, padding=pad(left=14, right=14, top=10, bottom=10),
        )]
    body = scroll_body(banner + [
        quick,
        ft.Container(height=8),
        txt("Functions", 22, WHITE, True),
        ft.Row(cells, alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
               vertical_alignment=ft.CrossAxisAlignment.START,
               spacing=gaps, run_spacing=12, wrap=True),
        ft.Container(height=8),
        txt("Safety Status", 22, WHITE, True),
        ft.Container(txt(STATUS_LABEL[key], 38, WHITE, True), alignment=center()),
        # Member A's big figure, re-described: a percentage of the circuit limit is a
        # fact from /calculate/load, not a safety rating.
        ft.Container(
            txt(f"{score:.0f}% of limit" if cap else "-", 30, color, True),
            alignment=center(),
        ),
        ft.Container(txt(load_line(load, cap), 14, "#BBBBBB", True), alignment=center()),
        ft.Container(txt("Estimate from the backend - not a guarantee of electrical safety.",
                         11, "#888888", True), alignment=center()),
        ft.Container(plug_graphic(key, color), alignment=center()),
    ], spacing=8)
    return home_header(app), body


# ==================================================================
# My appliances + 新增/編輯表單
# ==================================================================
def appliance_card(app, a):
    return ft.Container(
        content=ft.Row([
            ft.Row([circle(ICON_MAP.get(a["icon"], ICONS.POWER), 36, YELLOW, NAVY, 24),
                    txt(a["name"], 18, WHITE, True)], spacing=12),
            txt(f"Monthly Usage\n{kwh_of(a):,.1f} kWh", 14, YELLOW, True, align=ft.TextAlign.CENTER),
        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        height=52, bgcolor=CARD, border_radius=26, padding=pad(left=14, right=22),
        on_click=lambda e, i=a["id"]: app.go("form", mode="edit", id=i),
    )


def appliances_screen(app, p):
    st = app.store.st
    items = [appliance_card(app, a) for a in st["appliances"]]
    if not items:
        items.append(ft.Container(
            txt("No appliances yet.\nTap 'Or dial manually' to add one.", 18, "#BBBBBB", True,
                align=ft.TextAlign.CENTER),
            alignment=center(), height=90))
    manual = ft.Container(
        content=ft.Row([circle(ICONS.EDIT, 36, YELLOW, NAVY, 22), txt("Or dial manually", 18, WHITE, True)], spacing=12),
        height=64, bgcolor=CARD, border_radius=26, padding=pad(left=14, right=22),
        on_click=lambda e: app.go("form", mode="add"),
    )
    return yellow_header(app, "My appliances", 38), scroll_body(items + [manual], top=40, spacing=24)


def form_screen(app, p):
    st = app.store.st
    edit = next((a for a in st["appliances"] if a["id"] == p.get("id")), None) if p.get("mode") == "edit" else None

    name_tf = field("Appliance name", edit["name"] if edit else "")
    watts_tf = field("Power (W)", f"{edit['watts']:g}" if edit else "", number=True)
    hours_tf = field("Hours per day", fmt_hours(edit["hours"]) if edit else "", number=True)
    days_tf = field("Days per month", f"{edit['days']:g}" if edit else "30", number=True)
    on_sw = ft.Switch(value=edit["on"] if edit else True, active_color=YELLOW)
    msg = txt("", 15, RED, True)
    icon_key = {"v": edit["icon"] if edit else "custom"}

    def set_msg(t):
        msg.value = t
        app.page.update()

    def preset(pr):
        name_tf.value, icon_key["v"] = pr[0], pr[1]
        watts_tf.value, hours_tf.value = f"{pr[2]:g}", f"{pr[3]:g}"
        app.page.update()

    def save(e):
        name = (name_tf.value or "").strip()
        w = parse_num(watts_tf.value, 1, 10000)
        h = parse_num(hours_tf.value, 0, 24)
        d = parse_num(days_tf.value, 1, 31)
        if not name:
            return set_msg("Please enter a name.")
        if w is None:
            return set_msg("Power must be 1 - 10000 W.")
        if h is None:
            return set_msg("Hours per day must be 0 - 24.")
        if d is None:
            return set_msg("Days per month must be 1 - 31.")
        row = {"name": name, "power_watts": w, "hours_per_day": h, "days_per_month": d}
        try:
            if edit:
                request(f"/household/appliances/{edit['id']}", method="PUT", payload=row)
            else:
                request("/household/appliances", method="POST", payload={"appliance": row})
        except ApiError as error:
            return set_msg(str(error))
        # icon and the "used at the same time" switch are UI preferences: kept locally.
        app.store.remember(name, icon=icon_key["v"], on=bool(on_sw.value))
        app.store.reload()
        app.go("appliances")

    def delete(e):
        try:
            request(f"/household/appliances/{edit['id']}", method="DELETE")
        except ApiError as error:
            return set_msg(str(error))
        app.store.reload()
        app.go("appliances")

    controls = []
    if not edit:
        controls.append(txt("Quick fill", 18, WHITE, True))
        controls.append(ft.Row(
            [ft.Container(txt(pr[0], 14, NAVY, True), bgcolor=YELLOW, border_radius=16,
                          padding=pad(left=12, right=12, top=6, bottom=6),
                          on_click=lambda e, pr=pr: preset(pr)) for pr in PRESETS],
            wrap=True, spacing=8, run_spacing=8))
    controls += [
        name_tf, watts_tf, hours_tf, days_tf,
        ft.Row([txt("Used at the same time", 18, WHITE, True), on_sw],
               alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
        msg,
        button("Save", save),
    ]
    if edit:
        controls.append(button("Delete", delete, bg=RED, fg=WHITE))
    controls.append(button("Cancel", lambda e: app.go("appliances"), bg=CARD, fg=WHITE))
    title = "Edit\nappliance" if edit else "Add\nappliance"
    return yellow_header(app, title, 32, back="appliances"), scroll_body(controls, top=20)


# ==================================================================
# Cost Estimation
# ==================================================================
def cost_screen(app, p):
    st = app.store.st
    bill, tk, rows = cost_breakdown(st)
    top = ft.Container(
        content=txt(f"MONTHLY COST\nNT$ {bill:,.0f}", 28, NAVY, True, align=ft.TextAlign.CENTER),
        bgcolor=YELLOW, alignment=center(), height=84)
    bottom = ft.Container(
        content=ft.Row([
            ft.Column([txt("Daily Cost", 12, WHITE, True), txt(f"NT$ {bill / 30:,.0f}", 17, WHITE, True)], spacing=2),
            ft.Column([txt("Monthly Usage", 12, WHITE, True), txt(f"{tk:,.0f} kWh", 17, WHITE, True)], spacing=2),
        ], spacing=70),
        bgcolor=CARD, height=50, padding=pad(left=30, top=2))
    summary = ft.Container(content=ft.Column([top, bottom], spacing=0), border_radius=20,
                           clip_behavior=ft.ClipBehavior.ANTI_ALIAS)

    def row(a, k, c):
        return ft.Container(
            content=ft.Row([
                ft.Row([circle(ICON_MAP.get(a["icon"], ICONS.POWER), 52, NAVY, YELLOW, 30),
                        txt(a["name"], 22, NAVY, True)], spacing=10),
                txt(f"Monthly Cost\nNT$ {c:,.0f}", 15, NAVY, True, align=ft.TextAlign.CENTER),
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            height=76, bgcolor=YELLOW, border_radius=24, padding=pad(left=12, right=18))

    head = ft.Container(content=txt("COST BREAKDOWN", 28, NAVY, True), bgcolor=YELLOW, alignment=center(), height=52)
    rlist = [row(*r) for r in rows] or [ft.Container(txt("Add appliances to see the breakdown.", 16, WHITE, True),
                                                      alignment=center(), height=60)]
    breakdown = ft.Container(
        content=ft.Column([head, ft.Container(ft.Column(rlist, spacing=20),
                                              padding=pad(left=16, right=16, top=20, bottom=16))], spacing=0),
        bgcolor=CARD, border_radius=20, clip_behavior=ft.ClipBehavior.ANTI_ALIAS)
    return yellow_header(app, "Cost\nEstimation", 34), scroll_body([summary, breakdown], left=15, right=15, top=18)


# ==================================================================
# Safety Logs / Suggestion / App guide / Load profile
# ==================================================================
def logs_screen(app, p):
    st = app.store.st

    def clear(e):
        st["logs"] = []
        app.store.save()
        app.go("logs")

    cards = []
    for lg in st["logs"]:
        c = STATUS_COLOR.get(lg["status"], GREEN)
        cards.append(ft.Container(
            content=ft.Row([
                circle(ICONS.WARNING_AMBER if lg["status"] != "safe" else ICONS.CHECK, 40, c, WHITE, 26),
                ft.Column([
                    txt(STATUS_LABEL.get(lg["status"], lg["status"])
                        + (f" - {lg['pct']}% of limit" if lg.get("pct") is not None else ""),
                        20, WHITE, True),
                    txt(lg["detail"], 13, "#CCCCCC", True),
                    txt(lg["time"], 12, YELLOW, True),
                ], spacing=1, expand=True),
            ], spacing=12),
            bgcolor=CARD, border_radius=20, padding=pad(left=14, right=14, top=10, bottom=10)))
    if not cards:
        cards.append(ft.Container(txt("No safety events yet.", 18, "#BBBBBB", True), alignment=center(), height=80))
    else:
        cards.append(button("Clear logs", clear, bg=CARD, fg=WHITE, height=44))
    return yellow_header(app, "Safety Logs", 38), scroll_body(cards, top=30)


def suggest_screen(app, p):
    st = app.store.st

    def card(text, icon, tint=YELLOW):
        return ft.Container(
            content=ft.Row([circle(icon, 40, tint, NAVY, 26),
                            ft.Column([txt(text, 16, WHITE, True)], expand=True)], spacing=12,
                           vertical_alignment=ft.CrossAxisAlignment.START),
            bgcolor=CARD, border_radius=20,
            padding=pad(left=14, right=14, top=12, bottom=12))

    controls = [card(t, ICONS.LIGHTBULB_OUTLINE) for t in make_suggestions(st)]

    products = product_tips(st)
    if products:
        controls.append(txt("Products worth buying", 20, WHITE, True))
        controls += [card(t, ICONS.SHOPPING_BAG_OUTLINED) for t in products]

    return yellow_header(app, "Suggestion", 38, back="home"), scroll_body(controls, top=30)


def guide_screen(app, p):
    steps = [
        "1. Go to My appliances and tap 'Or dial manually' to register a device (power, hours per day, days per month).",
        "2. Turn on 'Used at the same time' for devices that may run together. This drives your Safety Status.",
        "3. Open Cost Estimation to see your monthly bill and each appliance's share.",
        "4. Set your breaker amps and voltage in Settings. The tariff is read-only there: rates live in the backend's tariff table, so every screen quotes the official rate.",
        "5. Check Suggestion for ways to lower cost and avoid overloads.",
    ]
    cards = [ft.Container(txt(s, 16, WHITE, True), bgcolor=CARD, border_radius=20,
                          padding=pad(left=16, right=16, top=12, bottom=12)) for s in steps]
    return yellow_header(app, "App guide", 38, back="home"), scroll_body(cards, top=30)


def load_screen(app, p):
    """24 小時負載圖:假設每個家電在『同一個時段』使用,依每日使用時數估算,先做簡易版"""
    st = app.store.st
    body = scroll_body([
        ft.Container(txt("Coming soon:\nhourly load chart needs a start time\nfor each appliance.",
                         18, "#BBBBBB", True, align=ft.TextAlign.CENTER), alignment=center(), height=200)
    ])
    return yellow_header(app, "24-hour\nload profile", 30, back="home"), body


# ==================================================================
# Settings
# ==================================================================
def settings_screen(app, p):
    st = app.store.st
    amps_tf = field("Breaker (A)", f"{st['amps']:g}", number=True)
    volts_tf = field("Voltage (V)", f"{st['volts']:g}", number=True)
    msg = txt("", 15, RED, True)

    def save(e):
        a = parse_num(amps_tf.value, 1, 200)
        v = parse_num(volts_tf.value, 1, 500)
        if a is None or v is None:
            msg.value = "Breaker / voltage value is invalid."
            msg.color = RED
            return app.page.update()
        st["amps"], st["volts"] = a, v
        app.store.reload()          # the backend recalculates with the new circuit
        msg.value = "Saved. Numbers recalculated by the backend."
        msg.color = GREEN
        app.page.update()

    def load_sample(e):
        app.store.load_sample()
        app.go("appliances")

    def clear_all(e):
        app.store.clear()
        app.go("home")

    rate = st.get("rate")
    controls = [
        txt("Circuit", 22, WHITE, True),
        amps_tf, volts_tf,
        txt(f"Backend uses {st['amps']:g} A x {st['volts']:g} V "
            f"= {st['amps'] * st['volts']:,.0f} W as the limit.", 13, "#BBBBBB", True),
        txt("Electricity tariff", 22, WHITE, True),
        txt(f"Plan: {st.get('plan_name') or '-'}", 13, "#BBBBBB", True),
        txt(f"Season: {st.get('season') or '-'}", 13, "#BBBBBB", True),
        txt(f"Current rate: NT$ {rate:.2f} / kWh" if rate else "Current rate: -", 13, "#BBBBBB", True),
        txt("Read-only. Rates come from the backend's tariff table, so this window, "
            "the web page and the API always agree.", 13, "#BBBBBB", True),
        msg,
        button("Save settings", save),
        button("Load sample appliances", load_sample, bg=CARD, fg=WHITE),
        button("Clear all data", clear_all, bg=RED, fg=WHITE),
    ]
    return yellow_header(app, "Settings", 38), scroll_body(controls, top=20)


SCREENS = {
    "home": home_screen, "appliances": appliances_screen, "form": form_screen,
    "cost": cost_screen, "logs": logs_screen, "suggest": suggest_screen,
    "guide": guide_screen, "load": load_screen, "settings": settings_screen,
}


# ==================================================================
# App
# ==================================================================
class App:
    def __init__(self, page, store=None):
        self.page = page
        self.store = store or Store()
        self.holder = ft.Container()
        self.size = viewport(page)
        self.current = None

    def build(self, name, **params):
        # Screens lay themselves out for this size (see home_screen's function grid).
        self.size = viewport(self.page)
        header, body = SCREENS[name](self, params)
        return ft.Container(
            content=ft.Column([header, body, bottom_nav(self)], spacing=0),
            width=self.size[0], height=self.size[1], bgcolor=DARK,
            clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
        )

    def go(self, name, **params):
        self.current = (name, params)
        self.holder.content = self.build(name, **params)
        self.page.update()

    def rebuild(self):
        """Redraw after the window changed size or the phone rotated."""

        if getattr(self, "current", None):
            self.go(*self.current[:1], **self.current[1])


def main(page: ft.Page):
    page.title = "VoltSpace"
    page.bgcolor = "#000000"
    page.padding = 0
    page.horizontal_alignment = ft.CrossAxisAlignment.CENTER
    page.vertical_alignment = ft.MainAxisAlignment.CENTER
    if FONTS:
        page.fonts = FONTS
    try:
        page.window.width = W + 16
        page.window.height = H + 39
    except Exception:
        try:
            page.window_width = W + 16
            page.window_height = H + 39
        except Exception:
            pass

    app = App(page)
    page.add(app.holder)

    # A phone rotates, and the web client resizes when browser chrome appears.
    def on_resized(_event=None):
        app.size = viewport(page)
        app.rebuild()

    page.on_resized = on_resized
    app.go("home")


def run() -> None:
    """Open the UI as a window, or serve it as a web page for phones and other devices.

    Flet web mode keeps the Python side on the machine that runs this file: the browser only
    renders. That means the app can call the backend at 127.0.0.1:8000 locally, or at any
    URL when it is hosted (set VOLTSPACE_API).

    Environment:
        VOLTSPACE_FLET_WEB=1        serve as a web page instead of opening a window
        VOLTSPACE_FLET_HOST         bind address (default 0.0.0.0, so a phone can reach it)
        VOLTSPACE_FLET_PORT         port (defaults to $PORT when a host sets it, else 8550)
        VOLTSPACE_API               backend base URL (default http://127.0.0.1:8000)
    """

    if os.environ.get("VOLTSPACE_FLET_WEB", "").strip() not in {"", "0"}:
        host = os.environ.get("VOLTSPACE_FLET_HOST", "0.0.0.0")
        # A hosting platform (Render, Railway, ...) injects PORT and expects the process to
        # listen there; falling back to it means the start command needs no arguments.
        port = int(os.environ.get("VOLTSPACE_FLET_PORT") or os.environ.get("PORT") or "8550")
        ft.run(
            main,
            assets_dir="assets",
            view=ft.AppView.WEB_BROWSER,
            host=host,
            port=port,
        )
        return

    if hasattr(ft, "run"):
        ft.run(main, assets_dir="assets")
    else:  # Flet 0.x fallback
        ft.app(target=main, assets_dir="assets")


if __name__ == "__main__":
    run()
