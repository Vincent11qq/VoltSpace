# 使用 Supabase（已實作，預設關閉）

VoltSpace 預設把家電存在**本地 SQLite**（`backend/.data/voltspace.db`），
因為這樣「下載就能跑」，不需要註冊任何雲端服務。

要把資料改放 Supabase（跨裝置、多人共用）**不需要改程式碼**——
設定環境變數即可，adapter 已經寫好（`app/store_supabase.py`）。

> 只想先試試看？直接啟動就是 SQLite 模式，功能完全一樣。
> 想確認目前的儲存模式，看 <http://127.0.0.1:8000/health> 的 `storage` 欄位。

---

## 1. 建立 schema

在 Supabase 專案的 **SQL Editor** 貼上並執行 [`../db/schema.sql`](../db/schema.sql)。

這份檔案是可重複執行的，會建立：

| 資料表 | 用途 |
| --- | --- |
| `profiles` | 使用者顯示名稱（註冊時自動建立） |
| `appliances` | 家電清單，**欄位與計算 API 完全一致** |
| `tariff_plans` | 電價方案（已預先寫入三個方案，內容來自 `app/data/tariffs.json`） |
| `households` | 家電集合，帶 `access_token` 讓匿名裝置也能擁有資料 |

### 與原始 SQL 的差異（以及為什麼）

原本的 `appliances.sql` / `security.sql` 有三個問題，這份 schema 已修正：

1. **欄位名稱／單位不同** — 舊版是 `Power` / `Minutes` / `Appliance`；
   計算核心用 `power_watts` / `hours_per_day` / `name`。
   現在資料庫欄位就是 API 欄位，不需要任何轉換。
2. **沒有電價表** — 電費計算需要級距資料，現在有 `tariff_plans`。
3. **RLS 政策只給 `authenticated`** — 但前端沒有登入流程，匿名請求的
   `auth.uid()` 是 `NULL`，因此新增／讀取都會被拒絕。
   現在改用 `households.access_token`，讓匿名裝置也能安全地讀寫自己的資料。

---

## 2. 環境變數

Supabase 的連線資訊**不要寫進程式碼**（原本的 `manager.py` 與 `Supabase.py`
各寫了一次金鑰）。

```bash
VOLTSPACE_SUPABASE_URL=https://YOUR-PROJECT.supabase.co
VOLTSPACE_SUPABASE_KEY=<publishable / anon key>
# 只有需要繞過 RLS 的伺服器端操作才用 service key，且絕不下放到前端
VOLTSPACE_SUPABASE_SERVICE_KEY=<service role key>
```

`publishable`（anon）key 本來就會出現在前端，所以它不是秘密；但仍應由環境變數注入，
方便換專案與輪替。

---

## 3. 資料欄位對照

| API / SQLite | Supabase `appliances` | 單位 |
| --- | --- | --- |
| `name` | `name` | text |
| `category` | `category` | text |
| `power_watts` | `power_watts` | W |
| `hours_per_day` | `hours_per_day` | **小時**（不是分鐘） |
| `days_per_month` | `days_per_month` | 0–31 |
| `quantity` | `quantity` | ≥ 1 |
| `voltage` | `voltage` | V |
| `power_factor` | `power_factor` | 0.1–1.0 |

`CHECK` 約束與 `ApplianceIn` 的驗證範圍一致，所以資料庫不會存進 API 會拒絕的值。

---

## 4. 把後端接到 Supabase

**這已經實作了**，不需要改程式碼，只要設環境變數。
`app/store_supabase.py` 是 Supabase 版本，`app/storage.py` 負責挑選用哪一個。

### 4.1 三個步驟

```powershell
# 1) 在 Supabase 的 SQL Editor 執行 backend/db/schema.sql（建立資料表）

# 2) 設定環境變數（PowerShell）
$env:VOLTSPACE_SUPABASE_URL = "https://YOUR-PROJECT.supabase.co"
$env:VOLTSPACE_SUPABASE_KEY = "<service_role key>"

# 3) 先檢查，再啟動
cd backend
python tools/supabase_doctor.py --write-test
run_app.bat
```

啟動後打開 <http://127.0.0.1:8000/health>，`"storage"` 應該變成 `"supabase"`。

### 4.2 為什麼要用 service_role key

`db/schema.sql` 的 RLS 只授權 `authenticated` 使用者存取 `appliances`，
而這個 App **沒有登入流程**。匿名請求的 `auth.uid()` 是 `NULL`，
所以用 anon key 讀寫會被 RLS 拒絕。

伺服器端用 `service_role` key 是 designed 的作法（它繞過 RLS），
**前提是它只存在於後端**。若你之後加入了登入流程，就可以改回 anon key。

用錯 key 時，doctor 會直接告訴你：

```
[FAIL] cannot read the appliances table  (Supabase refused the request (42501: ...).
       The table's row level security is blocking this key. Use the service_role key ...)
```

### 4.3 環境變數一覽

| 變數 | 必填 | 說明 |
| --- | --- | --- |
| `VOLTSPACE_SUPABASE_URL` | 是 | `https://<project>.supabase.co` |
| `VOLTSPACE_SUPABASE_KEY` | 是 | service_role key（見 4.2） |
| `VOLTSPACE_SUPABASE_SERVICE_KEY` | 否 | 設定時優先於上面那個 |
| `VOLTSPACE_STORAGE` | 否 | `auto`（預設）／`supabase`／`local` |
| `VOLTSPACE_SUPABASE_TABLE` | 否 | 預設 `appliances` |
| `VOLTSPACE_HOUSEHOLD_ID` | 否 | 指定 household uuid，只讀寫該戶的資料 |

### 4.4 三種模式的行為

| `VOLTSPACE_STORAGE` | 沒設定 Supabase 時 | Supabase 壞掉時 |
| --- | --- | --- |
| `auto`（預設） | 用 SQLite | **自動退回 SQLite** 並印出原因 |
| `supabase` | 啟動失敗並說明缺哪個變數 | 啟動失敗（不會假裝成功） |
| `local` | 用 SQLite | 用 SQLite（完全忽略 Supabase） |

`auto` 是為了讓 `run_app.bat` 在沒有雲端設定的機器上仍然可用；
示範時如果你**不想**它偷偷用 SQLite，就設 `VOLTSPACE_STORAGE=supabase`。

### 4.5 兩種欄位格式都支援

Adapter 會在第一次連線時偵測欄位：

* **current**（`db/schema.sql`）：`name` / `power_watts` / `hours_per_day` / …
* **legacy**（Member B 原本的 SQL）：`appliance` / `power` / `minutes` / …

遇到 legacy 格式會自動轉換（`minutes ÷ 60` → `hours_per_day`），
但 legacy 沒有 `days_per_month`、`voltage`、`power_factor` 欄位，
這三個值會用預設值且**不會被儲存**。想完整支援就重跑 `db/schema.sql`。

---

## 5. 注意事項

- **不要把 service role key 放進前端**。它會繞過所有 RLS。
- **專案被刪除或閒置太久，DNS 會消失**，連線會失敗。判斷方法：
  `python tools/supabase_doctor.py` 的 DNS 檢查會顯示
  `DNS does not resolve`。這時只能建新專案。
- Supabase 的免費方案會休眠，冷啟動可能要幾秒；本地 SQLite 沒有這個問題。
- **`replace_appliances`（前端「儲存全部」）不是交易性的**：它先 DELETE 再 INSERT，
  如果 INSERT 失敗，該戶的家電會是空的。SQLite 版本有交易保護，Supabase 版本沒有。
- 電價資料有兩份（`app/data/tariffs.json` 與 `tariff_plans` 表）。
  **目前計算一律以 JSON 為準**（後端要能離線執行）；`schema.sql` 的 seed
  已同步成 2025-10-01 的費率，若你改了資料庫的費率，記得也改 JSON。
