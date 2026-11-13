# Member B 的最新版本（2026-11-13 交付）

這個資料夾保存 Member B **最新一次**交來的檔案，跟上一層 `Supabase/Supabase/` 的
**最初版本**區分開來。原封不動保存，方便對照與報告分工。

## 檔案

| 檔案 | 說明 | 狀態 |
| --- | --- | --- |
| `appliances.sql` | 建 `appliances` 表 | ✅ **最重要，修對了** |
| `profile.sql` | 建 `profiles` + 註冊自動建檔 trigger | ✅ 可用 |
| `security.sql` | RLS 政策 | ✅ 可用（見下方注意） |
| `connect.sql` | GRANT + 重載 PostgREST schema cache | ✅ 可用 |
| `supabase.py` | 連線檢查（`SupabaseConnection`）| ⚠️ 有錯，見下 |
| `supabase_fixed.py` | 我修好的 `supabase.py` | ✅ 可執行 |

## 這批的價值：`appliances.sql` 終於對了

最初的版本是 `Appliance` / `Power` / `Minutes`（欄位名與單位都跟 API 不符）。
這次改成：

```sql
name, category, power_watts, hours_per_day,
days_per_month, quantity, voltage, power_factor, household_id
```

**與 `backend/app/schemas.py` 的 `ApplianceIn` 完全一致**，
所以 `backend/app/store_supabase.py` 偵測時會判定為 `current` 版面，直接可用。

這是目前 Supabase 專案裡**實際生效**的 schema（已驗證：線上表的欄位與此檔一致）。

## `supabase.py` 的兩個錯誤（已修於 `supabase_fixed.py`）

| 行 | 原本 | 應為 |
| --- | --- | --- |
| 10 | `def _init_(self):` | `def __init__(self):` |
| 53 | `if _name_ == "_main_":` | `if __name__ == "__main__":` |

單底線 → 建構子從未被呼叫，所有屬性都不存在。實測：

```
has .url     : False
test_connection() raised AttributeError: 'SupabaseConnection' object has no attribute 'url'
```

另外原本硬性依賴 `python-dotenv`（本專案未安裝），`supabase_fixed.py` 改成選用。

## 需要注意的設計問題

`security.sql` 的 `appliances` 政策是：

```sql
USING (household_id = auth.uid());
```

把「家戶 id」與「使用者 id」當成同一個東西。而且這批**沒有 `households` 表**，
所以 `household_id` 是一個沒有外鍵的孤立欄位。

實務影響：

* 後端用 `service_role` key → **繞過 RLS，不受影響**（目前就是這樣跑的）
* 若之後要用 anon key + 登入 → `VOLTSPACE_HOUSEHOLD_ID` 必須等於該使用者的 uid

## 跟 `backend/db/schema.sql` 的關係

**兩者目前不一致**，不要混用：

| 項目 | `backend/db/schema.sql`（Member C 版）| 本資料夾（Member B 版，= 線上實際）|
| --- | --- | --- |
| `appliances.user_id` | 有（`not null default auth.uid()`）| **沒有** |
| `appliances.household_id` | 用 `alter table` 加上 | 建表時就有 |
| `households` 表 | 有 | **沒有** |
| `tariff_plans` 表 | 有（含電價 seed）| **沒有** |
| RLS 依據 | `user_id = auth.uid()` | `household_id = auth.uid()` |

⚠️ **在目前這個線上專案上直接執行 `backend/db/schema.sql` 會失敗**，
因為它會嘗試在 `appliances` 上建立 `user_id` 索引與政策，但該欄位不存在：

```
create index if not exists appliances_user_id_idx on public.appliances (user_id);
ERROR: column "user_id" does not exist
```

目前線上專案是由本資料夾的 SQL 建立的。後端只需要 `appliances` 表存在且欄位正確
（已符合），所以**現在可以正常運作**；要整併兩份 schema 需要另外決定。
