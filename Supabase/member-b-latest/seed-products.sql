-- VoltSpace - products 表的種子資料（真實產品，逐筆查證）
--
-- 原則：只有「在節能標章資料庫實際查到消耗電力(W)」的型號才寫進來。
--       價格沒查到就留 null（前端不會顯示價格那一行），不編造。
--       每筆在 description 附來源與查證日期。
--
-- 分類要對得上 server/app/data/appliances.json：
--   cooling / heating / laundry / electronics / lighting / kitchen
--
-- 用法：Supabase -> SQL Editor -> 貼上執行（可重複執行）

insert into public.products
    (name, brand, category, model, power_watts, voltage, energy_rating,
     price, currency, product_url, description, is_active)
values
    -- 已查證：節能標章全球資訊網，證書 1100735續2（2025/12/01-2027/11/30）
    ('14 吋 DC 桌上電扇', '中央牌', 'cooling', 'KDF-121SR',
     28, 110, null, null, 'TWD',
     'https://ea03.moeaea.gov.tw/e0410/01/purchasing/product/fprint.aspx?itemp0=57183',
     '節能標章標示消耗電力 28 W（查證日 2026-11-19）。可取代約 45-60 W 的傳統交流風扇。',
     true)
on conflict do nothing;

-- 待查證清單（查到才加進上面的 insert）：
--   冷氣     一級能效變頻分離式 2.8 kW 級（對比常見 900 W 定頻）
--   冰箱     一級能效變頻 300-500 L（對比常見 130 W）
--   洗衣機   一級能效變頻（對比常見 500 W）
--   微波爐   變頻機種（對比常見 1000 W）
--   電熱水瓶 節能機種（對比常見 800 W）
--   電暖器   變頻機種（對比常見 1200 W）
--
-- 每筆需要：型號、廠牌、消耗電力(W)、電壓、分類、價格（查不到就 null）

select model, brand, category, power_watts,
       case when price is null then '價格待查' else price::text end as price
from public.products
where is_active
order by category, model;