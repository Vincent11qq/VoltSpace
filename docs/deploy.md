# 部署成網站（讓別人不用下載就能用）

VoltSpace 是**一個 FastAPI 服務同時提供 API 與網頁介面**，所以部署只要跑一個進程，
不需要 nginx、不需要前端建置流程。差別只在「跑在哪台機器」。

> 三個選項的差別，先看這張表：

| 方式 | 誰在用 | 網址 | 免費？ | 適合 |
| --- | --- | --- | --- | --- |
| **A. Cloudflare Tunnel** | 你自己的電腦 | 每次啟動都不同 | ✅ 不用註冊 | **簡報當天**、練習、給組員看 |
| **B. Render** | Render 的伺服器 | 固定 | ✅（會休眠）| **報告裡的連結**、助教自己點 |
| **C. Docker（HF Spaces 等）** | 平台容器 | 固定 | ✅ | 想放到 Hugging Face 或任何容器主機 |

三個方式都**不需要改程式碼** —— `start.py` 會自動配合平台。

---

## 0. 先決定資料要存在哪（很重要）

雲端平台給的容器通常是**暫時性**的：重新部署、或閒置後被回收，容器裡的檔案就沒了。
本機 SQLite 的檔案存在容器裡，所以「重開就回到空白」。

你已經做好的 Supabase 儲存層就是為此準備的 —— 部署時把環境變數填一填即可：

```
VOLTSPACE_STORAGE=auto
VOLTSPACE_SUPABASE_URL=https://<project-ref>.supabase.co
VOLTSPACE_SUPABASE_SERVICE_KEY=<service_role key>
VOLTSPACE_HOUSEHOLD_ID=<一個 uuid>
```

部署後打開 `/health`，看到 `"storage": "supabase"` 才代表資料真的存在雲端：

```bash
curl https://<你的網址>/health
```

看到 `local-sqlite` 代表它退回本機了（資料會消失），八成是某個變數沒填。

> `VOLTSPACE_STORAGE=auto` 的設計是「有設定就用 Supabase，沒有就退回本機並印出原因」。
> 想要「設定錯就直接啟動失敗」以免搞錯，改成 `supabase`。

---

## A. Cloudflare Tunnel（最快，5 分鐘，簡報當天用）

不用部署、不用註冊帳號，你的電腦就是伺服器，別人透過一個公開網址連進來。

```powershell
# 1. 下載 cloudflared（Windows，一次就好）
winget install --id Cloudflare.cloudflared

# 2. 啟動網站（本機）
cd backend
run_app.bat

# 3. 另開一個終端機，把本機的 8000 埠公開出去
cloudflared tunnel --url http://127.0.0.1:8000
```

它會印出一個像 `https://random-words-1234.trycloudflare.com` 的網址，任何人打開就能用。

**注意**

- **網址每次啟動都不一樣**，而且只在你電腦開著時有效 —— 簡報前先開好，把網址貼到簡報裡。
- 你的電腦睡著或關掉，網站就斷。
- 這是公開網址，**任何人拿到都能改你的家電清單**（這個 App 沒有登入）。

---

## B. Render（推薦：固定網址，報告用）

免費方案、不需要信用卡、支援 Python。免費服務閒置 15 分鐘會休眠，**下一個請求要等
約 30 秒**才回應（簡報前先自己點一次把它喚醒）。

### B-1 用 Blueprint（這個 repo 已經準備好 `render.yaml`）

1. 到 <https://dashboard.render.com/blueprints> → **New Blueprint Instance**
2. 選 `Vincent11qq/VoltSpace`，它會讀到根目錄的 `render.yaml`
3. 按 **Apply**，等第一次建置（約 2–4 分鐘）
4. 到該服務的 **Environment** 填三個 secret（`VOLTSPACE_SUPABASE_URL`、
   `VOLTSPACE_SUPABASE_SERVICE_KEY`、`VOLTSPACE_HOUSEHOLD_ID`）→ **Save**（會自動重新部署）
5. 打開網址 `/health` 確認 `storage` 是 `supabase`

### B-2 手動設定（不 Blueprint 的話）

| 欄位 | 值 |
| --- | --- |
| Environment | `Python` |
| Root Directory | `backend` |
| Build Command | `pip install -r requirements.txt` |
| Start Command | `python start.py --no-browser` |
| Health Check Path | `/health` |
| Environment Variables | 同 B-1 的四個變數 |

> `start.py --no-browser` 是雲端要用的：沒有瀏覽器可開，而且它會讀平台的 `$PORT`
> 並綁定 `0.0.0.0`（直接跑 `uvicorn app.main:app` 沒有這層處理也可以，但就少了
> 環境檢查與清楚的錯誤訊息）。

### B-3 讓 Flet 版也有自己的網址（選用）

上面部署的是 `backend/web/` 的網頁版。如果你想讓 **Flet 那套介面**（Member A 的新設計）
也有一個可以直接打開的網址（例如手機傳連結給助教），再加**第二個服務**：

| 欄位 | 值 |
| --- | --- |
| Environment | `Python` |
| Root Directory | `backend` |
| Build Command | `pip install -r requirements-flet-web.txt` |
| Start Command | `python desktop/app.py` |
| Health Check Path | `/` |
| `VOLTSPACE_FLET_WEB` | `1` |
| `VOLTSPACE_FLET_HOST` | `0.0.0.0` |
| `VOLTSPACE_API` | `https://<你的第一個服務>.onrender.com` |
| `VOLTSPACE_STORAGE` | `local`（這個服務只畫畫面，資料由 API 服務處理）|

`render.yaml` 裡已經寫好這第二個服務（`voltspace-flet`），用 Blueprint 會自動建立。

**運作方式**：Flet 的 web 模式是一個普通的 Python 網頁服務 —— Python 跑在 Render，
瀏覽器只負責畫面。它本身不含計算，所以每個請求都回到 `VOLTSPACE_API` 指的那個服務。

> **要確認的事項**：`PORT` 由平台注入，`desktop/app.py` 會自動沿用（不用在指令裡指定）。
> 這個服務不含 `flet-desktop`（那是開視窗用的約 100 MB 客戶端，伺服器永遠不會顯示視窗），
> 所以啟動比第一個服務快。
>
> **限制**：免費方案一樣會休眠，而且 Flet 這一頁要等 Flutter 的 web 客戶端載入，
> 第一次打開比網頁版慢。**簡報用的主要連結建議仍用網頁版**，Flet 版當「設計展示」。

---

## C. Docker（Hugging Face Spaces 或任何容器主機）

repo 根目錄的 `Dockerfile` 只需要這一個容器。

```bash
docker build -t voltspace .
docker run -p 8080:8080 -e PORT=8080 \
  -e VOLTSPACE_SUPABASE_URL=... \
  -e VOLTSPACE_SUPABASE_SERVICE_KEY=... \
  -e VOLTSPACE_HOUSEHOLD_ID=... \
  voltspace
# 開 http://127.0.0.1:8080/
```

**Hugging Face Spaces**：New Space → SDK 選 **Docker** → 把 repo 推上去（或用網頁上傳）。
Spaces 要求容器監聽 **7860**，`Dockerfile` 已經處理（`ENV PORT=7860`）。
secret 在 Space 的 **Settings → Variables and secrets** 填。

> 容器沒有持久化磁碟，所以一樣要接 Supabase（或掛 volume 到 `VOLTSPACE_DATA_DIR`）。

---

## 部署後檢查清單

| 檢查 | 怎麼看 |
| --- | --- |
| 服務活著 | `GET /health` 回 200 |
| 資料在雲端 | `/health` 的 `storage` 是 `supabase` |
| 介面正常 | 打開 `/`，加入一台家電，看電費有沒有算出來 |
| 中英切換 | 右上角 `EN` / `中文` 能切，而且重新載入後還記得 |
| API 文件 | `/docs` 打得開 |
| 多一台裝置 | 用手機開同一個網址，看得到同一份清單（代表真的存在 Supabase）|
| Flet 版（選用）| 開 `voltspace-flet` 的網址，畫面是 Flet 介面，數字與網頁版一致 |

---

## 安全提醒（要寫進報告的「限制」）

這個 App **沒有登入機制**。任何拿到網址的人都可以：

- 看到你的家電清單與用電估算
- 修改、刪除那些家電

對課程展示來說通常可以接受，但要知道兩件事：

1. **不要把 service_role key 洩漏出去。** 它只在伺服器的環境變數裡，不要寫進
   `app.js`、不要放進 repo（`.gitignore` 已經擋掉 `.env`）。
2. 要「只給某些人看」，最簡單的做法是改用 Cloudflare Tunnel + 只在簡報時開啟，
   或申請一個有存取控制的平台方案。真的要做登入，`db/schema.sql` 的 RLS 已經是
   `household_id = auth.uid()`，接上 Supabase Auth 就可以。

---

## 常見問題

**Q：部署後 `/health` 說 `local-sqlite`，資料會不見嗎？**
會。容器重啟就沒了。把三個 Supabase 變數填好並重新部署。

**Q：`500 storage_error`**
看服務 log。常見是 key 用了 `anon` 而不是 `service_role`、或表還沒建
（跑 `backend/db/schema.sql`）。也可以在本地先跑 `python tools/supabase_doctor.py` 檢查。

**Q：Render 第一次打開很慢（30 秒以上）**
免費方案休眠造成的，正常。簡報前先開一次喚醒它。

**Q：可以部署到 Vercel / Netlify 嗎？**
不適合。它們是 serverless 且檔案系統唯讀，SQLite 不能寫；雖然能跑 FastAPI，
但這個專案需要一個持續存在的進程。Render / Fly / HF Spaces / 任何 VPS 都比較合適。

**Q：一定要用 `start.py` 嗎？**
不用。`uvicorn app.main:app --host 0.0.0.0 --port $PORT --proxy-headers` 也可以，
`start.py` 只是多做了環境檢查與友善的錯誤訊息。
