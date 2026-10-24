import flet as ft
def main(page: ft.Page):
    
    page.title = "VoltSpace — Household Electricity & Circuit Safety Planner"
    page.bgcolor = "#F0F2F5"  
    page.padding = 20
    page.theme_mode = ft.ThemeMode.LIGHT

    
    state = {
        "max_watt": 1650,        
        "plugged_items": [],     
        "rate_per_kwh": 3.5      
    }

    
    def calculate_total_watt():
        return sum(item["watt"] for item in state["plugged_items"])

    def update_ui():
        total_watt = calculate_total_watt()
        max_w = state["max_watt"]
        load_ratio = min(total_watt / max_w, 1.0) if max_w > 0 else 0
        ampere = round(total_watt / 110, 1) 
        cost_per_hour = round((total_watt / 1000) * state["rate_per_kwh"], 2)

        
        if total_watt > max_w:
            glow_color = "#E74C3C" 
            status_text = "DANGER: CIRCUIT OVERLOADED!"
        elif load_ratio > 0.7:
            glow_color = "#F39C12" 
            status_text = "WARNING: HIGH LOAD"
        else:
            glow_color = "#2ECC71" 
            status_text = "STATUS: SAFE"

        
        status_badge.value = status_text
        status_badge.color = glow_color
        watt_text.value = f"{total_watt} W / {max_w} W"
        ampere_text.value = f"{ampere} A (110V Grid)"
        cost_text.value = f"Est. Cost: ${cost_per_hour} NTD / hr"
        load_bar.value = load_ratio
        load_bar.color = glow_color

        
        outlet_canvas_box.box_shadow = [
            ft.BoxShadow(spread_radius=3, blur_radius=22, color=glow_color, offset=ft.Offset(0, 0)), # 動態發光層
            ft.BoxShadow(spread_radius=1, blur_radius=12, color="#FFFFFF", offset=ft.Offset(-6, -6)), # 左上亮光
            ft.BoxShadow(spread_radius=1, blur_radius=12, color="#D1D9E6", offset=ft.Offset(6, 6)),   # 右下暗影
        ]

        
        plugged_list_view.controls.clear()
        if not state["plugged_items"]:
            plugged_list_view.controls.append(
                ft.Text("Drag appliances here or click (+) to connect", color="#A0AEC0", size=12, italic=True)
            )
        else:
            for idx, item in enumerate(state["plugged_items"]):
                plugged_list_view.controls.append(
                    ft.Container(
                        bgcolor="#E2E8F0",
                        padding=ft.padding.symmetric(horizontal=10, vertical=5),
                        border_radius=10,
                        content=ft.Row(
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            controls=[
                                ft.Text(f"{item['name']} ({item['watt']}W)", color="#2D3748", size=12, weight=ft.FontWeight.W_600),
                                ft.IconButton(
                                    icon=ft.icons.CLOSE,
                                    icon_size=14,
                                    icon_color="#E74C3C",
                                    tooltip="Unplug",
                                    on_click=lambda e, i=idx: remove_appliance(i)
                                )
                            ]
                        )
                    )
                )

        page.update()

    def add_appliance(appliance_data):
        state["plugged_items"].append(appliance_data)
        update_ui()

    def remove_appliance(index):
        if 0 <= index < len(state["plugged_items"]):
            state["plugged_items"].pop(index)
            update_ui()

    def reset_circuit(e):
        state["plugged_items"].clear()
        update_ui()

    
    def create_neumorphic_box(content, width=None, height=None, padding=15):
        return ft.Container(
            width=width,
            height=height,
            padding=padding,
            border_radius=20,
            bgcolor="#F0F2F5",
            box_shadow=[
                ft.BoxShadow(spread_radius=1, blur_radius=10, color="#FFFFFF", offset=ft.Offset(-5, -5)), # 左上光源
                ft.BoxShadow(spread_radius=1, blur_radius=10, color="#D1D9E6", offset=ft.Offset(5, 5)),   # 右下陰影
            ],
            content=content
        )

   
    appliances_db = [
        {"id": "hair_dryer", "name": "Hair Dryer", "watt": 1200, "icon": ft.icons.AIR},
        {"id": "microwave", "name": "Microwave", "watt": 800, "icon": ft.icons.MICROWAVE},
        {"id": "ac", "name": "Air Conditioner", "watt": 900, "icon": ft.icons.AC_UNIT},
        {"id": "laptop", "name": "Laptop Charger", "watt": 65, "icon": ft.icons.LAPTOP},
        {"id": "kettle", "name": "Electric Kettle", "watt": 1000, "icon": ft.icons.COFFEE_MAKER},
    ]

    drawer_items = []
    for app in appliances_db:
        
        draggable_card = ft.Draggable(
            group="appliance_group",
            data=app,
            content=create_neumorphic_box(
                content=ft.Row(
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    controls=[
                        ft.Row([
                            ft.Icon(app["icon"], color="#4A5568", size=22),
                            ft.Column([
                                ft.Text(app["name"], weight=ft.FontWeight.BOLD, color="#2D3748", size=13),
                                ft.Text(f"+{app['watt']} W", size=11, color="#718096")
                            ], spacing=1)
                        ]),
                        
                        ft.IconButton(
                            icon=ft.icons.ADD_CIRCLE_OUTLINE,
                            icon_color="#4A90E2",
                            icon_size=20,
                            tooltip="Quick Add",
                            on_click=lambda e, a=app: add_appliance(a)
                        )
                    ]
                )
            )
        )
        drawer_items.append(draggable_card)

    left_drawer = ft.Column(
        width=300,
        controls=[
            ft.Text("Appliance Library", size=18, weight=ft.FontWeight.BOLD, color="#2D3748"),
            ft.Text("Drag card or click (+) to plug into circuit", size=12, color="#A0AEC0"),
            ft.Container(height=10),
            *drawer_items,
            ft.Container(height=10),
            create_neumorphic_box(
                content=ft.ElevatedButton(
                    "Reset All Appliances",
                    icon=ft.icons.REFRESH,
                    color="#E74C3C",
                    bgcolor="#F0F2F5",
                    style=ft.ButtonStyle(elevation=0),
                    on_click=reset_circuit
                )
            )
        ]
    )

    
    status_badge = ft.Text("", weight=ft.FontWeight.BOLD, size=14)
    watt_text = ft.Text("", size=24, weight=ft.FontWeight.BOLD, color="#2D3748")
    ampere_text = ft.Text("", size=13, color="#718096")
    cost_text = ft.Text("", size=13, weight=ft.FontWeight.W_600, color="#4A90E2")
    load_bar = ft.ProgressBar(width=240, value=0)
    plugged_list_view = ft.Column(spacing=5, scroll=ft.ScrollMode.AUTO, height=100)

    
    def handle_drag_accept(e: ft.DragTargetAcceptEvent):
        src_control = page.get_control(e.src_id)
        if src_control and hasattr(src_control, "data"):
            app_data = src_control.data
            add_appliance(app_data)

    outlet_inner_content = ft.Column(
        alignment=ft.MainAxisAlignment.CENTER,
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        controls=[
            ft.Icon(name=ft.icons.POWER, size=50, color="#4A5568"),
            ft.Container(height=5),
            status_badge,
            ft.Container(height=5),
            watt_text,
            ampere_text,
            ft.Container(height=8),
            load_bar,
            ft.Container(height=8),
            cost_text,
            ft.Divider(height=15, color="transparent"),
            ft.Text("Plugged Devices:", size=12, weight=ft.FontWeight.BOLD, color="#4A5568"),
            plugged_list_view
        ]
    )

    outlet_canvas_box = ft.Container(
        width=340,
        height=380,
        border_radius=30,
        bgcolor="#F0F2F5",
        padding=20,
        alignment=ft.alignment.center,
        content=outlet_inner_content
    )

    
    outlet_drag_target = ft.DragTarget(
        group="appliance_group",
        content=outlet_canvas_box,
        on_accept=handle_drag_accept
    )

    center_canvas = ft.Column(
        expand=True,
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        controls=[
            ft.Text("Main Circuit Socket (15A Max)", size=20, weight=ft.FontWeight.BOLD, color="#2D3748"),
            ft.Container(height=15),
            outlet_drag_target
        ]
    )

    
    header = create_neumorphic_box(
        content=ft.Row(
            alignment=ft.MainAxisAlignment.BETWEEN,
            controls=[
                ft.Row([
                    ft.Icon(ft.icons.FLASH_ON, color="#4A90E2", size=26),
                    ft.Text("VoltSpace", size=22, weight=ft.FontWeight.BOLD, color="#2D3748"),
                    ft.Text("v1.0 (Front-end Prototype)", size=12, color="#A0AEC0")
                ]),
                ft.Text("Language: EN", size=12, color="#718096", weight=ft.FontWeight.W_600)
            ]
        )
    )

    main_layout = ft.Row(
        controls=[
            left_drawer, 
            ft.VerticalDivider(width=30, color="transparent"), 
            center_canvas
        ],
        vertical_alignment=ft.CrossAxisAlignment.START
    )

    page.add(header, ft.Container(height=15), main_layout)

    
    update_ui()

if __name__ == "__main__":
    ft.app(target=main)