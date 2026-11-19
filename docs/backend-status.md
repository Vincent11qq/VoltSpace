# VoltSpace — Backend 完成內容總覽

> 本文件說明 **Member C（喬元震）負責的 backend** 目前做到哪裡：完成了什麼、
> 怎麼驗證、還有什麼沒做。
>
> 最後更新：電價更新到 2025-10-01 費率之後。

---

## 1. 一句話總結

Backend 是一個**可獨立執行、可測試、已整合前端**的 FastAPI 服務，負責
**用電量計算、電費估算、電流負載警示、規則式節電建議、情境模擬**，
並額外提供**家電儲存**與**儀表板聚合端點**讓前端一次拿到所有數字。

| 項目 | 數字 |
| --- | --- |
| 應用程式碼 | 16 個模組（含 3 個套件 `__init__`）|
| 測試程式碼 | 21 個檔案 |
| API 路由 | **18 條**（17 個 JSON 端點 + 1 個網頁介面）|
| 測試 | **704 個**，全數通過（Python 3.12 與 3.14）|
| 開發工具 | 21 支腳本 |
| 電價方案 | 3 種（台電累進、時間電價、租屋單一費率） |
| 家電參考資料 | 12 種（含典型功率、電壓、使用時數、建議規則） |

---

## 2. 必做功能的完成狀況

課程要求的六大項，逐項對照：

### 2.1 用電量計算 — ✅ 完成

`app/calculators/consumption.py`

- 單一家電用電量：`kWh/月 = W ÷ 1000 × 每日時數 × 每月天數 × 數量`
- 所有家電總用電量，並計算每台佔比
- 可修改功率、每日時數、每月天數、數量
- 輸入驗證：型別、範圍（功率 0.1–100000 W、時數 0–24、天數 0–31）、
  非有限數（NaN/Inf）一律拒絕
- 合法但可疑的值回 `warnings`（例如 24 小時運轉、25000W），不是錯誤

### 2.2 電費計算 — ✅ 完成

`app/calculators/electricity_bill.py`

- **電價資料與程式完全分離**：所有費率在 `app/data/tariffs.json`，
  程式碼裡沒有任何一個費率常值（有測試守著）
- **級距（累進）計算**：台電住宅六級距，測到 100 萬度都不會失真
- **適用期間**：夏月（6–9 月）／非夏月自動判斷，也可強制指定
- **帳單期間**：支援台電「兩個月一期」，級距上限會依月數放大
  （1040 度兩月一期 = 520 度月單價 × 2，有測試驗證等價）
- 另外支援 **時間電價** 與 **租屋單一費率** 兩種方案
- 不支援的組合會明確報錯（例如單一費率不接受 `billing_months: 2`）

### 2.3 節電建議 — ✅ 完成

`app/services/recommendations.py`

- 找出用電量較高的家電（依佔比分級：≥20% 高、≥10% 中）
- **規則式**，不需要訓練 AI 模型：比對 `app/data/appliances.json` 的典型值，
  套用宣告式規則條件（`hours_per_day_gte`、`power_ratio_gte`、`is_high_power`、
  `is_always_on`、`share_gte`、`days_per_month_gte` 等 8 種，
  由 `data_check.py` 驗證規則只能用這幾種）
- 每筆建議都附 **原因（reason_zh）、做法（suggestion_zh）、
  預估節省度數與金額、假設條件、信心度**
- 中英文名稱都能比對，且名稱只要「包含」別名就會命中
  （冰箱／電冰箱／小冰箱都會對到冰箱）
- 同名家電不會互相吃掉建議（用家電身分而不是名稱做 key）
- 除了建議，還會給「換成高效率機種」的採購建議

### 2.4 情境模擬 — ✅ 完成

`app/services/simulation.py`

- 比較修改前後的用電量與電費
- 顯示節省度數、節省金額、節省百分比、年度節省金額
- **保證不修改使用者原本的資料**：進入函式先快照，改動只發生在副本上
  （`TestNonMutation` 有 4 個測試，另有 3 個測試在別處驗證不會改到輸入）
- 四種變更：改時數、改功率、改天數、換機種（`replace_with`）
- 換機種時改名不會把一列拆成兩列（保留原本身分，另外回報 `replaced_by`）

### 2.5 電流與負載估算 — ✅ 完成（簡化版）

`app/calculators/load_estimator.py`

- `I = P ÷ (V × 功率因數)`，支援單相與三相（三相除以 √3）
- 與使用者輸入的負載上限比較，給四種判定：
  `safe` / `near_limit` / `over_limit` / `no_limit`
- 可找出「哪幾台同時開會超載」的最小組合
- **明確不宣稱安全**：每次回應都附免責聲明，並列出模型限制
  （只算運轉電流、不含啟動電流、算術相加、不考慮線徑與延長線）

### 2.6 API、驗證與測試 — ✅ 完成

- **FastAPI** 提供 18 條路由（計算 5 條 + 家電儲存與儀表板 6 條 + 產品建議 1 條 + 參考資料與輔助 5 條 + 網頁介面 1 條），自動產生 OpenAPI 3.1 文件（`/docs` 可互動測試）
- **Pydantic** 驗證輸入，錯誤統一格式（每個錯誤回應都有這 5 個欄位）：
  `{error, code, message, field, details[]}`
  - **400** = 語意上無法計算（`appliance_not_found`、`invalid_value`）
  - **422** = 格式或數值不合理（`validation_error`，附 `field` 指出是哪個欄位）
  - **404** = 要操作的已儲存家電不存在（`appliance_not_found`）
  - **500** = 僅用於儲存層故障（`storage_error`）；`probe_errors.py` 的 51 個畸形請求
    確認一般錯誤不會走到 500

  全部錯誤碼只有 4 個：`validation_error`、`invalid_value`、`appliance_not_found`、
  `storage_error`，前端可以據此安全地分流。
- **pytest** 704 個測試，涵蓋計算函式與 API
- **API 使用說明**：`README.md` 有每個端點的 curl 範例與完整回應；
  `docs/openapi.json` 可直接匯入 Postman
- **啟動即驗證資料檔**：電價或家電資料有錯，伺服器直接拒絕啟動

---

## 3. 超出要求的部分

這些不在作業要求內，但為了讓前端能真的串起來而補的。

### 3.1 家電儲存（`app/store.py`）

原本的計算 API 是無狀態的（前端每次送完整清單），這對計算核心是優點，
但一個真的 App 需要記住清單。所以加了本地 SQLite 儲存：

| 端點 | 用途 |
| --- | --- |
| `GET /household/appliances` | 取得已儲存清單（含總用電量） |
| `POST /household/appliances` | 新增一台 |
| `PUT /household/appliances/{id}` | 修改單一欄位 |
| `DELETE /household/appliances/{id}` | 刪除 |
| `PUT /household/appliances` | 整批覆蓋（前端「儲存全部」） |

寫入前一定先過計算核心的驗證，所以不合法的家電不可能進資料庫。

**為什麼不用 Supabase 當預設**：Supabase 需要專案網址、金鑰、登入流程，
組員下載後不能直接跑。SQLite 讓 App 離線可用。

**Supabase 已經實作完成**（`app/store_supabase.py` + `app/storage.py`），
不用改程式碼，設環境變數就切換：

| `VOLTSPACE_STORAGE` | 行為 |
| --- | --- |
| `auto`（預設） | 有設定 Supabase 就用；連不上就退回 SQLite 並印出原因 |
| `supabase` | 強制使用，設定錯誤時啟動失敗（不會假裝成功） |
| `local` | 只用 SQLite |

`/health` 的 `storage` 欄位會回報實際使用的後端（`supabase` 或 `local-sqlite`）。
步驟見 `docs/supabase.md`；`tools/supabase_doctor.py` 可在接線前檢查專案是否可用。

### 3.2 儀表板聚合端點（`POST /household/dashboard`）

**一次回傳**用電量、電費、負載、建議。這是整合的關鍵：

- 前端只要一個請求，不用串四個
- 畫面上每個數字都來自後端，**前端不可能自行算出不同的答案**
- 可用已儲存清單，也可傳未儲存的臨時清單（即時編輯用）
- 有測試確認它的摘要與個別端點的數字完全一致

### 3.3 家電庫預設值（`GET /appliances/presets`）

回傳 12 種家電的建議值、4 種標準迴路（110V/15A、110V/20A、220V/15A、110V/50A）、
參考費率。用途是取代前端原本寫死的 `1650W` 迴路上限與 `3.5 元/度` 費率。

### 3.4 定價與資料正確性

- 電價表已更新到 **2025-10-01 生效的費率**（2026 年適用），
  並用台電公布範例交叉驗證（700 度 = 2,423.1 元）
- 新增 `tools/import_tariff.py`：把費率 dict 轉成 JSON 並驗證級距遞增，
  避免手改 JSON 打錯
- 舊費率保留在 `tariffs.json` 的 `notes` 裡方便對照

---

## 4. API 一覽（18 條路由）

### 計算（無狀態，純函式）

| Method | Endpoint | 用途 |
| --- | --- | --- |
| POST | `/calculate/consumption` | 計算單一或多個家電的每月用電量 |
| POST | `/calculate/cost` | 估算電費（級距／季節／帳單期間） |
| POST | `/calculate/load` | 估算電流並比較負載上限 |

### 建議與模擬

| Method | Endpoint | 用途 |
| --- | --- | --- |
| POST | `/recommendations` | 產生規則式節電建議 |
| POST | `/simulate` | 比較修改前後的用電量與電費 |
| POST | `/product-recommendations` | 依用電量推薦節能產品；節省金額用 `/calculate/cost` 的有效費率換算（費率只存在電價表），產品清單來自 Supabase 的 `products` 表 |

### 家電儲存

| Method | Endpoint | 用途 |
| --- | --- | --- |
| GET | `/household/appliances` | 取得已儲存清單 |
| POST | `/household/appliances` | 新增 |
| PUT | `/household/appliances/{id}` | 修改 |
| DELETE | `/household/appliances/{id}` | 刪除 |
| PUT | `/household/appliances` | 整批覆蓋 |
| POST | `/household/dashboard` | 一次取得儀表板全部數字 |

### 參考資料

| Method | Endpoint | 用途 |
| --- | --- | --- |
| GET | `/tariffs` | 電價方案與級距 |
| GET | `/appliances` | 家電參考資料 |
| GET | `/appliances/presets` | 前端家電庫預設值 |
| GET | `/health` | 健康檢查 |

另外 `/` 提供網頁介面、`/docs` 提供 Swagger UI、`/api` 提供端點索引。

---

## 5. 程式碼結構

```
backend/
├── app/                        16 個模組（含 3 個套件 __init__）
│   ├── main.py                 FastAPI 應用：端點、錯誤處理、生命週期
│   ├── schemas.py              Pydantic 模型（32 個 schema）
│   ├── store.py                本地 SQLite 儲存
│   ├── store_supabase.py       Supabase（PostgREST）儲存層
│   ├── storage.py              依環境變數挑選儲存後端
│   ├── data_check.py           啟動時資料檔完整性驗證
│   ├── calculators/            ← 純計算，完全不 import FastAPI 或資料庫
│   │   ├── consumption.py      用電量 + 輸入驗證
│   │   ├── electricity_bill.py 電費（級距／時間電價／單一費率）
│   │   └── load_estimator.py   電流與負載（含 limit_watts）
│   ├── services/               ← 規則與資料整合
│   │   ├── recommendations.py  規則式建議（中英雙語）
│   │   └── simulation.py       情境模擬
│   └── data/
│       ├── tariffs.json        3 種電價方案
│       └── appliances.json     12 種家電 + 10 條規則 + 替代機種
├── tests/                      19 個檔案、704 個測試（第 7 節）
├── tools/                      21 支腳本（第 8 節）
├── db/schema.sql               Supabase/PostgreSQL schema
├── docs/                       OpenAPI、整合說明、Supabase 說明、審查紀錄
├── start.py / run_app.bat      一鍵啟動（自行偵測 Python，無寫死路徑）
└── web/ , desktop/             前端（Member A 的部分，由後端提供）

專案根目錄另含：
├── docs/backend-status.md      本文件
├── README.md                   總覽與使用說明
├── prototype/                  Member A 的原始 Flet 原型（僅供對照）
├── Python/                     Member B 的原始 Python 模組（已被 backend 取代）
└── Supabase/member-b-latest/   Member B 最新交付的 SQL（線上專案即用這份）
```

**設計原則**

1. **計算與框架分離** — `calculators/` 與 `services/` 不 import FastAPI 或資料庫，
   可以單獨測試、重複使用
2. **電價與程式分離** — 改電價只改 JSON，有測試確認程式裡沒有費率常值
3. **前端不重算** — 畫面上每個數字都來自 API
4. **錯誤不吞掉** — 每個錯誤都有機器可讀的 `code`
5. **不誇大** — 電費是估算，負載估算不宣稱安全
6. **雙語在後端** — 家電、迴路、方案、建議、警告、免責聲明都同時提供
   `_zh` 與 `_en`，前端只挑選，不翻譯；缺英文時退回中文而不留空白
7. **介面可切換** — 右上角 `EN` / `中文`，選擇存在 `localStorage`

---

## 6. 計算公式與假設

| 項目 | 公式 |
| --- | --- |
| 每月用電量 | `W ÷ 1000 × 每日時數 × 每月天數 × 數量` |
| 電費（累進） | 各級距度數 × 該級距費率，逐級累加 |
| 平均每度 | 總電費 ÷ 總度數 |
| 電流（單相） | `P ÷ (V × 功率因數)` |
| 電流（三相） | `P ÷ (√3 × V × 功率因數)` |

**重要假設（簡報時要能說明）**

- 用電量以額定功率估算，**未考慮變頻、待機、效率曲線、實際負載率**；
  冰箱冷氣等壓縮機電器的實際耗電通常低於這個估算值
- 電費**不含**公共電費、基本費、分攤與節電折扣
- 級距以「每期」計算，`bi_monthly` 會放大級距上限
- 負載估算只算**運轉電流**，不含啟動電流；電流以算術相加近似
- 租屋若由房東轉售，實際單價常高於台電級距（有 `flat_rate_resell_reference` 可呈現）

---

## 7. 測試（704 個）

| 測試檔 | 數量 | 涵蓋 |
| --- | --- | --- |
| `test_consumption.py` | 53 | 公式、總計、數量、邊界值、各類不合理輸入 |
| `test_electricity_bill.py` | 95 | 台電範例、級距邊界、季節、兩月一期、三方案、0 度、期間限制 |
| `test_load_estimator.py` | 54 | 歐姆定律、功率因數、單相／三相、安全裕度、超載組合、`limit_watts`、免責聲明 |
| `test_recommendations.py` | 71 | 高耗電辨識、每條規則、名稱比對、同名電器、去重、統計一致 |
| `test_simulation.py` | 59 | 前後比較、四種變更、**不改動原始資料**、同名、改名替換 |
| `test_data_check.py` | 29 | 電價／家電資料檔完整性（壞檔必須啟動就被拒） |
| `test_household_api.py` | 30 | 儲存 CRUD、儀表板聚合、失效回滾 |
| `test_api.py` | 121 | 端點、錯誤格式、啟動驗證、`power_factor`、UI 一致性、雙語欄位、前端實際 payload、迴歸 |
| `test_portability.py` | 24 | 不得有寫死路徑、啟動器、port 偵測 |
| `test_tariff_import.py` | 7 | 電價匯入工具與資料檔一致 |
| `test_schema_sql.py` | 15 | `db/schema.sql` 的結構、RLS、可重複執行 |
| `test_store_supabase.py` | 33 | Supabase 儲存層（mock PostgREST，不連真實專案）|
| `test_api_supabase.py` | 8 | 走 Supabase 後端時的 API 行為 |
| `test_web_i18n.py` | 31 | 中英字典對稱、markup 金鑰、用假 DOM 實際渲染與按下切換鈕、HTTP 的 `_en` 欄位 |
| `test_web_number_input.py` | 4 | 前端數字輸入容錯（`150`、`150W`、`1,200`、`6 小時`）|
| `test_docs_consistency.py` | 7 | 三份文件不得對測試數、Python 比例、相對連結各說各話 |
| `test_deploy.py` | 18 | 綁定位址（$PORT / 0.0.0.0）、.env 讀取、部署設定檔與金鑰不得入版控 |
| `test_mobile.py` | 6 | 手機路徑：Flet 開成網頁、只綁 0.0.0.0、只開一個埠、flet-web 安裝提示 |
| `test_product_recommendations.py` | 7 | 產品建議：費率取自電價表（不得寫死）、與 `/calculate/cost` 一致、型錄壞掉不影響其他功能 |
| `test_desktop_app.py` | 26 | 桌面版的資料層：API 對應、verdict 用語、金額分攤、離線時不崩潰、不得再寫死費率 |

合計 **641**。

> Supabase 那三支**不會**連到線上專案：`conftest.py` 會強制 `VOLTSPACE_STORAGE=local`
> 並清掉 Supabase 環境變數。這個保護是被一次真實意外逼出來的 —— 測試曾經寫入
> 3 筆資料到線上表（見 commit `824d132`）。

**幾個刻意設計的測試**

- `test_prices_live_in_json_not_in_code` — 掃描所有 `.py`，確認沒有費率常值
- `TestNonMutation` — 對原始清單 `deepcopy` 比對，確認模擬不會改到使用者資料
- `TestCrossEndpointConsistency` / `test_dashboard_summary_matches_...` —
  確認各端點與儀表板的數字一致
- `test_rates_reflect_the_2025_10_01_adjustment` — 檢查各級距調幅，
  避免只改到一半
- `test_no_machine_specific_paths` — 確認程式裡沒有 `C:\Users\...` 這種路徑
- `test_ui_does_not_reimplement_the_physics_or_tariffs` — 確認前端沒有重算物理

---

## 8. 開發工具（21 支）

| 工具 | 用途 |
| --- | --- |
| `smoke_api.py` | 對執行中的伺服器做端對端檢查 |
| `smoke_app.py` | 完整使用流程（家電 CRUD → 儀表板 → 模擬） |
| `probe_errors.py` | 51 個畸形請求，確認無 5xx、錯誤格式統一 |
| `benchmark.py` | 量測各函式與端點耗時 |
| `check_docs_numbers.py` | 比對文件數字與程式輸出，抓出過時內容 |
| `check_web_ui.py` | 靜態檢查 HTML/JS 的元素 id 與結構 |
| `check_desktop.py` | 用假 Page 驅動 Flet 介面邏輯（不開視窗） |
| `check_launcher.py` | 驗證 Python 自動偵測與錯誤訊息 |
| `lint_unused.py` | 檢查未使用的 import |
| `export_openapi.py` / `export_examples.py` | 產生 OpenAPI 與 13 個真實範例 |
| `import_tariff.py` | 把費率表轉成 JSON 並驗證 |
| `resolve_pins.py` / `resolve_deps.py` | 查哪些套件版本有預編譯 wheel |
| `fetch_wheels.py` / `install_wheels.py` | 完全不需要 pip 的離線安裝 |
| `check_wheel_availability.py` | 快速檢查單一套件的 wheel |
| `check_schema_match.py` | 比對 `db/schema.sql` 與線上 Supabase 的實際欄位／政策 |
| `check_web_i18n.py` | 用假 DOM 在 Node 裡實際渲染中英兩種介面 |
| `supabase_doctor.py` | 連線健檢：DNS、金鑰、資料表、欄位、讀寫 |
| `python_share.py` | 算 Python 程式碼比例（下面的數字就是它算的）|

### Python 比例（課程要求的數字）

用 `tools/python_share.py` 算，它會排除虛擬環境與快取，只算自己寫的程式。
比例會隨每次改動小幅浮動（改一行文件也會動），所以這裡只寫**整數百分比**，
精確數字用下面的指令自己跑：

| 算法 | 目前 |
| --- | --- |
| 含測試與工具 | **90%** |
| 只算產品程式碼（`backend/` 不含 tests/tools）| **79%** |

非 Python 的部分主要是前端的 `app.js` / `app.css` / `index.html`。
**要報哪一個，先跟助教確認計算規則** —— 範例簡報上寫的是
「51.84% including tests/tooling; 42.16% production-only」，
並註明 *"agree the course counting rule"*。重跑方式：

```bash
python tools/python_share.py
```

---

## 9. 效能

用 `tools/benchmark.py` 實測（8 台家電，20 次取中位數）：

**純計算函式**

| 函式 | 中位數 | p95 |
| --- | --- | --- |
| `calculate_consumption` | 0.078 ms | 0.089 ms |
| `calculate_bill`（級距） | 0.010 ms | 0.011 ms |
| `estimate_load` | 0.030 ms | 0.039 ms |
| `generate_recommendations` | 0.160 ms | 0.198 ms |
| `simulate` | 0.374 ms | 0.447 ms |

**完整請求路徑（含 FastAPI + Pydantic）**

| 端點 | 中位數 | p95 |
| --- | --- | --- |
| `/calculate/consumption` | 1.41 ms | 1.88 ms |
| `/calculate/cost` | 1.22 ms | 1.51 ms |
| `/calculate/load` | 1.24 ms | 1.50 ms |
| `/recommendations` | 1.57 ms | 1.92 ms |
| `/simulate` | 1.69 ms | 2.10 ms |
| `/recommendations`（120 台家電） | 3.72 ms | 4.16 ms |

可以看出**計算本身極快（0.01–0.37 ms），其餘都是框架開銷**（驗證、序列化），
所以優化重點放在計算與資料查找，而不是框架設定。

> 上表是 0.2.0 的單次量測（`python tools/benchmark.py 20`）。數字會隨機器與
> 背景負載浮動，**看數量級就好**，不要當成保證值。

做過的優化：家電別名索引加 `lru_cache`、比對結果按字串快取、
避免重複 `deepcopy`、避免為了取筆數而建出整個 payload。
`generate_recommendations` 因此快了 72%。

### 9.1 優化前的量測與逐項對照

這一輪不是為了榨效能，而是「先量測、再動手」，順便修掉正確性問題。

**實測改善（8 台家電，中位數）**

| 項目 | 優化前 | 優化後 | 變化 |
| --- | --- | --- | --- |
| `generate_recommendations` | 0.477 ms | 0.132 ms | **−72%** |
| `POST /recommendations` | 1.217 ms | 0.876 ms | −28% |
| `POST /recommendations`（120 台家電） | 6.565 ms | 2.784 ms | **−58%** |

**逐項對照**

| 類別 | 問題 | 處理 |
| --- | --- | --- |
| 效能 | 每台家電都重建一次家電別名索引（約 36 筆），且同一台家電被比對兩次 | 索引與名稱正規化加 `lru_cache`；比對結果按字串快取 |
| 效能 | `catalog_summary()` 只為了取筆數而建出整個 payload | 直接讀 `len(catalog["appliances"])` |
| 效能 | 模擬時把家電清單 `deepcopy` 兩份 | 只快照一次，modified 由 baseline 複製 |
| 正確性 | 用電量 0 度時 `lines` 是空陣列，前端畫級距圖會沒資料 | 回傳 1 筆「0 度、費率 X」的示意級距，並標記 `no_consumption` |
| 正確性 | `flat`／時間電價默默接受 `billing_months: 2`，回應寫「2 個月」卻只算一個月的錢 | 改為回 400 `plan_does_not_support_billing_months` |
| 正確性 | `PlanId` 是寫死的 Literal，新增電價方案要改程式 | 由 `tariffs.json` 動態產生 enum |
| 正確性 | 資料檔有錯要等到第一個請求才炸 | 新增 `app/data_check.py`，啟動時驗證（lifespan），壞檔直接拒絕啟動 |
| 一致性 | 負載估算的 `warnings` 只有英文，其他部分都雙語 | 全部改為 `message_zh` + `message_en` |
| 死欄位 | `ApplianceLoadOut.power_factor` 永遠是 1.0，因為 request schema 用 `extra="forbid"` 擋掉了 | `ApplianceIn`／`ReplacementIn` 加上 `power_factor`（0.1–1.0），實際套用到電流計算 |
| 死程式碼 | 未使用的常數、變數、`_cost_per_kwh` 的例外吞掉邏輯、重複的 plan 查詢 | 移除／合併 |

**可維護性**

- `resolve_season`／`season_label` 可接受 `tariffs` 參數，不再重複解析同一個檔案。
- `BillBreakdown.as_dict()` 只查一次季節標籤（原本查兩次）。
- `tools/lint_unused.py` 讓 `app/` 與 `tools/` 維持**零未使用 import**。
- `tests/test_data_check.py`（29 個測試）守住資料檔完整性。

---

## 10. 還沒做 / 已知限制

| 項目 | 說明 |
| --- | --- |
| **多使用者** | 沒有登入。本機 SQLite 是一台機器一份；切到 Supabase 時所有列屬於同一個 `household_id`（由 `VOLTSPACE_HOUSEHOLD_ID` 指定），不是一人一份 |
| **前端登入流程** | 前端匿名使用。`db/schema.sql` 的 RLS 是 `household_id = auth.uid()`，但要真的多使用者還需要登入取得 `auth.uid()`，目前沒有做 |
| **即時電表資料** | 只做估算，沒有串接實際電表或台電 API |
| **電價自動更新** | 台電再調價時要手動改 `tools/import_tariff.py` 的費率表再匯入，沒有自動抓取 |
| **時間電價精確度** | 二段式時間電價是簡化估算，標示為 `is_estimate` |
| **家電功率** | 用典型值，不是使用者實際銘牌（UI 允許自訂） |
| **Flet 桌面版** | 已升級到 Flet 1.0 並可用，但不是預設；預設是網頁版 |
| **部署** | 只在開發環境跑過（uvicorn），沒有容器化或雲端部署設定 |

---

## 11. 快速驗證指令

```bash
cd backend

# 環境檢查（找 Python、驗資料檔）
python start.py --check

# 全部測試
python -m pytest

# 資料檔完整性
python -m app.data_check

# 文件數字是否過時
python tools/check_docs_numbers.py

# 未使用 import
python tools/lint_unused.py

# 啟動並開瀏覽器
run_app.bat
```

---

## 12. 對應到課程要求

| 要求 | 狀態 | 位置 |
| --- | --- | --- |
| 用電量計算 | ✅ | `app/calculators/consumption.py` |
| 電費計算（級距、期間、資料分離） | ✅ | `app/calculators/electricity_bill.py` + `app/data/tariffs.json` |
| 節電建議（規則式、含原因與節省量） | ✅ | `app/services/recommendations.py` |
| 情境模擬（不改原始資料） | ✅ | `app/services/simulation.py` |
| 電流負載估算（含警示，不宣稱安全） | ✅ | `app/calculators/load_estimator.py` |
| FastAPI + Pydantic + pytest | ✅ | `app/main.py`、`app/schemas.py`、`tests/` |
| API 使用說明 | ✅ | `README.md`、`docs/openapi.json` |
| 五個指定端點 | ✅ | 見第 4 節（全部實作，另外還有 11 個 JSON 端點與 1 個網頁介面）|
