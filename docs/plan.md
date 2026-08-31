# BTCM 整体开发计划

## 1. 项目定位

BTCM（副思考链模块）是可嵌入大型集成 Agent 的辅助思考器官：宿主 Agent 或人工将思考任务委托给它，由内部三个 Agent（创意生成、验证、总控）经“生成-验证-反思”循环处理后返回结构化结果。服务无状态，自带 Web 控制面板，单端口运行，其循环结构可作为思维模块范式移用。

设计原始意图见 docs/设计理念.md；总体设计见 share/spec.md；Agent 设计见 docs/Agents.md；接口契约以 share/protocol.md（alpha，版本号冻结 0.0.0）为唯一权威。

## 2. 当前状态

- 文档：设计理念、规格说明、接口协议已就位（协议 alpha，版本号冻结 0.0.0）。运行形态由 enable_creative / enable_validator 双开关（默认开启）组合定义：完整循环、纯创意、纯验证、长链持续思考；模型管理采用提供商注册表 + 按 Agent 路由。alpha-1：总控 decision 参与终止（controller_stop）且 next_direction 回灌下轮创意；纯创意 conclusion 综合全部候选；验证 Agent 接入 MCP 联网工具（内置预设，可用才调用）；admin_token 鉴权层；全局 timeout 强制执行。alpha-2：invoke 并发上限 4（429 RATE_LIMITED）；data.usage token 计量；verdict=fail 时禁止总控 stop；重试退避；api_key 缺失友好报错；工具输出注入防护；MCP 缓存随配置失效；/api/health；配置与日志加锁；结构化运行日志。前端完成按需分包（naive chunk 1414kB → 最大共享 chunk 233kB）。
- 代码：阶段一、二已完成——btcmodule（FastAPI 本体，含 core/agents/api 与 MCP 客户端）与 btcwebui（Vue3 面板：运行/配置/日志三页，含 MCP 注册表与管理令牌编辑），构建产物托管于 btcmodule/static/，单端口运行。测试 85 项覆盖四形态、终止路径、超时、MCP 配置与工具接入、鉴权、健康检查与 usage 计量。

## 3. 开发阶段

### 阶段一：项目本体（已完成）

目标：btcmodule 独立可运行、功能完整，仅通过 API 即可使用。

- 建立 btcmodule 目录结构与 FastAPI 入口（main.py、api/routes.py）
- Task/Result 数据模型与 JSON 配置加载校验（core/config.py，Pydantic + btcmodule/btcm.json；内置默认值，首次启动生成文件，原子写入）
- 模型网关（core/llm.py）：OpenAI 兼容提供商注册表，按 Agent 路由 provider/model，客户端缓存；提供商级请求超时（默认 120，本地模型放宽），本地服务（Ollama 等）即插即用；api_key 仅存 btcm.json、GET 不回显
- 三个 Agent 实现（agents/）：经模型网关调用，完成提示词与结构化输出解析；总控由 LLM 管理但反思限于要点级（短句要点，不展开长篇推理）；各 Agent 独立 temperature / max_tokens / timeout，按四层优先级解析生效参数；解析失败与单请求超时均按一次重试后降级 fail 处理
- core/loop.py 主循环与终止判定：validation_passed、max_iterations（默认 2）、timeout（默认 300，范围 1~3600）；超时且已完成至少一轮则成功返回 termination_reason=timeout，否则错误 TIMEOUT；四种形态由 enable_creative / enable_validator 双开关组合驱动（均默认开，controller 恒启用）：完整循环（双开）、纯创意、纯验证（candidate 必填，缺失返回 INVALID_REQUEST）、长链持续思考（双关，controller 逐轮深化思考，无 validation_passed 路径）
- 调用日志落盘（JSONL 单文件），GET /api/logs 返回摘要
- 验收：POST /api/invoke 四种形态均返回符合协议的结构（纯创意无验证字段；长链持续思考返回 conclusion 与 intermediate_log）；GET/PUT /api/config 读写并持久化（api_key 不回显，含 enable 开关）；完整循环端到端可用，intermediate_log 可观察每轮状态

### 阶段二：控制面板（已完成）

前提：本体功能验证无误。目标：btcwebui 可视化操作。

- Dashboard：发起测试调用，展示最近调用基本信息与 intermediate_log 每轮摘要
- ConfigPanel：可视化表单编辑 JSON 配置（运行参数、Agent 启用开关、providers/agents 模型路由、mcp_servers 注册表、admin_token；api_key 输入后不回显），保存到后端
- Logs：历史调用记录表格，可展开查看详细响应
- 构建产物复制到 btcmodule/static/

### 阶段三：联调与收尾

- 面板与本体的端到端联调，单端口同时提供 API 与面板
- 补充 README 与运行说明
- 依据实际使用决定推进项：WebSocket 实时推送、Agent 插件化、CLI、验证 Agent 联网搜索落地

## 4. 关键设计决策

- 配置分层与优先级：请求内 config > Agent 级（temperature、max_tokens、timeout 及专属参数）> 提供商级（timeout 等）> 内置默认；全局 timeout 默认 300（1~3600，管整次调用，服务端强制执行），单请求超时默认 120（Agent 级可覆盖），max_tokens 默认 creative/validator 2048、controller 1024；模型路由仅限全局配置。
- 总控形态：承担 meta 职责的全局思维管理者（半个元认识）——总体认识、批判性控制（接受合理发散，批驳怪异与逻辑错乱）、资源意识（要点级输出，以有效 token 为限）；decision=stop 参与终止（controller_stop，优先级低于 validation_passed），next_direction 回灌下轮创意；硬性上限仍由机械规则承载，总控只能提前收敛。
- 多候选循环语义：验证 Agent 对候选集整体判定并指明最优候选；未通过则下轮创意 Agent 基于最优候选、验证问题与总控方向修正，不再重新发散。
- 不使用模型自报置信度，也不设疲乏机制等启发式判据：终止由 validation_passed / controller_stop / max_iterations / timeout / single_pass 承载，行为可预期。
- 运行形态开关：enable_creative / enable_validator 两个布尔开关（默认开启）组合定义运行形态；controller 恒启用，无开关。
- 模型管理：providers 注册表（OpenAI 兼容多提供商）+ agents 按 Agent 路由；api_key 仅存于 btcm.json，GET /api/config 不回显；借鉴 DPIM 的 BYOK 模式独立实现，不照抄。
- MCP 联网工具：轻量自研客户端（httpx + JSON-RPC，单文件，不引 SDK），仅 initialize/tools/list/tools/call 子集；内置市面预设（tavily/exa/deepwiki/fetch）；可用才调用，不可用静默降级纯逻辑验证；工具输出上限 12000 字符，作为验证 Agent 的思考材料从宽保留。
- 响应统一外层结构 {success, data, error, request_id}；data 按运行形态分化。
- 服务无状态，调用历史仅作日志；日志 JSONL 内存镜像 + 5000 条上限裁剪 + 异步写。
- 配置统一用 JSON：运行时配置为 btcmodule/btcm.json，不纳入版本管理；PUT /api/config 校验后原子写入并立即生效；请求内 config 仅可覆盖运行时参数；admin_token 提供可选鉴权层（PUT/reset/logs），密钥类字段一律不回显。
- 不做临时部署流程：本体直接运行，面板构建后由本体托管。

## 5. 待定问题

- 验证 Agent 的事实验证深度：当前经 MCP 工具获取证据后仍由模型判定，是否需要结构化引用与来源置信度展示。
