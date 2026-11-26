// Run this adapter inside a host with connected MCP tools and workspace file access.
// Only the trusted local adapter is executable. Tool responses are archived as data.
function inspectConnection(catalog, required = []) {
  const names = new Map(catalog
    .filter(entry => /^mcp__guaikei__/i.test(entry.name))
    .map(entry => [entry.name.split("__").pop(), entry.name]));
  return {
    names,
    missing: [...new Set(required.filter(tool => !names.has(tool)))],
    installGuide: names.size ? null : "https://zt18211674869-droid.github.io/MediaCrawler/mcp/guaikei/"
  };
}

async function dispatch(batch, catalog, tools) {
  if (batch.jobs.length > 10) throw Error("每批最多同时执行 10 个任务");
  const {names, missing, installGuide} = inspectConnection(catalog, batch.jobs.map(job => job.tool));
  if (installGuide) throw Error("请配置怪 K MCP：" + installGuide);
  if (missing.length) throw Error("缺少怪 K MCP 工具：" + missing.join(", "));

  const results = await Promise.allSettled(batch.jobs.map(async job => {
    let response;
    try {
      response = await tools[names.get(job.tool)](job.args);
    } catch {
      response = {status: "error", error_code: "TRANSPORT_UNKNOWN"};
    }
    // Exact integer IDs can still be recovered from the original text or a canonical URL.
    const payload = JSON.stringify(response, (_, value) =>
      typeof value === "number" && Number.isInteger(value) && !Number.isSafeInteger(value) ? null : value);
    if (!payload) throw Error("缺少可归档的回包");
    const result = await tools.apply_patch("*** Begin Patch\n*** Add File: " + job.output +
      "\n+" + payload + "\n*** End Patch");
    if (result?.isError) throw Error("写入回包失败");
  }));
  return {
    assigned: batch.jobs.length,
    filesToCheck: batch.jobs.filter((_, index) => results[index].status === "rejected")
      .map(job => job.output)
  };
}

// The host owns the MCP connection. Keep it alive from the user's single confirmation
// through all ready batches, including when the local form waits across a shell yield.
async function runCollection(commands, catalog, tools) {
  const {names, installGuide} = inspectConnection(catalog);
  if (installGuide) return {status: "missing_mcp", installGuide};
  const toolNames = [...names.keys()].filter(name => /^[a-z0-9_]+$/.test(name));

  async function localJson(cmd, options = {}) {
    let part = await tools.exec_command({...options, cmd, max_output_tokens: 8192, yield_time_ms: 1000});
    let output = part.output;
    while (part.session_id != null && part.exit_code == null) {
      part = await tools.write_stdin({session_id: part.session_id, chars: "", yield_time_ms: 1000, max_output_tokens: 8192});
      output += part.output;
    }
    if (part.exit_code !== 0) throw Error(output.trim().slice(-500));
    // start.py also logs the local browser address on stderr, before its final JSON line.
    return JSON.parse(output.trim().split(/\r?\n/).pop());
  }

  const started = await localJson(commands.start + " --tools " + toolNames.join(","), commands.startOptions);
  if (started.status === "cancelled") return started;
  if (started.status !== "queued") throw Error("未能确认本轮队列状态");
  while (true) {
    const batch = await localJson(commands.next);
    if (!batch.jobs.length) break;
    const sent = await dispatch(batch, catalog, tools);
    if (sent.filesToCheck.length) {
      throw Error("回包写入失败，请核对本轮目录后恢复：" + started.run);
    }
  }
  return await localJson(commands.report);
}
