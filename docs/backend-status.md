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
| 應用程式碼 | 12 個模組，**4,176 行** |
| 測試程式碼 | 10 個檔案，**3,563 行** |
| API 端點 | **15 個**（5 個核心 + 6 個儲存 + 4 個參考資料） |
| 測試 | **535 個**，全數通過（Python 3.12 與 3.14） |
| 開發工具 | 17 支腳本 |
| 電價方案 | 3 種（台電累進、時間電價、租屋單一費率） |
| 家電參考資料 | 12 種（含典型功率、電壓、使用時數、建議規則） |

---

## 2. 必做功能的完成狀況

課程要求的六大項，逐項對照：

### 2.1 用電量計算 — ✅ 完成

`app/calculators/consumption.py`（324 行）

- 單一家電用電量：`kWh/月 = W ÷ 1000 × 每日時數 × 每月天數 × 數量`
- 所有家電總用電量，並計算每台佔比
- 可修改功率、每日時數、每月天數、數量
- 輸入驗證：型別、範圍（功率 0.1–100000 W、時數 0–24、天數 0–31）、
  非有限數（NaN/Inf）一律拒絕
- 合法但可疑的值回 `warnings`（例如 24 小時運轉、25000W），不是錯誤

### 2.2 電費計算 — ✅ 完成

`app/calculators/electricity_bill.py`（451 行）

- **電價資料與程式完全分離**：所有費率在 `app/data/tariffs.json`，
  程式碼裡沒有任何一個費率常值（有測試守著）
- **級距（累進）計算**：台電住宅六級距，測到 100 萬度都不會失真
- **適用期間**：夏月（6–9 月）／非夏月自動判斷，也可強制指定
- **帳單期間**：支援台電「兩個月一期」，級距上限會依月數放大
  （1040 度兩月一期 = 520 度月單價 × 2，有測試驗證等價）
- 另外支援 **時間電價** 與 **租屋單一費率** 兩種方案
- 不支援的組合會明確報錯（例如單一費率不接受 `billing_months: 2`）

### 2.3 節電建議 — ✅ 完成

`app/services/recommendations.py`（653 行）

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

`app/services/simulation.py`（467 行）

- 比較修改前後的用電量與電費
- 顯示節省度數、節省金額、節省百分比、年度節省金額
- **保證不修改使用者原本的資料**：進入函式先快照，改動只發生在副本上
  （`TestNonMutation` 有 4 個測試，另有 3 個測試在別處驗證不會改到輸入）
- 四種變更：改時數、改功率、改天數、換機種（`replace_with`）
- 換機種時改名不會把一列拆成兩列（保留原本身分，另外回報 `replaced_by`）

### 2.5 電流與負載估算 — ✅ 完成（簡化版）

`app/calculators/load_estimator.py`（355 行）

- `I = P ÷ (V × 功率因數)`，支援單相與三相（三相除以 √3）
- 與使用者輸入的負載上限比較，給四種判定：
  `safe` / `near_limit` / `over_limit` / `no_limit`
- 可找出「哪幾台同時開會超載」的最小組合
- **明確不宣稱安全**：每次回應都附免責聲明，並列出模型限制
  （只算運轉電流、不含啟動電流、算術相加、不考慮線徑與延長線）

### 2.6 API、驗證與測試 — ✅ 完成

- **FastAPI** 提供 15 個端點，自動產生 OpenAPI 3.1 文件（`/docs` 可互動測試）
- **Pydantic** 驗證輸入，錯誤統一格式（每個錯誤回應都有這 5 個欄位）：
  `{error, code, message, field, details[]}`
  - **400** = 語意上無法計算（`appliance_not_found`、`invalid_value`）
  - **422** = 格式或數值不合理（`validation_error`，附 `field` 指出是哪個欄位）
  - **404** = 要操作的已儲存家電不存在（`appliance_not_found`）
  - **500** = 僅用於儲存層故障（`storage_error`）；`probe_errors.py` 的 51 個畸形請求
    確認一般錯誤不會走到 500

  全部錯誤碼只有 4 個：`validation_error`、`invalid_value`、`appliance_not_found`、
  `storage_error`，前端可以據此安全地分流。
- **pytest** 535 個測試，涵蓋計算函式與 API
- **API 使用說明**：`README.md` 有每個端點的 curl 範例與完整回應；
  `docs/openapi.json` 可直接匯入 Postman
- **啟動即驗證資料檔**：電價或家電資料有錯，伺服器直接拒絕啟動

---

## 3. 超出要求的部分

這些不在作業要求內，但為了讓前端能真的串起來而補的。

### 3.1 家電儲存（`app/store.py`，220 行）

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
組員下載後不能直接跑。SQLite 讓 App 離線可用；Supabase 仍支援，
schema 在 `db/schema.sql`，切換方式見 `docs/supabase.md`。

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

## 4. API 一覽（15 個端點）

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
├── app/                        12 個模組，4,176 行
│   ├── main.py                 796 行  FastAPI 應用：端點、錯誤處理、生命週期
│   ├── schemas.py              690 行  Pydantic 模型（32 個 schema）
│   ├── store.py                220 行  本地 SQLite 儲存
│   ├── data_check.py           179 行  啟動時資料檔完整性驗證
│   ├── calculators/            ← 純計算，完全不 import FastAPI 或資料庫
│   │   ├── consumption.py      324 行  用電量 + 輸入驗證
│   │   ├── electricity_bill.py 451 行  電費（級距／時間電價／單一費率）
│   │   └── load_estimator.py   355 行  電流與負載
│   ├── services/               ← 規則與資料整合
│   │   ├── recommendations.py  653 行  規則式建議
│   │   └── simulation.py       467 行  情境模擬
│   └── data/
│       ├── tariffs.json        5.2 KB  3 種電價方案
│       └── appliances.json    13.9 KB  12 種家電 + 規則
├── tests/                      10 個檔案、3,563 行、535 個測試（第 7 節）
├── tools/                      17 支腳本、2,113 行（第 8 節）
├── db/schema.sql               Supabase/PostgreSQL schema
├── docs/                       OpenAPI、整合說明、Supabase 說明、審查紀錄
├── start.py / run_app.bat      一鍵啟動（自行偵測 Python，無寫死路徑）
└── web/ , desktop/             前端（Member A 的部分，由後端提供）

專案根目錄另含：
├── docs/backend-status.md      本文件
├── README.md                   總覽與使用說明
├── frontend/ , prototype/      Member A 的原始 Flet 原型（僅供對照）
├── Python/ , Supabase/         Member B 的原始成果（已被 backend 取代）
```

**設計原則**

1. **計算與框架分離** — `calculators/` 與 `services/` 不 import FastAPI 或資料庫，
   可以單獨測試、重複使用
2. **電價與程式分離** — 改電價只改 JSON，有測試確認程式裡沒有費率常值
3. **前端不重算** — 畫面上每個數字都來自 API
4. **錯誤不吞掉** — 每個錯誤都有機器可讀的 `code`
5. **不誇大** — 電費是估算，負載估算不宣稱安全

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

## 7. 測試（535 個）

| 測試檔 | 數量 | 涵蓋 |
| --- | --- | --- |
| `test_consumption.py` | 53 | 公式、總計、數量、邊界值、各類不合理輸入 |
| `test_electricity_bill.py` | 95 | 台電範例、級距邊界、季節、兩月一期、三方案、0 度、期間限制 |
| `test_load_estimator.py` | 52 | 歐姆定律、功率因數、單相／三相、安全裕度、超載組合、免責聲明 |
| `test_recommendations.py` | 71 | 高耗電辨識、每條規則、名稱比對、同名電器、去重、統計一致 |
| `test_simulation.py` | 59 | 前後比較、四種變更、**不改動原始資料**、同名、改名替換 |
| `test_data_check.py` | 29 | 電價／家電資料檔完整性（壞檔必須啟動就被拒） |
| `test_household_api.py` | 30 | 儲存 CRUD、儀表板聚合、失效回滾 |
| `test_api.py` | 115 | 端點、錯誤格式、啟動驗證、`power_factor`、UI 一致性、迴歸 |
| `test_portability.py` | 24 | 不得有寫死路徑、啟動器、port 偵測 |
| `test_tariff_import.py` | 7 | 電價匯入工具與資料檔一致 |

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

## 8. 開發工具（17 支）

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

---

## 9. 效能

用 `tools/benchmark.py` 實測（8 台家電，20 次取中位數）：

**純計算函式**

| 函式 | 中位數 |
| --- | --- |
| `calculate_consumption` | 0.078 ms |
| `calculate_bill`（級距） | 0.010 ms |
| `estimate_load` | 0.029 ms |
| `generate_recommendations` | 0.135 ms |
| `simulate` | 0.367 ms |

**完整請求路徑（含 FastAPI + Pydantic）**

| 端點 | 中位數 | p95 |
| --- | --- | --- |
| `/calculate/consumption` | 1.35 ms | 1.57 ms |
| `/calculate/cost` | 1.16 ms | 1.43 ms |
| `/calculate/load` | 1.26 ms | 1.58 ms |
| `/recommendations` | 1.45 ms | 1.67 ms |
| `/simulate` | 1.67 ms | 1.98 ms |
| `/recommendations`（120 台家電） | 3.62 ms | 4.01 ms |

可以看出**計算本身極快（0.01–0.37 ms），其餘都是框架開銷**（驗證、序列化），
所以優化重點放在計算與資料查找，而不是框架設定。

做過的優化：家電別名索引加 `lru_cache`、比對結果按字串快取、
避免重複 `deepcopy`、避免為了取筆數而建出整個 payload。
`generate_recommendations` 因此快了 72%。

---

## 10. 還沒做 / 已知限制

| 項目 | 說明 |
| --- | --- |
| **多使用者** | 目前沒有登入，資料存在本機 SQLite，一台機器一份。要多使用者需接 Supabase 並開啟登入 |
| **前端登入流程** | 前端目前匿名使用；Supabase 的 RLS 已設計好 `households.access_token` 方案 |
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
| 五個指定端點 | ✅ | 見第 4 節（全部實作，另加 10 個輔助端點） |
