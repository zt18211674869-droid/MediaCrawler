# 可审计分析快照

`analysis.json` 存储本轮冻结结果。原始响应保留在同一 run 目录下，引用文件使用相对路径。采集工具变化只影响输入映射，不能暗中改变分析口径。

## 从采集包到分析证据

先读取 `manifest.json` 判断实际覆盖和失败项，再逐行读取 `items.jsonl`。本版分析格式保留历史字段 `note_id`，它统一表示平台内的独立内容 ID，涵盖笔记、视频和文章；从采集项的 `content_id` 原样映射，不截断，不重新编号。

| 采集字段 | 分析字段或处理 |
|---|---|
| platform / content_id / unit_id | platform / note_id / unit_id，组成来源单元身份 |
| text / raw_ref | 从 raw_ref 指向的原文字段选择连续片段作为 evidence.text；保留引用路径 |
| unit_type / text_kind | 原样保留；摘要、转写、改写、未知文本分别标明 |
| title / author_id / author_name / parent_unit_id | 保留上下文，不把标题拼到评论原文中 |
| url / published_at / collected_at | 原样保留；未知日期可 null，collected_at 缺失按下述离线元数据规则记录，抓取日不等于发布日期 |
| metrics | 保留具体指标名称及缺失值；不当作人数或使用量 |
| raw_field / raw_time / time_source / time_unit | 原样保留字段路径、时间原值与单位依据；不能只留下转换后的日期 |
| profile / provenance_layer / content_sha256 | 保留对应响应的映射版本、实际输出层及文本哈希 |
| source_caption / unmapped_metrics | 保留尚未归并的文案和指标，不擅自混入正文或可比统计 |

`prepare_analysis.py` 只创建待编码快照：同一身份的完全相同快照可合并重复引用；文本、采集时间、指标或其它来源元数据变化时拒绝静默合并。先在本轮 items 中明确选用快照，保留未选原件与选择理由，再导入分析。摘要与正文使用不同 unit_id；报告中的独立作品数仍按 platform/content_id 合并。

完整正文与摘要分开保留；同一来源的摘要和正文不会算成两个独立用户表达。润色过的视频文案只能用于背景或待验证线索，不能作为逐字转写引用。转写保留时间段和是否经过原媒体核对。

分析快照放在采集 run 根目录时可直接使用已有相对 raw_ref。合并多轮材料时，在新 run 的 raw 下按来源 run 分目录保存原始文件并更新引用路径，避免覆盖不同轮次同名响应。保存采集时间和来源 run_id；单纯迁移不改变原始时间。

## 顶层结构

```json
{
  "meta": {
    "run_id": "example-run",
    "collection_mode": "offline",
    "coding_version": "v1",
    "analysis_as_of": "2026-11-05T12:00:00+08:00"
  },
  "evidence": [],
  "annotations": [],
  "findings": []
}
```

这里的时间只是格式示例，必须替换。新任务的 `collection_mode` 仅使用 offline / mcp。历史快照中的 cli / mixed 原样保留作为历史取得方式，本轮离线导入不会启用这些通道。JSON 数组中是一条条真实记录，不能用示例占位完成报告。

新完成的报告快照设置 `meta.stage: "final"`，并在顶层保存实际使用的 `coding_rules`，不能只留一个版本号。`coding_rules.version` 必须等于 `meta.coding_version`；`themes` 是非空数组，每项包含唯一的非空 `id`、非空 `definition`、`include` 和 `exclude`。后两项均为字符串数组，用实际纳入与排除边界填写；没有额外排除条件时可用空数组，不用空字符串占位。所有 admitted 记录的 `primary_theme` 必须存在于这份主题表。模型进行开放编码后按本次材料形成规则，不从示例硬套主题。

`meta.stage: "pending_coding"` 可用于刚完成输入转换、尚未分析的快照，不触发最终规则完整性门槛。缺少 stage 的历史快照仍可检查原文和计数，但会提示未验证最终编码规则；不能据此宣称已复核旧报告的分类口径。

## evidence：不改写原文

每条必备 `id/platform/note_id/unit_id/published_at/collected_at/text/url/raw_ref`。

- `unit_id` 是帖子正文或评论/回复的来源单元 ID；已知帖子 ID 的正文可用 `body`。离线材料没有平台来源单元 ID 时，使用下述持久本地来源 ID。若一单元有多个连续片段，加不同 `span_id`。
- `raw_ref` 含 `file` 和标准 JSON Pointer `pointer`，定位到保存原文的字符串，例如 `{"file":"raw/detail.json","pointer":"/response/results/content"}`。pointer 中 `~` 写作 `~0`、`/` 写作 `~1`。原文片段必须是该字符串的连续子串；翻译和省略显示放到其他字段，不替换 text。
- `published_at` 不明可 null。`collected_at` 是实际抓取该原文的时间；离线迁移也不改为迁移当天。不明时保留字段并填 null，记录缺失原因和独立的 imported_at，不能用导入时间冒充采集时间。
- `url` 字段必须存在，来源未提供或本地反馈没有网络地址时填 null；依靠 raw_ref 和来源身份回查，不编造 URL。报告注明链接缺失。
- 建议另有 `unit_type/text_kind/author_id/author_name/author_type/evidence_type/parent_unit_id/source_unit_key/source_snapshot_id/translation`。没有作者身份用 unknown，不猜。
- `source_unit_key` 推荐平台 + 完整帖子 ID + 来源单元 ID。`id` 用平台、来源单元、片段与原文内容的稳定哈希，或持久分配的永不复用 ID。不能用流水号重排、原文前 40 字或单独的文本相似度做永久身份。
- 同内容重复抓取合并来源快照；来源单元发生编辑保留新旧版本，本轮只选择明确的有效版本。多片段归于同一来源单元，统计独立来源时合并。

### 类型、时间和层级检查

`published_at` 可为 null、真实 ISO 日期 `YYYY-MM-DD`（仅知道日期）或带时区的 ISO 时间，例如 `2026-11-05T12:00:00+08:00`、`2026-11-05T04:00:00Z`。保留原始精度，不为日期补出虚构时刻。非空的 `collected_at`、`imported_at` 以及 `meta.analysis_as_of` 必须为带时区的 ISO 时间。数字时间戳先由已核实的采集映射按正确秒/毫秒单位转换，不能直接塞进这些字段。校验器检查格式、实际日期及是否有时区，不替代对来源字段、时间单位和窗口筛选的核实。

`unit_type`、`text_kind` 可在历史离线材料中省略；一旦提供，必须分别属于 `note/comment/reply/transcript` 和 `full_text/summary/transcript/rewritten/unknown`，不能用任意字符串或 null 混过类型检查。新采集包应按采集合同完整保留这两个字段。校验器无法从一个省略类型的旧记录判断其内容是否确为全文。

`metrics` 可为 null 或指标字典。每项允许 null、非负有限数值，或 `{"raw":"12000","value":12000,"unit":"次"}` 这样的对象。对象必须有 raw 和 value；raw 用于追溯，可保留合法 JSON 原值，包括负数、布尔值、数组或对象，不能把它直接用于计算。value 为非负有限数值或 null；如填写 unit，应为非空字符串。无法确定含义的值保留 raw 并令 value 为 null，例如 `{"raw":-1,"value":null}`、`{"raw":"1.2万","value":null}`，这类缺失不影响有效正文进入分析。

value 非空时，raw 必须是可解释的非负数值或普通十进制数字串，且换算后与 value 一致；当前校验器不猜测“万”等单位、分隔符或特殊对象的含义。`{"raw":-1,"value":5}`、布尔值/对象配非空 value、raw/value 不相符都会被拒绝。负数或布尔值作为裸指标值、无穷大、NaN 及裸的格式化计数字串也会被拒绝；非有限数值不能藏在 raw 的嵌套对象里。该检查不能证明播放、点赞、评论、回复等指标映射及平台间口径相同，统计只使用已确认的 value，缺失不补零。

从归一化采集项接收指标时，原样保留 `raw_field.metrics`（单数 raw_field），结构为指标名到原始文件内完整 JSON Pointer 的映射，例如 `{"likes":"/data/0/digg_count","views":null}`；CLI 输出可能是 `/results/0/digg_count`，以实际保存的路径为准。指标与文本使用同一个 `raw_ref.file`。校验器按这些路径重新读取原响应，要求每项 `metrics[name].raw` 与原始字段值及 JSON 类型相符，再检查 raw/value 数值关系；同时篡改 raw 和 value 也不能绕过原响应核对。已有映射却缺键、路径不存在或指针非法会报错。映射为 null 只表示未取得或未映射该指标，此时 raw/value 都必须为 null；它不属于已回查的数值。

没有 raw_field 的历史离线数据仍可通过结构和数值检查，但会提示指标未回查。校验摘要 `metric_provenance` 分别记录 `source_checked`、`declared_unavailable`、`unverified` 和 `invalid` 的指标项数；这些是字段核对数量，不是平台互动量。final 报告也不能将 unverified 指标标为已验证；需补原始映射回查，或披露未回查并不把它作为已核实的定量结论。字段路径核对验证的是保存值与声明来源一致，不代替采集映射中字段业务含义的审查。

`parent_unit_id` 若存在，值应为非空字符串或 null，不能指向自身。note/transcript 不设评论父单元。若一级 comment 记录了父单元，已知父类型应为 note；reply 的已知父类型应为 comment 或 reply。父单元在当前证据中且作品身份已知时，必须属于同平台同作品。缺少父单元、父作品身份或 reply 的父 ID 时保留材料并发出上下文缺失提示，不把离线截取材料硬判成无效，也不能据此声称完整验证了讨论串。该校验不补取缺失回复或证明平台返回的父 ID 本身正确。

### 离线元数据与本地身份

平台未知可写 `platform: "unknown"`。`note_id` 和 `collected_at` 字段必须存在；确实无法恢复时可为 null，并在 `missing_metadata` 字典对应键填写非空的具体原因。`collected_at: null` 还必须有非空字符串 `imported_at`，如实记录本轮导入时间。已知的真实帖子 ID、来源单元 ID 和采集时间原样保留；不能为了格式统一重新编号。

例如，一份没有平台 ID 和采集记录的本地反馈，可以保留以下元数据，并另填真实的 text、raw_ref 等必需字段：

```json
{
  "platform": "unknown",
  "note_id": null,
  "unit_id": "local:feedback-archive-a:record-7b8e",
  "collected_at": null,
  "imported_at": "2026-11-05T12:00:00+08:00",
  "missing_metadata": {
    "note_id": "原始反馈表未保留平台帖子 ID",
    "collected_at": "原始文件未记录数据采集时间"
  }
}
```

示例时间和 ID 不能直接用于实际记录。本地 `unit_id` 只是可回查的来源身份，不是平台 ID：首次导入时给原始文件及其记录分配持久 ID，保存映射，后续重排或再次导入复用；也可用不变的原始文件标识和原始记录键生成。没有稳定记录键时持久分配 ID，不用当前行号或原文截断代替。多个片段复用同一 unit_id，并用 span_id 区分。note_id 未知时，source_unit_key 使用平台加完整本地 unit_id，不捏造帖子 ID。

独立帖子数只计算已有 note_id 的平台/帖子组合；null 不算一篇，也不参与去重推断。校验结果的 `unknown_note_evidence` 是缺少帖子 ID 的证据片段数，报告同时交代已知帖子覆盖与这部分缺失。`support_note_count` 同样只计已知帖子，不能把它当作所有支持材料的完整帖子数。证据条数和来源单元数仍可按各自身份计算，都不等于人数。

## annotations：可更新的判定

每条必备 `evidence_id/status/reason/assessor/coding_version`。本轮每条证据最多一份有效判定，旧判定存入历史快照。

`status` 为 admitted / excluded / uncertain / pending；没有 annotation 的证据按 pending 计。`assessor` 为 model / human / mixed，只如实记录参与方式。模型自检仍为 model。

纳入项必须有 `primary_theme`，可另含 `themes/opinion/products/context/task/behavior/outcome/expression_types/confidence_notes/action_hypothesis`。`opinion` 是研究者对这一行原文的观点概括，`action_hypothesis` 是候选业务动作，都不能当直接引语。不确定属性留 null 或 unknown。多主题只影响交叉分析，不增加总证据数。

这就是逐行观点层：一行关联明确的证据片段、主题与观点，并记录正反评价、理由和不确定性。同一来源单元有几个独立观点时可切成多个可定位片段，但统计独立来源时仍合并；不以增加观点行数提高某项优先级。

## findings：可回链的发现

必备 `id/claim/support_ids/counter_ids/interpretation/limits/opportunity/validation`。

这些是台账字段，不是固定报告章节。opportunity/validation 按本轮用途记录：设计任务可写改善假设与验证，竞品了解任务可写关键比较缺口与核查方向；确实不适用时写具体原因，不为通过格式检查虚构建议或实验。正文只选影响主问题判断的内容。

- support_ids 和 counter_ids 只能引用本轮 admitted 的 evidence；非体验材料如用于背景或事实核验，另列背景来源，不混入体验声量。
- `quotes` 可选，每项含 evidence_id/text，直接引语必须是该证据原文的连续子串。明确标为 summary、rewritten 或 unknown 的证据不得放入 quotes；若需说明它提供的背景信息，在正文中明确标“摘要/整理稿/来源性质未明”，通过 evidence_id 回链，不能当作用户原声。transcript 仍需另行核对媒体与时间位置；原文回链只证明引文存在于保存的文字，不证明识别无误。
- 可选 `support_count/support_note_count`；脚本复算并核对。主张内容和证据的语义关联仍须复核。
- 可选 `proportion` 对象包含 `numerator_ids/denominator_ids/unit/multi_label/window/description`，unit 仅 evidence 或 note。分母必须属于纳入证据，分子是其子集。unit 为 note 时，分子或分母任一证据缺少 note_id 都会拒绝该比例；不能默默丢弃缺失来源后报告全部样本的占比。可明确另建元数据完整的子样本并说明覆盖，或只报告证据条数。脚本输出实际分数，不接受手填百分数作为事实来源。
- `counter_ids` 为空合法，但报告写明尚未找到或尚未检查，不能写“无反例”。

## 可选：研究问题、机制与体验方向

需要 decision-synthesis.md 的深入综合时，可在 research-spec 中给研究问题稳定 ID，在 finding 的 `research_question_ids` 记录对应关系。机制解释、替代解释和适用条件放入 interpretation/limits；不要用另一份不可回链的“心理结论表”覆盖这些发现。

体验方向可在 finding 添加可选 `experience_design` 对象，使用 `current_situation/desired_outcome/perceive/act/recover/tradeoffs` 保存当前场景、期望结果、信息、动作、恢复及潜在代价。缺项为 null，不编造功能；验证方法仍记录在 validation。该对象是设计假设，原文只存 evidence/quotes，支持来源沿用 support_ids/counter_ids。报告中的跨主题判断模式注明关联 finding ID，不增加证据计数。

这些扩展字段由实际参与的审阅者检查语义；validate_analysis.py 保留原有范围。统一 validate_run.py 及主计划连接检查另核对研究问题 ID 和必需产物，但不判断设计解释是否成立。

## facts：可选的统计事实导出

需要一源多观点、方面级正负向、聚类与场景旅程联动时，可按 [opinion-contract.md](opinion-contract.md) 建立独立 opinions.json。它通过源文件哈希和 evidence_id 关联本快照，保留旧编码与原文；旧校验器不验证这层扩展，需另查观点合同与语义。不是所有分析都必须另建文件。

报告需要较多统计时，从冻结的 evidence 与 annotations 导出 `facts.json`，避免在不同章节手工另算。它是派生产物，保留 run_id、coding_version、生成时间与来源快照；不在其中独立维护一份可手改的证据清单。

每个指标保留稳定的 metric_id、描述、值、单位、过滤条件与缺失情况。比例另外记录分子/分母的证据 ID 或来源单元 ID、去重单位、多选规则和时间窗口。采集覆盖数字引用 manifest 的实际返回状态，不用证据条数代替召回或取回量。

正文绑定 metric_id 对应的含义；数字相同不代表同一个指标。资格或分母无法确定时不导出比例，保留条数与案例；小基数但分母明确时可报告有边界的 `n/N`。展示顺序用稳定 ID 作最后排序键，精选引语显式保存所选证据 ID，确保相同输入不会因集合迭代顺序改变精选结果。

需要观点、场景或其他样本分布时，按 [quantitative-analysis.md](quantitative-analysis.md) 保存定量计划、分类快照及统计事实。它将必需表与研究问题连接，并通过实际文件哈希和分子/分母成员回算；补足既有校验器只核对已声明数字、无法检查缺失统计产物的范围。小样本不自动禁止比例，分母或资格确实不完整时才保留未计算状态。

现有 `validate_analysis.py` 核验 analysis 中声明的 support_count、support_note_count 与 proportion，并检查上述日期、可选类型、指标形状及已有映射的原始值、已知父子关系和 final 阶段编码规则。它不执行平台字段映射，不单独验证独立 facts 文件、报告绑定、未收集上下文、所有扩展字段或研究解释是否成立。报告绑定与依赖失效另按 [report-bindings.md](report-bindings.md) 检查。导出 facts 后应使用宿主已有计算能力逐项复算，并核对报告绑定关系。

## 对账

完整流程见 [coverage.md](coverage.md)。以下是分析证据内部的对账，必须再从原始文件独立枚举输入、核对 items 与 evidence 的 ID 差集；否则一条材料在导入阶段消失，下面等式仍可能成立。

```text
全部证据 = 纳入 + 明确排除 + 待核 + 未处理
已判定证据 = 纳入 + 明确排除
主题占比只按声明的分母计算
证据数、来源单元数、独立帖子数分别计算
```

原始候选帖中没有提取成证据的记录仍留在采集日志里，不能用 evidence 数替代召回量或正文取回量。

上述“已判定”只表示资格明确，不表示相关观点都已提取；uncertain 是判定仍待核，不自动等于没读过。语义处理与遗漏复核另存复核账，分别统计，不用一个完成率混报。
