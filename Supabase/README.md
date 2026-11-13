# Member B 的 Supabase 成果

這個資料夾保存 Member B 交來的 SQL。分成兩批：

| 資料夾 | 內容 | 說明 |
| --- | --- | --- |
| `Supabase/` | **最初版本** | 欄位名與單位跟 API 不符，已被取代 |
| [`member-b-latest/`](member-b-latest/README.md) | **2026-11-13 最新版本** | `appliances.sql` 已修正，**是目前線上專案實際使用的 schema** |

> 目前 Supabase 線上專案是用 `member-b-latest/` 的 SQL 建立的。
> 後端 `app/store_supabase.py` 讀寫的就是那張表（欄位已驗證一致）。

## 最初版本（`Supabase/`，已被取代）

| 原始檔案 | 現況 |
| --- | --- |
| `Supabase/appliances.sql` | 欄位名稱與單位與計算 API 不一致（`Appliance`/`Power`/`Minutes`）|
| `Supabase/profiles.sql` | 可用，但沒有自動建立 profile |
| `Supabase/security.sql` | RLS 只給 `authenticated`，匿名使用者讀寫全失敗 |
| `Supabase/connect.sql` | 只是重設 `user_id` 預設值 |
| `Python/Supabase.py` | import 時就查資料庫並 print；金鑰寫死 → 已清理 |
| `Python/manager.py` | 金鑰寫死；`power`/`minutes` 與 API 不符 → 已清理 |
| `Python/validation.py` | 規則比計算核心寬鬆 → 已由計算核心統一 |

## `Python/` 那三支的處理

金鑰已改成環境變數、import 副作用已移除、單位已對齊 API。
它們保留作為紀錄，但**後端實際使用的是 `backend/app/store.py` 與 `backend/app/store_supabase.py`**。

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
