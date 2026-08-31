# BTCM（Beside-Thinking Chain Module，副思考链模块）

可嵌入大型集成 Agent 的辅助思考器官：接收思考任务，内部由创意生成、验证、总控三个 Agent 经“生成-验证-反思”循环处理后返回结构化结果。总控承担元认知式的全局思维管理（可提前收敛终止），验证 Agent 可按需接入 MCP 联网工具。服务无状态，自带 Web 控制面板，单端口运行。

- 总体设计：[share/spec.md](share/spec.md)
- Agent 设计：[docs/Agents.md](docs/Agents.md)
- 接口契约：[share/protocol.md](share/protocol.md)（唯一权威；alpha 阶段随实现迭代）

---

## 快速使用

### 1. 启动后端本体（btcmodule）

包管理使用 [uv](https://docs.astral.sh/uv/)（Python >=3.14），环境与前端完全隔离，位于 `btcmodule/` 内。

```bash
cd btcmodule
uv sync                                            # 安装依赖，自动创建 .venv 并生成 uv.lock
uv run python -m uvicorn main:app --port 8000      # 启动服务
```

首次启动自动生成配置文件 `btcmodule/btcm.json`（内置默认值，已配置 DeepSeek 与本地 Ollama 示例路由），不纳入版本管理。

### 2. 配置模型 API Key

```bash
# 将 deepseek 提供商替换为你的 api_key（本地 Ollama 可跳过）
curl -X PUT http://localhost:8000/api/config \
  -H "Content-Type: application/json" \
  -d '{"providers":{"deepseek":{"api_key":"sk-xxx"}}}'
```

`GET /api/config` 不会回显任何 api_key、MCP 密钥与管理令牌。

可选：设置管理令牌（设置后写配置/重置/日志接口需 `X-Admin-Token` 头）：

```bash
curl -X PUT http://localhost:8000/api/config \
  -H "Content-Type: application/json" \
  -d '{"admin_token":"your-token"}'
```

可选：为验证 Agent 接入 MCP 联网工具（可用才调用，不可用自动退回纯逻辑验证）：

```bash
# 注册一个内置预设（tavily / exa / deepwiki / fetch），并允许验证 Agent 使用
curl -X PUT http://localhost:8000/api/config \
  -H "Content-Type: application/json" \
  -d '{
    "mcp_servers": {"tavily": {"preset": "tavily", "api_key": "tvly-xxx"}},
    "agents": {"validator": {"enable_web_search": true, "mcp_servers": ["tavily"]}}
  }'
```

### 3. 发起调用

运行形态由 `enable_creative` / `enable_validator` 两个开关组合决定（均默认开启，总控 Agent 恒启用）：

```bash
# 完整循环（默认）：生成-验证-反思，可多轮迭代
curl -X POST http://localhost:8000/api/invoke \
  -H "Content-Type: application/json" \
  -d '{"user_query":"下周去东京，预算 5000，能去哪些地方？"}'

# 纯创意：只生成候选
curl -X POST http://localhost:8000/api/invoke \
  -H "Content-Type: application/json" \
  -d '{"user_query":"设计一个周末活动方案","enable_creative":true,"enable_validator":false}'

# 纯验证：验证给定候选（candidate 必填）
curl -X POST http://localhost:8000/api/invoke \
  -H "Content-Type: application/json" \
  -d '{"user_query":"验证这个方案","candidate":"去公园野餐","enable_creative":false,"enable_validator":true}'

# 长链持续思考：仅总控多轮自省，无验证环节
curl -X POST http://localhost:8000/api/invoke \
  -H "Content-Type: application/json" \
  -d '{"user_query":"深入思考一个开放性问题","enable_creative":false,"enable_validator":false}'
```

响应为统一外层结构 `{success, data, error, request_id}`，`data` 按运行形态分化（完整循环/纯验证含 `verdict`，纯创意含 `candidates`，长链含 `conclusion` 与逐轮 `intermediate_log`），并含可选 `usage` token 计量。`/api/invoke` 并发上限 4（满载返回 429；设置 `admin_token` 后写配置/重置/日志接口需 `X-Admin-Token` 头）。

### 4. 运行测试

```bash
cd btcmodule
uv run python -m unittest discover -s ../tests -t ..
```

### 5. 控制面板（btcwebui）

开发模式（前端 dev 服务将 `/api` 代理到 `localhost:8000`）：

```bash
cd btcwebui
pnpm install
pnpm dev        # 访问 http://localhost:5173
```

生产模式（构建产物复制到 `btcmodule/static/`，由后端单端口托管）：

```bash
cd btcwebui
pnpm install
pnpm build      # 产物自动复制到 btcmodule/static/
# 重启后端后访问 http://localhost:8000 即可同时获得 API 与控制面板
```

面板提供三页：**运行**（发起调用并观察中间过程）、**配置**（可视化编辑运行参数、模型路由、MCP 服务器注册表与管理令牌，密钥类输入不回显）、**日志**（历史调用记录分页查看，含 token 计量）。

---

更多接口细节（错误码、配置覆盖规则、超时语义等）见 [share/protocol.md](share/protocol.md)。
