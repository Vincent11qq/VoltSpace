# Member B 的原始 Python 模組（參考用）

這三個檔案是 Member B 交來的版本，**已被後端取代**，保留作為紀錄。

## 已處理的問題

| 檔案 | 問題 | 處理 |
| --- | --- | --- |
| `manager.py` | Supabase URL 與 key **寫死在程式碼裡**並已提交進 Git | 改從環境變數讀取；加上 `power_watts`／`hours_per_day` 的單位轉換；改呼叫共用的計算函式 |
| `Supabase.py` | 同上，而且 **import 時就查資料庫並 print** | 金鑰改環境變數；所有動作移到 `main()`，import 不再有副作用 |
| `validation.py` | 驗證規則比計算核心寬鬆 | 由 `backend/app/calculators/consumption.py` 統一 |

`manager.py` 與 `Supabase.py` 執行時都需要：

```
set VOLTSPACE_SUPABASE_URL=https://YOUR-PROJECT.supabase.co
set VOLTSPACE_SUPABASE_KEY=<publishable / anon key>
```

沒有設定時會給出清楚訊息，而不是直接爆掉。

> **注意：** 這個 Supabase 專案的 publishable key 曾以明文提交到 Git。
> publishable key 本來就會出現在前端，風險低（資料是否可讀由 RLS 決定），
> 但如果你要繼續使用同一個專案，建議在 Supabase 後台
> **Settings → API** 輪替金鑰，並確認 RLS 已啟用。

## 現在該用哪個

| 需求 | 用這個 |
| --- | --- |
| 直接跑 App（預設，不需要雲端） | `backend/app/store.py`（本地 SQLite） |
| 改用 Supabase | `backend/db/schema.sql` + [`../backend/docs/supabase.md`](../backend/docs/supabase.md) |
| 輸入驗證 | `backend/app/calculators/consumption.py` |
| 電費計算 | `backend/app/calculators/electricity_bill.py` |
