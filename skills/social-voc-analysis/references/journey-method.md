# 旅程与场景分析规范

目的：解释用户为完成什么任务采取了哪些行动，在哪里受阻，以及如何验证改进。旅程不能只把主题换成阶段名称，也不能把多个作者拼成一位用户。

## 先界定分析对象

每张图声明行动者、目标、场景、触发条件、范围、材料日期及证据类型。场景描述具体情境，例如“复工后由长辈执行辅食计划”；旅程描述这一情境中的行动、交接和状态变化。角色或关键步骤明显不同则拆图；小差异保留支线。无完整事件序列的舆情材料，应标为“任务汇总图/待验证旅程”，不强制套完整生命周期。

## 汇总模板

横轴为材料支持的阶段；纵轴依次为目标、行为、用户关注点、触点/渠道、阻碍、已有应对、明确情绪、证据覆盖、待验证指标。阶段数由问题与材料决定。每一格保留观点 ID；代表性原声使用连续原文并回链。选用本模块时，对本轮观点记录 mapped 或 unknown，允许多阶段；区分未覆盖与无法归类，并说明原因，不按关键词自动判阶段。

阶段摘要优先使用体验自述。推广功能列为供给声明；求助区分已发生障碍与期待，不能把愿望写成用户已完成的行为。正负向评价与情绪分开；“麻烦”不直接等于愤怒，“方便”不直接等于安心。情绪须有明确自述；缺失留空。跨用户、无统一量尺的材料不画平均情绪曲线。一个案例内的前后情绪只代表该案例。

## 指标与推断分层

1. 可观测材料：去重来源/作品数、具体行为陈述、显式情绪及原声。覆盖数衡量材料厚度，不能充当用户比例或任务成功率。
2. 研究者解释：关注点、心理模型、任务分段和改进机会，均需支持证据、替代解释和适用边界。
3. 待测表现：任务成功率、完整记录用时、交接信息完整率、历史查找正确率、纵向记录策略变化。没有测试或埋点时 `value=null`，显示“待测”。

指标按 [module-framework.md](module-framework.md) 记录口径。表现指标另定义任务起止点与成功条件；成功率分母包含已开始任务中的失败/放弃，成功任务耗时需另报未完成数。不同产品须同任务、同条件比较。不要用帖子数量推算转化/留存，也不把查阅指南后的安心当成健康效果。

## 展示与复核

先用可横向对读的汇总矩阵，每格只留关键行为或问题；阶段详情展开看分支、原声、指标定义。阶段是任务循环时不要画单向漏斗。样本覆盖和待测表现分别标注，颜色不代替文字。复核观点覆盖完整、引用连续、角色分层、数值可复算、分支未拼接；证据不足时缩小结论。

## 可执行数据契约

独立文件 `journey-map.json` 使用 `meta.schema_version=journey-map-v1`，meta记录actor/scenario/model_type；`meta.source_files` 保存源文件的相对 `path/sha256`，至少包括opinions.json及其源证据快照。`stage_assignment` 每观点一条，含 `opinion_id/source_key/evidence_role/status/stage_ids/rationale`；status为mapped时阶段非空，为unknown时阶段为空并说明原因。`stages` 用稳定id连接分配表，保存title、goal、emotion_note、evidence_opinion_ids与按experience/context/supply划分的evidence_by_role；actions/concerns/touchpoints/frictions/workarounds的每格保存text及本阶段evidence_opinion_ids。representative_quote保存source_key、连续quote及本阶段观点依据；emotions另需label、basis=explicit与连续情绪原声，不从极性生成。

`measurement` 每项含name/definition/unit/limitations/type/value。v1的observed_proxy专指本阶段全部体验观点对应的来源覆盖，保存evidence_opinion_ids、source_keys及复算值，不能承载任意业务指标；proposed_test未测必须value=null。已知作品数与来源数分开，未知作品ID不凑成一篇。可选branches记录关联stages及有依据的cases。校验入口见 [SKILL.md](../SKILL.md#校验与运行环境)，检查通过不代表阶段划分、情绪解释或旅程完整性成立。

## 方法来源与边界

- [NN/g Journey Mapping 101](https://www.nngroup.com/articles/journey-mapping-101/)：采用行动者、场景、阶段、行为/想法/情绪及机会结构；本轮不采用无纵向证据的情绪线。
- [GOV.UK Creating an experience map](https://www.gov.uk/service-manual/user-research/creating-an-experience-map)：采用共同步骤汇总、差异路径拆分及摘要图；社交文本片段不能替代完整经历研究。
- [GOV.UK Measuring completion rate](https://www.gov.uk/service-manual/measuring-success/measuring-completion-rate)：采用明确任务起止和完成分母的原则；不把政务交易指标原样套作 App 舆情结果。

资料核对日期：2026-11-09。
