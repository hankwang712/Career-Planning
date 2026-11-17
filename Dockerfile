# ---- 前端构建：只产出 frontend/static/dist 与 vendor ----
FROM node:22-slim AS frontend
WORKDIR /app
COPY package.json package-lock.json ./
COPY frontend/package.json frontend/package.json
RUN npm ci
COPY frontend frontend
RUN npm run build

# ---- 运行镜像：Python 依赖按 requirements.txt 的锁定版本安装 ----
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONUTF8=1 \
    HOST=0.0.0.0 \
    PORT=8080 \
    JOB_MARKET_SCHEDULER=0 \
    CAREER_APP_DATA_DIR=/var/lib/career/app_data

# tesseract 用于简历/招聘图片的本地 OCR（可选能力）；curl 供健康检查使用。
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-chi-sim curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY backend backend
COPY data data
COPY artifacts artifacts
COPY asserts asserts
COPY frontend/templates frontend/templates
COPY frontend/static frontend/static
COPY --from=frontend /app/frontend/static/dist frontend/static/dist
COPY --from=frontend /app/frontend/static/vendor frontend/static/vendor

RUN useradd --system --create-home career \
    && mkdir -p "$CAREER_APP_DATA_DIR" \
    && chown -R career:career "$CAREER_APP_DATA_DIR" /app/data
USER career

# 账号、报告、聊天记录都在这个目录里，务必挂载成卷。
VOLUME ["/var/lib/career/app_data"]
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${PORT}/healthz" || exit 1

CMD ["python", "backend/server.py"]
