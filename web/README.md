# LoopForge Web

一个轻量 Web 控制台，用来启动 `search.py`，订阅 `runs/<id>/events.jsonl`，并把 agent 的调研、生成、验证、评估和代码变化可视化。

```bash
cd web
npm install
npm run dev
```

前端默认在 `http://127.0.0.1:5173`，API 在 `http://127.0.0.1:8787`。

## 公网快速部署

公网模式先复制配置文件，并设置账号密码：

```bash
cd web
cp server.config.example.json server.config.json
vim server.config.json
npm ci
npm run dev:public
```

`server.config.json` 示例：

```json
{
  "server": {
    "apiHost": "127.0.0.1",
    "apiPort": 8787
  },
  "auth": {
    "enabled": true,
    "username": "admin",
    "password": "change-this-password",
    "sessionSecret": "change-this-long-random-secret",
    "sessionTtlHours": 12
  }
}
```

只需要开放 `5173/tcp`。API 默认仍监听 `127.0.0.1:8787`，由 Vite 代理访问，不需要直接暴露。

如果要使用真实 LLM，还需要在项目根目录配置 `agent/agent_llm.settings.json`，或设置 `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL`。
