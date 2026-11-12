---
name: social-voc-analysis
description: 独立分析小红书、抖音等社交材料，开展舆情、竞品、需求与体验研究，生成证据可追溯的正式报告。唯一外部调用为 guaikei MCP，亦支持本地材料离线分析。
---

# 社交平台 VOC 分析

先理解用户为什么分析，检查问题、证据与方法能否支持目标，再决定收集什么、怎样解释和展示。总览迅速说明答案，主体保留必要推理，原声随时可查；深度由问题与证据决定。

## 外部调用边界

本 Skill 独立完成研究，**唯一外部调用为已连接的 guaikei（怪客）MCP**。不与 VoiceScope 打标签或其他分析平台交接，不向其他服务上传材料，不调用其他采集 Skill、直接 HTTP/API、CLI、网页搜索或在线分词/模型服务。宿主本地文件、标准库计算和本地报告检查属于本地处理，不增加外部通道。参考文档中的方法链接仅为出处，不是执行入口。

离线任务使用 collection_mode=offline；需要补采时使用 mcp。旧包 cli/mixed 作为历史来源保留，本轮按离线再分析记录。当前产品功能、价格和地区限制，只能依据用户已有的有日期一手资料或 guaikei MCP 实际提供的材料核验；不足时保留未知，不另开外部核验通道。本边界持续适用于后续维护，用户明确修改时再调整。

## 默认报告标准

面向业务读者生成专业、客观、简洁的正式报告。标题与正文用自然准确的中文，直接说明对象、行为、发现或问题；朴素的日常用词可以使用，不用抒情、煽情、聊天腔或营销措辞替代分析。有证据的用户情绪仍可作为研究对象，报告不代入情绪或替用户抒情。

先确定读者需要获得的判断，再组织结论、支持材料与详细依据。语言、信息层级、界面呈现、数据与证据分别验收；不能用代码通过或字数减少代替报告质量。通用标准跨行业复用，不固化具体案例、产品结论、章节数量或页面模板。用户明确要求其他文体时按任务调整，数据与证据要求始终保留。

研究报告默认以发现组织正文，按问题结合关键统计、具体场景、代表原声与行为解释，说明这些发现对读者的意义。完整统计与逐条台账另有明确入口；统计完成范围与正文展示范围分别确定，不将全部分析维度逐一铺成图表。定量与质性材料按解释需要组合，不规定数据/文字比例，也不把每项发现套成固定卡片。

将使用场景作为分析模块时，正文必须直接提供场景数量或分布统计，并交代有效样本、`n/N`、必要占比、多选及未知项，结合案例解释；不能只写场景描述或将全部场景统计放在附件。材料不足时明确已确认条数与统计缺口，不虚构分母或比例。

## 先明确问题与报告用途

新任务或目标发生变化时，先读 [references/research-brief.md](references/research-brief.md)。从已有对话提取用户要了解或决定的事；明确的意图直接沿用，不能把“竞品对比”自动改成新产品设计、把“至少100篇”解释为要一份长报告。

若不同目的会改变选样、比较对象或最终结论，先问能消除分歧的关键问题，并等待回答后推进依赖该答案的采集与成稿。等待时可盘点已有材料和工具能力。不要替用户回答后继续批量取数；用户明确委托自行判断时可说明依据并推进。格式、配色等可逆细节通常自行处理。

将主问题、意图依据、范围及“子问题—所需证据—分析方法—完成标准”记入本轮 `research-spec.json`，新任务使用 research-spec-v1，参考 [assets/research-spec.example.json](assets/research-spec.example.json)。按 [references/module-framework.md](references/module-framework.md) 选择模块并定义指标口径；完整框架不等于每份报告堆满模块。按 [references/run-workflow.md](references/run-workflow.md) 分阶段填写：采集前形成问题与比较维度，分析后记录每题回答状态和真实缺口，成稿时确定输出；不预写结论。长期复用时区分稳定方法、本轮设置与带日期来源的历史发现，不把旧结论固化为模板。

明确本轮是案例探索还是样本分布研究。用户需要频次、占比、主导观点/场景或模块需要分布比较时，按 [references/quantitative-analysis.md](references/quantitative-analysis.md) 定义必需统计表、合格分母与完成标准；交付逐条分类、`n/N`、必要比例和未知/排除数量。小样本可以报告有边界的样本内比例，不能仅用精选案例替代已要求的定量分析。

## 在线采集前检查怪客 MCP

在线研究先读取 [references/mcp-connection.md](references/mcp-connection.md)，发现实际工具、核对所需能力与参数，检查连接和业务可用性。不能把工具列在列表中当作在线鉴权成功，也不能编造通用 ping 工具。

不可用时提示「怪客（guaikei）MCP 当前不可用，请联系仓库维护者或 MCP 服务提供方协助处理」，附脱敏原因和受影响能力。停止依赖失败能力的取数，保留已取得的数据；没有足够材料时停在数据准备阶段，不生成实时分析结论。检查通过后继续下面的框架；已受理但尚未完成的任务先等待结果。

不自动安装 SkillHub/CLI、配置 Node 或索取 API Key，不用其它采集方式绕过 MCP 故障。用户明确只分析已有本地文件时走离线流程，记录 collection_mode=offline，无须调用 MCP。在线任务失败后，已有材料可支持有限分析，但必须说明实时补采未完成。

## 数量与取样

需要补采时，用户指定数量优先；未指定时，每个已明确的采集任务默认以 50 条为目标（搜索或博主作品 50 篇，评论 50 条）。调用前核对 MCP 工具参数；数量字段为 `limit` 时，显式传入 `limit=50`。创建与查询同一任务时保持数量参数一致，轮询不代表新增一批 50 条。实际返回受服务上限、套餐、可用结果及预算约束，记录实际取得数量和不足原因。按 [references/handoff.md](references/handoff.md) 执行取数；多平台、多关键词不自动倍增全局预算。此默认仅用于采集，不限制已有材料的分析条数。

取样用于填补已明确问题的证据缺口。达到条数不代表竞品覆盖或解释已充分；品牌推广不能代替用户体验，同名对象未核不能凑成一家产品。满足用户指定的数量目标，同时记录材料性质与不足，不因报告精简而少做已授权的研究。

## 工作流程

1. **检查证据并按需取数。** 读取用户材料与已有采集包，区分召回、详情、评论、媒体转写及缺失状态。已有材料足够时不重复采集；需要在线取数时先完成 MCP 前置检查，再按 [references/handoff.md](references/handoff.md) 直接调用已发现的 guaikei MCP。本 Skill 自包含，不委派给其他采集或分析 Skill。
2. **构造连续证据片段。** 保留原始文本与上下文，按平台和来源单元去重；摘要、转写、改写稿分别标记。采集字段到分析字段的映射、原文回链和分析快照见 [references/data-contract.md](references/data-contract.md)。已有规范采集包且宿主有 Python 时，可用 `python scripts/prepare_analysis.py <run-dir>` 生成全部为 pending 的初始快照；它不自动纳入材料或生成发现，不覆盖既有快照。原始返回值应先经采集端的平台适配，不能在分析阶段猜测字段含义。
3. **提取观点与聚类。** 读取 [references/analysis.md](references/analysis.md) 和 [references/coverage.md](references/coverage.md)。默认处理本轮全部选定材料，先从原始输入独立建立分母，再分批读取完整文字，保存逐来源、逐段处理及观点复核结果；不能用 ID 齐全或批次摘要代替阅读和语义分析。逐来源记录资格与具体理由，再提取“对象、方面、判断、条件或理由”的全部相关观点。正负向落到方面；观点类别、证据性质、主题、场景和旅程分别记录。先描述性聚类，再回看原文检查遗漏、正反例和机制。选用词语/词云时读 [references/keyword-method.md](references/keyword-method.md)，选用场景旅程时读 [references/journey-method.md](references/journey-method.md)，不把评价极性当情绪或补造业务指标。需要一源多观点、跨视图联动或全量观点验收时按 [references/opinion-contract.md](references/opinion-contract.md) 建立可回链的独立观点层。
4. **解释材料并形成回答。** 读取 [references/decision-synthesis.md](references/decision-synthesis.md)。舆情研究先区分事件、来源说法与争议，再解释不同评价；竞品研究同维度比较定位、优势、不足及成立条件，按需结合场景、旅程与用户预期。区分来源明说与分析推断，用户需要产品设计时才展开方案。证据关系按具体主张判定，统计从冻结判定计算；不同立场不自动构成反证，共同主题不能代替产品差异，未知不能写成缺功能。
5. **编写并审阅正式报告。** 读取 [references/output.md](references/output.md) 和 [references/report-language.md](references/report-language.md)；HTML 另读 [references/report-design.md](references/report-design.md)。将分析台账转写为明确判断，以专业书面语回答主问题；按阅读任务选择段落、比较表、行为路径或图表，证据就近可查。根据内容选择连续章节、目录、Tab 或独立视图，各视图共用证据口径；不默认堆满模块或交互。语言修订与实质分析修订分别留痕，不暗改编码、分母、引文和来源日期。

## 可信边界

- 帖子/视频数、已取评论数、证据片段数、观点数与可辨认账号数分别统计。对每个比例说明分子、分母、单位、窗口及多选规则；只描述本次样本，不推算平台用户占比。
- 亲历自述、教程、品牌内容、期待、咨询与行业观点分别判定用途。自述不等于已验证真实使用，教程标题不等于用户亲历；缺失信息保留未知。
- 原文、翻译、研究者归纳和外部事实分字段。直接引语定位到对应来源的连续原文；媒体摘要或改写稿不能冒充逐字原声。事实核验遵守本页外部调用边界，缺少可得的一手资料时保留未知。
- 高互动、同帖集中、跨平台失衡与转载相关性须披露。同一来源拆出多个观点不增加独立来源数，点赞不能直接代表认同人数或产品优先级。
- 机会排序说明后果严重度、任务阻断、来源覆盖、证据强弱与产品目标。实现成本未知就写未知，不用固定权重公式或最低行数替代判断。
- 原始材料和历史判定保留快照。只有计数或版式变化时，不声称完成了新一轮洞察分析。

## 校验与运行环境

附带脚本使用 Python 3.9 及以上，仅依赖标准库。本文 `python scripts/...` 命令以本技能根目录为工作目录；宿主在其他目录运行时，使用脚本的绝对路径，并明确指定本轮数据目录。

已有本地 Python 时，先运行 `python scripts/validate_run.py <run-dir> --profile analysis` 检查研究进度；正式交付运行 `--profile delivery --output <run-dir>/run-validation.json`。主计划连接、必需产物、分维度状态、修订和实际审阅契约统一见 [references/run-workflow.md](references/run-workflow.md)。无 Python 时用宿主现有本地计算能力完成同项核对并说明，不为此安装环境或使用在线服务。

| 条件 | 读取或执行 |
|---|---|
| 研究设计、试编码、冻结与修订 | [运行规范](references/run-workflow.md) |
| MCP 输出映射与任务恢复 | [本地 MCP 工具](references/mcp-local-tools.md) |
| 来源、观点与完整复核 | validate_analysis.py、validate_opinions.py、validate_coverage.py；见 [覆盖规范](references/coverage.md) |
| 样本分布 | validate_quantitative.py；见 [定量规范](references/quantitative-analysis.md) |
| 关键词或旅程 | validate_research_modules.py 显式指定 keywords/journey/all；auto 跳过不代表必需模块通过 |
| 报告数字、发现、原声与修订依赖 | [报告绑定](references/report-bindings.md)、validate_report_bindings.py、artifact_manifest.py |
| 正式成稿与实际界面 | [输出](references/output.md)、[语言](references/report-language.md)、[视觉](references/report-design.md)；语言扫描仅提示候选问题 |

原文回链、覆盖、统计单位和分母必须核对；确定性全量完成声明继续使用 coverage 的 --require-complete。结构校验不证明语义正确，复核记录不证明真人参与，未实际渲染不能声称视觉验收通过。真实歧义、未处理及未执行的检查分别披露。局部检查和统一入口均保留原件与历史快照，不自动补签完成。
