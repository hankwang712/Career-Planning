# 静态页与动态 API 分离部署

目标：让 Nginx 直接从磁盘提供 HTML/CSS/JS，Uvicorn 提供动态接口：FastAPI 处理 `/api/chat/*`，其余接口交给 Flask。

## 1) 导出静态站点

在项目根目录执行：

```bash
python frontend/scripts/export_static_site.py
```

导出目录为：

- `deploy/static-site/index.html`
- `deploy/static-site/static/*`

## 2) Nginx 配置

参考文件：

- `deploy/nginx.static-api.conf`

关键点：

- `root` 指向导出的 `static-site` 目录
- `/static/*` 直接由 Nginx 读磁盘
- `/api/*` 反向代理到 Uvicorn（如 `127.0.0.1:8080`），其中 `/api/chat/*` 关闭代理缓冲以支持流式回答

## 3) 后端 CORS（跨域时）

如果你的前端与 API 不在同一域名，请设置环境变量：

```bash
FRONTEND_ORIGIN=https://your-frontend-domain.com
```

FastAPI 聊天接口和 Flask 其他 API 均支持允许来源的 CORS 响应头及 `OPTIONS` 预检。聊天接口支持携带 Cookie 和 `X-CSRF-Token`，包含重命名所需的 `PATCH` 方法。

## 4) API 基址（可选）

前端支持 `window.__API_BASE__`：

- 为空：默认同域请求（`/api/...`）
- 非空：请求会发到该基址（如 `https://api.example.com`）

例如可在 `index.html` 里放：

```html
<script>
  window.__API_BASE__ = "https://api.example.com";
</script>
```

## 5) 启动建议

- Uvicorn：仅对内监听（如 `127.0.0.1:8080`）
- Nginx：对外监听 80/443
- 浏览器只访问 Nginx 地址

从项目根目录启动统一后端：

```bash
python -m uvicorn server:asgi_app --app-dir backend --host 127.0.0.1 --port 8080
```

必须使用 `server:asgi_app`；`server:app` 是仅含原有页面和其他接口的 Flask WSGI 应用，不提供聊天 API。

