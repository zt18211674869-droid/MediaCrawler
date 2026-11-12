# 报告绑定与修订影响

本规范用于本地校验报告与冻结分析之间的连接；不执行网络请求。此 Skill 唯一外部调用仍为 guaikei MCP。纯文字整理可不生成 HTML，不能把静态绑定通过写成语义或视觉验收通过。

## 将报告引用连接到冻结内容

新任务在 `research-spec.json.outputs` 中保存实际输出，例如 `{"path":"report.html","format":"html","bindings_required":true}`。HTML 默认要求绑定；历史 `"html"` 按 `report.html` 识别。JSON/CSV 等非 HTML 输出不使用下面的 HTML 检查，需按其数据合同核对。

在 run 根目录建立 `report-bindings.json`：

```json
{
  "schema_version": "report-bindings-v1",
  "source_hashes": {
    "quantitative-facts.json": "实际文件字节的SHA256",
    "analysis.json": "实际文件字节的SHA256",
    "opinions.json": "实际文件字节的SHA256"
  },
  "reports": [{
    "path": "report.html",
    "metrics": [{
      "id": "M-task-count",
      "source": {"file": "quantitative-facts.json", "pointer": "/tables/0/rows/0/n"},
      "format": "number"
    }],
    "findings": [{"id": "F1", "source": "opinions"}],
    "quotes": [{"id": "Q1", "evidence_id": "E1", "text": "选定的连续原文"}]
  }]
}
```

示例 ID、指针、哈希和引语必须替换为本轮真实值。`source_hashes` 只列实际使用文件，不需要为不存在的层创建占位文件。全部路径相对于 run，拒绝绝对路径及越界路径。

HTML 用元素标记实际展示内容：

```html
<span data-metric-id="M-task-count">实际数量</span>
<section data-finding-id="F1">本项发现及必要解释</section>
<blockquote data-quote-id="Q1">选定的连续原文</blockquote>
```

- 指标读取 `facts.json` 或 `quantitative-facts.json` 的实际值；绑定文件不能自己定义一份指标事实。指针采用标准 JSON Pointer。
- `format` 为 `number`、`percent` 或 `text`。数字可指定 `decimals`（0–10）；百分比的源值使用已计算的百分数，例如 `50.0`，脚本只增加 `%`，不再乘以100。括号、单位等放标记元素外。未知值不能伪装为0；未知说明使用普通文本并披露范围。
- 脚本读取元素实际文本，包括子元素文本；`data-value` 等自报属性不作为数字依据。相同指标可以在多处展示，每处均核对。声明但未展示的绑定、未声明的标记均失败。
- 发现需显式指定 `analysis` 或 `opinions`。默认文件分别为 `analysis.json`、`opinions.json`；历史文件可用 `source_file` 指定，例如 `source-analysis.json`。ID存在性不证明正文解释与该发现语义一致。
- 引语默认从 `analysis.json` 读取，也可显式指定 `source_file`。必须属于 admitted 来源，是其原文的连续子串，HTML 展示与引语一致。summary、rewritten、unknown 不可作为直接原声。翻译和省略展示按独立规则审阅，不能替换本项逐字绑定。
- 动态生成而无静态文本的数字不能通过此检查。提供同源静态正文或单独执行并记录真实页面检查，不能以脚本变量中的值代替读者看到的值。

运行 `python scripts/validate_report_bindings.py <run-dir> --output <run-dir>/report-binding-validation.json`。它不检查未标注的所有自然语言数字，不执行 JavaScript，也不判断 CSS 可见性、解释、交互或 PDF 导出。成稿语义与实际渲染仍分别验收。

## 用工件快照追踪修订影响

`artifact_manifest.py` 仅快照显式选择的文件，不扫描无关目录、不修改源文件。依赖方向是“子产物依赖父输入”。例如：

```text
python scripts/artifact_manifest.py snapshot <run-dir> --artifact plan=research-spec.json --artifact analysis=analysis.json --artifact opinions=opinions.json --artifact report=report.html --depends analysis=plan --depends opinions=analysis --depends report=opinions
python scripts/artifact_manifest.py validate <run-dir> --output <run-dir>/artifact-validation.json
```

`artifact-manifest-v1` 保存各工件的 role、相对路径、实际字节 SHA256、可得的 schema_version 及依赖的角色和快照哈希。快照生成工具版本与时间分别记录。输入变化时，检查报告直接变化的角色及传递受影响的下游角色；不会自动重算、重写或签发语义完成。

显式补足实际依赖。例如定量分类依赖 analysis/opinions，统计依赖分类与定量计划，报告依赖实际使用的统计、发现和原声；只记录一条链不能证明其他依赖不存在。没有依赖的独立原始文件可单独快照。

先完成主数据和报告，再记录真实审阅的 `quality-review.json`，最后生成工件清单并运行统一验收。工件清单不能包含自身或最终总验收输出；quality-review 的 source_hashes 也不能包含自身。避免生成顺序造成循环哈希。

已有快照不覆盖。修订后先保留旧版，重算和复核受影响产物，再用 `--output artifact-manifest-v2.json` 生成新快照；可用 `validate --manifest artifact-manifest-v2.json` 核验指定版本。总验收默认使用 `artifact-manifest.json`，准备交付新版本时明确选择并保留相应 run 快照，不静默改写旧件。
