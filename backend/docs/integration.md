# 整合說明：三個成員的成果如何組成一個 App

這份文件回答三個問題：**組員做了什麼？**、**有哪些問題？**、**我怎麼整合與修正？**

---

## 0. 一句話總結

| 成員 | 交付的內容 | 狀態 |
| --- | --- | --- |
| Member A（前端） | `front.txt` — Flet 原型，單一檔案 266 行 | 已修正並改接後端，現在可執行 |
| Member B（資料庫） | 4 個 Supabase SQL 檔 + 3 個 Python 模組 | schema 已修正、模組已重寫 |
| Member C（後端，我） | `backend/` — 計算核心 + API | 補上儲存與儀表板端點 |

**一鍵啟動**：`run_app.bat`（Windows）或 `./run_app.sh`。

---

## 1. Member A 的前端

### 交付內容

`front.txt` 是一個 **Flet**（Python 的 Flutter 綁定）桌面原型，266 行，做得相當完整：

- 新擬物（neumorphic）風格：柔和陰影、發光插座。
- 左側「家電庫」可拖曳或點擊加入。
- 中間插座即時顯示總瓦數、電流、每小時電費、負載進度條。
- 家電可移除、可全部重置。

### 發現的問題

| # | 問題 | 影響 |
| --- | --- | --- |
| A1 | **完全沒有呼叫後端** | 所有數字都是前端自己算的，跟我做的計算核心是兩套邏輯，可能算出不同答案 |
| A2 | **電流用 `total_watt / 110`** | 220V 的電器（冷氣、電熱水器）會被高估一倍 |
| A3 | **`max_watt` 寫死 1650** | 1650 W = 110V × 15A 只對「110V 15A 迴路」成立；換迴路就錯 |
| A4 | **`rate_per_kwh` 寫死 3.5** | 這不是台電的任何一個費率，也不是級距。台電住宅是 1.68 起、累進到 8.46 |
| A5 | **只算「每小時」電費** | 沒有每月用電量、沒有級距、沒有季節（夏月／非夏月） |
| A6 | **家電功率寫死 5 筆** | 吹風機 1200W、微波爐 800W 等是手動填的，沒有依據 |
| A7 | **Flet 0.x API，在 Flet 1.0 完全無法啟動** | `ft.icons` → `ft.Icons`、`ft.alignment` → `ft.Alignment`、`ft.ElevatedButton` → `ft.Button`、`ft.app(target=)` → `ft.run()` |
| A8 | 檔案是 `.txt`，不是可執行的 `.py` | 無法直接跑 |

### 處理方式

**沒有丟掉他的設計**，新擬物風格完整保留（同樣的色票 `#F0F2F5` / `#4A90E2`，
同樣的發光插座、同樣的家電庫＋插座佈局）。

| 問題 | 修正 |
| --- | --- |
| A1 | 改成呼叫後端：`GET /appliances/presets`（家電庫）、`POST /household/dashboard`（所有數字） |
| A2–A5 | 刪掉前端所有算式。電流由後端用歐姆定律算（含電壓、功率因數、單相／三相）；電費由級距電價表算 |
| A3 | `GET /appliances/presets` 回傳 4 種標準迴路（110V/15A、110V/20A、220V/15A、110V/50A），上限由 `amps × voltage` 算出 |
| A4 | 費率由 `GET /tariffs` 提供（3 個方案），前端只負責顯示 |
| A6 | 家電庫改成後端的 12 筆參考資料（含功率、電壓、典型使用時數） |
| A7 | 全部升級到 Flet 1.0 API（`desktop/app.py`） |
| A8 | 分成兩個可執行版本（見下） |

### 交付兩個前端

1. **`web/`（預設）** — 同樣的設計，用 HTML/CSS/JS 重做。理由：Flet 在受限環境下
   會因為要寫入暫存檔而失敗，而且 `flet` + `flet-web` 約 30MB，還需要 Flutter 資產。
   網頁版**零額外依賴**，由同一個 FastAPI 伺服器提供，瀏覽器打開就能用。
2. **`desktop/app.py`（選用）** — 保留 Flet，已升級到 1.0 並改接 API。
   用 `run_app.bat --flet` 啟動（需先 `pip install -r requirements-desktop.txt`）。

兩個前端都只透過 API 取數字，所以它們與測試**不可能算出不同答案**。

---

## 2. Member B 的資料庫

### 交付內容

```
appliances.sql   profiles.sql   security.sql   connect.sql
manager.py       Supabase.py    validation.py
```

### 發現的問題

| # | 問題 | 影響 |
| --- | --- | --- |
| B1 | **欄位名稱與 API contract 不一致**：`Power` / `Minutes` / `Appliance` vs `power_watts` / `hours_per_day` / `name` | 前端要為兩種格式各寫一份轉換 |
| B2 | **單位不一致**：DB 用「分鐘」，計算核心用「小時」 | `minutes / 60` 的轉換散落在各處，容易錯 |
| B3 | **沒有任何電價表** | 電費計算需要 tariff 資料，DB 卻沒有 |
| B4 | **RLS 政策是 `to authenticated`，但前端沒有登入流程** | 匿名請求的 `auth.uid()` 是 NULL → 新增與讀取**全部失敗** |
| B5 | **`Supabase.py` 在 import 時就執行查詢並 `print`** | 被當成模組 import 時會有意外的副作用 |
| B6 | **金鑰直接寫在程式碼裡** | `sb_publishable_...` 是 publishable key（可公開），但仍應放環境變數；且 `manager.py` 與 `Supabase.py` 各寫一次 |
| B7 | `manager.py` 的 `calculate_energy` 與我的計算核心重複 | 兩套公式 |
| B8 | `validation.py` 的規則比計算核心寬鬆（沒有上限、沒有型別檢查） | 兩套驗證標準 |

### 處理方式

| 問題 | 修正 |
| --- | --- |
| B1–B2 | `db/schema.sql`：欄位改成與 `ApplianceIn` 完全一致（`power_watts`, `hours_per_day`, `days_per_month`, `quantity`, `voltage`, `power_factor`），並加上 `CHECK` 約束 |
| B3 | 新增 `tariff_plans` 表，內容與 `app/data/tariffs.json` 一致，並預先 seed 三個方案 |
| B4 | 保留 RLS；新增 `households` 表 + `access_token`，讓**匿名裝置也能安全擁有自己的資料**。簽入的使用者仍然用 `auth.uid()` 隔離 |
| B5–B6 | 三個 Python 模組整合成 `app/store.py`，連線延遲建立、沒有 import 副作用、金鑰不進程式碼 |
| B7–B8 | 儲存與驗證都走計算核心的規則；`app/store.py` 寫入前會先呼叫 `calculate_consumption` 驗證 |

### 為什麼預設用 SQLite 而不是 Supabase

Supabase 需要：專案網址 + 金鑰 + （可選）登入。要讓組員**下載就能跑**，
預設用本地 SQLite（`app/store.py`），資料存在 `backend/.data/voltspace.db`。
Supabase 的完整 schema 與切換方式見 [`supabase.md`](supabase.md)。

---

## 3. 我補上的東西（Member C）

原本的計算 API 是**無狀態**的：前端每次送完整家電清單。這對計算核心是優點，
但一個真的 App 需要記住清單。所以補了：

| 新增 | 用途 |
| --- | --- |
| `app/store.py` | 本地 SQLite：家電的新增／查詢／修改／刪除／整批覆蓋 |
| `GET /appliances/presets` | 家電庫預設值 + 4 種標準迴路 + 參考費率（取代前端的寫死值） |
| `GET/POST/PUT/DELETE /household/appliances` | 已儲存家電的 CRUD |
| `PUT /household/appliances` | 整批覆蓋（前端「儲存全部」） |
| `POST /household/dashboard` | **一次回傳**用電量、電費、負載、建議 —— 前端只要一個請求 |
| `web/` + `/` 路由 | 由後端直接提供網頁介面 |
| `start.py` / `run_app.bat` / `run_app.sh` | 一鍵啟動 |
| `db/schema.sql` | 修正後的 Supabase schema |
| `docs/*.md` | 整合與 Supabase 說明 |

`/household/dashboard` 是這次整合的關鍵：它讓前端**完全不需要自己算**，
也保證網頁版、Flet 版、測試三者結果一致。

---

## 4. 驗證

```bash
run_app.bat --check                       # 環境 + 資料檔檢查
python -m pytest                          # 500 個測試
python tools/smoke_app.py                 # 完整使用流程（需伺服器在跑）
python tools/check_desktop.py             # Flet 介面邏輯（不開視窗）
python tools/probe_errors.py              # 51 個畸形請求，確認無 5xx
```

| 檢查 | 結果 |
| --- | --- |
| `pytest`（Python 3.14 與 3.12） | **500 passed** |
| `smoke_app.py`（21 項端對端） | 全部通過 |
| `check_desktop.py`（Flet 介面邏輯） | 全部通過，12 筆家電庫正常渲染 |
| `probe_errors.py` | 無 5xx，每個 4xx 都是統一格式 |

其中兩個測試**專門防止整合退化**：

- `test_ui_does_not_reimplement_the_physics_or_tariffs` — 掃描 `app.js`，
  確認沒有 `1650`、`3.5`、`/ 110` 這些原型留下來的寫死值。
- `TestDashboard::test_dashboard_summary_matches_the_individual_endpoints` —
  確認儀表板摘要與個別計算端點的數字一致。

---

## 5. 已知限制

- **網頁版沒有登入**，資料存在本機 SQLite，一台機器一份。要多使用者需接 Supabase
  並開啟登入（見 `supabase.md`）。
- **Flet 桌面版保留但非預設**：Flet 1.0 的網頁模式會寫入系統暫存目錄，在部分受限
  環境（含本專案的開發沙箱）會失敗；因此預設用網頁版，Flet 版留給本機示範。
- **家電功率是典型值**，不是使用者的實際銘牌。UI 允許自訂。
- 電費與節電量皆為估算，**負載估算不保證電路安全**（畫面上有免責聲明）。
