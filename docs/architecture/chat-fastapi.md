# FastAPI 会话聊天

聊天模块使用 FastAPI，复用原有 `ChatService`、`RecentCache` 和 `ChatStore`。前端仍访问原来的 `/api/chat/*`，请求和响应格式不变，已有 SQLite 数据无需迁移。

```text
浏览器 → Uvicorn :8080
           ├─ /api/chat/* → FastAPI → ChatService → 模型流式回答
           │                            ├─ SQLite：完整消息、摘要、记忆
           │                            ├─ Redis：近期上下文缓存
           │                            └─ Chroma：语义记忆检索
           └─ 其他路径 → Flask：登录、页面、报告等
```

## 启动与验证

在项目根目录执行：

```bash
pip install -r backend/requirements.txt
python backend/server.py
```

也可以使用 `npm start`，或直接启动 ASGI 应用：

```bash
python -m uvicorn server:asgi_app --app-dir backend --host 127.0.0.1 --port 8080
```

主站地址：`http://localhost:8080`。聊天 Swagger：`http://localhost:8080/api/chat/docs`。
先在主站登录，再在 Swagger 中调用接口。写操作的 `X-CSRF-Token` 参数使用主站 `GET /api/auth/security` 返回的 `csrf_token`，浏览器会携带同域登录 Cookie。

Redis 服务单独运行，通过环境变量 `CHAT_REDIS_URL` 指定连接，默认 `redis://127.0.0.1:6380/0`。Redis 不可用时回退到 SQLite；Redis 仍是近期上下文缓存，不承担完整聊天记录的持久化。

## 接口

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/api/chat/sessions` | 当前用户的会话列表和模型状态 |
| POST | `/api/chat/sessions` | 创建会话，JSON：`{"title":"面试准备"}`，可省略 title |
| PATCH | `/api/chat/sessions/{session_id}` | 重命名，JSON：`{"title":"新标题"}` |
| DELETE | `/api/chat/sessions/{session_id}` | 删除会话和近期缓存 |
| GET | `/api/chat/sessions/{session_id}/messages` | 聊天历史，支持 `before` 分页 |
| POST | `/api/chat/sessions/{session_id}/messages` | 发送消息并返回 SSE |
| POST | `/api/chat/sessions/{session_id}/finish` | 安排整理对话记忆 |
| GET | `/api/chat/memories` | 记忆与资料来源，可带 `session_id` 查看上下文 |
| POST | `/api/chat/sources/resume/sync` | 同步当前用户已上传的简历 |
| DELETE | `/api/chat/memories/{memory_id}` | 移除记忆 |

发送消息的请求体：

```json
{
  "content": "帮我准备后端开发面试",
  "request_id": "327d9ade-98a0-4720-9b7a-3ce6fe17f014"
}
```

每条新消息使用新 UUID，重试同一条消息复用原 UUID 和内容。回答使用 `text/event-stream`，事件保留 `start`、`status`、`context`、`delta`、`done`、`error` 格式。成功回答写入 SQLite 后清除近期缓存；断开连接时关闭流并释放当前轮次的锁，以便重试。

## 登录与校验

FastAPI 通过主站的 Flask session 接口验证签名 Cookie，并调用原有 `current_user()` 检查登录是否过期、被撤销或账号被禁用。客户端无需传入 owner，不能用请求中的用户名访问其他用户的会话。

写操作继续检查 `X-CSRF-Token`，请求体上限为 64 KiB（包含分块上传），标题 1–80 字，消息 1–12000 字。错误保留 `{"message":"..."}` 格式。所有聊天响应带 `Cache-Control: no-store`，跨域前端通过 `FRONTEND_ORIGIN` 配置。

离线回归（使用临时数据库和假模型）：

```bash
npm run check:chat
```
