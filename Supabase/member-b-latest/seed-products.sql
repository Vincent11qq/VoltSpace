-- VoltSpace - products 表資料範本（目前留空）
--
-- 這份檔案不是資料，是「要填什麼」的說明。products 表的內容屬於 Member B 的工作
-- （產品型錄：品牌、型號、瓦數、價格），我們這邊只負責把它接起來：
--   /product-recommendations 依家電分類到 products 表找更省電的替代品
--   表若是空的，端點會誠實回 {"recommendations": [], "total": 0}，前端顯示
--   「沒有可推薦的產品」——不是壞掉，只是沒有資料。
--
-- 填入時請照下面的欄位補，並且：
--   * power_watts 必須「低於」使用者實際家電的瓦數，否則不會被推薦
--   * category 要對得上 server/app/data/appliances.json
--     （cooling / heating / laundry / electronics / lighting / kitchen）
--   * price 查不到就留 null，前端會自動不顯示價格，不要編造
--   * description 建議寫上資料來源與查詢日期

-- 範本（取消註解並填入真實資料後再執行）：
--
-- insert into public.products
--     (name, brand, category, model, power_watts, voltage, energy_rating,
--      price, currency, product_url, description, is_active)
-- values
--     ('產品名稱', '廠牌', 'cooling', '型號',
--      700, 220, '1', 23900, 'TWD', 'https://...',
--     '資料來源：節能標章／賣場，查詢日 YYYY-MM-DD', true);

select count(*) as products_in_table
from public.products
where is_active;