# 技能包

这里收录可以复制、安装和使用的完整技能包。每个技能使用独立目录，入口文件命名为 `SKILL.md`。

| 技能 | 用途 | 使用条件 |
| --- | --- | --- |
| [social-voc-analysis](social-voc-analysis/SKILL.md) | 分析社媒观点、场景与行为，开展舆情、竞品、需求与体验研究，生成证据可追溯的报告 | 支持本地材料离线分析；在线补采需要已连接的 GUAIKEI MCP |

## 安装 social-voc-analysis

下载或克隆本仓库后，将 `skills/social-voc-analysis/` **整个目录**复制到 AI 宿主支持的技能目录。保留 `SKILL.md`、`agents/`、`references/`、`scripts/`、`assets/`、`tests/` 和 `release.json`；只复制 `SKILL.md` 会缺少参考材料和脚本。

Codex 可以选择以下一种安装范围：

| 范围 | 复制后的目录 |
| --- | --- |
| 当前用户的所有项目 | `~/.agents/skills/social-voc-analysis/` |
| 指定项目 | `<项目目录>/.agents/skills/social-voc-analysis/` |

Windows 中 `~` 对应当前用户目录。目录依据 [OpenAI 官方技能文档](https://learn.chatgpt.com/docs/build-skills)；其他 AI 宿主请使用其支持的技能目录。避免在多个位置重复安装同名技能。Codex 会自动发现技能变化，未显示时重启 Codex。

## 环境与依赖

- AI 宿主需要能够读取本地文件并保存分析产物。
- 在线采集需要事先配置有效的 GUAIKEI MCP 连接，参考 [安装与配置指南](https://zt18211674869-droid.github.io/MediaCrawler/mcp/guaikei/)。技能包不包含服务账号、TOKEN 或调用额度；可获取的数据见 [MCP 说明](../docs/mcp/guaikei/README.md)。
- 已有本地材料可以直接离线分析，无需调用 MCP。
- 附带脚本使用 **Python 3.9 及以上**，只依赖标准库，无需安装第三方 Python 包。已在 Python 3.11.9 运行现有回归测试；未实际运行 Python 3.9。无 Python 时，按技能说明使用宿主现有的本地计算能力，不自动安装环境。

## 开始使用

安装后，在 AI 对话中明确调用技能，并说明研究目的、材料、范围和输出要求，例如：

> 使用 $social-voc-analysis，离线分析我提供的用户反馈，识别主要使用场景和体验问题，附关键统计与可回查的原文证据。

> 使用 $social-voc-analysis，通过已连接的 GUAIKEI MCP 研究小红书上关于某产品的用户反馈。采集 50 条笔记，分析主要观点和使用场景，并说明样本范围与缺口。

问题、采集数量及预算按实际任务确定。技能中的 MCP 连接失败提示会引导用户联系仓库维护者或 MCP 服务提供方。

## 运行附带脚本

技能里的 `python scripts/...` 命令以 **`social-voc-analysis/` 技能根目录**为工作目录。从仓库根目录执行回归检查时：

```sh
cd skills/social-voc-analysis
python -B -m unittest discover -s tests -p "test_*.py"
```

运行分析工具时，也可以使用脚本的绝对路径，并明确指定本轮数据目录。不要将示例路径直接当成实际输入；各工具的用途、参数及产物见 [技能入口](social-voc-analysis/SKILL.md)。

技能专用脚本随技能一起维护。独立执行的通用分析脚本放在 [scripts/](../scripts/README.md)，案例通过链接引用技能。
