# MCP 响应归一化与本地采集台账

本 skill 的唯一外部调用是宿主提供的 guaikei MCP。本页两个标准库脚本只处理本地文件、计算哈希及记录状态，不访问网络、不读取密钥、不安装环境，也不调用其它 skill 或平台。

## 何时使用

- MCP 返回结构已经核对，需要把保存的输出稳定转换为统一输入时，使用 normalize_mcp.py。
- 有多个采集任务、异步处理或需要中断恢复时，使用 collection_ledger.py。
- 已有合格的 items/manifest 可以直接复用；纯离线分析不要求建立在线采集台账。

## 显式映射，保留原件

先保存宿主实际返回的 MCP 输出为 JSON。检查实际工具 schema、真实业务字段及少量记录，再编写映射；不从名称猜测正文、发布日期、评论总数或转写性质。

以下只说明格式，使用了合成的 MCP 包装，不代表线上已验证的返回结构：

```json
{
  "schema_version": "mcp-mapping-v1",
  "provider": "guaikei",
  "run_id": "本轮稳定ID",
  "mapping_version": "本轮映射版本",
  "mapping_basis": "实际工具schema及本地响应的核对依据",
  "collected_at": "实际取得响应的带时区时间",
  "payload": {"pointer": "/content/0/text", "decode_json": true},
  "records_pointer": "/notes",
  "fields": {
    "platform": {"literal": "xiaohongshu"},
    "content_id": {"pointer": "/id"},
    "unit_id": {"literal": "body"},
    "unit_type": {"literal": "note"},
    "text_kind": {"literal": "full_text"},
    "text": {"pointer": "/body"},
    "url": {"pointer": "/url", "optional": true},
    "published_at": {"pointer": "/published_at", "optional": true}
  },
  "metrics": {"likes": {"pointer": "/likes", "optional": true, "unit": "次"}},
  "excluded_records": []
}
```

`payload.pointer` 从完整 MCP 响应根开始。JSON 字符串明确使用 decode_json=true；直接 structuredContent 可使用 `{"pointer":"/structuredContent","decode_json":false}`。records_pointer 从解码后或选中的 payload 根开始，必须指向数组。所有路径均为标准 JSON Pointer；不同内容块必须分别建立已核对的映射，不自动选第一个可解析块。

fields 的 pointer 从每条记录根开始，literal 仅用于已确认的稳定值或明确缺失值。每项必须二选一；正文 text 只能用 pointer。必需字段为 platform/content_id/unit_id/unit_type/text_kind/text/url/published_at；collected_at 默认取映射中的实际采集时间，也可逐行映射。可选 title/author_id/author_name/parent_unit_id/missing_metadata/imported_at。时间戳先按实际 schema 确认单位并在独立保存的派生文件中转换，脚本不猜秒或毫秒。

ID 使用完整字符串或 JSON 精确整数；浮点 ID 拒绝导入。全文、摘要、转写和改写稿分别标明 text_kind；本地校验通过不改变它们的引文资格。metrics 每项使用原始字段 pointer，保留 raw；无法直接解释的数值令 value=null，不补零、不把格式化字符串猜成数值。没有原始映射的指标不凭空生成。

明确范围外记录可在 excluded_records 中写 `{"index":0,"reason":"该条具体的排除理由"}`；index 是原始数组的零基索引。空文本、完全重复和明确排除均进入原始记录账。重复指向保留记录；相同来源的文本或元数据冲突会拒绝转换，先明确本轮选用版本。空文本不算已读。

```text
python scripts/normalize_mcp.py saved-response.json reviewed-mapping.json RUN_DIR
python scripts/prepare_analysis.py RUN_DIR
```

RUN_DIR 必须不存在或为空目录。先在临时工作区验证原文指针、时间、指标和来源字段，再发布；不覆盖旧 run。产物为：

- raw/mcp-response.json：逐字节保留完整的已保存 MCP 输出。
- raw/decoded-payload.json：仅 decode_json=true 时生成，manifest 保存原内容块 pointer 与解码文件哈希。
- mapping.json：实际映射及其哈希。
- items.jsonl：通过来源校验的选定记录，不生成主题、观点或完成声明。
- raw-inventory.json：每条原始记录的去向、位置和重复目标。
- manifest.json：实际数量、映射来源、采集时间及派生关系。

这些记录证明本地转换和来源连接，不证明 MCP 上游 HTTP 全链路、抽样代表性、字段业务含义或作者身份。错误响应 isError=true 不作为分析输入。原件不能含 API 密钥或鉴权头；本 skill 不索取这些信息。

## 采集任务台账与恢复

台账由宿主执行 MCP 调用前后维护。本地脚本不能替宿主强制远端预算或保证服务端幂等。调用前先查看剩余预算；每次实际调用后记录观察到的状态。任务数、宿主工具调用数、HTTP 次数和费用分别记录；MCP 内部不可见的 HTTP 次数及费用为 null。

```text
python scripts/collection_ledger.py init RUN_DIR --target-count 50 --max-tasks 3 --max-tool-calls 8
python scripts/collection_ledger.py record RUN_DIR request.json
python scripts/collection_ledger.py status RUN_DIR
python scripts/collection_ledger.py transition RUN_DIR request-1 event.json
```

以上数量仅演示参数，本轮按已授权范围填写。init 不覆盖已有台账；纯离线分析不用此步骤。

request.json 保存 request_id、实际工具名 tool、脱敏业务 parameters，以及本任务 target_count/effective_limit。provider 缺省为 guaikei，其他 provider 拒绝。工具名来自宿主实际发现结果；脚本不执行或验证远端工具。参数对象按键排序后计算 fingerprint，同 ID 或同工具及参数的任务不重复登记。

```json
{
  "request_id": "request-1",
  "tool": "本轮实际guaikei工具名",
  "parameters": {"keyword": "本轮关键词", "limit": 50},
  "target_count": 50,
  "effective_limit": 50
}
```

新登记状态为 planned。实际提交后写 event.json，例如已受理但未完成时：

```json
{
  "state": "submitted_pending",
  "action": "submit",
  "reason": "本轮实际观察到的受理状态",
  "tool_calls": 1,
  "http_requests": null,
  "fee": null,
  "provider_task_id": "仅在真实返回时填写"
}
```

state 支持 planned/submitted_pending/timeout_pending/submission_unknown/complete/failed。submit 只允许从 planned 开始一次。处理中期限已到可用 action=observe、state=timeout_pending、tool_calls=0 记录观察；它不代表新增请求。后续查询使用 action=query、query_supported=true，前提是实际工具提供查询能力。

提交结果不明的 submission_unknown 只能通过实际支持的查询恢复，且必须提供查询输出的 result_ref；不得重复提交来试探状态。complete 必须有已保存的结果引用，合法空结果可 returned_count=0。failed 与 complete 为终止状态，不自动重试；先核查失败原因及是否受理，再按实际工具能力决定后续操作，脚本不声称重复创建免费或安全。

```json
{
  "state": "complete",
  "action": "query",
  "query_supported": true,
  "reason": "实际查询已返回完成结果",
  "tool_calls": 1,
  "http_requests": null,
  "returned_count": 0,
  "result_ref": {"file": "raw/query-result.json"}
}
```

result_ref 必须指向 RUN_DIR 内的现有文件；脚本计算 SHA256，已有声明必须一致。鉴权字段和 Bearer 凭据拒绝写入台账。费用只在实际取得时写 `{"amount":0,"currency":"实际币种"}`，不能把未知写零。预算耗尽、非法状态转换、目录外引用和重复登记均失败且保留原状态。台账使用互斥锁与临时文件替换；发现遗留锁或 .pending 文件时先检查中断情况，不自动删除历史或倒填事件。

恢复时读取 collection-ledger.json 和已保存结果，核实状态后继续；不能靠聊天记忆重新创建任务。最终仍按 [coverage.md](coverage.md) 对账材料与分析，台账 complete 不等于已完成语义分析。
