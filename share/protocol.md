# BTCM 接口协议（Protocol Specification）

**版本**：0.9  
**基础路径**：`/api`  
**协议**：HTTP/HTTPS  
**数据格式**：JSON（UTF-8）  
**无状态**：所有请求独立，服务器不保留客户端会话状态，调用历史仅作为日志存储。

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
| `user_query` | string | 是 | - | 用户问题或任务描述，作为思考的主要输入 |
| `candidate` | string | 否 | null | 待验证或待改进的候选内容；`enable_creative=false` 且 `enable_validator=true`（纯验证形态）时必填，缺失返回 `INVALID_REQUEST`；其他形态可选 |
| `evidence` | array of strings | 否 | [] | 提供给验证 Agent 的参考证据列表，可来自外部知识库/工具 |
| `context_summary` | string | 否 | null | 由主控压缩的上下文摘要，帮助 BTCM 理解背景 |
| `enable_creative` | boolean | 否 | true | 是否启用创意生成 Agent；与 `enable_validator` 组合决定运行形态，见下方形态说明 |
| `enable_validator` | boolean | 否 | true | 是否启用验证 Agent；与 `enable_creative` 组合决定运行形态，见下方形态说明 |
| `config` | object | 否 | null | 覆盖默认配置，见下方配置结构 |

**运行形态**：由 `enable_creative` 与 `enable_validator` 两个开关组合决定，总控 Agent（controller）恒启用：

| enable_creative | enable_validator | 形态 | 说明 |
|-----------------|-----------------|------|------|
| true | true | 完整循环（默认） | 创意生成-验证-反思循环，可多轮迭代，直至通过或达上限 |
| true | false | 纯创意 | 仅创意 Agent 单次生成候选，不进入循环 |
| false | true | 纯验证 | 仅验证 Agent 单次验证 `candidate`，不进入循环 |
| false | false | 长链持续思考 | 仅总控 Agent 多轮持续思考，自行迭代完善并产出最终结论 |

两种纯形态为单次执行（`iterations_used` 恒为 1，`termination_reason` 恒为 `single_pass`）；完整循环与长链持续思考为多轮执行，受 `max_iterations` / `timeout` 约束。

**`config` 对象字段**（可覆盖全局配置，未提供的字段使用默认值；仅接受下列运行时参数，模型与提供商（`providers`/`agents` 的 provider、model）为全局配置，不接受请求内覆盖；`enable_creative` / `enable_validator` 为请求体顶层字段，不受 `config` 约束）：

| 字段 | 类型 | 说明 |
|------|------|------|
| `max_iterations` | integer | 最大循环轮数，范围 1~10，默认 2（仅完整循环与长链持续思考形态生效） |
| `timeout` | integer | 单次调用（含全部循环轮次）超时秒数，范围 1~3600，默认 300 |
| `agents.creative.num_candidates` | integer | 创意 Agent 每轮生成候选数量，范围 1~10，默认 3 |
| `agents.<agent>.temperature` | float | 各 Agent 采样温度，范围 0~2；`<agent>` 可为 creative / validator / controller，默认值分别为 0.8 / 0.3 / 0.3 |
| `agents.<agent>.max_tokens` | integer | 各 Agent 单次请求最大输出 token 数，范围 256~32768；默认值 creative / validator 为 2048，controller 为 1024 |
| `agents.<agent>.timeout` | integer | 各 Agent 单次 LLM 请求超时秒数，范围 1~3600；默认未设置，使用所属提供商的 `timeout` |
| `agents.validator.enable_web_search` | boolean | 是否允许验证 Agent 联网搜索，默认 false |
| `agents.validator.web_sources` | array of strings | 联网搜索白名单域名，默认 `["wikipedia.org", "gov.cn", "edu.cn"]` |

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
      "controller_reflection": {
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
      "controller_reflection": {
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
  "conclusion": "综合各候选的推荐说明，或最优候选的展开",
  "iterations_used": 1,
  "termination_reason": "single_pass"
}
```

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

**`termination_reason` 取值**：

| 取值 | 说明 |
|------|------|
| `validation_passed` | 完整循环中验证 Agent 判定 `pass`，提前结束循环 |
| `max_iterations` | 达到最大循环轮数 |
| `timeout` | 达到超时限制 |
| `single_pass` | 纯形态（纯创意 / 纯验证）单次执行完成 |

#### 2.1.3 错误响应

常见错误码：

| 错误码 | 说明 |
|--------|------|
| `INVALID_REQUEST` | 请求体缺少必要字段或格式错误 |
| `CONFIG_VALIDATION_ERROR` | `config` 中参数超出允许范围或类型错误 |
| `TIMEOUT` | 任务执行超时 |
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
        "max_tokens": 1024,
        "log_intermediate": true
      }
    }
  }
}
```

**说明**：

- `enable_creative` / `enable_validator` 为 Agent 启用开关的全局默认值，请求体顶层字段可对当次调用覆盖；总控 Agent（controller）恒启用，无开关。
- `providers` 为 OpenAI 兼容提供商注册表，各 Agent 通过 `provider` + `model` 指向其一，可分别使用不同提供商与模型。
- 提供商字段：`base_url`（必填）、`models`（该提供商可用模型列表）、`timeout`（可选，单次 LLM 请求超时秒数，默认 120）。本地推理服务（Ollama、llama.cpp、LM Studio 等）同样经 OpenAI 兼容接口接入，推理较慢，建议按需放宽 `timeout`（如 600）；本地服务无需鉴权，`api_key` 可省略或填任意占位值。
- `providers.<name>.api_key` 仅在 `PUT /api/config` 时写入，`GET /api/config` 不回显该字段。

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

只需提供需要更新的字段，未提供的字段保持不变。提供商与 Agent 路由可整体或局部更新；`providers.<name>` 的部分更新按字段合并。

#### 2.3.2 响应体

返回更新后的完整配置，结构同 `GET /api/config`。

**错误**：若配置校验失败，返回 `CONFIG_VALIDATION_ERROR`。

---

### 2.4 获取调用历史

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
        "user_query": "下周去东京，预算 5000，能去哪些地方？"
      }
    ]
  }
}
```

`verdict` 在纯创意与长链持续思考形态的记录中为 null。

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
- `providers.<name>.api_key` 仅通过 `PUT /api/config` 写入，任何读取接口不回显。

---

## 4. 超时与中断

- 超时分为三层，各司其职：
  - **全局 `timeout`**（默认 300 秒）：单次调用（含全部循环轮次）的总时长限制。
  - **Agent 级 `agents.<name>.timeout`**（可选）：该 Agent 单次 LLM 请求超时，设置后覆盖提供商值。
  - **提供商级 `providers.<name>.timeout`**（默认 120 秒）：该提供商下单次 LLM 请求超时，Agent 级未设置时生效。
- 达到全局超时后：若已至少完成一轮迭代（有可用的结果——完整循环中为验证判定，长链持续思考中为本轮思考要点），返回成功响应并置 `termination_reason` 为 `timeout`；若一轮都未完成（无可返回的结果），返回错误 `TIMEOUT`。
- 单次 LLM 请求超时视为该请求失败，触发一次重试，仍失败则该轮降级为 `fail` 判定（与输出解析失败同路径处理）。
- 使用本地模型时应保证 全局 timeout ≥ 单请求 timeout × 预计请求数，否则调用会在模型完成前被整体掐断。

---

## 5. 未来扩展预留

- **WebSocket**：用于实时推送循环中间状态，计划在后续版本通过 `/api/ws` 提供。
- **自定义 Agent 插件**：内部架构支持插件化，但对外协议无需变化，只需通过配置文件启用即可。

---

## 6. 变更记录

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