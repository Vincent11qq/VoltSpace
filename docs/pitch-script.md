# 講稿：第 4、5 頁（約 2 分鐘）

> 使用方式：粗體是**動作**（指畫面、點一下），`斜體`是停頓。整份唸完約 110–120 秒。
> 兩頁各有一個「一句話結論」——如果時間被壓縮，直接講那句。

---

## 第 4 頁 — 三種狀態，一個計算引擎

<!-- 投影片標題：Three states, one calculation engine. -->
<!-- 左：Within margin / Near limit / Over limit　右：手機截圖 55% of limit -->

**（指右邊手機畫面）**

這一頁是我們的第二個核心：**電路負載檢查**。

畫面上這個 **55% of limit**，不是我寫死的，是後端算出來的 ——
把標記為「會同時使用」的家電瓦數加起來，除以這條迴路的容量：
900 瓦 ÷ 1650 瓦 = 55%。`（停）`

**（指左邊三種狀態）**

我們刻意只用三種**中性**說法：**Within margin、Near limit、Over limit**。

不說「安全」或「危險」——因為這只是**估算**。真正的用電安全還牽涉線路老化、
插座品質、電線粗細，我們沒辦法保證，所以我們不宣稱。`（停）`

**（回來指右邊）**

還有一點：容量不是寫死的。**15 安培在 110 伏是 1650 瓦，在 220 伏就是 3300 瓦** ——
這個換算在後端做，所以切換迴路時，左邊三種狀態、右邊的百分比**同時**改變，
不會出現「數字說 55%、顏色說危險」這種前後矛盾。

> 一句話結論：**「它告訴你離上限還有多遠，但不替你保證安全。」**

---

## 第 5 頁 — 錢

<!-- 投影片標題：Save your money 24/7!　左：Cost Estimation 截圖　右：Alerie 情境 -->

**（指右邊的文字）**

這一頁講錢。Alerie 是我們設定的使用者：外宿、預算吃緊，最想知道三件事 ——
**這個月大概多少錢、哪一台在吃我的電、我能怎麼改。**

**（指左邊截圖）**

左邊就是答案。最上面 **NT$309** 是整月電費；中間是**每日成本**和**月用電量 162 度**；
再往下是**每一台家電分攤到的金額**。`（停）`

分攤原則是「**按用電比例**」—— 所以下面的數字加起來，永遠等於上面的總額。
這不是四捨五入湊出來的，是一致性設計。`（停）`

電費也不是寫死的：它來自**電價表**，夏月與非夏月不同級距，用的是
**2025 年 10 月**生效的版本。

**（指右邊下面的建議）**

右邊是我們的建議：系統會指出**最主要的那一台**（例如冷氣佔了你多少比例），
並給出可執行的做法，附上**預估省下的金額**——那個金額也是用同一份電價表算的。

> 一句話結論：**「同一個數字，出現在三個介面：網頁版、Flet 版、`/docs`。」**

### 收尾（兩頁合起來的一句）

這兩個功能其實是同一件事：**把你家看不到的東西變成看得見的數字** ——
一個是「離上限多遠」，一個是「錢花在哪」。

---

## 英文版（若要求用英文報告，各 40 秒）

**Slide 4**

> This is our circuit load check. The **55% of limit** on screen is computed by the backend:
> the appliances you mark as used at the same time, divided by the circuit capacity —
> 900 watts out of 1,650. `(pause)`
>
> We deliberately use neutral wording: **within margin, near limit, over limit**. We never
> say "safe" or "dangerous", because this is an **estimate** — wiring age and socket quality
> also matter, and we cannot guarantee those. `(pause)`
>
> The capacity is not hard-coded either: 15 amps is 1,650 watts at 110 volts and 3,300 at
> 220. The backend does that conversion, so the number and the colour always agree.

**Slide 5**

> This slide is about money. Alerie is on a budget and wants three things: how much this
> month, which appliance is responsible, and what she can change. `(pause)`
>
> The bill — NT$309 — comes from our tariff table, summer and non-summer tiers, the
> 2025-10-01 version. Below it, each appliance's share is allocated **by usage**, so the
> parts always sum to the total. `(pause)`
>
> The suggestions point at the appliance driving most of the bill and quantify the saving
> using that same tariff table. And every figure here also appears in the web version, the
> Flet version and `/docs` — one API, so they cannot disagree.

---

## 可能被打斷的三個問題（一句話回答）

| 問題 | 回答 |
| --- | --- |
| 「55% 怎麼算的？」 | 同時使用的瓦數 ÷（安培 × 伏特），後端算，前端只顯示。 |
| 「為什麼不用 Safe / Danger？」 | 我們不能保證安全，只報「離上限多遠」。有測試禁止 UI 出現 SAFE 字樣。 |
| 「電費跟台電帳單一樣嗎？」 | 不一樣：我們只算**依級距的電能費用**，不含基本電費、公共電費、節電折扣。 |

---

## 上台前（30 秒檢查）

1. 手機／投影片上的截圖是不是**最新版**（有 `WITHIN MARGIN`、`55% of limit`）？
2. 網頁先開一次，確認 API 醒著（避免講到一半轉圈）。
3. 講到「三個介面」時，**手指真的指一下**另外兩個入口，不要只是說。
