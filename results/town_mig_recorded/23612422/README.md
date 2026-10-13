# 开启 thinking 的小镇试点：23612422

本轮 Qwen3-8B 开启 thinking，自动选择工具，每次输出上限 4096 tokens。单人及四人团队共五名玩家：四名在第一步工具动作前耗尽输出上限并报错；一名实际行动，但未完成订单。实际返回的 49 次 HTTP 响应均包含 reasoning 文本。

- [events.jsonl](events.jsonl)：原始模型输入、输出、服务返回的 reasoning 文本、工具反馈和错误。`http_response.body.choices[].message.reasoning_content` 是服务返回的文字，不代表可以观测模型内部计算。
- [traces.jsonl](traces.jsonl)：每个玩家的工具调用、参数、反馈和终止状态。
- [codeworld.jsonl](codeworld.jsonl)：交付数、状态、预算与 token 指标。
- [replay.json](replay.json)：实际环境事件回放。
- `source.tar.gz`、`source.patch`、`source-sha256.json`：当时源码快照与校验；`commit.txt` 是运行时基础提交。
- `config.json`、`job.sh`、`timing.txt`：实验配置、任务脚本与用时。

需要 HTML 查看器时可运行 `python scripts/report_codeworld_run.py results/town_mig_recorded/23612422`，再用浏览器打开生成的 `process.html`。服务器及硬件原始日志留在 Nibi 和本地，不公开上传。
