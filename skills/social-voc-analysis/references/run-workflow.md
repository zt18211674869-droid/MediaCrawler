# 研究计划、冻结与统一验收

## 一份主计划，分阶段填写

新任务使用 schema_version=research-spec-v1，保留 external_access={"provider":"guaikei","transport":"mcp"}；本轮 collection_mode 仅 offline 或 mcp。该策略在离线任务中也保留，不意味着必须调用外部工具。

研究前填写 intent、question_plan、module_plan、quantitative_plan 和取样预算；分析后填写 question_coverage；成稿时确定 outputs 和 report_plan。示例见 [research-spec.example.json](../assets/research-spec.example.json)。旧计划可只读归一化，不覆写旧文件，不给无稳定 ID 的旧问题自动编造连接。

每题保存 id/question/evidence_needed/method/completion_criteria。模块保存 module/selected/question_ids；keywords、journey、opinions 用这些稳定名称，其他模块可用业务名称。样本分布在 quantitative_plan 中明确 mode=sample_distribution 和 required_tables，每表含 id/axis_id/question_ids；独立 quantitative-spec 必须与主计划一致。案例解释使用 case_exploration，不能以此跳过用户要求的频次或场景分布。

question_coverage 每项含 question_id、status（answered/partial/unknown）、finding_ids、table_ids、gaps。每个问题均有去向；partial/unknown 写具体缺口，answered 提供实际支撑。没有证据时可以保留未知，不为消除未知虚构发现。结构连接不等于问题已被正确回答，仍需语义审阅。

## 按缺口取证，按预算停止

在研究计划的 evidence_gaps 中记录问题、对象、材料性质、已有来源、欠缺、补采任务及停止理由。对象只有宣传、关键判断冲突、重要任务缺上下文时优先补证。条数目标和问题覆盖分别记录；达到预算或可得结果耗尽时披露剩余缺口。事实核验同样只能用已有材料与 guaikei MCP，不能转向其他外部通道。

在线任务台账和响应适配见 [本地 MCP 工具](mcp-local-tools.md)。先保存原始返回与实际 schema，再显式映射。台账只记录宿主发出的 guaikei 调用；不执行网络，不证明服务端幂等或费用。真实 HTTP 次数及费用不可见时保留 null。

## 试编码、冻结与回编码

1. 选择覆盖对象、来源性质、长短文本、正反共存及零观点情况的小批材料试编码，不固定比例。
2. 在 coding-review.json 记录具体歧义、来源 ID、候选判定、实际采用判定、理由和参与方式；模型自检仍为 model。
3. 修订本轮 coding_rules，保存类别定义、纳入/排除边界及易混淆例子，冻结版本后再展开全量编码。
4. 出现新类别或定义变化时，在 change-impact.json 记录 from_version/to_version、reason、affected_source_ids、affected_artifacts、recoding_status，回看受影响的旧批次，不只修改版本字符串。
5. 按 [coverage.md](coverage.md) 完成全部选定原文的处理和复核。工具准备字符位置、哈希和批次；实际阅读者记录语义结果。抽查可以评价质量，不能替代已要求的全量处理。

这些记录支持语义审阅，不由脚本根据数量自动生成正确或完成。新任务启用独立观点层时，analysis 维护来源资格和原始证据，opinions 维护本轮观点、聚类及观点发现；兼容旧 findings 时明确报告引用的来源，不手工维护两套相同结论。旧原文、判定和采集日期继续保留。

## 工件依赖与报告绑定

本轮主配置、证据、观点、分类、统计、报告和审阅记录通过实际文件哈希关联，见 [报告绑定与工件清单](report-bindings.md)。只登记本轮使用的文件，不能把文件系统扫描当作语义审阅。

资格或原文变化后重核观点及下游；代码表变化后回编码并重算；只改语言时保持原文、统计和引用不变，重做实际成稿审阅。旧清单用于识别哪些工件失效，修订后生成新清单，不静默重签旧验收。

## 分维度验收

从 Skill 根目录运行：

```text
python scripts/validate_run.py RUN_DIR --profile analysis
python scripts/validate_run.py RUN_DIR --profile delivery --output RUN_DIR/run-validation.json
```

analysis 汇总当前数据与分析状态；delivery 检查正式交付；revision 用于保持冻结分析的文字/展示修订，仍检查源文件、绑定与实际审阅，不免除证据要求。

总入口依主计划检查必需模块与统计，调用既有来源、观点、覆盖和模块校验，核对研究问题连接、输出文件、报告绑定及工件哈希。单个 validator 的退出码不能直接作为正式交付状态。旧文件允许读取并报告缺失绑定，不能自动补签本轮交付证明。

交付使用 quality-review.json：schema_version=quality-review-v1，source_hashes 保存实际被审阅文件相对路径及 SHA256，覆盖主计划、analysis、items、复核账和全部输出，以及本轮实际使用的 opinions、定量计划/分类/事实、关键词、旅程和报告绑定。不要把自身、工件清单或最终总验收输出纳入审阅哈希。

dimensions 含 data_evidence、language、hierarchy、visual_interaction，每项含 status（passed/not_run/not_applicable）、method，必要时 limits 或 reason。记录实际执行的检查和问题；不能只填通过。HTML/PDF 的视觉和交互需实际渲染，纯数据交付可具体说明不适用。方法、事实或数值修订后，旧审阅哈希失效，应重审受影响维度。

分别展示数据完整性、处理覆盖、复核覆盖、未处理与待核数、定量复算、报告绑定及实际界面检查。已完整复核仍有真实歧义时可披露为 completed_with_uncertainty；ready 也只代表所声明门槛通过，不证明模型语义绝无遗漏。旧 --require-complete 仍要求确定性编码无待核，不因新增状态而放宽。

## 可重复的本地检查

从 Skill 根目录运行 python -m unittest discover -s tests -p "test_*.py"。合成材料只用于验证结构、回链、预算与失效传播，不宣称实时接口已联调。按项目积累具体语义错例供真实阅读评估，优先检查错对象、期待当体验、宣传当口碑、漏方面、因果拔高和错误分母；计数正确不能代替这些判断。
