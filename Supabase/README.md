# Member B 的原始 Supabase 成果（參考用）

這些檔案是 Member B 交來的原始版本，**已被後端的實作取代**，保留作為紀錄。

| 原始檔案 | 現況 | 取代它的東西 |
| --- | --- | --- |
| `Supabase/appliances.sql` | 欄位名稱與單位與計算 API 不一致 | `backend/db/schema.sql` |
| `Supabase/profiles.sql` | 可用，但沒有自動建立 profile | `backend/db/schema.sql`（加上 trigger） |
| `Supabase/security.sql` | RLS 只給 `authenticated`，匿名使用者讀寫全失敗 | `backend/db/schema.sql`（改用 `households.access_token`） |
| `Supabase/connect.sql` | 只是重設 `user_id` 預設值 | 已併入 `backend/db/schema.sql` |
| `Python/Supabase.py` | import 時就查資料庫並 print；金鑰寫死 | 已清理：金鑰改環境變數、副作用移除；功能併入 `backend/app/store.py` |
| `Python/manager.py` | 金鑰寫死；`power`/`minutes` 與 API 不符 | 已清理：金鑰改環境變數、加上單位轉換、改呼叫共用計算 |
| `Python/validation.py` | 規則比計算核心寬鬆 | 已由 `backend/app/calculators/consumption.py` 統一 |

## 三個實際的問題（以及為什麼要改）

1. **欄位與單位不一致** —— 舊 schema 是 `Appliance` / `Power` / `Minutes`；
   計算 API 是 `name` / `power_watts` / `hours_per_day`。
   兩邊都存同一件事卻要轉換，容易出錯，所以 `backend/db/schema.sql` 直接採用 API 的欄位名。

2. **沒有電價表** —— 電費計算需要級距資料。新的 schema 有 `tariff_plans`，
   內容與 `backend/app/data/tariffs.json` 一致。

3. **RLS 讓匿名使用者無法使用** —— 政策是 `to authenticated` 搭配 `auth.uid() = user_id`，
   但 App 沒有登入流程，所以 `auth.uid()` 是 NULL，新增與讀取都會被拒絕。
   新 schema 用 `households.access_token` 讓匿名裝置也能安全擁有自己的資料。

## 想真的用 Supabase

見 [`../backend/docs/supabase.md`](../backend/docs/supabase.md)。
執行 `../backend/db/schema.sql` 即可，不需要用這裡的舊檔。
