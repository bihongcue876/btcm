# BTCM 项目规格说明（Specification）

## 1. 项目概述

BTCM（Beside-Thinking Chain Module，副思考链模块）是一个可嵌入大型集成 Agent 的辅助思考器官。它接收外部传入的“思考任务”，内部通过三个核心 Agent（创意生成、验证、总控）协作，完成验证、创意生成或混合任务，并以结构化 JSON 返回结果。

定位与边界：

- 无状态服务：每次调用独立，不保留对话上下文，仅依赖传入的任务包，调用历史仅作为日志存储。
- 任务由调用方决定：集成使用时由宿主 Agent 选择录入的内容（问题、候选、证据、上下文摘要）；人工直接调用时通过请求参数（Agent 启用开关与 `config`）控制使用需求与使用量。
- 自包含与可配置：本体系统与 Web 控制面板一体化部署，单端口同时提供 API 与面板。
- 范式移用：内部采用“生成-验证-反思”循环结构，该结构可作为思维模块范式，供其他验证或思考模块参照复用。

本项目包含两个主要部分：

- **btcmodule**：后端核心模块，基于 Python + FastAPI，提供 REST API 和内部 Agent 逻辑。
- **btcwebui**：前端控制面板，基于 Vue 3 + Vite，提供配置和运行观察界面，构建后由 FastAPI 托管静态文件，实现单端口访问。

## 2. 目录结构

```
project-root/
├── btcmodule/                 # 后端核心模块
│   ├── __init__.py
│   ├── main.py                # FastAPI 入口，挂载 API 和静态面板
│   ├── core/
│   │   ├── __init__.py
│   │   ├── task.py            # 任务对象定义
│   │   ├── result.py          # 结果对象定义
│   │   ├── config.py          # 配置加载与校验（Pydantic）
│   │   ├── llm.py             # 模型网关：提供商注册表 + 按 Agent 路由
│   │   └── loop.py            # 主循环控制器（总控 Agent）
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── creative.py        # 创意生成 Agent
│   │   ├── validator.py       # 验证 Agent
│   │   └── controller.py      # 总控 Agent（含反思）
│   ├── api/
│   │   ├── __init__.py
│   │   └── routes.py          # REST API 路由
│   ├── static/                # 存放 Vue 构建产物（部署时复制到此）
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
└── README.md
```

## 3. 技术栈

### 3.1 后端（btcmodule）
- **Python** 3.11+
- **FastAPI**：Web 框架
- **Uvicorn**：ASGI 服务器
- **Pydantic**：数据校验与配置管理
- **openai**：OpenAI 兼容协议客户端，统一对接各模型服务（DeepSeek、Ollama、OpenRouter 等）
- **asyncio**：异步并发控制

### 3.2 前端（btcwebui）
- **Vue 3** + **TypeScript**
- **Vite**：构建工具
- **Naive UI**：UI 组件库（轻量、适合管理面板）
- **Axios**：HTTP 客户端
- **Vue Router**：路由管理

## 4. 后端核心设计

### 4.1 运行形态
BTCM 的运行形态由请求体中的两个 Agent 启用开关决定：`enable_creative`（创意生成 Agent）与 `enable_validator`（验证 Agent），均默认开启；总控 Agent（controller）恒启用，无开关。四种组合对应四种形态：

| enable_creative | enable_validator | 形态 | 说明 |
|-----------------|-----------------|------|------|
| true | true | 完整循环 | 创意生成-验证-反思循环，直到满足终止条件（默认） |
| true | false | 纯创意 | 只调用创意生成 Agent，生成方案或观点，返回候选列表 |
| false | true | 纯验证 | 只调用验证 Agent，检查已有结论/计划，返回 verdict 及问题报告 |
| false | false | 长链持续思考 | 只调用总控 Agent，多轮自我迭代思考并产出最终结论 |

纯创意与纯验证为单次执行，不进入循环（`iterations_used` 恒为 1，`termination_reason` 恒为 `single_pass`）；设计理念中“反复自思考和自验证”的能力由完整循环与长链持续思考两种形态承担，前者通过创意/验证 Agent 协作，后者由总控 Agent 独立完成。开关的全局默认值可经配置持久化，请求体顶层字段可对当次调用覆盖。

### 4.2 核心 Agent

三个 Agent 的职责相互独立，各自经模型网关路由到独立的提供商与模型（见 4.4），互不绑定同一模型。

#### 4.2.1 创意生成 Agent（Creative Agent）
- **职责**：针对用户问题或给定候选，发散式地生成多个新方案、观点、修正建议。
- **输入**：任务描述、用户问题、当前候选（可选）、上下文摘要。
- **输出**：候选内容列表，每项包含文本与简要理由。
- **特点**：鼓励多样性，可配置生成数量（如 2~5 个）。

#### 4.2.2 验证 Agent（Validator Agent）
- **职责**：对给定候选或结论进行验证，发现逻辑漏洞、事实错误、信息缺口。
- **输入**：任务描述、用户问题、待验证内容、证据列表。
- **输出**：验证报告，包含判定（pass/conditional_pass/fail）、问题列表、改进建议。
- **特点**：支持两种子验证：
  - **逻辑验证**：检查一致性、完备性、推理漏洞。
  - **事实验证**：可选联网搜索（白名单控制），核对事实依据。

#### 4.2.3 总控 Agent（Controller Agent）
- **职责**：兼任调度器、反思器和终止判断器，是 BTCM 的核心大脑；当创意与验证 Agent 均未启用时，独立承担长链持续思考。
- **形态**：由 LLM 管理，但反思过程控制在要点级——提示词与输出只覆盖当轮整合结论、剩余问题、下轮动作（短句要点，不展开长篇推理），单轮反思时长可控。
- **输入**：初始任务、配置参数；长链持续思考形态下为任务与上一轮思考要点。
- **输出**：最终结构化结果，以及每轮循环的中间状态（供日志/前端观察）。
- **功能**：
  - 根据 `enable_creative` / `enable_validator` 开关决定调用哪些 Agent。
  - 管理循环：每轮执行后，基于验证判定判断是否继续；轮次达到 `max_iterations` 即准备返回。
  - 长链持续思考形态下，作为唯一执行者逐轮深化思考：基于任务与上一轮要点输出新一轮思考要点，多轮迭代直至 `max_iterations` 或 `timeout`，最后整合为最终结论。
  - 生成最终结果 JSON。
- **边界**：终止判定仍由机械规则承载（verdict 为 pass / 达到轮数 / 超时），总控反思不引入额外的终止启发式。

### 4.3 主循环流程

```
外部请求 → 接入层解析为 Task 对象
                ↓
        总控 Agent 启动循环
                ↓
   ┌─────────── 循环（最多 max_iterations 轮）───────────┐
   │  创意 Agent（若需要）→ 生成候选集                    │
   │          ↓                                          │
   │  验证 Agent（若需要）→ 验证候选，输出判定与问题      │
   │          ↓                                          │
   │  总控 Agent 反思：                                   │
   │     - 整合结果                                      │
   │     - 判断是否满足终止条件                           │
   │          │                                          │
   │          ├── 是 → 跳出循环                          │
   │          └── 否 → 调整输入，继续下一轮               │
   └──────────────────────────────────────────────────┘
                ↓
        总控 Agent 生成最终结果
                ↓
        接入层封装为标准 JSON 响应
```

**终止条件**（满足任一即可）：
1. 验证 Agent 判定 `pass`（对应 `validation_passed`，仅完整循环形态）
2. 达到 `max_iterations`
3. 达到 `timeout`（秒）

循环终止完全由结构化判定与硬性上限决定，不引入置信度数值或改善趋势等启发式判据，行为可预期。

多候选循环语义：创意 Agent 一次生成多个候选时，验证 Agent 对候选集整体给出判定并指明最优候选；若未通过，下一轮创意 Agent 基于该最优候选与验证问题进行修正，不再重新发散。

**长链持续思考形态**（两个开关均关闭）下流程简化为：总控 Agent 每轮基于任务与上一轮要点输出新的思考要点，逐轮深化；无验证 Agent 参与，故无 `validation_passed` 终止路径，仅由 `max_iterations` 与 `timeout` 决定终止；最终由总控整合所有轮次为最终结论。

### 4.4 配置体系（本体）

配置文件采用 JSON 格式，位于 `btcmodule/btcm.json`，不受版本管理；内置默认配置存在于代码中（Pydantic 模型默认值），首次启动若文件不存在则据此生成。写入采用原子方式（先写临时文件再替换）。

模型管理采用提供商注册表 + 按 Agent 路由（借鉴 DPIM 的 BYOK 模式独立实现）：

- `providers`：注册多个 OpenAI 兼容提供商，各含 `base_url`、`api_key`、`models`（可用模型列表）、`timeout`（可选，单次 LLM 请求超时秒数，默认 120）。
- `agents`：三个 Agent 各自通过 `provider` + `model` 指向注册表条目，可分别使用不同提供商、不同模型。
- Agent 级公共参数：`temperature`（采样温度，creative 默认 0.8，validator/controller 默认 0.3）、`max_tokens`（单次请求最大输出 token 数，creative/validator 默认 2048，controller 默认 1024）、`timeout`（可选，单请求超时，设置后覆盖所属提供商值）；另有各 Agent 专属参数（creative 的 `num_candidates`，validator 的 `enable_web_search`/`web_sources`，controller 的 `log_intermediate`）。
- 参数优先级（从高到低）：请求内 `config`（仅运行时参数） > Agent 级 > 提供商级 > 内置默认值。
- `enable_creative` / `enable_validator`：创意与验证 Agent 启用开关的全局默认值（均默认 true），请求体顶层可对当次调用覆盖；controller 恒启用，无开关。
- `api_key` 仅存于配置文件；`GET /api/config` 返回时省略该字段，不回显。
- 本地模型：Ollama、llama.cpp、LM Studio 等本地推理服务经其 OpenAI 兼容接口接入，无需额外适配；本地推理较慢，建议放宽该提供商的 `timeout`（如 600），并相应调大全局 `timeout`。

示例结构：

```json
{
  "max_iterations": 2,
  "timeout": 300,
  "enable_creative": true,
  "enable_validator": true,
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
  "agents": {
    "creative": {
      "provider": "deepseek",
      "model": "deepseek-chat",
      "num_candidates": 3,
      "temperature": 0.8,
      "max_tokens": 2048
    },
    "validator": {
      "provider": "deepseek",
      "model": "deepseek-reasoner",
      "temperature": 0.3,
      "max_tokens": 2048,
      "timeout": 300,
      "enable_web_search": false,
      "web_sources": ["wikipedia.org", "gov.cn", "edu.cn"]
    },
    "controller": {
      "provider": "deepseek",
      "model": "deepseek-chat",
      "temperature": 0.3,
      "max_tokens": 1024,
      "log_intermediate": true
    }
  }
}
```

模型网关（`core/llm.py`）按 Agent 角色解析提供商配置并缓存客户端，按生效参数（优先级解析后的 temperature、max_tokens、单请求超时）下发每次调用；请求内 `config` 仅可覆盖运行时参数（max_iterations、全局 timeout、候选数、温度、token 上限、单请求超时、联网开关），不可变更模型路由；Agent 启用开关（`enable_creative` / `enable_validator`）为请求体顶层字段，不受 `config` 约束。

### 4.5 API 设计

所有 API 前缀为 `/api`。

#### 4.5.1 调用 BTCM

- **POST** `/api/invoke`

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
  "config": {                            // 可选，覆盖默认配置（仅运行时参数）
    "max_iterations": 2,
    "agents": { "validator": { "enable_web_search": true } }
  }
}
```

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

#### 4.5.2 获取当前配置

- **GET** `/api/config`

返回当前生效的完整配置（JSON，统一外层结构）。

#### 4.5.3 更新配置

- **PUT** `/api/config`

接收部分配置更新，校验通过后持久化到 `btcmodule/btcm.json` 并立即生效。是否需要密码保护列为待定问题，当前版本不实现。

#### 4.5.4 查看调用历史

- **GET** `/api/logs?limit=20`

返回最近的调用记录摘要（不包括完整中间日志）。

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
- 表格展示历史调用记录：时间、运行形态（Agent 启用开关）、请求 ID、结果判定、迭代轮数。
- 支持点击展开查看详细响应。

### 5.2 前端技术细节
- 使用 **Naive UI** 组件库搭建界面。
- API 封装在 `src/api/client.ts`，统一处理请求和错误。
- 路由：`/` 重定向到 Dashboard，`/config` 配置页，`/logs` 日志页。
- 构建命令：`npm run build`，输出到 `btcwebui/build/`，然后复制到 `btcmodule/static/` 供 FastAPI 托管。

## 6. 构成与运行

项目由两部分构成，实现顺序为先本体、后面板：

- **项目本体（btcmodule）**：独立可运行，提供全部 API 功能。
  - 运行：`uvicorn btcmodule.main:app --port 8000`
  - 通过 API 即可完成调用、配置管理与日志查看，不依赖控制面板。
- **控制面板（btcwebui）**：本体功能验证无误后开发。
  - 构建命令：`npm run build`，输出到 `btcwebui/build/`，然后复制到 `btcmodule/static/` 供 FastAPI 托管。
  - 面板就绪后，访问 `http://localhost:8000` 即可同时获得 API 和控制面板，再进行联调。

### 6.1 依赖管理
- 后端：`requirements.txt` 列出 fastapi, uvicorn, pydantic, openai 等。
- 前端：`package.json` 管理依赖，使用 npm。

## 7. 扩展性与后续规划

- **Agent 插件化**：定义 `BaseAgent` 接口，允许注册新的思维单元（如安全审核、情感分析），通过配置启用。
- **思维格式引擎**：未来支持链式、树状、辩论等多种格式，由总控 Agent 选择。
- **WebSocket 实时监控**：在循环过程中推送中间状态，提升控制面板体验。
- **CLI 工具**：提供命令行调用方式，方便测试和脚本集成。

（多提供商多模型路由已在配置体系中支持，不列为扩展项。）

---

该规格文档基于当前讨论的框架，后续可根据具体实现进一步细化。