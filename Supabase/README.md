# Member B 的 Supabase 成果

這個資料夾保存 Member B 交來的 SQL（最新一批），以及我修正過的 `supabase.py`。

> 他**最初**交的四個 SQL（`Appliance` / `Power` / `Minutes` 的舊欄位）與三支 Python 模組
> （金鑰寫死、`power` / `minutes` 單位不符）都已被取代，並已從 repo 移除。
> 需要對照時可用 `git log --diff-filter=A -- Supabase/` 找回當初的 commit。
> 差異整理在下面。

| 檔案 | 說明 |
| --- | --- |
| `appliances.sql` | 建 `appliances` 表 —— **線上專案實際使用的 schema** |
| `profile.sql` | `profiles` 表 + 註冊時自動建檔的 trigger |
| `security.sql` | RLS 政策 |
| `connect.sql` | GRANT + 重載 PostgREST schema cache |
| `supabase.py` | 他的連線檢查（原檔，含 `_init_` 的錯，保留作對照）|
| `supabase_fixed.py` | 我修好的可執行版本 |

後端 `app/store_supabase.py` 讀寫的就是這張表，欄位已用
`tools/check_schema_match.py` 驗證與 `backend/db/schema.sql` 一致。

## 這批修好了什麼

最初版本 → 現在：

| 項目 | 最初 | 現在 |
| --- | --- | --- |
| 欄位名 | `Appliance` / `Power` / `Minutes` | `name` / `power_watts` / `hours_per_day`（與 `ApplianceIn` 一致）|
| 單位 | 分鐘 | 小時 |
| 缺欄位 | 沒有 `days_per_month`、`voltage`、`power_factor` | 都有 |
| 電價表 | 沒有 | 選用的 `backend/db/optional-tariff-plans.sql` |
| 金鑰位置 | 寫死在程式碼裡 | 環境變數（`.env` 或平台的設定）|

## `supabase.py` 的錯誤（已修於 `supabase_fixed.py`）

| 行 | 原本 | 應為 |
| --- | --- | --- |
| 10 | `def _init_(self):` | `def __init__(self):` |
| 53 | `if _name_ == "_main_":` | `if __name__ == "__main__":` |

單底線 → 建構子從未被呼叫，所有屬性都不存在（實測 `AttributeError: no attribute 'url'`）。
另外原本硬性依賴 `python-dotenv`（本專案未安裝），修正版改成選用。

## 想真的用 Supabase

見 [`../backend/docs/supabase.md`](../backend/docs/supabase.md)。
跑 `../backend/db/schema.sql` 即可（不是用這裡的檔案）。
