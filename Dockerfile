# VoltSpace — 單一容器的部署方式（Hugging Face Spaces、Fly.io、任何 Docker 主機）
#
#   docker build -t voltspace .
#   docker run -p 8080:8080 -e PORT=8080 voltspace
#
# 前端是靜態檔案，由 FastAPI 一起提供，所以**只需要這一個容器**，沒有 nginx、
# 沒有前端建置流程。

FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# 先只複製 requirements，讓套件層可以被快取，改程式時不用重裝。
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./

# Hugging Face Spaces 要求容器監聽 7860；其他平台會注入自己的 $PORT 覆蓋這裡的值。
ENV PORT=7860
EXPOSE 7860

# 平台（或 docker）可以用這個判斷服務是否活著。
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD python -c "import os,urllib.request as u;u.urlopen('http://127.0.0.1:'+os.environ.get('PORT','7860')+'/health',timeout=4)"

# start.py 會挑選可用的 Python、必要時把 .pylibs 加進路徑，然後啟動 uvicorn。
CMD ["python", "start.py", "--no-browser"]
