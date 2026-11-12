# 可回链的观点与分类层

当一条来源包含多个方面的观点，或报告需要分类、场景、旅程及原声联动时，用独立 `opinions.json` 扩展旧 `analysis.json`。原分析中的 evidence、原始ID、原文和历史判定保持不变；新版观点层记录本轮提取、聚类与解释，不重新编号原始来源。

## 顶层与来源基准

顶层为 `meta/source_reviews/opinions/clusters/findings`。数组必须记录真实对象，不使用示例占位完成研究。

meta 保存：

- `schema_version: "opinions-v1"`。
- `source_analysis`：相对于 opinions.json 的源 analysis.json 路径；移动交付包时保持可解析。
- `source_sha256`：源文件实际字节的 SHA-256；不是文件名或JSON重排后的哈希。
- `analysis_as_of`：本次分析的带时区 ISO 时间，不改变原采集日期。
- `coding_version`：本轮观点、分类规则版本。
- `review_complete`：只有逐一完成所有来源资格与观点提取复核时才为 true；结构检查不能证明已经阅读理解。

该布尔字段是过程声明，不是完成证明。严格全量验收另按 [coverage.md](coverage.md) 保存逐条、逐段复核账并检查全部选定输入；不能自动从 source_reviews 的数量推导 review_complete=true。旧版字段为 true 但没有可回查复核记录时，不能据此补签全量复核。

来源资格记录 `source_reviews` 每项包含 `evidence_id/source_key/status/reason/opinion_ids`。evidence_id 对应源 evidence.id；source_key 使用源 display_key，源未提供时复用 evidence.id，不能靠数组位置重建身份。status 使用 admitted/excluded/uncertain/pending。无观点时 opinion_ids 可为空，并说明没有相关具体观点、仅作背景或其他真实原因；已阅读无观点不等于未处理。

本扩展沿用源 analysis 的资格，不直接更改 status。复核发现分歧时保留修订依据；确需改资格，先建立有修订关系的新 analysis 快照，再让观点层引用它，保留原快照。正式观点和发现只使用 admitted 材料；尚未解决的来源争议保留为待核，不能静默升为体验证据。

## opinions：一个具体方面的判断

| 字段 | 含义与要求 |
|---|---|
| id | 本轮唯一、持久的观点ID；修订文字不靠重排重新分配ID |
| evidence_id / source_key | 回链源 evidence 与展示键；同源多观点共享同一来源身份 |
| product | 原文明确的产品或替代方案；未消歧保留原称呼与限制，不能猜商店身份 |
| aspect | 评价的具体任务或属性 |
| polarity | positive / negative / neutral / mixed；可拆分的不同方面优先分别提取 |
| kind | self_report / help / recommendation / tutorial / vendor_claim / expectation / question / context |
| evidence_role | experience / supply / context；宣传可支持供给定位，不因此成为独立体验 |
| statement | 研究者对具体观点的准确概括，不能冒充引语 |
| quote | 源 evidence.text 中的连续原文；省略、翻译、润色另作展示，不替换该字段 |
| scene / journey_stage | 情境与任务环节，未知为 null；不硬填完整旅程 |
| behavior / expectation / consequence | 来源支持的行为、预期和结果，未知为 null；研究者解释放 finding |
| candidate_theme | 提取时的描述性候选代码；最终归属以 clusters 为准 |
| limits | 与该观点相关的版本、身份、理解或证据限制；没有额外限制可 null，不能省略实质限制 |

除明确允许未知的字段外，用非空、可理解的值。未知属性不填“无”或零来暗示否定。产品方讲述用户行为仍需保留产品方身份，用户提问也不能自动变成已发生故障。

同帖多观点和同帖多评论不能增加独立作品数。同作者多帖不等于不同用户；统计来源数、作品数、账号数分别去重，未提供身份的部分说明缺失。

## clusters 与 findings

cluster 必含 `id/title/definition/opinion_ids`。definition 解释本簇共同表达及边界；必要时另记纳入/排除规则。正式聚类人工或模型逐项判定，不能只按 candidate_theme 名称或关键词相同自动合并。多重归属允许，但报告注明多选，避免占比误读。

若本轮选择互斥主分类，设置 `meta.cluster_mode: "primary_exclusive"`，全部观点须且仅须属于一个主簇；场景、旅程等仍为独立维度。可选的 opinion_count/source_count/work_count/author_count 必须从引用复算；source_count 按来源单元身份去重，不能按片段数累加。

finding 必含 `id/claim/support_opinion_ids/counter_opinion_ids/interpretation/limits/question_ids`。问题ID来自 research-spec；支持和反证回链真实观点，原声继续回链 evidence。没有反证可为空，但说明尚未找到或尚未检查。供给定位与用户体验使用不同资格，不将开发者自荐累计为用户口碑。

可选 `boundary_opinion_ids` 存补充观察、替代解释或适用条件，不能为了凑反证将它们全部填入 counter_opinion_ids。审查每个引用对具体主张的作用；同一来源的其他方面不自动支持该结论。

场景旅程、心理模型和关键词索引可以作为报告派生视图，每项仍关联观点或发现ID。机制必须说明推断和替代解释；关键词区分原词与研究者归并。不能另造无法回链的心理标签表。

各视图计数从同一冻结观点层计算。支持观点数、独立来源单元数与独立作品数不是同一指标；筛选后的局部统计明确当前范围。

## 校验与限制

宿主已有 Python 时运行 `python scripts/validate_opinions.py <run-dir>/opinions.json`，检查源文件哈希、来源资格、ID、连续引语、簇与发现引用及可复算计数；同目录有 research-spec 时核对真实问题 ID。缺少旧计划时仅披露连接未核验，不能据此通过新任务交付。meta.review_complete 为 true 时要求全部源 evidence 有复核记录。不存在Python时用宿主现有工具完成同项核对，不为此安装环境。

旧 validate_analysis.py 继续检查旧合同，不替代观点层校验。新脚本也不证明提取语义正确、聚类合理、心理推断成立或筛选交互可用；这些仍需逐项语义审查与实际报告验收。
