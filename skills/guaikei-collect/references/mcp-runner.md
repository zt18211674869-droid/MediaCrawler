# 宿主执行入口

用户要求采集时，由宿主执行一次 `runCollection`。为本轮选一个尚不存在的输出目录，整个会话共用同一路径。用户只需在弹窗里确认。程序会在应答成功之前把配置和任务写入该目录，再依次调度本轮各批任务，最后返回工作簿路径。取消或超时返回 `cancelled`，不会创建本轮目录或提交采集任务。

### Codex 调用示例

以下是 Windows PowerShell 工作区的示例，假设 Skill 位于 `skills/guaikei-collect`。其他安装位置使用该包的实际路径。通过 `functions.exec` 加载本地适配器；宿主 yield 后继续等待同一个执行单元。代码中的路径由宿主生成，检索词等表单内容直接从本机表单传入队列。

```js
const source = await tools.exec_command({
  cmd: "Get-Content -Raw -Encoding utf8 -LiteralPath skills/guaikei-collect/scripts/dispatch.js"
});
if (source.exit_code !== 0) throw Error("无法加载本地采集适配器");
const runCollection = Function(source.output + "\nreturn runCollection")();
const scripts = "skills/guaikei-collect/scripts";
const dir = "outputs/guaikei-" + Date.now();
const result = await runCollection({
  start: "python -B " + scripts + "/start.py " + dir,
  next: "python -B " + scripts + "/run.py next " + dir,
  report: "python -B " + scripts + "/run.py report " + dir
}, ALL_TOOLS, tools);
text(result);
```

若宿主对启动浏览器有单独的权限设置，可通过 `commands.startOptions` 传入该次启动所需的 `exec_command` 选项。

其他客户端可以采用相同顺序。`start.py 本轮目录` 打开表单并在确认时持久化队列，`run.py next 本轮目录` 按空闲名额领取任务。按返回的短工具名和 `args` 调用同一怪 K 服务，把原始信封或完整 `content` 包装写入对应的 `output`。等本批处理完，再领取下一批。单轮默认及最大并发为 10，用户选更低的数值时以该值为准。只发起不同的独立任务。保留工具响应中的原始文本可避免长 ID 在 JavaScript 中丢失精度。

默认执行器只向会话返回摘要与归档路径。若其他客户端会把结果全文放入会话，应通过表单调小单次请求条数。已有明确配置可用 `run.py init 配置.json 本轮目录` 建队，再按同一流程执行。已有工作目录可直接从 `next` 恢复。

### 续查与结束

- `TIMEOUT` 有 UUID 时，下一批仅以 `{"id":"原回执"}` 调原工具。连续两次超时的任务保留为 `pending` 并占用远端任务名额。等候后，可运行 `python -B scripts/run.py resume 本轮目录` 再 `next` 续查。不要改 `limit` 或换业务参数重建任务。
- `issued` 表示已领取但尚无落盘回包。中断后先核对原调用与落盘路径。`needs_review` 包括无回执的传输异常、陌生响应、身份不符等，不能当空结果。参数错误单列。限流、鉴权或疑似额度不足会暂停新任务。只有明确解决原因后才 `resume`，失败的原请求保留待核，其余未发任务可继续。
- `jobs` 为空时检查 `states`。仍有在途任务则等原调用；有阻塞或待核项则如实交付缺口。每轮可随时输出当前结果。

```powershell
python -B skills/guaikei-collect/scripts/run.py report 本轮目录
```

先给用户 `workbook` 对应的「采集结果.xlsx」。主帖和评论分表，通过平台和作品 ID 对应，评论明细也带主帖标题。作者只收录成功获取的主页。账号及作品 ID 在 Excel 中以文本保存。超过 Excel 单元格容量的原文可在同目录 JSONL 中查看全文。已有运行再次执行 `report` 即可离线更新。

`posts.jsonl`、`comments.jsonl`、`authors.jsonl` 分别存去重明细。`tasks.jsonl` 含原参、回执、状态、计数和原始文件位置。`summary.json` 按平台给出已取主帖、顶层评论、嵌套回复和作者数，并列出时间待核、触顶和已知回复缺口下界。`counts.comments` 合计评论和回复，`by_platform` 中的 `comments` 和 `replies` 分开计数。缺口下界为零时，仍需查看上游是否提供完整分页。单轮可重复导出。跨轮核对时另开新目录并提供旧档案，先比平台及实体 ID，再以回执及原始结果指纹核对缓存。
