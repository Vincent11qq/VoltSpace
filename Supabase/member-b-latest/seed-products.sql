-- VoltSpace — 示範用產品資料（Member B 的 products 表）
--
-- 為什麼需要這一份：`/product-recommendations` 會依家電分類去 products 表找「更省電」的
-- 替代品。表若沒有資料，端點會誠實地回 `{"recommendations": [], "total": 0}`，
-- 前端就會顯示「沒有可推薦的產品」——不是壞掉，只是沒有東西可推薦。
--
-- 用法：Supabase → SQL Editor → 貼上整份執行（可重複執行，已用 on conflict 防重複）。
--
-- 分類要跟 server/app/data/appliances.json 對得上：
--   cooling（冷氣、冰箱）、heating（電暖器）、laundry（洗衣機）、
--   electronics（電腦、電視）、lighting（照明）、kitchen（電鍋、微波爐）
--
-- 瓦數刻意比常見機種低（例如冷氣 900W → 700W），這樣才會被判定為「更省電」；
-- 價格與型號是示範值，不是實際報價。

insert into public.products
    (name, brand, category, model, power_watts, voltage, energy_rating,
     price, currency, product_url, description, is_active)
values
    ('一級能效變頻冷氣（示範）', 'Demo', 'cooling', 'AC-700',
     700, 220, '1', 23900, 'TWD', null,
     '對比常見的 900 W 定頻機種，瓦數較低。示範資料。', true),

    ('雙門變頻冰箱（示範）', 'Demo', 'cooling', 'RF-90',
     90, 110, '1', 18900, 'TWD', null,
     '對比常見的 130 W 機種。示範資料。', true),

    ('DC 直流電風扇（示範）', 'Demo', 'cooling', 'FAN-25',
     25, 110, null, 1890, 'TWD', null,
     '對比常見的 45 W 交流風扇。示範資料。', true),

    ('LED 燈泡 10 W（示範）', 'Demo', 'lighting', 'LED-10',
     10, 110, null, 149, 'TWD', null,
     '對比 60 W 白熾燈泡。示範資料。', true),

    ('一級能效變頻洗衣機（示範）', 'Demo', 'laundry', 'WM-350',
     350, 110, '1', 15900, 'TWD', null,
     '對比常見的 500 W 機種。示範資料。', true),

    ('變頻微波爐（示範）', 'Demo', 'kitchen', 'MW-800',
     800, 110, null, 3990, 'TWD', null,
     '對比常見的 1000 W 機種。示範資料。', true),

    ('節能電熱水瓶（示範）', 'Demo', 'kitchen', 'KT-600',
     600, 110, null, 2490, 'TWD', null,
     '對比常見的 800 W 機種。示範資料。', true),

    ('變頻電暖器（示範）', 'Demo', 'heating', 'HT-800',
     800, 110, null, 4290, 'TWD', null,
     '對比常見的 1200 W 機種。示範資料。', true)
on conflict do nothing;

-- 檢查：應該要有 8 筆
select category, count(*) as products
from public.products
where is_active
group by category
order by category;
