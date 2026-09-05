# BTCM 项目规格说明（Specification）

## 1. 项目概述

BTCM（Beside-Thinking Chain Module，副思考链模块）是一个可嵌入大型集成 Agent 的辅助思考器官。它接收外部传入的“思考任务”，内部通过四个核心 Agent（创意生成、验证、长链思考总控、检查管理 meta）协作，完成验证、创意生成或混合任务，并以结构化 JSON 返回结果。

定位与边界：

- 无状态服务：每次调用独立，不保留对话上下文，仅依赖传入的任务包，调用历史仅作为日志存储。

- 任务由调用方决定：集成使用时由宿主 Agent 选择录入的内容（问题、候选、证据、上下文摘要）；人工直接调用时通过请求参数（Agent 启用开关与 `config`）控制使用需求与使用量。

- 自包含与可配置：后端本体独立提供全部 API，可单独运行；前端面板为独立 SPA，与后端解耦（不打包绑定）。

- 范式移用：内部采用“生成-验证-反思”循环结构，该结构可作为思维模块范式，供其他验证或思考模块参照复用。

本项目包含两个主要部分：

- **btcmodule**：后端核心模块，基于 Python + FastAPI，提供 REST API 和内部 Agent 逻辑。

- **btcwebui**：前端控制面板，独立 Vue 3 + Vite SPA，提供配置和运行观察界面，与后端解耦，经 CORS / vite 代理访问本体 API。

## 2. 目录结构

```
project-root/
├── btcmodule/                 # 后端核心模块
│   ├── __init__.py
│   ├── main.py                # FastAPI 入口，挂载 API 路由（不托管前端）
│   ├── core/
│   │   ├── __init__.py
│   │   ├── task.py            # 任务对象定义
│   │   ├── result.py          # 结果对象定义
│   │   ├── config.py          # 配置加载与校验（Pydantic）
│   │   ├── llm.py             # 模型网关：提供商注册表 + 按 Agent 路由 + 工具调用循环
│   │   ├── mcp.py             # MCP 最小客户端（Streamable HTTP）与工具管理
│   │   ├── logger.py          # 调用日志（JSONL 追加，永久留存）
│   │   └── loop.py            # 主循环控制器（Engine）
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── creative.py        # 创意生成 Agent
│   │   ├── validator.py       # 验证 Agent
│   │   ├── controller.py      # 总控 Agent（长链思考）
│   │   └── meta.py            # meta Agent（完整循环检查与管理）
│   ├── api/
│   │   ├── __init__.py
│   │   └── routes.py          # REST API 路由
│   └── btcm.json              # 运行时配置（不受 git 管理，首次启动由内置默认配置生成）
├── btcwebui/                  # 前端控制面板
│   ├── package.json
│   ├── vite.config.ts
│   ├── src/
│   │   ├── main.ts
│   │   ├── App.vue
│   │   ├── views/
│   │   │   ├── Dashboard.vue      # 运行状态
│   │   │   ├── ConfigPanel.vue    # 配置编辑
│   │   │   └── Logs.vue           # 调用日志
│   │   ├── components/
│   │   └── api/
│   │       └── client.ts       # API 请求封装
│   └── build/                 # 构建输出目录（git ignore）
├── LICENSE                    # Apache-2.0 许可证
└── README.md
```

## 3. 技术栈

### 3.1 后端（btcmodule）

- **Python** 3.14（uv 管理，面向 Python 3.14 后端环境的宿主 Agent）

- **FastAPI**：Web 框架

- **Uvicorn**：ASGI 服务器

- **Pydantic**：数据校验与配置管理

- **openai**：OpenAI 兼容协议客户端，统一对接各模型服务（DeepSeek、Ollama、OpenRouter 等）

- **httpx**：MCP Streamable HTTP 客户端与异步 HTTP

- **asyncio**：异步并发控制（`asyncio.timeout` 强制全局超时）

### 3.2 前端（btcwebui）

- **Vue 3** + **TypeScript**

- **Vite**：构建工具

- **Naive UI**：UI 组件库（轻量、适合管理面板）

- **Vue Router**：路由管理

- 包管理使用 pnpm；构建产物独立输出到 `btcwebui/build/`，与后端解耦，不复制进后端包

## 4. 后端核心设计

### 4.1 运行形态

BTCM 的运行形态由请求体中的两个 Agent 启用开关决定：`enable_creative`（创意生成 Agent）与 `enable_validator`（验证 Agent），均默认开启；总控类 Agent（controller / meta）恒启用，无开关。四种组合对应四种形态：

| enable\_creative | enable\_validator | 形态     | 说明                                     |
| ---------------- | ----------------- | ------ | -------------------------------------- |
| true             | true              | 完整循环   | 创意生成-验证-反思循环，直到满足终止条件（默认）              |
| true             | false             | 纯创意    | 只调用创意生成 Agent，生成方案或观点，返回候选列表           |
| false            | true              | 纯验证    | 只调用验证 Agent，检查已有结论/计划，返回 verdict 及问题报告 |
| false            | false             | 长链持续思考 | 只调用 controller，多轮自我迭代思考并产出最终结论         |

纯创意与纯验证为单次执行，不进入循环（`iterations_used` 恒为 1，`termination_reason` 恒为 `single_pass`）；设计理念中“反复自思考和自验证”的能力由完整循环与长链持续思考两种形态承担，前者通过创意/验证/meta Agent 协作，后者由 controller Agent 独立完成。开关的全局默认值可经配置持久化，请求体顶层字段可对当次调用覆盖。

### 4.2 核心 Agent

四个 Agent 的职责相互独立，各自经模型网关路由到独立的提供商与模型（见 4.4），互不绑定同一模型。

#### 4.2.1 创意生成 Agent（Creative Agent）

- **职责**：针对用户问题或给定候选，发散式地生成多个新方案、观点、修正建议。

- **输入**：任务描述、用户问题、当前候选（可选）、上下文摘要。

- **输出**：候选内容列表，每项包含文本与简要理由。

- **特点**：鼓励多样性，可配置生成数量（如 2\~5 个）。

#### 4.2.2 验证 Agent（Validator Agent）

- **职责**：对给定候选或结论进行验证，发现逻辑漏洞、事实错误、信息缺口。

- **输入**：任务描述、用户问题、待验证内容、证据列表。

- **输出**：验证报告，包含判定（pass/conditional\_pass/fail）、问题列表、改进建议。

- **特点**：支持两种子验证：

  - **逻辑验证**：检查一致性、完备性、推理漏洞。

  - **事实验证**：经 MCP 联网工具核对事实依据。`enable_web_search` 为工具总开关，`mcp_servers` 指向注册表中启用的服务器（内置市面预设 tavily/exa/deepwiki/fetch）；工具经 OpenAI function calling 调用，遵循"可用才调用"——服务器不可用时静默降级为纯逻辑验证。`web_sources` 作为期望权威域名写入提示词。

- **工具边界**：BTCM 是辅助思考模块而非工具执行器，外部工具仅挂在验证 Agent 上、仅服务于更权威的验证这一件事；创意/总控/meta Agent 一律不接触工具，保持纯思考。预设与注册表不倾向扩展——检索类（如 duckduckgo）覆盖事实核对即可，不再引入写操作类、代码执行类等多余工具。

#### 4.2.3 总控 Agent（Controller Agent）

- **职责**：当创意与验证 Agent 均未启用时，作为唯一执行者独立承担长链持续思考——每轮批判性深化（think），最终整合全部轮次为最终结论（finalize）。

- **形态**：要点级输出，每轮只产出新的思考要点，不重复已有内容、不展开长篇推理。

- **输入**：初始任务、上一轮思考要点（历史超限时保留首条 + 最近 5 条）。

- **输出**：每轮思考要点（`thought`），最终结论（`conclusion`）。

- **边界**：无 `validation_passed` 终止路径，仅由 `max_iterations` / `timeout` 机械规则决定终止。

#### 4.2.4 meta Agent（Meta Agent）

- **职责**：完整循环中的检查与管理——以半个元认识的视角总体认识当轮结果，批判性控制（接受合理发散，批驳过于怪异或逻辑错乱的候选），并以资源意识决定继续或收敛。

- **形态**：反思过程控制在要点级——提示词与输出只覆盖当轮整合结论、剩余问题、下轮方向与 continue/stop 决定（短句要点，不展开长篇推理），以有效 token 为限。

- **输入**：初始任务、当轮候选、验证报告。

- **输出**：反思要点（conclusion / remaining\_issues / next\_direction / decision）。

- **实权**（完整循环中）：

  - `decision=stop` 参与终止判定（`controller_stop` 终止原因，优先级低于 `validation_passed`；`verdict=fail` 时 stop 无效——验证判定存在严重问题不得提前定稿）；

  - 未终止时 `next_direction` 作为下轮创意 Agent 的修正方向输入，实现"反思调整输入，继续下一轮"。

- **边界**：硬性上限（`max_iterations` / `timeout`）仍由机械规则承载，meta 只能提前收敛、不能突破上限。

### 4.3 主循环流程

```
外部请求 → 接入层解析为 Task 对象
                ↓
        Engine（主循环）启动循环
                ↓
   ┌─────────── 循环（最多 max_iterations 轮）───────────┐
   │  创意 Agent（若需要）→ 生成候选集                    │
   │          ↓                                          │
   │  验证 Agent（若需要）→ 验证候选，输出判定与问题      │
   │          ↓                                          │
   │  meta Agent（检查与管理）反思：                      │
   │     - 整合结果                                      │
   │     - 判断是否满足终止条件                           │
   │          │                                          │
   │          ├── 是 → 跳出循环                          │
   │          └── 否 → 调整输入，继续下一轮               │
   └──────────────────────────────────────────────────┘
                ↓
        组装最终结果
                ↓
        接入层封装为标准 JSON 响应
```

**终止条件**（按判定顺序，满足任一即止）：

1. 验证 Agent 判定 `pass`（对应 `validation_passed`，仅完整循环形态）
2. meta Agent 反思判定 `decision=stop`（对应 `controller_stop`，仅完整循环形态）
3. 达到 `max_iterations`
4. 达到 `timeout`（秒，服务端强制执行，超时即掐断进行中的 LLM 调用）

硬性上限（轮数、超时）由结构化判定与机械规则决定，meta 只能提前收敛、不能突破上限，行为可预期。

多候选循环语义：创意 Agent 一次生成多个候选时，验证 Agent 对候选集整体给出判定并指明最优候选；若未通过，下一轮创意 Agent 基于该最优候选、验证问题与 meta `next_direction` 进行修正，不再重新发散。

**长链持续思考形态**（两个开关均关闭）下流程简化为：controller 每轮基于任务与上一轮要点输出新的思考要点，逐轮深化；无验证 Agent 参与，故无 `validation_passed` 终止路径，仅由 `max_iterations` 与 `timeout` 决定终止；最终由 controller 整合所有轮次为最终结论。

### 4.4 配置体系（本体）

配置文件采用 JSON 格式，位于 `btcmodule/btcm.json`，不受版本管理；内置默认配置存在于代码中（Pydantic 模型默认值），首次启动若文件不存在则据此生成。写入采用原子方式（先写临时文件再替换）。

模型管理采用提供商注册表 + 按 Agent 路由（借鉴 DPIM 的 BYOK 模式独立实现）：

- `providers`：注册多个 OpenAI 兼容提供商，各含 `base_url`、`api_key`、`models`（可用模型列表）、`timeout`（可选，单次 LLM 请求超时秒数，默认 600）、`options`（可选，模型私有参数，透传进请求）。

- `mcp_servers`：MCP 服务器注册表（Streamable HTTP），条目含 `preset`（内置预设 tavily/exa/deepwiki/fetch/duckduckgo）或 `url`、`api_key`、`enabled`、`timeout`（默认 60）、`allowed_tools`（工具白名单）、`allow_private`（默认 false，指向内网/回环地址需显式放行，且 URL 仅允许 http/https）；验证 Agent 经 `agents.validator.mcp_servers` 引用，可用才调用。`duckduckgo` 预设指向本地 MCP 子进程（`http://127.0.0.1:7070/mcp`，免密钥，条目需 `allow_private=true`），后端启动时经 uvx 自动拉起 `duckduckgo-mcp-server`（含 browser extra，curl\_cffi 用于 Chrome TLS 伪装），提供 `search` 与 `fetch_content` 工具；拉起失败仅告警，验证 Agent 降级纯逻辑验证。

- `agents`：四个 Agent（creative / validator / controller / meta）各自通过 `provider` + `model` 指向注册表条目，可分别使用不同提供商、不同模型。

- Agent 级公共参数：`temperature`（采样温度，creative 默认 0.8，validator/controller/meta 默认 0.3）、`max_tokens`（单次请求最大输出 token 数，默认 16384，面向本地推理的大输出预算；云端提供商上限较低时按需调低）、`timeout`（可选，单请求超时，设置后覆盖所属提供商值）、`options`（可选，模型私有参数，Agent 级覆盖提供商级）；另有各 Agent 专属参数（creative 的 `num_candidates`，validator 的 `enable_web_search`/`web_sources`/`mcp_servers`，meta 的 `log_intermediate`）。

- 参数优先级（从高到低）：请求内 `config`（仅运行时参数） > Agent 级 > 提供商级 > 内置默认值。

- `enable_creative` / `enable_validator`：创意与验证 Agent 启用开关的全局默认值（均默认 true），请求体顶层可对当次调用覆盖；总控类 Agent（controller / meta）恒启用，无开关。

- `admin_token`（可选）：管理令牌，设置后 PUT /api/config、POST /api/config/reset、GET /api/logs 要求 `X-Admin-Token` 请求头；/api/invoke 与 GET /api/config 恒开放。

- `lock_invoke`（可选，默认 false）：开启后 /api/invoke 也要求 `X-Admin-Token`（保护开放到局域网时的付费模型调用）。

- `api_key` 与 `admin_token` 仅存于配置文件；`GET /api/config` 返回时省略这些字段，不回显。密钥亦可经环境变量注入（`BTCM_ADMIN_TOKEN`、`BTCM_PROVIDER_<NAME>_API_KEY`、`BTCM_MCP_<NAME>_API_KEY`），优先级高于配置文件且不回写、不回显。

- 本地模型：Ollama、llama.cpp、LM Studio 等本地推理服务经其 OpenAI 兼容接口接入，无需额外适配；本地推理较慢，建议放宽该提供商的 `timeout`（如 600），并相应调大全局 `timeout`。

示例结构：

```json
{
  "max_iterations": 2,
  "timeout": 3600,
  "enable_creative": true,
  "enable_validator": true,
  "admin_token": null,
  "lock_invoke": false,
  "providers": {
    "deepseek": {
      "base_url": "https://api.deepseek.com/v1",
      "api_key": "sk-...",
      "models": ["deepseek-chat", "deepseek-reasoner"]
    },
    "ollama-local": {
      "base_url": "http://localhost:11434/v1",
      "api_key": "not-set",
      "models": ["llama3:8b"],
      "timeout": 600
    }
  },
  "mcp_servers": {
    "tavily": {
      "preset": "tavily",
      "api_key": "tvly-...",
      "enabled": true,
      "timeout": 60,
      "allowed_tools": []
    }
  },
  "agents": {
    "creative": {
      "provider": "deepseek",
      "model": "deepseek-chat",
      "num_candidates": 3,
      "temperature": 0.8,
      "max_tokens": 16384
    },
    "validator": {
      "provider": "deepseek",
      "model": "deepseek-reasoner",
      "temperature": 0.3,
      "max_tokens": 16384,
      "timeout": 600,
      "enable_web_search": false,
      "web_sources": ["wikipedia.org", "gov.cn", "edu.cn"],
      "mcp_servers": []
    },
    "controller": {
      "provider": "deepseek",
      "model": "deepseek-chat",
      "temperature": 0.3,
      "max_tokens": 16384
    },
    "meta": {
      "provider": "deepseek",
      "model": "deepseek-chat",
      "temperature": 0.3,
      "max_tokens": 16384,
      "log_intermediate": true
    }
  }
}
```

模型网关（`core/llm.py`）按 Agent 角色解析提供商配置并缓存客户端，按生效参数（优先级解析后的 temperature、max\_tokens、单请求超时）下发每次调用；模型私有参数 `options` 经 OpenAI SDK `extra_body` 合并进请求体顶层透传；SSE 流式调用时模型输出以增量前传给前端；请求内 `config` 仅可覆盖运行时参数（max\_iterations、全局 timeout、候选数、温度、token 上限、单请求超时、联网开关），不可变更模型路由；Agent 启用开关（`enable_creative` / `enable_validator`）与思考深度（`effort`）为请求体顶层字段，不受 `config` 约束。

### 4.5 API 设计

所有 API 前缀为 `/api`。

#### 4.5.1 调用 BTCM

- **POST** `/api/invoke`

并发上限默认 4（满载立即返回 429 `RATE_LIMITED`，不排队），防止失误循环或误调用打爆模型账单；成功响应 `data` 可含 `usage` 计量（prompt/completion tokens、llm\_calls、tool\_calls）。

请求体（JSON）：

```json
{
  "request_id": "uuid-optional",
  "user_query": "用户问题或任务描述",
  "candidate": "待验证/改进的候选内容（可选）",
  "evidence": ["证据1", "证据2"],        // 可选，供验证 Agent 使用
  "context_summary": "上下文摘要（可选）",
  "enable_creative": true,               // 可选，默认 true；与 enable_validator 组合决定运行形态
  "enable_validator": true,              // 可选，默认 true
  "effort": "standard",                  // 可选，思考深度三档：light（略想）/ standard（通用）/ deep（深层）
  "config": {                            // 可选，覆盖默认配置（仅运行时参数）
    "max_iterations": 2,
    "agents": { "validator": { "enable_web_search": true } }
  }
}
```

`effort` 三档：`light`（略想）强制单轮并注入快速思考提示词，对本地推理服务（llama.cpp/vLLM）额外关闭模型思考开关，追求最短路径出结果；`standard` 为默认行为；`deep`（深层）注入充分深思的提示词。深度分级仅作用于提示词与轮次，不改变响应结构。

响应体（JSON，统一外层结构，`data` 按运行形态分化，完整字段定义以 `share/protocol.md` 为准）。以完整循环为例：

```json
{
  "success": true,
  "data": {
    "verdict": "pass",                  // pass | conditional_pass | fail
    "conclusion": "最终结论/修改后的候选",
    "issues": ["发现的问题1", "问题2"],
    "suggestions": ["改进建议1"],
    "next_actions": ["下一步行动建议"],
    "iterations_used": 2,
    "termination_reason": "validation_passed",
    "intermediate_log": []              // 若配置 log_intermediate，包含每轮摘要
  },
  "error": null,
  "request_id": "uuid"
}
```

纯创意形态下 `data` 不含 `verdict` 等验证字段，改为返回 `candidates`（候选列表）与 `conclusion`；长链持续思考形态下仅返回 `conclusion` 与 `intermediate_log`（每轮思考要点），无验证字段。

#### 4.5.1.1 流式调用

- **POST** `/api/invoke/stream`

请求体与 `/api/invoke` 一致；响应为 `text/event-stream`（SSE），增量推送各 Agent 的思考与输出过程，结束时以 `done` 事件返回与 `/api/invoke` 同构的完整结果。校验失败（400/401/429）返回普通 JSON。事件定义与示例以 `share/protocol.md` 2.1.4 为准。

#### 4.5.2 获取当前配置

- **GET** `/api/config`

返回当前生效的完整配置（JSON，统一外层结构）。

#### 4.5.3 更新配置

- **PUT** `/api/config`

接收部分配置更新，校验通过后持久化到 `btcmodule/btcm.json` 并立即生效。配置 `admin_token` 后，本端点与 `POST /api/config/reset`、`GET /api/logs` 要求请求头 `X-Admin-Token`，缺失或错误返回 401 `UNAUTHORIZED`；`admin_token` 仅可写入、不回显。

#### 4.5.4 查看调用历史

- **GET** `/api/logs?limit=20`

返回最近的调用记录摘要（不包括完整中间日志；配置 admin\_token 后需 `X-Admin-Token`）。

#### 4.5.5 健康检查

- **GET** `/api/health`

探活端点：返回 `{status, version, uptime_s}`，恒开放、无敏感信息。

## 5. 前端控制面板设计

### 5.1 页面结构

#### 5.1.1 Dashboard（运行状态）

- 展示最近一次调用的基本信息：运行形态（Agent 启用开关）、请求 ID、耗时、迭代次数、判定结果（verdict）。

- 以列表或卡片展示 `intermediate_log`，每轮的状态摘要。

- 提供“发起测试调用”按钮，方便快速验证。

#### 5.1.2 ConfigPanel（配置编辑）

- 可视化表单编辑 JSON 配置（字段对应后端配置结构）。

- 支持保存到后端（PUT /api/config）。

- 可选“重置为默认”按钮。

#### 5.1.3 Logs（调用日志）

- 表格展示历史调用记录：时间、状态、结论、问题、耗时；成功调用直显结论文本（多行截断，悬浮查看全文），失败调用显示错误码提示。

- 支持结论字号缩放（localStorage 记忆档位）。

### 5.2 前端技术细节

- 使用 **Naive UI** 组件库搭建界面。

- API 封装在 `src/api/client.ts`，统一处理请求和错误。

- 路由：`/` 重定向到 Dashboard，`/config` 配置页，`/logs` 日志页。

- 构建命令：`pnpm build`，独立输出到 `btcwebui/build/`；后端不托管前端，生产用 `VITE_API_BASE` 指向后端 API（后端已开 CORS）。

## 6. 构成与运行

项目由两部分构成，实现顺序为先本体、后面板：

- **项目本体（btcmodule）**：独立可运行，提供全部 API 功能。

  - 运行：`uvicorn btcmodule.main:app --port 8000`

  - 通过 API 即可完成调用、配置管理与日志查看，不依赖控制面板。

- **控制面板（btcwebui）**：本体功能验证无误后开发。

- 构建命令：`pnpm build`，独立输出到 `btcwebui/build/`；开发联调用 `pnpm dev`（vite 代理 `/api` 到 8000）。

- 分包策略：路由级懒加载 + `unplugin-vue-components` 按需引入 naive-ui（不再全量 `use(naive)`），`manualChunks` 仅固定 vue/vue-router，已用组件由 rollup 自动聚合为共享 chunk。

  - 面板就绪后，`pnpm dev` 访问 `http://localhost:5173` 联调（dev 代理 `/api` 至 8000）；生产由独立静态服务器托管 `build/` 产物，经 `VITE_API_BASE` 指向后端。

### 6.1 依赖管理

- 后端：`btcmodule/pyproject.toml`（uv 管理）：fastapi、uvicorn\[standard]、pydantic、openai、httpx（MCP Streamable HTTP）。

- 前端：`btcwebui/package.json`（pnpm 管理）；构建工具 vite，dev 依赖含 `unplugin-vue-components` 与 naive-ui 解析器。

## 7. 扩展性与后续规划

- **Agent 插件化**：定义 `BaseAgent` 接口，允许注册新的思维单元（如安全审核、情感分析），通过配置启用。

- **思维格式引擎**：未来支持链式、树状、辩论等多种格式，由 meta Agent 选择。

- **WebSocket 实时监控**：在循环过程中推送中间状态，提升控制面板体验。

- **CLI 工具**：提供命令行调用方式，方便测试和脚本集成。

（多提供商多模型路由已在配置体系中支持，不列为扩展项。）

***

该规格文档基于当前讨论的框架，后续可根据具体实现进一步细化。
