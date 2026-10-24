# Member A 的原始 Flet 原型（僅供對照）

這個資料夾保存 Member A 交來的原始原型，**不是可執行的應用程式**。

## 這個檔案有什麼問題

`voltspace.py` 是 Flet **0.x** 的寫法，在現在的 Flet 1.0 上**完全無法啟動**：

| 原型寫法 | Flet 1.0 |
| --- | --- |
| `ft.icons.CLOSE` | `ft.Icons.CLOSE` |
| `ft.alignment.center` | `ft.Alignment.CENTER` |
| `ft.ElevatedButton(...)` | `ft.Button(...)` |
| `ft.Container(box_shadow=[...])` | `ft.Container(shadow=[...])` |
| `ft.app(target=main)` | `ft.run(main)` |

除此之外，它把計算寫死在前端，這與後端不一致：

- `max_watt = 1650` —— 只對 110V/15A 迴路成立
- `rate_per_kwh = 3.5` —— 不是台電任何費率（住宅是 1.68 起、累進到 8.46）
- `ampere = total_watt / 110` —— 220V 電器會被高估一倍
- 只算「每小時」電費，沒有每月用電量與級距

## 想跑起來請用這些

| 用途 | 指令 | 位置 |
| --- | --- | --- |
| **網頁版（建議）** | `run_app.bat` | `backend/` |
| **Flet 桌面版**（已升級 1.0 並改接 API） | `run_app.bat --flet` | `backend/desktop/app.py` |

兩個版本都只透過 API 取得數字，所以和後端測試的結果一致。

## 保留這份的用意

作為設計來源的紀錄 —— 新擬物的色票與佈局（`#F0F2F5`、`#4A90E2`、發光插座、
家電庫＋插座佈局）都沿用到 `backend/web/` 與 `backend/desktop/`。

`prototype/flet_prototype.py` 是同一個檔案的另一份快照。
