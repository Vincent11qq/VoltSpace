"""VoltSpace desktop UI (Flet 1.0).

This is Member A's Flet prototype, migrated and rewired:

* **Migrated to Flet 1.0** — the prototype used the 0.x API, which no longer exists
  (``ft.icons`` → ``ft.Icons``, ``ft.alignment`` → ``ft.Alignment``,
  ``ft.ElevatedButton`` → ``ft.Button``, ``ft.app(target=...)`` → ``ft.run(...)``), so it
  could not start at all on a current install.
* **Rewired to the backend** — the prototype did its own arithmetic (a fixed circuit
  ceiling, a guessed per-kWh price, ``watts / 110``). Now every number comes from the
  calculation API, so the desktop UI, the web UI and the tests all agree.

Run it with the backend already serving::

    python start.py --flet          # starts the backend, then this window

or on its own against a running backend::

    python desktop/app.py

The backend URL defaults to http://127.0.0.1:8000 and can be overridden with the
``VOLTSPACE_API`` environment variable.
"""

from __future__ import annotations

import os
import sys
import urllib.error
import urllib.request
from json import dumps, loads
from pathlib import Path

import flet as ft

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

API = os.environ.get("VOLTSPACE_API", "http://127.0.0.1:8000").rstrip("/")

# Palette inherited from the original prototype.
BG = "#F0F2F5"
INK = "#2D3748"
MUTED = "#718096"
FAINT = "#A0AEC0"
ACCENT = "#4A90E2"
OK = "#2ECC71"
WARN = "#F39C12"
DANGER = "#E74C3C"
LIGHT = "#FFFFFF"
DARK = "#D1D9E6"


# --------------------------------------------------------------------------- API


class ApiError(RuntimeError):
    pass


def call(method: str, path: str, payload: dict | None = None) -> dict:
    """Minimal JSON client. Uses urllib so Flet needs no extra dependency."""

    data = dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        f"{API}{path}", data=data, method=method, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8")
            return loads(body) if body else {}
    except urllib.error.HTTPError as error:
        raw = error.read().decode("utf-8")
        try:
            detail = loads(raw)
        except ValueError:
            detail = {"message": raw}
        raise ApiError(detail.get("message") or f"HTTP {error.code}") from error
    except urllib.error.URLError as error:
        raise ApiError(
            f"cannot reach the backend at {API} — start it with:  python start.py"
        ) from error


# ----------------------------------------------------------------------- styling


def neumorphic(content: ft.Control, *, padding: int = 15, width: int | None = None):
    """The prototype's soft raised panel."""

    return ft.Container(
        width=width,
        padding=padding,
        border_radius=20,
        bgcolor=BG,
        shadow=[
            ft.BoxShadow(spread_radius=1, blur_radius=10, color=LIGHT, offset=ft.Offset(-5, -5)),
            ft.BoxShadow(spread_radius=1, blur_radius=10, color=DARK, offset=ft.Offset(5, 5)),
        ],
        content=content,
    )


def glow(box: ft.Container, colour: str) -> None:
    box.shadow = [
        ft.BoxShadow(spread_radius=3, blur_radius=22, color=colour, offset=ft.Offset(0, 0)),
        ft.BoxShadow(spread_radius=1, blur_radius=12, color=LIGHT, offset=ft.Offset(-6, -6)),
        ft.BoxShadow(spread_radius=1, blur_radius=12, color=DARK, offset=ft.Offset(6, 6)),
    ]


# ------------------------------------------------------------------------ the app


def main(page: ft.Page) -> None:
    page.title = "VoltSpace — 租屋用電與迴路安全"
    page.bgcolor = BG
    page.padding = 20
    page.theme_mode = ft.ThemeMode.LIGHT
    page.window.width = 1180
    page.window.height = 820

    state: dict = {
        "items": [],          # [{'name','power_watts','hours_per_day','days_per_month','quantity','voltage'}]
        "presets": [],
        "circuits": [],
        "plans": [],
        "plan_id": None,
        "month": None,
        "limit_amps": 15,
        "margin": 0.8,
        "summary": {},
        "busy": False,
    }

    # --- widgets that get updated in place ---------------------------------
    status_badge = ft.Text("—", weight=ft.FontWeight.BOLD, size=14)
    watts_text = ft.Text("0 W", size=26, weight=ft.FontWeight.BOLD, color=INK)
    amps_text = ft.Text("0 A", size=13, color=MUTED)
    cost_text = ft.Text("—", size=13, weight=ft.FontWeight.W_600, color=ACCENT)
    load_bar = ft.ProgressBar(width=260, value=0, color=OK, bgcolor="#E2E8F0")
    plugged_list = ft.Column(spacing=5, scroll=ft.ScrollMode.AUTO, height=150)
    kwh_value = ft.Text("—", size=17, weight=ft.FontWeight.BOLD, color=INK)
    bill_value = ft.Text("—", size=17, weight=ft.FontWeight.BOLD, color=INK)
    rate_value = ft.Text("—", size=17, weight=ft.FontWeight.BOLD, color=INK)
    season_value = ft.Text("—", size=17, weight=ft.FontWeight.BOLD, color=INK)
    breakdown_list = ft.Column(spacing=8, scroll=ft.ScrollMode.AUTO, height=170)
    suggestions = ft.Column(spacing=8, scroll=ft.ScrollMode.AUTO, height=230)
    saving_text = ft.Text("", size=12, color=MUTED)
    note_text = ft.Text("", size=11, color=FAINT)
    plan_dropdown = ft.Dropdown(width=250, label="電價方案", dense=True)
    month_dropdown = ft.Dropdown(width=130, label="月份", dense=True)
    circuit_dropdown = ft.Dropdown(width=300, label="迴路上限", dense=True)
    margin_dropdown = ft.Dropdown(
        width=170,
        label="安全裕度",
        dense=True,
        value="0.8",
        options=[
            ft.dropdown.Option("0.8", "80%（建議）"),
            ft.dropdown.Option("0.7", "70%（保守）"),
            ft.dropdown.Option("1.0", "100%"),
        ],
    )
    outlet_box = ft.Container(
        width=360,
        padding=20,
        border_radius=30,
        bgcolor=BG,
        alignment=ft.Alignment.CENTER,
    )

    # --- rendering ---------------------------------------------------------
    def render_plugged() -> None:
        plugged_list.controls.clear()
        if not state["items"]:
            plugged_list.controls.append(
                ft.Text("點選左側家電加入", color=FAINT, size=12, italic=True)
            )
        else:
            for index, item in enumerate(state["items"]):
                plugged_list.controls.append(
                    ft.Container(
                        bgcolor="#E2E8F0",
                        padding=ft.padding.symmetric(horizontal=10, vertical=5),
                        border_radius=10,
                        content=ft.Row(
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            controls=[
                                ft.Text(
                                    f"{item['name']} ({item['power_watts']:g}W · "
                                    f"{item['hours_per_day']:g}h/日)",
                                    size=12,
                                    weight=ft.FontWeight.W_600,
                                    color=INK,
                                ),
                                ft.IconButton(
                                    icon=ft.Icons.CLOSE,
                                    icon_size=14,
                                    icon_color=DANGER,
                                    tooltip="移除",
                                    on_click=lambda e, i=index: remove_item(i),
                                ),
                            ],
                        ),
                    )
                )

    def render_summary(data: dict) -> None:
        summary = data.get("summary") or {}
        state["summary"] = summary
        verdict = summary.get("load_verdict")
        colour, label = {
            "over_limit": (DANGER, "DANGER: CIRCUIT OVERLOADED"),
            "near_limit": (WARN, "WARNING: HIGH LOAD"),
            "safe": (OK, "STATUS: SAFE"),
        }.get(verdict, (FAINT, "—"))

        status_badge.value = label
        status_badge.color = colour
        glow(outlet_box, colour)

        load = data.get("load") or {}
        watts_text.value = f"{round(load.get('total_power_watts', 0))} W"
        current = summary.get("estimated_total_current_amps")
        limit = state["limit_amps"]
        amps_text.value = (
            f"{current:.2f} A（上限 {limit:g} A）" if current is not None else "—"
        )
        ratio = min((current or 0) / limit, 1.0) if limit else 0
        load_bar.value = ratio
        load_bar.color = colour
        cost_text.value = f"預估 {summary.get('estimated_monthly_cost_twd', 0):.0f} 元 / 月"

        kwh_value.value = f"{summary.get('total_monthly_kwh', 0):.1f} 度"
        bill_value.value = f"{summary.get('estimated_monthly_cost_twd', 0):.0f} 元"
        rate_value.value = f"{summary.get('effective_rate_per_kwh', 0):.2f} 元/度"
        season_value.value = summary.get("season_label_zh") or "—"

        breakdown_list.controls.clear()
        appliances = (data.get("consumption") or {}).get("appliances", [])
        for appliance in sorted(appliances, key=lambda a: -a["monthly_kwh"]):
            breakdown_list.controls.append(
                ft.Column(
                    spacing=2,
                    controls=[
                        ft.Row(
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            controls=[
                                ft.Text(appliance["name"], size=12, color=INK),
                                ft.Text(
                                    f"{appliance['monthly_kwh']:.1f} 度 · "
                                    f"{appliance['share_of_total_percent']:.1f}%",
                                    size=11,
                                    color=MUTED,
                                ),
                            ],
                        ),
                        ft.ProgressBar(
                            value=min((appliance["share_of_total_percent"] or 0) / 100, 1),
                            color=ACCENT,
                            bgcolor="#E2E8F0",
                            bar_height=6,
                        ),
                    ],
                )
            )

        suggestions.controls.clear()
        recommendations = data.get("recommendations")
        if not recommendations or not recommendations.get("recommendations"):
            saving_text.value = "目前沒有可提供的建議。"
        else:
            saving_text.value = (
                f"每月約可省 {recommendations['total_potential_monthly_saving_kwh']:.1f} 度"
                f"（{recommendations['total_potential_monthly_saving_twd']:.0f} 元）"
            )
            for item in recommendations["recommendations"]:
                saved = item["estimated_monthly_saving_kwh"]
                suggestions.controls.append(
                    ft.Container(
                        bgcolor=BG,
                        padding=10,
                        border_radius=14,
                        content=ft.Column(
                            spacing=4,
                            controls=[
                                ft.Row(
                                    controls=[
                                        ft.Container(
                                            bgcolor="#E2E8F0",
                                            padding=ft.padding.symmetric(horizontal=6, vertical=2),
                                            border_radius=8,
                                            content=ft.Text(
                                                item["severity"].upper(), size=9, color=MUTED
                                            ),
                                        ),
                                        ft.Text(
                                            item["title_zh"],
                                            size=12,
                                            weight=ft.FontWeight.BOLD,
                                            color=INK,
                                        ),
                                    ]
                                ),
                                ft.Text(item["reason_zh"], size=11, color=MUTED),
                                ft.Text(item["suggestion_zh"], size=11, color=INK),
                                ft.Text(
                                    f"預估每月省 {saved:.1f} 度 / "
                                    f"{item['estimated_monthly_saving_twd']:.0f} 元"
                                    if saved > 0
                                    else "（用電安全建議，未估算節省度數）",
                                    size=11,
                                    color="#1E8449" if saved > 0 else MUTED,
                                ),
                            ],
                        ),
                    )
                )

    # --- data flow ---------------------------------------------------------
    def refresh() -> None:
        render_plugged()
        if state["busy"]:
            return
        if not state["items"]:
            status_badge.value = "尚未接上電器"
            status_badge.color = FAINT
            glow(outlet_box, OK)
            watts_text.value = "0 W"
            amps_text.value = "0 A"
            cost_text.value = "—"
            load_bar.value = 0
            kwh_value.value = bill_value.value = rate_value.value = season_value.value = "—"
            breakdown_list.controls.clear()
            suggestions.controls.clear()
            saving_text.value = ""
            page.update()
            return

        state["busy"] = True
        page.update()
        try:
            payload: dict = {
                "appliances": state["items"],
                "load_limit_amps": state["limit_amps"],
                "safety_margin": state["margin"],
                "include_recommendations": True,
                "max_recommendations": 6,
            }
            if state["plan_id"]:
                payload["plan_id"] = state["plan_id"]
            if state["month"]:
                payload["month"] = state["month"]
            data = call("POST", "/household/dashboard", payload)
            render_summary(data)
        except ApiError as exc:
            status_badge.value = "計算失敗"
            status_badge.color = DANGER
            cost_text.value = str(exc)
        finally:
            state["busy"] = False
            page.update()

    def add_preset(preset: dict) -> None:
        state["items"].append(
            {
                "name": preset["name_zh"],
                "category": preset["category"],
                "power_watts": preset["power_watts"],
                "hours_per_day": preset["hours_per_day"],
                "days_per_month": preset["days_per_month"],
                "quantity": 1,
                "voltage": preset["voltage"],
            }
        )
        refresh()

    def remove_item(index: int) -> None:
        if 0 <= index < len(state["items"]):
            state["items"].pop(index)
            refresh()

    def reset_all(e=None) -> None:
        state["items"].clear()
        try:
            call("PUT", "/household/appliances", {"appliances": []})
            note_text.value = "已清除儲存的家電。"
        except ApiError as exc:
            note_text.value = f"清除失敗：{exc}"
        refresh()

    def save_all(e=None) -> None:
        try:
            listing = call(
                "PUT",
                "/household/appliances",
                {"appliances": [{k: v for k, v in item.items()} for item in state["items"]]},
            )
            note_text.value = f"已儲存 {listing['count']} 台家電（每月約 {listing['total_monthly_kwh']:.1f} 度）"
        except ApiError as exc:
            note_text.value = f"儲存失敗：{exc}"
        page.update()

    def load_saved() -> None:
        try:
            listing = call("GET", "/household/appliances")
        except ApiError as exc:
            note_text.value = f"無法載入已存清單：{exc}"
            return
        state["items"] = [
            {
                "name": row["name"],
                "category": row["category"],
                "power_watts": row["power_watts"],
                "hours_per_day": row["hours_per_day"],
                "days_per_month": row["days_per_month"],
                "quantity": row["quantity"],
                "voltage": row["voltage"],
            }
            for row in listing["appliances"]
        ]
        note_text.value = (
            f"已載入 {listing['count']} 台已儲存家電"
            if listing["count"]
            else "目前沒有已儲存的家電。"
        )
        refresh()

    # --- controls ----------------------------------------------------------
    def on_plan_change(e) -> None:
        state["plan_id"] = plan_dropdown.value or None
        refresh()

    def on_month_change(e) -> None:
        state["month"] = int(month_dropdown.value) if month_dropdown.value else None
        refresh()

    def on_circuit_change(e) -> None:
        try:
            state["limit_amps"] = float(circuit_dropdown.value)
        except (TypeError, ValueError):
            return
        refresh()

    def on_margin_change(e) -> None:
        state["margin"] = float(margin_dropdown.value)
        refresh()

    def handle_drop(e: ft.DragTargetAcceptEvent) -> None:
        source = page.get_control(e.src_id)
        data = getattr(source, "data", None)
        if isinstance(data, dict):
            add_preset(data)

    # --- build the layout --------------------------------------------------
    def build_presets() -> list[ft.Control]:
        controls: list[ft.Control] = []
        for preset in state["presets"]:
            card = ft.Container(
                padding=8,
                border_radius=14,
                bgcolor=BG,
                content=ft.Row(
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    controls=[
                        ft.Column(
                            spacing=1,
                            controls=[
                                ft.Text(
                                    preset["name_zh"],
                                    size=13,
                                    weight=ft.FontWeight.BOLD,
                                    color=INK,
                                ),
                                ft.Text(
                                    f"{preset['power_watts']:g}W · {preset['voltage']:g}V · "
                                    f"{preset['hours_per_day']:g}h/日",
                                    size=11,
                                    color=MUTED,
                                ),
                            ],
                        ),
                        ft.IconButton(
                            icon=ft.Icons.ADD_CIRCLE_OUTLINE,
                            icon_color=ACCENT,
                            icon_size=20,
                            tooltip="加入",
                            on_click=lambda e, p=preset: add_preset(p),
                        ),
                    ],
                ),
            )
            controls.append(
                ft.Draggable(group="appliances", data=preset, content=card)
            )
        return controls

    outlet_inner = ft.Column(
        alignment=ft.MainAxisAlignment.CENTER,
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        spacing=6,
        controls=[
            ft.Icon(ft.Icons.POWER, size=46, color=INK),
            status_badge,
            watts_text,
            amps_text,
            ft.Container(height=6),
            load_bar,
            cost_text,
            ft.Divider(height=12, color="transparent"),
            ft.Text("已接上的電器", size=12, weight=ft.FontWeight.BOLD, color=MUTED),
            plugged_list,
        ],
    )
    outlet_box.content = outlet_inner

    # Placeholder column, filled once the presets arrive from the API. The original
    # prototype (and this port's first draft) built the cards before the fetch, which left
    # the appliance library permanently empty.
    preset_column = ft.Column(spacing=8, controls=[])

    left_panel = ft.Column(
        width=300,
        spacing=10,
        scroll=ft.ScrollMode.AUTO,
        controls=[
            ft.Text("家電庫", size=18, weight=ft.FontWeight.BOLD, color=INK),
            ft.Text("點選 ＋ 或拖曳到插座", size=12, color=FAINT),
            preset_column,
            ft.Container(height=8),
            neumorphic(
                ft.Button(
                    "清除全部",
                    icon=ft.Icons.REFRESH,
                    color=DANGER,
                    bgcolor=BG,
                    elevation=0,
                    on_click=reset_all,
                )
            ),
        ],
    )

    right_panel = ft.Column(
        width=330,
        spacing=12,
        scroll=ft.ScrollMode.AUTO,
        controls=[
            neumorphic(
                ft.Column(
                    spacing=8,
                    controls=[
                        ft.Text("本月估算", size=15, weight=ft.FontWeight.BOLD, color=INK),
                        ft.Row(
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            controls=[ft.Text("每月用電", size=11, color=MUTED), kwh_value],
                        ),
                        ft.Row(
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            controls=[ft.Text("預估電費", size=11, color=MUTED), bill_value],
                        ),
                        ft.Row(
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            controls=[ft.Text("平均每度", size=11, color=MUTED), rate_value],
                        ),
                        ft.Row(
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            controls=[ft.Text("季節", size=11, color=MUTED), season_value],
                        ),
                    ],
                )
            ),
            neumorphic(
                ft.Column(
                    spacing=6,
                    controls=[
                        ft.Text("用電等級", size=15, weight=ft.FontWeight.BOLD, color=INK),
                        breakdown_list,
                    ],
                )
            ),
            neumorphic(
                ft.Column(
                    spacing=6,
                    controls=[
                        ft.Text("節電建議", size=15, weight=ft.FontWeight.BOLD, color=INK),
                        saving_text,
                        suggestions,
                    ],
                )
            ),
            neumorphic(
                ft.Column(
                    spacing=6,
                    controls=[
                        ft.Text("儲存", size=13, weight=ft.FontWeight.BOLD, color=INK),
                        ft.Row(
                            controls=[
                                ft.Button(
                                    "儲存我的家電",
                                    bgcolor=ACCENT,
                                    color=LIGHT,
                                    elevation=0,
                                    on_click=save_all,
                                ),
                                ft.Button(
                                    "重新載入",
                                    bgcolor=BG,
                                    color=MUTED,
                                    elevation=0,
                                    on_click=lambda e: load_saved(),
                                ),
                            ]
                        ),
                        note_text,
                        ft.Text(
                            "數值與電費皆由後端計算 API 提供，未在介面中重算。",
                            size=10,
                            color=FAINT,
                        ),
                    ],
                )
            ),
        ],
    )

    header = neumorphic(
        ft.Row(
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            controls=[
                ft.Row(
                    controls=[
                        ft.Icon(ft.Icons.FLASH_ON, color=ACCENT, size=26),
                        ft.Text("VoltSpace", size=22, weight=ft.FontWeight.BOLD, color=INK),
                        ft.Text("Flet 1.0 desktop · API-driven", size=12, color=FAINT),
                    ]
                ),
                ft.Row(
                    controls=[plan_dropdown, month_dropdown, margin_dropdown],
                ),
            ],
        )
    )

    page.add(
        header,
        ft.Container(height=12),
        ft.Row(
            alignment=ft.MainAxisAlignment.START,
            vertical_alignment=ft.CrossAxisAlignment.START,
            controls=[
                left_panel,
                ft.Container(width=20),
                ft.Column(
                    width=380,
                    spacing=12,
                    controls=[
                        ft.Text(
                            "主要迴路插座",
                            size=18,
                            weight=ft.FontWeight.BOLD,
                            color=INK,
                        ),
                        ft.DragTarget(group="appliances", content=outlet_box, on_accept=handle_drop),
                        neumorphic(
                            ft.Column(
                                spacing=6,
                                controls=[
                                    ft.Text(
                                        "迴路設定", size=13, weight=ft.FontWeight.BOLD, color=INK
                                    ),
                                    circuit_dropdown,
                                    ft.Text(
                                        "迴路上限來自標準迴路規格；電流由後端負載估算提供。",
                                        size=10,
                                        color=FAINT,
                                    ),
                                ]
                            )
                        ),
                    ],
                ),
                ft.Container(width=20),
                right_panel,
            ],
        ),
    )

    # --- first load --------------------------------------------------------
    try:
        presets = call("GET", "/appliances/presets")
        tariffs = call("GET", "/tariffs")
    except ApiError as exc:
        page.add(ft.Text(str(exc), color=DANGER, size=13))
        page.update()
        return

    state["presets"] = presets["presets"]
    state["circuits"] = presets["circuits"]
    state["limit_amps"] = presets["default_circuit_amps"]
    state["plan_id"] = tariffs["default_plan_id"]
    state["month"] = None

    # Fill the appliance library now that the presets are known.
    preset_column.controls = build_presets()

    plan_dropdown.options = [
        ft.dropdown.Option(plan["id"], plan.get("name_zh") or plan["id"])
        for plan in tariffs["plans"]
    ]
    plan_dropdown.value = tariffs["default_plan_id"]
    month_dropdown.options = [
        ft.dropdown.Option(str(month), f"{month} 月") for month in range(1, 13)
    ]
    circuit_dropdown.options = [
        ft.dropdown.Option(
            str(circuit["amps"]),
            f"{circuit['label_zh']}（{circuit['amps']:g}A）",
        )
        for circuit in presets["circuits"]
    ]
    circuit_dropdown.value = str(presets["default_circuit_amps"])
    plan_dropdown.on_change = on_plan_change
    month_dropdown.on_change = on_month_change
    circuit_dropdown.on_change = on_circuit_change
    margin_dropdown.on_change = on_margin_change
    page.update()

    load_saved()


if __name__ == "__main__":
    ft.run(main)
