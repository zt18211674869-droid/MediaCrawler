# 通过怪客 MCP 取数与接收材料

## 取数入口

本页承接已明确的研究目的；关键意图尚待回复时，不用首个业务采集来代替澄清。取数前按 [mcp-connection.md](mcp-connection.md) 检查 guaikei MCP，失败提示联系仓库维护者或 MCP 服务提供方。直接使用宿主实际提供的 guaikei MCP 工具。本 Skill 自包含，不调用其他采集或分析 Skill、CLI、HTTP/API 或外部平台。

确定研究对象与别名、平台、关键词、作品与评论各自的发布时间区间、所需正文/评论/回复/转写、数量、预算、已有来源 ID、输出目录和停止条件。只补实际缺口；已有授权沿用，不为预检增加重复采集。

用户指定数量优先；未指定时，每个明确操作目标为 50 条，搜索/博主作品按篇，评论按条。多平台、多关键词不自动倍增全局预算。显式传入实际 schema 的数量字段，不依赖默认值；记录 target_count、effective_limit 和 returned_count。任务数、HTTP 次数和费用分开；MCP 内部不可观测的次数或金额记 null，不假定一次工具调用等于一次请求或固定费用。

## 小红书独立评论

小红书独立评论的已知业务字段为 url、limit、可选 expired_at。实际工具、必填项、类型和状态以本轮 guaikei MCP schema 为准；历史底层接口不作为可直接调用的入口。

请求 50 条时将数量映射为 `limit: 50`；`expired_at` 是评论时间过滤，不是数量或页码。用户指定近 30 天时才传相应条件，不能擅自加 30 天窗口。若 MCP 要求时间字段必填，按研究范围和工具说明确定值，没有确认的“全部时间”值时不猜 0。创建与查询保持同一组业务参数；MCP 已负责轮询时不再重复创建。

历史发布说明中的套餐上限不代表当前 MCP 或本账户权益。实际权限不支持目标时记录限制并提示联系仓库维护者或 MCP 服务提供方，不重复抓相同结果凑数。详情附带评论与独立评论工具分开，不能把详情 limit 直接当评论数。

其它平台分别核对实际 MCP schema，不复制小红书枚举或上限。历史参数文档不要求在线读取。

## 保存与映射

每次调用保存脱敏参数、请求 ID、实际 MCP 原始输出、起止时间、状态、返回量和缺失项。鉴权信息不进入数据包。异步受理不等于完成；按实际状态与时限等待，处理中不重复创建。没有分页/回复能力时说明覆盖不足，不声称取全。

保存 manifest.json、raw/ 和 items.jsonl。manifest 使用 collection_mode=mcp、provenance_layer=mcp_tool_output，包含研究问题、窗口、工具/schema 来源、mcp_check、任务记录、覆盖、失败和停止原因。

MCP 输出可能是内容块或嵌套 JSON。依据实际 schema 和保存的响应确认字段路径，写明映射后构造 items，不直接假定等于 API data 或 CLI results。raw_ref 必须指向保存的文本字段；JSON 包成字符串时保留完整 MCP 输出，再另存解码 JSON、原内容块路径和派生关系，以解码文件中的指针回查原文。不要改原件或冒称逐次 HTTP 响应。按 [本地 MCP 工具](mcp-local-tools.md) 使用显式字段映射保存和归一化；未知包装明确拒绝，不自动猜字段。任务台账记录预算与恢复状态，但不执行网络。

每行 item 包括 platform/content_id/unit_id/unit_type/title/text/text_kind/author_id/author_name/url/published_at/collected_at/parent_unit_id/metrics/raw_ref。分析映射见 [data-contract.md](data-contract.md)。

- unit_type 为 note/comment/reply/transcript；text_kind 为 full_text/summary/transcript/rewritten/unknown。正文、摘要、标题与视频改写分开；无文本候选计入覆盖但不作为引文。
- ID 保留完整字符串；未知身份不猜造。published_at 未确认则 null，collected_at 记录真实取得时间；指标缺失不补零，保留原值及来源字段指针。
- raw_ref 用相对文件路径和 JSON Pointer 定位原文字符串。未知单位、字段缺失、回复未取全和日期不明分别记录；原文或身份无法确认时先待核，不编造证据。
- 实际取得的评论按评论数组长度核对，回复另计；展示评论总数不等于取回量。用少量真实记录核对每种实际形状，原文与来源匹配后再批量处理。

## 进入分析与增量

材料足够且可回查时继续证据整理、逐行判断、规则冻结、统计、发现与报告流程。部分失败说明范围，不能当成没有相应声音。缺少原始证据时只能做已有报告审计或假设整理，不能反推用户比例。

明确要求离线分析时可直接使用本地材料，保留原件与转换来源，不访问 MCP。补采后只合并真实新增或明确选版的来源，编码后再判断发现增强、削弱或撤回；旧帖首次获取、编辑、互动变化和编码变更分别记录。
