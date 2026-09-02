# BTCM 接口协议（Protocol Specification）

**版本**：0.0.0（alpha）  
**基础路径**：`/api`  
**协议**：HTTP/HTTPS  
**数据格式**：JSON（UTF-8）  
**无状态**：所有请求独立，服务器不保留客户端会话状态，调用历史仅作为日志存储。

> 项目整体处于 alpha 搭建验证阶段，版本号冻结为 0.0.0，直至作者发布升级指令；下方变更记录按迭代顺序保留。

---

## 1. 通用约定

### 1.1 请求头
| 头字段 | 说明 |
|--------|------|
| `Content-Type` | 必须为 `application/json`（GET 请求可省略） |
| `Accept` | 必须为 `application/json` |

### 1.2 时间格式
所有时间字段使用 ISO 8601 格式，例如：`2025-01-01T12:00:00Z`。

### 1.3 通用响应结构
所有 API 响应均使用以下外层结构：

```json
{
  "success": true,
  "data": { ... },          // 业务数据（不同端点不同）
  "error": null,            // 错误信息，仅在 success=false 时存在
  "request_id": "uuid"      // 本次请求的唯一 ID（来自请求体，或服务端生成）
}
```

**错误响应**：

```json
{
  "success": false,
  "data": null,
  "error": {
    "code": "INVALID_REQUEST",
    "message": "请求体缺少必要字段：user_query",
    "details": { ... }      // 可选，附加信息
  },
  "request_id": "uuid"
}
```

---

## 2. 端点定义

### 2.1 调用 BTCM

**端点**：`POST /api/invoke`

**功能**：向 BTCM 提交一个思考任务，触发内部 Agent 循环，返回结构化结果。

#### 2.1.1 请求体

```json
{
  "request_id": "optional-uuid",
  "user_query": "下周去东京，预算 5000，能去哪些地方？",
  "candidate": "建议去浅草、秋叶原、台场，住胶囊旅馆。",
  "evidence": [
    "下周东京天气以晴为主。",
    "浅草、秋叶原、台场为免费或低成本景点。"
  ],
  "context_summary": "用户预算 5000 元，机票未计算在内。",
  "enable_creative": true,
  "enable_validator": true,
  "config": {
    "max_iterations": 2,
    "agents": {
      "validator": {
        "enable_web_search": true
      }
    }
  }
}
```

**字段说明**：

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `request_id` | string (uuid) | 否 | 服务端生成 | 客户端追踪 ID，若不提供则服务端生成并返回 |
| `user_query` | string | 是 | - | 用户问题或任务描述，作为思考的主要输入；长度上限 20000 字符 |
| `candidate` | string | 否 | null | 待验证或待改进的候选内容；`enable_creative=false` 且 `enable_validator=true`（纯验证形态）时必填，缺失返回 `INVALID_REQUEST`；其他形态可选；长度上限 20000 字符 |
| `evidence` | array of strings | 否 | [] | 提供给验证 Agent 的参考证据列表，可来自外部知识库/工具；最多 100 条，每条上限 20000 字符 |
| `context_summary` | string | 否 | null | 由主控压缩的上下文摘要，帮助 BTCM 理解背景；长度上限 300000 字符（大上下文直传，不压缩） |
| `enable_creative` | boolean | 否 | true | 是否启用创意生成 Agent；与 `enable_validator` 组合决定运行形态，见下方形态说明 |
| `enable_validator` | boolean | 否 | true | 是否启用验证 Agent；与 `enable_creative` 组合决定运行形态，见下方形态说明 |
| `config` | object | 否 | null | 覆盖默认配置，见下方配置结构 |

**运行形态**：由 `enable_creative` 与 `enable_validator` 两个开关组合决定，总控类 Agent（controller / meta）恒启用，无开关：

| enable_creative | enable_validator | 形态 | 说明 |
|-----------------|-----------------|------|------|
| true | true | 完整循环（默认） | 创意生成-验证-反思循环，可多轮迭代，直至通过或达上限 |
| true | false | 纯创意 | 仅创意 Agent 单次生成候选，不进入循环 |
| false | true | 纯验证 | 仅验证 Agent 单次验证 `candidate`，不进入循环 |
| false | false | 长链持续思考 | 仅 controller 多轮持续思考，自行迭代完善并产出最终结论 |

两种纯形态为单次执行（`iterations_used` 恒为 1，`termination_reason` 恒为 `single_pass`）；完整循环与长链持续思考为多轮执行，受 `max_iterations` / `timeout` 约束。

**`config` 对象字段**（可覆盖全局配置，未提供的字段使用默认值；仅接受下列运行时参数，模型与提供商（`providers`/`agents` 的 provider、model）为全局配置，不接受请求内覆盖；`enable_creative` / `enable_validator` 为请求体顶层字段，不受 `config` 约束）：

| 字段 | 类型 | 说明 |
|------|------|------|
| `max_iterations` | integer | 最大循环轮数，范围 1~10，默认 2（仅完整循环与长链持续思考形态生效） |
| `timeout` | integer | 单次调用（含全部循环轮次）超时秒数，范围 1~3600，默认 300 |
| `agents.creative.num_candidates` | integer | 创意 Agent 每轮生成候选数量，范围 1~10，默认 3 |
| `agents.<agent>.temperature` | float | 各 Agent 采样温度，范围 0~2；`<agent>` 可为 creative / validator / controller / meta，默认值分别为 0.8 / 0.3 / 0.3 / 0.3 |
| `agents.<agent>.max_tokens` | integer | 各 Agent 单次请求最大输出 token 数，范围 256~32768；默认值 creative / validator 为 2048，controller / meta 为 1024 |
| `agents.<agent>.timeout` | integer | 各 Agent 单次 LLM 请求超时秒数，范围 1~3600；默认未设置，使用所属提供商的 `timeout` |
| `agents.validator.enable_web_search` | boolean | 是否允许验证 Agent 使用联网工具（MCP），默认 false |
| `agents.validator.web_sources` | array of strings | 联网验证期望的权威域名（提示词参考），默认 `["wikipedia.org", "gov.cn", "edu.cn"]` |
| `agents.validator.mcp_servers` | array of strings | 验证 Agent 可用的 MCP 服务器名列表，引用 `mcp_servers` 注册表条目 |

**MCP 联网工具**：`enable_web_search=true` 且 `mcp_servers` 非空时，验证 Agent 经 OpenAI function calling 调用 MCP 工具获取外部事实。工具"可用才调用"：连接失败、握手失败或超时的服务器被跳过，当次退回纯逻辑验证，不报错。内置市面 MCP 预设（`tavily` / `exa` / `deepwiki` / `fetch`），经全局配置的 `mcp_servers` 注册表启用（详见 2.2/2.3）。

#### 2.1.2 响应体

`data` 字段按运行形态分化。验证相关字段（`verdict` 等）仅出现在含验证环节的形态（完整循环、纯验证）中；纯创意形态无验证概念，返回候选列表；长链持续思考形态仅返回总控的思考结论与过程。

**完整循环（enable_creative=true、enable_validator=true）** 的 `data` 字段：

```json
{
  "verdict": "conditional_pass",
  "conclusion": "建议去浅草、秋叶原、台场，但需先确认机票是否包含在预算内。",
  "issues": [
    "预算中未包含机票，需确认用户是否为往返总预算",
    "胶囊旅馆不适合行李较多或睡眠敏感的用户"
  ],
  "suggestions": [
    "先确认机票是否已单独支付",
    "增加一个低成本住宿备选，如青年旅舍单人间"
  ],
  "next_actions": [
    "补充询问机票与住宿偏好"
  ],
  "iterations_used": 2,
  "termination_reason": "max_iterations",
  "intermediate_log": [
    {
      "iteration": 1,
      "creative_output": ["候选1", "候选2"],
      "validator_output": {
        "verdict": "fail",
        "issues": ["问题1"]
      },
      "meta_reflection": {
        "decision": "continue"
      }
    },
    {
      "iteration": 2,
      "creative_output": ["修正候选"],
      "validator_output": {
        "verdict": "conditional_pass",
        "issues": ["仍存在轻微问题"]
      },
      "meta_reflection": {
        "decision": "stop"
      }
    }
  ]
}
```

**纯验证（enable_creative=false、enable_validator=true）**：字段同完整循环（`iterations_used` 恒为 1，`termination_reason` 恒为 `single_pass`），无 `intermediate_log` 循环记录。

**纯创意（enable_creative=true、enable_validator=false）** 的 `data` 字段：

```json
{
  "candidates": [
    "候选方案1（含简要理由）",
    "候选方案2（含简要理由）",
    "候选方案3（含简要理由）"
  ],
  "conclusion": "创意 Agent 综合全部候选给出的推荐说明（概括各候选取舍，不偏向单一候选）",
  "iterations_used": 1,
  "termination_reason": "single_pass"
}
```

`conclusion` 由创意 Agent 在同一次调用中给出，候选数量不限（`num_candidates` 可调）；若模型未输出该字段，回退为全部候选的串联。

**长链持续思考（enable_creative=false、enable_validator=false）** 的 `data` 字段：

```json
{
  "conclusion": "经过多轮持续思考、自我完善后的最终结论",
  "iterations_used": 3,
  "termination_reason": "max_iterations",
  "intermediate_log": [
    {
      "iteration": 1,
      "thought": "第一轮思考要点"
    },
    {
      "iteration": 2,
      "thought": "第二轮思考要点"
    },
    {
      "iteration": 3,
      "thought": "第三轮思考要点"
    }
  ]
}
```

**字段说明**：

| 字段 | 类型 | 适用形态 | 说明 |
|------|------|----------|------|
| `verdict` | string | 纯验证、完整循环 | 最终判定，可选值：`pass`（通过）、`conditional_pass`（有条件通过）、`fail`（不通过） |
| `candidates` | array of strings | 纯创意 | 生成的候选内容列表 |
| `conclusion` | string | 全部 | 最终结论：完整循环为修正后的候选，纯验证为验证结论，纯创意为综合推荐，长链持续思考为最终思考结果 |
| `issues` | array of strings | 纯验证、完整循环 | 发现的问题列表，可能为空 |
| `suggestions` | array of strings | 纯验证、完整循环 | 改进建议列表，可能为空 |
| `next_actions` | array of strings | 纯验证、完整循环 | 建议的下一步行动，供主控参考 |
| `iterations_used` | integer | 全部 | 实际执行轮数（纯形态恒为 1） |
| `termination_reason` | string | 全部 | 终止原因，见下方说明 |
| `intermediate_log` | array of objects | 完整循环、长链持续思考 | 每轮循环的中间摘要（完整循环若配置 `log_intermediate: true`，长链持续思考恒记录），否则可能省略或为 null |
| `usage` | object | 全部（可选） | 本次调用 LLM 计量：`prompt_tokens` / `completion_tokens` / `llm_calls` / `tool_calls`；发生至少一次 LLM 调用时返回 |

**`termination_reason` 取值**：

| 取值 | 说明 |
|------|------|
| `validation_passed` | 完整循环中验证 Agent 判定 `pass`，提前结束循环 |
| `controller_stop` | 完整循环中 meta Agent 反思判定 `decision=stop`（结论可用或继续修正边际收益过低），提前结束循环；判定优先级低于 `validation_passed` |
| `max_iterations` | 达到最大循环轮数 |
| `timeout` | 达到超时限制 |
| `single_pass` | 纯形态（纯创意 / 纯验证）单次执行完成 |

**meta 反思的实效**：完整循环中，meta Agent 的 `decision` 参与终止判定（见上表；`verdict=fail` 时 `decision=stop` 无效，循环强制继续，验证判定存在严重问题不得提前定稿）；未终止时其 `next_direction` 作为下轮创意 Agent 的修正方向输入（不重新发散）；`intermediate_log` 各轮的 `meta_reflection` 含 `decision` 与 `next_direction`。响应 `verdict` 恒为验证 Agent 的原判，不因 `controller_stop` 改写。

#### 2.1.3 错误响应

常见错误码：

| 错误码 | 说明 |
|--------|------|
| `INVALID_REQUEST` | 请求体缺少必要字段或格式错误 |
| `CONFIG_VALIDATION_ERROR` | `config` 中参数超出允许范围或类型错误 |
| `TIMEOUT` | 任务执行超时 |
| `RATE_LIMITED` | 并发调用达到上限（默认 4），稍后重试（HTTP 429） |
| `UNAUTHORIZED` | 受保护端点缺少或错误的管理令牌（HTTP 401） |
| `PROVIDER_ERROR` | 拉取模型列表时上游提供商请求失败（HTTP 502，仅 `/api/providers/{name}/models`） |
| `INTERNAL_ERROR` | 服务器内部异常 |

---

### 2.2 获取当前配置

**端点**：`GET /api/config`

**功能**：返回 BTCM 当前生效的完整配置。

#### 2.2.1 响应体

```json
{
  "success": true,
  "data": {
    "max_iterations": 2,
    "timeout": 300,
    "enable_creative": true,
    "enable_validator": true,
    "providers": {
      "deepseek": {
        "base_url": "https://api.deepseek.com/v1",
        "models": ["deepseek-chat", "deepseek-reasoner"]
      },
      "ollama-local": {
        "base_url": "http://localhost:11434/v1",
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
        "max_tokens": 1024
      },
      "meta": {
        "provider": "deepseek",
        "model": "deepseek-chat",
        "temperature": 0.3,
        "max_tokens": 1024,
        "log_intermediate": true
      }
    }
  }
}
```

**说明**：

- `enable_creative` / `enable_validator` 为 Agent 启用开关的全局默认值，请求体顶层字段可对当次调用覆盖；总控类 Agent（controller / meta）恒启用，无开关。
- `providers` 为 OpenAI 兼容提供商注册表，各 Agent 通过 `provider` + `model` 指向其一，可分别使用不同提供商与模型。
- `mcp_servers` 为 MCP 服务器注册表（验证 Agent 联网工具），条目字段：`preset`（内置预设名，可选）或 `url`（直接给出 Streamable HTTP 端点）、`api_key`（预设需要密钥时填写）、`enabled`（默认 true）、`timeout`（单请求超时秒数，默认 60）、`allowed_tools`（工具白名单，留空 = 全部）、`allow_private`（默认 false，指向内网/回环地址时需显式放行）。Agent 经 `agents.validator.mcp_servers` 引用条目名。
- 提供商字段：`base_url`（必填，仅接受 `http` / `https` scheme 且必须含主机名，如 `https://api.deepseek.com/v1`、`http://localhost:11434/v1`；`ftp://` 或缺 scheme 等无效地址返回 400 `CONFIG_VALIDATION_ERROR`。本地地址合法，不受 MCP 那套私网限制）、`models`（该提供商可用模型列表）、`timeout`（可选，单次 LLM 请求超时秒数，默认 120）。本地推理服务（Ollama、llama.cpp、LM Studio 等）同样经 OpenAI 兼容接口接入，推理较慢，建议按需放宽 `timeout`（如 600）；本地服务无需鉴权，`api_key` 可省略或填任意占位值。
- `providers.<name>.api_key`、`mcp_servers.<name>.api_key` 与 `admin_token` 仅在 `PUT /api/config` 时写入，`GET /api/config` 不回显这些字段；但回显只读布尔：`providers.<name>.api_key_set`、`mcp_servers.<name>.api_key_set` 与顶层 `admin_token_set`（环境变量注入的密钥亦计为已设置），供控制面板展示 BYOK 配置状态。

---

### 2.3 更新配置

**端点**：`PUT /api/config`

**功能**：更新 BTCM 配置（可部分更新），新配置立即生效并持久化到文件。

#### 2.3.1 请求体

```json
{
  "max_iterations": 5,
  "enable_validator": false,
  "providers": {
    "deepseek": {
      "api_key": "sk-..."
    }
  },
  "agents": {
    "validator": {
      "provider": "deepseek",
      "model": "deepseek-reasoner"
    }
  }
}
```

只需提供需要更新的字段，未提供的字段保持不变。提供商与 Agent 路由可整体或局部更新；`providers.<name>` 与 `mcp_servers.<name>` 的部分更新按字段合并。

**删除语义（JSON Merge Patch / RFC 7386）**：值为 `null` 的键表示删除该键。移除注册表条目必须显式发送 `null`——如 `{"providers": {"old-name": null}}`、`{"mcp_servers": {"old-name": null}}`；**仅在 payload 中省略该条目不会删除它**（深合并会保留旧值）。同一规则下 `{"admin_token": null}` 清除令牌，`{"agents": {"creative": {"provider": null, "model": null}}}` 让该 Agent 回退为跟随全局默认。删除后仍执行整体校验：若仍有 Agent 引用被删的提供商，返回 400 `CONFIG_VALIDATION_ERROR`。

**鉴权**：配置 `admin_token` 后，`PUT /api/config`、`POST /api/config/reset` 与 `GET /api/logs` 要求请求头 `X-Admin-Token` 携带该令牌，缺失或错误返回 401 `UNAUTHORIZED`；`POST /api/invoke` 与 `GET /api/config` 恒为开放端点（响应不含任何密钥）。`admin_token` 本身仅可写入、不回显，丢失后只能直接编辑 `btcm.json` 或经 `POST /api/config/reset` 重置（重置同样需要令牌）。

- **`lock_invoke`**（默认 false）：配置 `lock_invoke=true` 后，`POST /api/invoke` 也要求 `X-Admin-Token`（用于开放到局域网时保护付费模型调用）。
- **密钥环境变量注入**：`admin_token` 与各 `api_key` 可经环境变量提供，优先级高于配置文件，绝不回写 `btcm.json`、绝不经任何读取接口回显：`BTCM_ADMIN_TOKEN`、`BTCM_PROVIDER_<NAME>_API_KEY`、`BTCM_MCP_<NAME>_API_KEY`（`<NAME>` 为 provider / MCP 服务器名，非字母数字字符转 `_`）。

#### 2.3.2 响应体

返回更新后的完整配置，结构同 `GET /api/config`。

**错误**：若配置校验失败，返回 `CONFIG_VALIDATION_ERROR`。

---

### 2.4 重置配置为默认

**端点**：`POST /api/config/reset`

**功能**：将配置重置为内置默认值（DeepSeek + 本地 Ollama 示例路由、双开形态、全部 Agent 定义），立即生效并持久化。

#### 2.4.1 请求体

无。

#### 2.4.2 响应体

返回重置后的完整配置，结构同 `GET /api/config`。

**错误**：若重置写入失败，返回 `INTERNAL_ERROR`。

> 供控制面板"重置为默认"按钮调用；API 调用方也可直接使用深度合并部分更新达到相同效果。

---

### 2.5 获取调用历史

**端点**：`GET /api/logs?limit=20&offset=0`

**功能**：获取最近的调用记录摘要，用于控制面板展示。

**查询参数**：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `limit` | integer | 否 | 20 | 返回记录数，最大 100 |
| `offset` | integer | 否 | 0 | 偏移量，用于分页 |

**响应体**：

```json
{
  "success": true,
  "data": {
    "total": 42,
    "items": [
      {
        "request_id": "uuid",
        "timestamp": "2025-01-01T12:00:00Z",
        "enable_creative": true,
        "enable_validator": true,
        "verdict": "conditional_pass",
        "iterations_used": 2,
        "termination_reason": "max_iterations",
        "user_query": "下周去东京，预算 5000，能去哪些地方？",
        "duration_ms": 52300,
        "conclusion": "……",
        "error": null,
        "usage": {"prompt_tokens": 12000, "completion_tokens": 3400, "llm_calls": 6, "tool_calls": 2}
      }
    ]
  }
}
```

`verdict` 在纯创意与长链持续思考形态的记录中为 null；`conclusion` 仅成功记录携带；`error` 为该次调用的错误码（成功为 null）；`usage` 与响应 `data.usage` 同构，未发生 LLM 调用（如被拒请求）时为 null。

---

### 2.6 健康检查

**端点**：`GET /api/health`

**功能**：探活端点，供宿主 Agent 与运维检查；恒开放、无需鉴权、不含敏感信息。

**响应体**：

```json
{
  "success": true,
  "data": {
    "status": "ok",
    "version": "0.0.0",
    "uptime_s": 3600
  },
  "error": null,
  "request_id": "uuid"
}
```

---

### 2.7 拉取提供商模型列表

**端点**：`GET /api/providers/{name}/models`

**功能**：代理访问 OpenAI 兼容提供商的 `GET /models`，返回其可用模型列表，供控制面板 BYOK 配置时填充 `providers.<name>.models`。密钥解析与调用一致（环境变量 `BTCM_PROVIDER_<NAME>_API_KEY` 优先），超时取该提供商的 `timeout`。

**鉴权**：设置 `admin_token` 后需 `X-Admin-Token`（该端点会触发一次对外请求，与写配置同级保护）。

**响应体**：

```json
{
  "success": true,
  "data": {
    "models": ["deepseek-chat", "deepseek-reasoner"]
  },
  "error": null,
  "request_id": "uuid"
}
```

**错误**：提供商不存在返回 `NOT_FOUND`（404）；上游请求失败（网络、鉴权、超时）返回 `PROVIDER_ERROR`（502），message 面向使用者可读。

---

## 3. 配置覆盖规则

- 参数分层与优先级（从高到低）：
  1. 请求内 `config`（仅可覆盖运行时参数，见 2.1.1）
  2. Agent 级参数（`agents.<name>` 的 temperature、max_tokens、timeout 及各 Agent 专属参数）
  3. 提供商级参数（`providers.<name>` 的 timeout 等）
  4. 内置默认值
- Agent 级 `timeout` 未设置时，使用所属提供商的 `timeout`；提供商也未设置时，使用默认值 120。
- 模型与提供商路由（`agents.<name>` 的 provider、model）为全局配置，不接受请求内覆盖。
- `enable_creative` / `enable_validator` 的全局默认值通过 `PUT /api/config` 持久化；请求体顶层同名开关仅对当次调用有效，未提供时使用全局默认值。
- 请求体中的 `config` 字段仅对当次调用有效，不会持久化。
- 服务端启动时加载配置文件 `btcmodule/btcm.json`；该文件不受版本管理，首次启动若不存在，则由内置默认配置生成。
- `PUT /api/config` 更新会写入该配置文件（原子写入），并立即生效。
- 若请求中未提供 `config`，则完全使用全局配置。
- `providers.<name>.api_key`、`mcp_servers.<name>.api_key` 与 `admin_token` 仅通过 `PUT /api/config` 写入，任何读取接口不回显。

---

## 4. 超时与中断

- 超时分为三层，各司其职：
  - **全局 `timeout`**（默认 300 秒）：单次调用（含全部循环轮次）的总时长限制。
  - **Agent 级 `agents.<name>.timeout`**（可选）：该 Agent 单次 LLM 请求超时，设置后覆盖提供商值。
  - **提供商级 `providers.<name>.timeout`**（默认 120 秒）：该提供商下单次 LLM 请求超时，Agent 级未设置时生效。
- 全局 `timeout` 由服务端强制执行（对整次调用计时，超时即掐断进行中的 LLM 请求）：若已至少完成一轮迭代（有可用的结果——完整循环中为验证判定，长链持续思考中为本轮思考要点），返回成功响应并置 `termination_reason` 为 `timeout`；若一轮都未完成（无可返回的结果），返回错误 `TIMEOUT`。
- 单次 LLM 请求超时视为该请求失败，触发一次重试，仍失败则该轮降级为 `fail` 判定（与输出解析失败同路径处理）。
- 使用本地模型时应保证 全局 timeout ≥ 单请求 timeout × 预计请求数，否则调用会在模型完成前被整体掐断。

---

## 5. 未来扩展预留

- **WebSocket**：用于实时推送循环中间状态，计划在后续版本通过 `/api/ws` 提供。
- **自定义 Agent 插件**：内部架构支持插件化，但对外协议无需变化，只需通过配置文件启用即可。

---

## 6. 变更记录

- alpha-5（2026-09-02，内部迭代）：`PUT /api/config` 深度合并改为遵循 JSON Merge Patch（RFC 7386）语义——值为 `null` 的键表示删除，修复注册表条目无法删除的缺陷（此前仅在 payload 中省略 `providers.<name>` / `mcp_servers.<name>` 会被旧配置深合并复活，控制面板删除后服务端仍保留）；`providers.<name>.base_url` 新增 scheme 校验（仅 `http` / `https` 且必须含主机名，此前 `ftp://`、缺 scheme 等无效地址被静默接受，直到实际调用才报错）；控制面板新增提供商时前置校验 `base_url`、未保存条目显示「未保存」标记，对未保存提供商点击「拉取模型」改为引导「保存并拉取」，不再直接返回 404「提供商不存在」。
- alpha-4（2026-08-31，内部迭代）：`GET /api/config` 回显只读布尔 `providers.<name>.api_key_set` / `mcp_servers.<name>.api_key_set` / 顶层 `admin_token_set`（不回显密钥内容，环境变量注入亦计入）；新增 `GET /api/providers/{name}/models` 模型发现端点（代理 OpenAI 兼容 `GET /models`，填充 `providers.<name>.models`；admin_token 设置时需 `X-Admin-Token`，新增 502 `PROVIDER_ERROR` 与 404 `NOT_FOUND` 错误路径）。
- alpha-3（2026-08-31，内部迭代）：总控 Agent 拆分为 controller（长链思考产成者）与新增的 meta Agent（完整循环的检查与管理，输出 decision / next_direction，`log_intermediate` 归属 meta）；`intermediate_log` 键名由 `controller_reflection` 改为 `meta_reflection`；新增输入护栏（user_query / candidate ≤20000 字符，context_summary ≤300000 字符，evidence ≤100 条 × ≤20000 字符）；新增 `lock_invoke` 开关（默认 false，开启后 invoke 需 `X-Admin-Token`）；密钥支持环境变量注入（`BTCM_ADMIN_TOKEN` / `BTCM_PROVIDER_<NAME>_API_KEY` / `BTCM_MCP_<NAME>_API_KEY`，优先于配置文件、不回写不回显）；MCP 服务器新增 `allow_private`（默认 false）与仅允许 http/https scheme 的校验；生产环境抬升 httpx 日志级别以防请求 URL 泄漏密钥。
- alpha-2（2026-08-30，内部迭代）：`/api/invoke` 加并发上限（默认 4，满载立即 429 `RATE_LIMITED`，不排队）；响应 `data` 新增可选 `usage` 计量（prompt/completion tokens、llm_calls、tool_calls）并同步进调用日志；完整循环中 `verdict=fail` 时总控 `decision=stop` 无效（不得定稿失败）；LLM 失败重试加 0.5s 退避；非本地提供商缺 api_key 时直接返回可操作错误；MCP 工具输出加注入防护包裹（资料非指令）；MCP 连接缓存随配置变更失效；新增 `GET /api/health` 探活端点；配置更新与日志写入加锁串行化；调用日志加上限裁剪与异步写；新增结构化运行日志（btcmodule.* logger）。
- alpha-1（2026-08-28，内部迭代，原文记 1.0）：总控 Agent 实权化——反思 `decision` 参与终止判定（新增 `controller_stop`，优先级低于 `validation_passed`），`next_direction` 回灌下轮创意输入并在 `intermediate_log` 中输出；纯创意 `conclusion` 改为创意 Agent 综合全部候选给出（缺失回退候选串联），不再取首个候选；验证 Agent 接入 MCP 联网工具（`mcp_servers` 注册表 + 内置预设 tavily/exa/deepwiki/fetch，可用才调用，不可用降级纯逻辑验证），`enable_web_search` 语义变为工具总开关；新增 `admin_token`（仅写不回显，PUT/reset/logs 端点要求 `X-Admin-Token`，新增 401 `UNAUTHORIZED`）；全局 `timeout` 改为强制执行（掐断进行中调用）；调用日志加上限裁剪与异步写。
- 0.9（2026-08-23）：移除 `mode` 字段与全局 `modes` 开关，改为请求体顶层 `enable_creative` / `enable_validator` 两个布尔开关（默认 true），由组合定义运行形态：均开=完整循环（原 hybrid）、仅创意=纯创意、仅验证=纯验证、均关=长链持续思考（新增，仅 controller 多轮自我迭代）；总控 Agent 恒启用，删除 `MODE_DISABLED` / `INVALID_MODE` 错误码；`termination_reason` 的 `single_pass` 适用范围改为纯创意/纯验证；`GET/PUT /api/config` 增加开关字段。
- 0.8（2026-08-23）：新增 Agent 级公共参数 temperature（creative 默认 0.8，validator/controller 默认 0.3）、max_tokens（creative/validator 默认 2048，controller 默认 1024）、timeout（可选，覆盖所属提供商单请求超时）；确立配置四层优先级（请求内 config > Agent 级 > 提供商级 > 内置默认）；请求内 config 可覆盖项扩展至温度、token 上限、单请求超时；明确单次 LLM 请求超时按"一次重试后降级 fail"处理。
- 0.7（2026-08-23）：全局 `timeout` 范围由 1~300 放宽为 1~3600、默认 60 改为 300（本地模型多轮循环所需）；`max_iterations` 默认 3 改为 2；`pure_validation` 模式下 `candidate` 必填，缺失返回 INVALID_REQUEST；明确超时的成功/错误路径（完成至少一轮则成功返回 termination_reason=timeout，否则错误 TIMEOUT）。
- 0.6（2026-08-23）：提供商条目新增可选 `timeout`（单次 LLM 请求超时，默认 120），明确本地推理服务（Ollama 等）经 OpenAI 兼容接口接入及超时配置建议；移除 X-Request-ID 请求头（与请求体 request_id 重复，仅保留后者）。
- 0.5（2026-08-23）：移除疲乏机制（no_improvement）与 user_abort 预留值，终止原因仅剩 validation_passed / max_iterations / timeout / single_pass；新增 modes 开关（两种纯模式可全局启停，关闭返回 MODE_DISABLED）；模型配置重构为 providers 注册表（OpenAI 兼容多提供商）+ agents 按 Agent 路由 provider/model，api_key 不回显；移除 output.fields 冗余配置。
- 0.4（2026-08-23）：配置文件更名为 `btcmodule/btcm.json`，移入 btcmodule 目录根部，不纳入版本管理；明确首次启动由内置默认配置生成。
- 0.3（2026-08-23）：移除 confidence 与 has_error 字段（模型自报置信度不可靠，verdict 已承载判定语义）；终止判定改为基于 verdict，`confidence_reached` 更名为 `validation_passed`；响应 `data` 按模式分化，`pure_creative` 返回 `candidates` 且不含验证字段；配置文件由 YAML 改为 JSON。
- 0.2（2026-08-23）：明确纯模式单次执行语义；`termination_reason` 增加 `single_pass`，标注 `user_abort` 为预留值并解释 `no_improvement` 的疲乏机制含义；补充本节。
- 0.1：初稿（依据设计理念由 Deepseek 专家模式生成）。

---

该协议文档为 BTCM 模块的对外接口标准，实现时请以此为准。后续修改需同步更新版本号。