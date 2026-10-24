# VoltSpace — 完整可執行的 MVP

VoltSpace 是 Group 9 的租屋用電管理 App。這個目錄現在是**整套可以一鍵執行的系統**：

- **後端計算核心（Member C，喬元震）** — 用電量、電費、負載、節電建議、情境模擬。
- **前端（Member A，郭潼）** — 原本的 Flet 原型，已修好並改成呼叫後端計算。
- **資料庫（Member B，呂婉菲）** — 原始 Supabase SQL 的 contract 問題已修正；
  另附本地 SQLite，讓 App 不需要雲端帳號就能跑。

## 一鍵啟動

### 第一次使用（下載後）

只需要一個前置條件：**這台電腦有 Python 3.10 以上**，然後**先進入 `backend/` 資料夾**：

```
cd backend
python start.py --setup        # 建立 .venv 並安裝套件（約 1 分鐘）
```

`start.py` 會**自己尋找**這台電腦上的 Python（依序找
`.venv` → 執行本程式的解譯器 → `py` → `python` → `python3` → 常見安裝路徑），
**沒有任何寫死的路徑**，所以複製到任何電腦都能用。

### 之後每次（一樣在 `backend/` 資料夾內）

```
run_app.bat            # Windows：雙擊即可
./run_app.sh           # macOS / Linux
```

它會自動挑選可用的 Python、啟動後端、**開啟瀏覽器**到 App。
網頁介面與 API 同一個伺服器，所以不需要另外跑前端。

| 指令 | 作用 |
| --- | --- |
| `run_app.bat` | 啟動並開瀏覽器 |
| `run_app.bat --setup` | 建立 `.venv` 並安裝套件 |
| `run_app.bat --check` | 只檢查環境與資料檔，不啟動 |
| `run_app.bat --port 8080` | 換連接埠（網址變成 `:8080`） |
| `run_app.bat --flet` | 同時開 Flet 桌面版（需 `requirements-desktop.txt`） |

| 網址 | 內容 |
| --- | --- |
| <http://127.0.0.1:8000/> | 網頁介面（家電庫、插座、電費、建議） |
| <http://127.0.0.1:8000/docs> | Swagger 互動式 API 文件 |
| <http://127.0.0.1:8000/health> | 健康檢查 |

> 詳細的整合說明、三個成員的原始成果分別被怎麼處理，見
> [`backend/docs/integration.md`](backend/docs/integration.md)。
>
> 其他文件：[Supabase 整合](backend/docs/supabase.md)（選用）、
> [程式碼審查紀錄](backend/docs/code-review-audit.md)、
> [API 規格](backend/docs/openapi.json)。

### 換到另一台電腦時

整個專案資料夾複製過去即可，**不需要修改任何路徑**：

- 程式裡沒有 `C:\Users\...` 這類絕對路徑（`backend/tests/test_portability.py` 會檢查）。
- `.venv/` 不必一起複製；到新電腦跑一次 `python start.py --setup` 重建即可
  （`.venv` 綁定作業系統與 Python 版本，複製過去通常不能用）。
- 家電資料存在 `backend/.data/voltspace.db`；想保留就一起複製，不想保留刪掉即可。

**如果沒有網路**，用離線安裝（見 [`backend/README` 的疑難排解](backend/docs/integration.md)），
不需要 pip。

---

## 設計原則

1. **計算與框架分離** — `app/calculators/` 與 `app/services/` 完全不 import FastAPI 或
   資料庫，可以單獨測試、重複使用。
2. **電價資料與程式分離** — 所有費率都放在 `app/data/tariffs.json`，調整電價只需改資料。
3. **前端不重算** — 畫面上的每個數字都來自後端 API；前端沒有任何公式或寫死的費率。
4. **兩種驗證並存** — Pydantic 檢查 JSON 格式（HTTP 422），計算模組負責領域規則。
5. **不誇大** — 電費與節電量都標示為估算；負載估算明確聲明**不保證電路安全**。

---

## 1. 目錄結構

```
VoltSpace/
├── README.md                    本文件：怎麼跑、怎麼整合
├── backend/                     ← 可執行的系統（主體）
│   ├── app/
│   │   ├── main.py              FastAPI 應用：計算 API + 家電儲存 + 儀表板端點
│   │   ├── schemas.py           Pydantic 請求／回應模型（含 OpenAPI 範例）
│   │   ├── store.py             本地 SQLite 家電儲存（不需要雲端就能用）
│   │   ├── data_check.py        啟動時的資料檔完整性檢查（壞資料直接拒絕啟動）
│   │   ├── calculators/         ← 純計算，無框架相依
│   │   │   ├── consumption.py       每月用電量 + 輸入驗證
│   │   │   ├── electricity_bill.py  電費（級距／時間電價／單一費率）
│   │   │   └── load_estimator.py    電流與負載估算
│   │   ├── services/            ← 規則與資料整合
│   │   │   ├── recommendations.py   規則式節電建議
│   │   │   └── simulation.py        情境模擬
│   │   └── data/
│   │       ├── tariffs.json         電價方案（台電住宅累進等 3 種）
│   │       └── appliances.json      12 種家電參考功率／電壓／規則
│   ├── web/                     ← Member A 的介面（HTML/CSS/JS，由後端提供）
│   │   ├── index.html
│   │   ├── app.css              沿用原型的新擬物風格
│   │   └── app.js               只呼叫 API，不含公式與費率
│   ├── desktop/app.py           Flet 桌面版（已升級到 Flet 1.0 並改接 API）
│   ├── db/schema.sql            Supabase/PostgreSQL schema（已修正 contract）
│   ├── start.py                 一鍵啟動器（挑 Python、起後端、開瀏覽器）
│   ├── run_app.bat / run_app.sh 雙擊用的一鍵入口
│   ├── tests/                   525 個測試
│   │   ├── conftest.py
│   │   ├── test_consumption.py
│   │   ├── test_electricity_bill.py
│   │   ├── test_load_estimator.py
│   │   ├── test_recommendations.py
│   │   ├── test_simulation.py
│   │   ├── test_data_check.py
│   │   ├── test_household_api.py    儲存與儀表板端點
│   │   ├── test_portability.py      可攜性（不得有寫死路徑）
│   │   └── test_api.py
│   ├── docs/
│   │   ├── integration.md       三個成員的成果如何整合（先讀這份）
│   │   ├── supabase.md          如何使用 Member B 的 Supabase schema
│   │   ├── openapi.json         產生的 OpenAPI 3.1 規格
│   │   ├── examples/*.json      13 個真實請求範例（由程式產生）
│   └── code-review-audit.md     對抗式程式碼審查紀錄與修正對照表
├── tools/                       產生文件、smoke test、benchmark、離線安裝等
│   ├── pytest.ini
│   ├── requirements.txt         執行後端所需
│   └── requirements-desktop.txt 選用：Flet 桌面版
├── frontend/                    Member A 的原始 Flet 原型（Flet 0.x，僅供對照）
├── prototype/                   同上（對照用快照）
├── Python/                      Member B 的原始 Python 模組（已被 backend/app/store.py 取代）
└── Supabase/                    Member B 的原始 SQL（已被 backend/db/schema.sql 取代）
```

---

## 2. 快速開始

> ### ⚠️ 先看這裡：為什麼連不上 `127.0.0.1:8000/docs`？
>
> `/docs` 是**執行中的伺服器**提供的頁面，不是檔案。必須先完成 2.1 安裝、再啟動 2.2，
> 而且**終端機視窗要保持開著**（關掉或按 Ctrl+C 服務就結束了）。常見的三個原因：
>
> 1. **根本沒啟動伺服器** —— 瀏覽器會顯示「無法連上這個網站 / ERR_CONNECTION_REFUSED」。
> 2. **終端機有錯誤但沒注意** —— 通常是 `ModuleNotFoundError: No module named 'fastapi'`
>    或 `No module named 'app'`，代表套件沒裝好或**不在 `backend/` 目錄下執行**。
> 3. **連接埠不同** —— 如果啟動時用了 `--port 8080`，網址就必須是 `...:8080/docs`。
>
> **最省事的做法**：直接雙擊 `run_app.bat`（見 2.2 的說明）。
>
> 要確認到底有沒有在跑，開另一個終端機執行：
>
> ```bash
> curl http://127.0.0.1:8000/health
> # 有回應 → 伺服器正常，要用 /docs 開文件
> # 連不上   → 伺服器沒在跑，回到 2.1 / 2.2
> ```

### 2.1 安裝

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate            # Windows
# source .venv/bin/activate       # macOS / Linux
pip install -r requirements.txt
```

> **如果 `python -m venv` 失敗**（例如 `ensurepip is not available`、`No module named pip`），
> 代表這台機器上的 Python 是精簡版的執行環境。請改用附帶的腳本，不需要 pip 也不需要網路：
>
> ```bash
> python tools\resolve_deps.py --dest .wheels fastapi==0.143.0 uvicorn==0.54.0 ^
>        pydantic==2.14.1 pydantic-core==2.50.1 pytest==9.1.1 httpx==0.28.1
> python tools\install_wheels.py --src .wheels --dest .pylibs
> ```
>
> 之後用 `run_app.bat` 啟動即可（它會自動設定 `PYTHONPATH`）。詳見第 8 節。
>
> ### ⚠️ 遇到 `pydantic-core` 編譯失敗？
>
> ```
> error: the configured Python interpreter version (3.14) is newer than
>        PyO3's maximum supported version (3.13)
> ERROR: Failed building wheel for pydantic-core
> ```
>
> 這不是網路或 Rust 環境的問題，而是**版本不相容**。`pydantic-core` 是 Rust 編譯的擴充套件，
> 舊版（例如 `2.27.x`，對應 `pydantic 2.10`）最高只支援到 **Python 3.13**。你的 Python 是
> **3.14**，pip 找不到預編譯 wheel 就改成從原始碼編譯，於是失敗。
>
> **解法**：`requirements.txt` 已改成 `pydantic==2.14.1` + `pydantic-core==2.50.1`，
> 這個版本同時提供 cp312 與 cp314 的預編譯 wheel，因此 **3.12 與 3.14 都能安裝，不需要編譯器**。
> 只要 `pip install -r requirements.txt` 即可。已實測 Python 3.14 可完整載入並通過全部測試。
>
> 想自己確認某個 Python 版本有沒有預編譯 wheel：
>
> ```bash
> python tools/resolve_pins.py --tag cp312 --tag cp314
> ```
>
> 若想強制用最新的套件版本（略過 requirements.txt 的指定）：
> `python tools/resolve_deps.py --dest .wheels --tag cp314 <套件>==<版本> ...`
>
> ⚠️ **不要混用不同 Python 版本的 `.pylibs`**：`.pylibs` 裡的 `.pyd` 是為特定版本編譯的。
> 用 3.12 的 `.pylibs` 搭配 3.14 的直譯器會出現
> `ImportError: cannot import name 'ArgsKwargs' from 'pydantic_core._pydantic_core'`。
> `run_app.bat` 已處理這件事：有 `.venv` 時只用 venv、不會再疊上 `.pylibs`。

### 2.2 啟動 API

**Windows 最簡單的方式**（會自動設定環境變數並印出網址）：

```bash
run_app.bat            # 預設 8000
run_app.bat --port 8080   # 換連接埠，網址就要跟著改成 :8080/docs
```

或者手動啟動：

```bash
cd backend
uvicorn app.main:app --reload --port 8000
```

**必須在 `backend/` 目錄下執行**（`app.main` 是相對於這個目錄的套件路徑），
而且這個終端機視窗要一直開著。看到下面這行才算成功：

```
Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
```

| 網址 | 說明 |
| --- | --- |
| <http://127.0.0.1:8000/docs> | Swagger UI（可直接點按測試） |
| <http://127.0.0.1:8000/redoc> | ReDoc 文件 |
| <http://127.0.0.1:8000/openapi.json> | OpenAPI 規格 |
| <http://127.0.0.1:8000/health> | 健康檢查（用來確認伺服器活著） |

手機模擬器要連本機時，iOS Simulator 用 `http://127.0.0.1:8000`，
Android Emulator 用 `http://10.0.2.2:8000`，實機測試請用電腦的區域網路 IP。

### 2.3 執行測試

```bash
python -m pytest                     # 全部 525 個測試
python -m pytest tests/test_api.py   # 只測 API
python -m pytest -k tier             # 只測名稱含 tier 的測試
```

對執行中的伺服器做端對端檢查：

```bash
python tools/smoke_api.py http://127.0.0.1:8000
```

用畸形與邊界請求確認 API 不會回 5xx、且每個 4xx 都是統一錯誤格式：

```bash
python tools/probe_errors.py
```

重新產生文件產物（改過 API 或電價後執行）：

```bash
python tools/export_openapi.py
python tools/export_examples.py
```

---

## 3. API 一覽

| Method | Endpoint | 用途 |
| --- | --- | --- |
| POST | `/calculate/consumption` | 計算單一或多個家電的每月用電量 |
| POST | `/calculate/cost` | 計算預估電費（級距／季節／帳單期間） |
| POST | `/calculate/load` | 估算電流並與負載上限比較（初步警示） |
| POST | `/recommendations` | 產生規則式節電建議（含原因與預估節省量） |
| POST | `/simulate` | 比較修改前後的用電量與電費（不改動原始資料） |
| GET | `/tariffs` | 取得電價方案與級距（前端做選單／說明頁用） |
| GET | `/appliances` | 取得家電參考功率、電壓、典型使用時數 |
| GET | `/health` | 健康檢查 |

所有錯誤都回傳同一個形狀：

```json
{
  "error": true,
  "code": "validation_error",
  "message": "Input should be greater than 0",
  "field": "appliances.0.power_watts",
  "details": [{"field": "appliances.0.power_watts", "message": "...", "type": "greater_than"}]
}
```

| HTTP | 代表意義 | 常見 `code` |
| --- | --- | --- |
| 422 | 格式或數值不合理 | `validation_error`、`power_not_positive`、`days_out_of_range` |
| 400 | 語意上無法計算 | `appliance_not_found`、`unknown_plan`、`unsupported_change_field` |

### 3.1 `POST /calculate/consumption`

```
kWh/月 = 功率(W) ÷ 1000 × 每日時數 × 每月天數 × 數量
```

```bash
curl -X POST http://127.0.0.1:8000/calculate/consumption \
  -H "Content-Type: application/json" \
  -d '{
        "appliances": [
          {"appliance_id":"a1","name":"冷氣機","category":"cooling",
           "power_watts":900,"hours_per_day":9,"days_per_month":30,"voltage":220},
          {"appliance_id":"a2","name":"冰箱","category":"cooling",
           "power_watts":130,"hours_per_day":24,"days_per_month":30,"voltage":110},
          {"appliance_id":"a3","name":"桌上型電腦",
           "power_watts":250,"hours_per_day":6,"days_per_month":30,"voltage":110}
        ]
      }'
```

回應（節錄，完整內容見 `backend/docs/examples/consumption_household.json`）：

```json
{
  "count": 3,
  "total_daily_kwh": 12.72,
  "total_monthly_kwh": 381.6,
  "average_monthly_kwh_per_appliance": 127.2,
  "highest_consumption_appliance": "冷氣機",
  "appliances": [
    {
      "appliance_id": "a1", "name": "冷氣機", "power_watts": 900.0,
      "hours_per_day": 9.0, "days_per_month": 30, "quantity": 1,
      "daily_kwh": 8.1, "monthly_kwh": 243.0,
      "share_of_total_percent": 63.68, "replacement_label": null, "warnings": []
    },
    {
      "appliance_id": "a2", "name": "冰箱", "monthly_kwh": 93.6,
      "share_of_total_percent": 24.53,
      "warnings": [{"code": "near_continuous_use", "field": "hours_per_day",
                    "message_zh": "每日 24 小時幾乎是全天運轉，建議再用負載估算確認用電安全。",
                    "message_en": "24 hours/day means this appliance runs almost continuously; ..."}]
    },
    {"appliance_id": "a3", "name": "桌上型電腦", "monthly_kwh": 45.0, "share_of_total_percent": 11.79}
  ]
}
```

**欄位說明**

| 欄位 | 型別 | 必填 | 預設 | 說明 |
| --- | --- | --- | --- | --- |
| `appliance_id` | string | ✗ | `null` | Member B 資料庫主鍵，模擬時用來指定要改哪一台 |
| `name` | string | ✓ | — | 家電名稱（1–80 字元，不能只有空白） |
| `category` | string | ✗ | `null` | 分類，也會用來比對參考資料庫 |
| `power_watts` | number | ✓ | — | 功率，`0 < W ≤ 100000` |
| `hours_per_day` | number | ✓ | — | 每日時數，`0 ≤ h ≤ 24` |
| `days_per_month` | integer | ✗ | `30` | 每月天數，`0–31` |
| `quantity` | integer | ✗ | `1` | 相同電器數量，`1–999` |
| `voltage` | number | ✗ | `null`→110 | 電壓；用電量計算不受影響，只影響負載估算 |
| `power_factor` | number | ✗ | `null`→1.0 | 功率因數 0.1–1.0；只影響 `/calculate/load` 的電流。馬達／壓縮機可填 0.8–0.9 |

> `warnings` 不是錯誤，是「數值合法但可疑」的提醒（例如 24000W、每日 24 小時運轉、
> 時數為 0）。前端可以直接顯示 `message_zh`。

### 3.2 `POST /calculate/cost`

兩種用法：直接給度數，或給家電清單讓後端先算度數。

```bash
# (a) 夏月 381.6 度，住宅累進電價
curl -X POST http://127.0.0.1:8000/calculate/cost \
  -H "Content-Type: application/json" \
  -d '{"consumption_kwh":381.6,"month":8,"plan_id":"tw_residential_tiered"}'

# (b) 直接送家電清單（會忽略 consumption_kwh 並回報計算出來的度數）
curl -X POST http://127.0.0.1:8000/calculate/cost \
  -H "Content-Type: application/json" \
  -d '{"consumption_kwh":0,"month":8,"appliances":[{"name":"冷氣機","power_watts":900,"hours_per_day":9,"days_per_month":30,"voltage":220}]}'

# (c) 台電兩個月一期（1040 度）
curl -X POST http://127.0.0.1:8000/calculate/cost \
  -H "Content-Type: application/json" \
  -d '{"consumption_kwh":1040,"month":8,"billing_period":"bi_monthly"}'
```

回應（節錄）：

```json
{
  "plan_id": "tw_residential_tiered",
  "plan_name_zh": "台電住宅用電－累進（級距）電價",
  "plan_type": "tiered",
  "season": "summer",
  "season_label_zh": "夏月（6月1日至9月30日）",
  "billing_months": 1,
  "consumption_kwh": 381.6,
  "total_amount": 907.02,
  "total_amount_rounded": 907,
  "currency": "TWD",
  "effective_rate_per_kwh": 2.3769,
  "lines": [
    {"tier_index": 1, "label_zh": "120度以下部分", "range_from_kwh": 0.0, "range_to_kwh": 120.0,
     "rate_per_kwh": 1.68, "kwh_in_tier": 120.0, "amount": 201.6},
    {"tier_index": 2, "label_zh": "121~330度部分", "range_from_kwh": 120.0, "range_to_kwh": 330.0,
     "rate_per_kwh": 2.45, "kwh_in_tier": 210.0, "amount": 514.5},
    {"tier_index": 3, "label_zh": "331~500度部分", "range_from_kwh": 330.0, "range_to_kwh": 500.0,
     "rate_per_kwh": 3.7, "kwh_in_tier": 51.6, "amount": 190.92}
  ],
  "warnings": [{"code": "estimate_only", "message_zh": "此為依 VoltSpace 電價表計算的估算值。..."}],
  "is_estimate": false,
  "consumption_source": "input_kwh",
  "computed_total_monthly_kwh": null
}
```

**選項欄位**

| 欄位 | 型別 | 預設 | 說明 |
| --- | --- | --- | --- |
| `consumption_kwh` | number | — | 用電度數（提供 `appliances` 時會被忽略） |
| `appliances` | array | `null` | 家電清單；有值時後端先算總度數 |
| `plan_id` | enum | `tw_residential_tiered` | `tw_residential_tiered`／`tw_residential_tou`／`flat_rate_resell_reference` |
| `month` | integer | `null` | 1–12，用來判斷夏月／非夏月（未提供視為非夏月） |
| `season` | enum | `null` | `summer`／`non_summer`，提供時覆蓋 `month` |
| `billing_period` | enum | `monthly` | `monthly` 或 `bi_monthly`（台電兩個月一期） |
| `billing_months` | integer | `null` | 1–12，提供時覆蓋 `billing_period` |
| `peak_share` | number | `0.5` | 0–1，僅時間電價方案使用 |

**`billing_period` 的意義**：台電的級距上限是「每期」計算，所以 `bi_monthly` 會把
120/330/500/700/1000 度都乘以 2。因此 1040 度兩月一期的費用，等於 520 度月單價 × 2。

### 3.3 `POST /calculate/load`

```
單相：I = P ÷ (V × 功率因數)
三相：I = P ÷ (√3 × V × 功率因數)
```

```bash
curl -X POST http://127.0.0.1:8000/calculate/load \
  -H "Content-Type: application/json" \
  -d '{
        "appliances": [
          {"name":"吹風機","power_watts":1200,"hours_per_day":0.3,"voltage":110},
          {"name":"電暖器","power_watts":1200,"hours_per_day":3,"voltage":110}
        ],
        "voltage": 110,
        "load_limit_amps": 15,
        "breaker_amps": 20,
        "circuit_label": "房間插座迴路",
        "include_overload_combinations": true
      }'
```

回應（節錄）：

```json
{
  "circuit_label": "房間插座迴路",
  "voltage_used": 110,
  "total_power_watts": 2400.0,
  "estimated_total_current_amps": 21.8182,
  "limit_amps": 15.0,
  "recommended_max_current_amps": 12.0,
  "usage_percent_of_limit": 145.45,
  "verdict": "over_limit",
  "severity": "danger",
  "verdict_message_zh": "估算總電流 21.82A 已超過上限 15.00A，請勿同時開啟這些電器，並請專業電工檢查迴路。",
  "highest_current_appliance": {"name": "吹風機", "current_amps": 10.9091},
  "overload_combinations": {
    "combination_size": 2,
    "combinations": [{"appliances": ["吹風機", "電暖器"], "total_current_amps": 21.8182, "over_by_amps": 6.8182}],
    "message_zh": "以下電器組合的估算電流會超過上限，請避免同時使用。"
  },
  "disclaimer_zh": "本工具僅提供初步負載估算，不構成電路安全保證，也不能取代專業電工的現場檢查。"
}
```

`verdict` 四種值：`safe`（≤ 上限 × `safety_margin`）、`near_limit`、
`over_limit`、`no_limit`（沒給上限）。對應 `severity`：`ok`／`warning`／`danger`／`info`。

`phases` 設為 `3` 時會改用三相公式 `I = P ÷ (√3 × V × PF)`，`estimated_total_current_amps`
與 `appliances[].current_amps` 都會跟著變（同一台 3000W/220V 的電器：單相 13.64A、
三相 7.87A）。一般租屋房間是單相，請保持預設 `1`。
`include_overload_combinations: true` 時，`overload_combinations` 會列出**最小**的
同時使用超載組合（例如「吹風機 + 電暖器」），適合直接變成前端警語。

**這個功能做不到什麼（前端文案請一起說明）**

- 只算**運轉電流**，不含馬達／壓縮機的**啟動電流**（可能高出數倍）。
- 電流以**算術相加**近似，混合電感性與電阻性負載時偏保守。
- 不考慮延長線、插座老舊、線徑、迴路共用。
- **不保證電路安全**，也不能取代專業電工檢查。

### 3.4 `POST /recommendations`

```bash
curl -X POST http://127.0.0.1:8000/recommendations \
  -H "Content-Type: application/json" \
  -d '{"appliances":[
        {"appliance_id":"a1","name":"冷氣機","category":"cooling","power_watts":900,"hours_per_day":9,"days_per_month":30,"voltage":220},
        {"appliance_id":"a2","name":"冰箱","category":"cooling","power_watts":130,"hours_per_day":24,"days_per_month":30,"voltage":110},
        {"appliance_id":"a3","name":"桌上型電腦","power_watts":250,"hours_per_day":6,"days_per_month":30,"voltage":110}
      ],"month":8,"top_n":3}'
```

回應（節錄，完整內容見 `backend/docs/examples/recommendations_student_room.json`）：

```json
{
  "total_monthly_kwh": 381.6,
  "blended_rate_per_kwh": 2.3769,
  "top_consumers": [
    {"appliance": "冷氣機", "monthly_kwh": 243.0, "share_of_total_percent": 63.68},
    {"appliance": "冰箱", "monthly_kwh": 93.6, "share_of_total_percent": 24.53},
    {"appliance": "桌上型電腦", "monthly_kwh": 45.0, "share_of_total_percent": 11.79}
  ],
  "recommendation_count": 7,
  "total_potential_monthly_saving_kwh": 116.1,
  "total_potential_monthly_saving_twd": 275.95,
  "total_potential_annual_saving_twd": 3311.4,
  "potential_saving_percent_of_usage": 30.42,
  "comprehensive_monthly_saving_kwh": 224.55,
  "comprehensive_monthly_saving_twd": 533.73,
  "aggregation_note_zh": "total_potential_* 只計算每台家電最有效的一項建議（避免同一台家電重複計算）；comprehensive_* 則是所有建議都落實時的合計，數字會較大。",
  "recommendations": [
    {
      "id": "ac_hours_high",
      "appliance": "冷氣機",
      "title_zh": "冷氣每日使用超過 8 小時",
      "reason_zh": "冷氣是租屋處最常見的高耗電來源，每多吹 1 小時，月用電量就會線性增加。",
      "suggestion_zh": "設定 26-28 度並搭配電風扇或循環扇，睡前使用定時功能，可減少 1-2 小時運轉。",
      "estimated_monthly_saving_kwh": 48.6,
      "estimated_monthly_saving_twd": 115.52,
      "estimated_annual_saving_twd": 1386.24,
      "assumption_zh": "假設每日可減少 1.8 小時使用（原 9.0 小時），每月 30 天。",
      "priority": 1, "severity": "high", "confidence": "medium", "rule_id": "ac_hours_high"
    },
    {
      "id": "swap_air_conditioner",
      "appliance": "冷氣機",
      "title_zh": "考慮更換為一級能效變頻冷氣",
      "is_purchase_advice": true,
      "alternative_label_zh": "一級能效變頻冷氣",
      "alternative_power_watts": 700,
      "estimated_monthly_saving_kwh": 54.0,
      "estimated_monthly_saving_twd": 128.35,
      "assumption_zh": "假設使用時數（每日 9 小時、每月 30 天）與目前完全相同，僅更換機種功率。"
    }
  ],
  "per_appliance": [
    {"appliance": "冷氣機", "monthly_kwh": 243.0, "matched_catalog_key": "air_conditioner", "recommendation_count": 3},
    {"appliance": "冰箱", "monthly_kwh": 93.6, "matched_catalog_key": "refrigerator", "recommendation_count": 3},
    {"appliance": "桌上型電腦", "monthly_kwh": 45.0, "matched_catalog_key": "desktop_computer", "recommendation_count": 1}
  ],
  "disclaimer_zh": "以上節電量與金額皆為規則式估算，實際節省效果會因機種、環境與使用習慣而不同，不保證可達成相同金額。"
}
```

**為什麼有兩個合計欄位？**
同一台冷氣可能同時觸發「少吹一點」和「換變頻機」，兩者不能相加。
`total_potential_*` 只取每台家電**最有效的一項**建議（給前端顯示「每月約可省」）；
`comprehensive_*` 是所有建議都落實的合計。前端建議用前者當主數字。

**建議是怎麼產生的（規則式，沒有訓練 AI 模型）**

1. 用 `app/data/appliances.json` 的典型功率與使用時數比對家電
   （可用 `appliance_id`／`category`／中英文名稱，名稱比對會忽略大小寫與空白）。
2. 判斷用電量占比：≥ 20% 為高耗電，≥ 10% 為中等。
3. 套用該家電在資料檔中宣告的規則，例如
   `hours_per_day_gte`、`power_ratio_gte`、`is_high_power`、`is_always_on`。
4. 依規則的 `reduction_ratio` 或 `reduction_cap_hours` 估算節省度數，再乘上
   **該用電量下的平均每度成本**（會反映累進級距，所以省下高級距的電更值錢）。
5. 排序：`severity` → `priority` → 節省度數。

`advice_only: true` 的建議（例如吹風機）只談用電安全與使用習慣，**不宣稱節省度數**。

**同名電器不會互相吃掉建議**：`recommendations` 是「每台家電 × 每條規則」一筆，
所以兩台冷氣都會各自拿到 `ac_hours_high`。`id` 是穩定的規則代碼（前端可用來選圖示），
`recommendation_key` 是「規則::家電身分」的唯一鍵（請用它當列表 key）。
`appliance_key` 在家電有 `appliance_id` 時就是該 id，否則用名稱加位置。

**名稱比對**：中英文都能比對，且名稱只要「包含」參考資料庫的別名就會命中
（`冰箱`、`電冰箱`、`小冰箱` 都會對到冰箱），最長別名優先。
若完全對不到，才會退回只給通用建議。

### 3.5 `POST /simulate`

```bash
curl -X POST http://127.0.0.1:8000/simulate \
  -H "Content-Type: application/json" \
  -d '{
        "appliances": [
          {"appliance_id":"a1","name":"冷氣機","power_watts":900,"hours_per_day":9,"days_per_month":30,"voltage":220},
          {"appliance_id":"a2","name":"冰箱","power_watts":130,"hours_per_day":24,"days_per_month":30,"voltage":110},
          {"appliance_id":"a3","name":"桌上型電腦","power_watts":250,"hours_per_day":6,"days_per_month":30,"voltage":110}
        ],
        "changes": [
          {"appliance_id":"a1","field":"hours_per_day","value":6,"label_zh":"冷氣每天少吹 3 小時"}
        ],
        "month": 8,
        "load_limit_amps": 15
      }'
```

回應（節錄，完整內容見 `backend/docs/examples/simulate_reduce_ac_hours.json`）：

```json
{
  "plan_id": "tw_residential_tiered",
  "billing_period": "monthly",
  "season_label_zh": "夏月（6月1日至9月30日）",
  "baseline": {
    "total_monthly_kwh": 381.6, "estimated_bill_twd": 907.02,
    "appliances": [{"name": "冷氣機", "power_watts": 900.0, "monthly_kwh": 243.0}]
  },
  "modified": {
    "total_monthly_kwh": 300.6, "estimated_bill_twd": 644.07,
    "appliances": [{"name": "冷氣機", "power_watts": 900.0, "monthly_kwh": 162.0,
                    "replacement_label": null}]
  },
  "delta": {
    "saved_kwh": 81.0, "saved_amount_twd": 262.95, "saved_amount_rounded_twd": 263,
    "saved_percent_of_kwh": 21.23, "saved_percent_of_amount": 28.99,
    "annual_saved_amount_twd": 3155.4, "is_saving": true
  },
  "comparison_table": [
    {"appliance": "冷氣機", "baseline_kwh": 243.0, "modified_kwh": 162.0,
     "saved_kwh": 81.0, "percent_change": -33.33, "status": "changed",
     "replaced_by": null, "replacement_label": null},
    {"appliance": "冰箱", "baseline_kwh": 93.6, "modified_kwh": 93.6,
     "saved_kwh": 0.0, "percent_change": 0.0, "status": "unchanged",
     "replaced_by": null, "replacement_label": null},
    {"appliance": "桌上型電腦", "baseline_kwh": 45.0, "modified_kwh": 45.0,
     "saved_kwh": 0.0, "percent_change": 0.0, "status": "unchanged",
     "replaced_by": null, "replacement_label": null}
  ],
  "applied_changes": [
    {"appliance": "冷氣機", "new_name": null, "field": "hours_per_day",
     "before": 9, "after": 6, "label_zh": "冷氣每天少吹 3 小時"}
  ],
  "load": {"limit_amps": 15.0, "baseline_current_amps": 7.5455, "modified_current_amps": 7.5455,
           "current_change_amps": 0.0,
           "baseline_verdict": "safe", "modified_verdict": "safe"},
  "notes": [
    "baseline 資料為原始家電資料的複本，模擬過程不會修改使用者已儲存的資料。",
    "所有金額與度數皆為估算值，實際帳單可能因級距、季節與房東收費方式而不同。"
  ]
}
```

`backend/docs/examples/simulate_swap_efficient_ac.json` 是更換機種的版本
（功率 900W → 700W、時數 9 → 7 小時）：381.6 → 285.6 度，每月省 299.7 元，
年度省 3,596.4 元。

**`comparison_table` 的識別方式**：每一列固定用**原本的家電名稱**當 `appliance`，
所以替換機種後不會多出一列。若新機種改了名字，會另外用 `replaced_by` 表示新名稱，
`replacement_label` 則是前端顯示用的機種標籤。`applied_changes[].new_name`
同樣只在改名時才有值。`status` 會是 `changed`／`unchanged`／`added`。

**帳單期間**：`/simulate` 也接受 `billing_period` 與 `billing_months`，並且會回報
`billing_months`。前後兩邊用同一個期間計價，數字才能和 `/calculate/cost` 對得上。

**為什麼省下的金額比例（28.99%）高於度數比例（21.23%）？**
因為電費是累進級距，省下的電會從最高級距開始少付，所以金額的節省幅度通常大於度數。

**`changes` 支援的 `field`**

| `field` | 需要的欄位 | 說明 |
| --- | --- | --- |
| `hours_per_day` | `value` | 修改每日時數（0–24） |
| `power_watts` | `value` | 修改功率（模擬不同瓦數） |
| `days_per_month` | `value`（整數） | 修改使用天數 |
| `quantity` | `value`（整數） | 修改數量 |
| `replace_with` | `replacement` 物件 | 換成別台電器（可只給 `power_watts`／`label`） |

指定對象用 `appliance_id` 或 `name`。**原始 `appliances` 不會被修改**：
後端會 `deepcopy` 一份再套用變更，`baseline` 永遠是原始資料。
`baseline_override_kwh` 可以帶入實際抄表度數，讓比較基準更貼近真實帳單（Member B 整合後很有用）。

### 3.6 輔助端點

- `GET /tariffs` — 方案清單（`id`／`type`／`is_estimate`／`supports_billing_months`）與資料檔說明，
  適合做電價方案的選單與說明頁。
- `GET /appliances` — 12 種家電的典型功率區間、電壓、典型使用時數、效率建議與
  `efficient_alternative`。**前端可以用它當輸入表單的預設值與提示**，
  Member B 也可以直接把它當資料表內容。
- `GET /health` — 回報版本、電價資料版本、家電目錄筆數。

---

## 4. 計算與電價規則

### 4.1 台電住宅累進電價（`tw_residential_tiered`）

資料來源：台電住宅用電電價表（級距與費率自 2024-04-01 起適用，2025 年電價審議會決議住宅凍漲）。

| 每月用電度數分段 | 夏月（6/1–9/30） | 非夏月 |
| --- | --- | --- |
| 120 度以下 | 1.68 元/度 | 1.68 元/度 |
| 121–330 度 | 2.45 | 2.16 |
| 331–500 度 | 3.70 | 3.03 |
| 501–700 度 | 5.04 | 4.14 |
| 701–1000 度 | 6.24 | 5.07 |
| 1001 度以上 | 8.46 | 6.63 |

**累進計算範例（同時也是測試案例）**：8 月用電 800 度

```
1.68×120 + 2.45×210 + 3.70×170 + 5.04×200 + 6.24×100 = 2,977.10 元
```

（台電文宣將此例印為 2,977 元，差異來自最後四捨五入。測試用 `abs=0.5` 容許這一步。）

### 4.2 其他方案

| `plan_id` | 類型 | 說明 |
| --- | --- | --- |
| `tw_residential_tou` | 時間電價（二段式） | 尖峰／離峰估算，需 `peak_share`；標示為估算 |
| `flat_rate_resell_reference` | 單一費率 | 租屋常見房東轉售價 5.5 元/度（常見區間 5.0–6.5），標示為估算 |

### 4.3 重要假設與限制（簡報時要說明）

- 用電量以「功率 × 時數 × 天數」估算，**未考慮變頻、待機、效率曲線與實際負載率**。
  冰箱、冷氣等壓縮機電器的實際耗電通常低於額定功率全時運轉的估算值。
- 電費**不含**公共電費、基本費、分攤與節電折扣。
- 租屋若由房東轉售，實際單價常高於台電級距，本 API 用
  `flat_rate_resell_reference` 呈現這個情境。
- 級距以「每期」為單位；`bi_monthly` 會放大級距上限。
- 負載估算只算運轉電流，且**不保證電路安全**。

---

## 5. 測試（以下指令都在 `backend/` 內執行）

```bash
python -m pytest -q
# 525 passed
```

| 檔案 | 測試數 | 重點 |
| --- | --- | --- |
| `test_consumption.py` | 53 | 公式、單一／多家電總計、數量、邊界值、各類不合理輸入 |
| `test_electricity_bill.py` | 92 | 台電範例 800 度、級距邊界、夏月／非夏月、兩個月一期、三種方案、年估算、電價不得寫死、0 度級距、帳單期間限制 |
| `test_load_estimator.py` | 52 | 歐姆定律、功率因數、單相／三相、安全裕度、超載組合、免責聲明 |
| `test_recommendations.py` | 71 | 高耗電辨識、每條規則、中英文名稱比對、同名電器、去重、排序、統計一致性 |
| `test_simulation.py` | 59 | 前後比較、四種變更類型、**不改動原始資料**、同名家電、改名替換、負載比較 |
| `test_data_check.py` | 29 | 電價／家電資料檔的完整性檢查（壞檔必須在啟動時就被拒絕） |
| `test_api.py` | 111 | 五個端點、驗證錯誤形狀、錯誤碼、端點間一致性、啟動驗證、`power_factor`、迴歸案例 |

幾個刻意設計的測試：

- **電價不在程式碼裡**：`test_prices_live_in_json_not_in_code` 走訪 `app/` 下所有 `.py`，
  確認 `1.68`、`8.46` 等費率沒有以數值常值寫死在程式中（只有說明文字可以提到）。
  這個測試已用「故意寫死一個費率」驗證過會失敗。
- **不會改到使用者資料**：`test_simulation.py::TestNonMutation` 對原始清單做
  `deepcopy` 比對，並驗證 `replace_with` 情境下原資料不變。
- **端點間一致**：`test_api.py::TestCrossEndpointConsistency` 確認
  `/calculate/consumption` 的總度數與 `/calculate/cost`、`/recommendations`、`/simulate` 的基準一致。
- **不誇大安全**：確認免責聲明一定存在，且措辭不出現「保證安全」。

### 5.1 程式碼審查紀錄

`backend/docs/code-review-audit.md` 是一次對抗式自我審查的完整紀錄：在 371 個測試全過的版本上，
仍找出 5 個真實缺陷（三相電流被忽略、`/simulate` 忽略 `billing_months`、
改名替換把一列拆成兩列、同名家電的建議被去重吃掉、含別名的中文名稱比對不到）
與 2 個文件過時問題。這些全部已修正，且每個都補上迴歸測試；該文件保留
「問題 → 修正 → 對應測試」的對照表，可作為測試充分性的佐證。

### 5.2 效能與程式碼品質優化紀錄

第二輪做了完整的程式碼瀏覽與優化。**先用 `tools/benchmark.py` 量測再改**，避免憑感覺優化。

**實測改善（8 台家電，中位數）**

| 項目 | 優化前 | 優化後 | 變化 |
| --- | --- | --- | --- |
| `generate_recommendations` | 0.477 ms | 0.132 ms | **−72%** |
| `POST /recommendations` | 1.217 ms | 0.876 ms | −28% |
| `POST /recommendations`（120 台家電） | 6.565 ms | 2.784 ms | **−58%** |

其餘端點約 0.5–1.1 ms，120 台家電仍在 3 ms 內 —— 所以這輪的重點**不是**榨效能，
而是修掉正確性問題與重複邏輯：

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

**效能以外的可維護性改善**

- `resolve_season`／`season_label` 可接受 `tariffs` 參數，不再重複解析同一個檔案。
- `BillBreakdown.as_dict()` 只查一次季節標籤（原本查兩次）。
- 新增 `tools/lint_unused.py`，目前 `app/` 與 `tools/` **零未使用 import**。
- 新增 `tests/test_data_check.py`（29 個資料完整性測試）。

**怎麼重現這些數字**

```bash
python tools/benchmark.py 40      # 各函式與端點耗時
python tools/lint_unused.py       # 未使用 import
python tools/probe_errors.py      # 51 個畸形請求，確認無 5xx
```

---

## 6. 給 Member A（前端）的整合建議

- 先打 `GET /appliances` 取得表單預設值與提示文字，再讓使用者修改。
- 送出的家電資料保留 `appliance_id`（Member B 的主鍵），`/simulate` 會用到。
- 錯誤處理：讀 `code` 判斷類型、`field` 指出哪個欄位、
  `details[]` 可一次列出所有問題。
- 電費畫面直接用 `lines[]` 畫級距堆疊圖，`effective_rate_per_kwh` 顯示「平均每度」。
- 建議畫面用 `reason_zh` + `suggestion_zh` 當卡片內容，
  `total_potential_monthly_saving_twd` 當主數字，
  `comprehensive_*` 放在次要位置（避免看起來像重複計算）。
- 負載畫面務必一起顯示 `disclaimer_zh` 與 `warnings[]`。
- `docs/openapi.json` 可以直接餵給型別產生器或 Postman。

## 7. 給 Member B（資料庫）的整合建議

- `app/data/tariffs.json` 與 `app/data/appliances.json` 就是建議的資料表內容，
  需要新增方案時**只改 JSON**（`load_tariffs()` 有快取，重啟即生效）。
- 目前所有端點都是無狀態的：前端送完整資料，後端只做計算。
  接上資料庫後，可以在 `app/services/` 加一層，把 `appliance_id` 換成資料庫查詢結果，
  計算模組不用改。
- 資料格式對應：`appliances` 表的欄位可直接對應 `ApplianceIn`
  （`appliance_id`、`name`、`category`、`power_watts`、`hours_per_day`、
  `days_per_month`、`quantity`、`voltage`）。
- 模擬結果要在資料庫留下紀錄時，建議存 `baseline`／`modified`／`delta` 三塊，
  並記下 `plan_id`、`month` 與當時的電價資料版本。

---

## 8. 安裝疑難排解

一般環境請直接用：

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

以下兩種情況需要替代方案。

### 8.1 `pip install` 在建置 `pydantic-core` 時失敗

見 2.1 的說明。`requirements.txt` 已經選用同時支援 Python 3.12／3.14 的版本
（`pydantic==2.14.1` / `pydantic-core==2.50.1`），**不需要 Rust 或 C 編譯器**。
如果仍然失敗，先確認你用的不是舊的 `requirements.txt`。

要檢查任何套件在指定 Python 上是否有預編譯 wheel：

```bash
python tools/resolve_pins.py --tag cp312 --tag cp314
```

### 8.2 `python -m venv` 失敗（`ensurepip` 不可用）

少數 Python 版本是精簡版，沒有 `ensurepip`，`venv` 也就沒有 `pip`。
`start.py --setup` 會偵測並提示。此時用 `tools/` 裡的腳本，**完全不需要 pip**：

```bash
# 1) 走訪依賴圖，抓出這個解譯器可用的完整 wheel 集合（略過 extras）
python tools/resolve_deps.py --dest .wheels --tag cp314 ^
       fastapi==0.143.0 uvicorn==0.54.0 pydantic==2.14.1 ^
       pydantic-core==2.50.1 pytest==9.1.1 httpx==0.28.1

# 2) 用標準庫解壓 wheel 到指定目錄（wheel 就是 ZIP，不需要 pip）
python tools/install_wheels.py --src .wheels --dest .pylibs

# 3) 啟動（start.py / run_app.bat 會自動把 .pylibs 加進 PYTHONPATH）
run_app.bat
```

若只想用「最新可用」版本而不指定版本，可改用簡單的抓取腳本：

```bash
python tools/fetch_wheels.py --dest .wheels --index https://pypi.org/simple ^
       fastapi uvicorn pydantic pytest httpx
```

> **重點：`.pylibs` 綁定 Python 版本。** 裡面的 `.pyd` 是為特定版本編譯的，
> 拿 3.12 的 `.pylibs` 配 3.14 的直譯器會出現
> `ImportError: cannot import name 'ArgsKwargs' from 'pydantic_core._pydantic_core'`。
> 每個 Python 版本請各自準備一份 `.pylibs`，或直接用 venv。
> `run_app.bat` 會自動配對：有 `.venv` 就只跑 venv，不會再疊上 `.pylibs`。

### 8.3 驗證安裝是否正確

```bash
python -m pytest                     # 應該 525 passed
run_app.bat                          # 然後開 http://127.0.0.1:8000/docs
python tools/smoke_api.py http://127.0.0.1:8000
```

本專案已實測通過的組合：

| Python | 套件來源 | 結果 |
| --- | --- | --- |
| 3.14.7（系統 Python，無 ensurepip） | `.venv314` + 解壓 wheel | 525 passed，`/docs` 正常 |
| 3.12.14（專案內建 runtime） | `.pylibs` | 525 passed，`/docs` 正常 |
