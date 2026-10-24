# 使用 Member B 的 Supabase（選用）

VoltSpace 預設把家電存在**本地 SQLite**（`backend/.data/voltspace.db`），
因為這樣「下載就能跑」，不需要註冊任何雲端服務。

若要把資料放到 Supabase（例如多人共用、跨裝置），照以下步驟。

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

`app/store.py` 定義了後端需要的介面（`list_appliances`、`add_appliance`、
`update_appliance`、`delete_appliance`、`replace_appliances`）。
要換成 Supabase，新增一個同名方法的類別即可，計算模組完全不用改：

```python
# app/store_supabase.py（示意）
import os
from supabase import create_client

class SupabaseStore:
    def __init__(self, household_token: str):
        self.client = create_client(
            os.environ["VOLTSPACE_SUPABASE_URL"],
            os.environ["VOLTSPACE_SUPABASE_KEY"],
        )
        self.token = household_token

    def list_appliances(self):
        response = (
            self.client.table("appliances")
            .select("*")
            .eq("household_id", self.token)
            .order("id")
            .execute()
        )
        return response.data
```

然後在 `app/main.py` 的 lifespan 裡決定要用哪一個：

```python
store = SupabaseStore(token) if os.environ.get("VOLTSPACE_SUPABASE_URL") else ApplianceStore()
```

> 因為 `app/main.py` 只依賴那幾個方法，這是**唯一**需要改的地方；
> `_saved_list`、`household_dashboard` 等端點都不用動。

---

## 5. 注意事項

- **不要把 service role key 放進前端**。它會繞過所有 RLS。
- 匿名裝置的 `households.access_token` 等於密碼：只放在裝置端，用 header 傳給後端，
  不要出現在 URL 或日誌。
- Supabase 的免費方案會休眠，冷啟動可能要幾秒；本地 SQLite 沒有這個問題，
  所以示範時建議用預設設定。
- 電價資料有兩份（`app/data/tariffs.json` 與 `tariff_plans` 表）。
  **目前計算一律以 JSON 為準**（後端要能離線執行）；若你在資料庫改了費率，
  記得同步更新 JSON，或把 `calculate_bill` 改成讀資料庫。
