# Qwen3-8B 入门试点：Nibi 23645311

2026-10-09，使用 H100 3g.40gb MIG，关闭 thinking，要求工具调用。实验设计见[入门诊断说明](../../../docs/tutorial-diagnostic.md)。

| 阶段 | 随机种子 | 完成订单 | 实际行为 |
| --- | --- | --- | --- |
| 单人 | 11、22、33 | 3/3 | 采样、推断两台机器的规则、记录、验证、提交 |
| 双人 | 11、22、33 | 6/6 | 每人询问队友一次缺失规则，验证两个公开样例、提交 |

全部玩家状态为 `completed`，无错误交付或预算耗尽。模型启动 341 秒，实验运行 99 秒；整个 Slurm 任务 7 分 27 秒。

这是有明确步骤的两机器入门诊断。双人各自预先获得一条正确规则，`ask` 的回复由程序从队友笔记自动生成。结果不能直接推广到五人复杂小镇，也不能证明协作优势。

- [codeworld.jsonl](codeworld.jsonl)：六个案例的指标和终止状态。
- [traces.jsonl](traces.jsonl)：每名玩家的完整工具参数、反馈、预算和动作顺序。
- [events.jsonl](events.jsonl)：完整模型请求/响应、工具和环境事件；本次关闭 thinking，没有额外推理文字。
- [process.html](process.html)：展开查看模型与工具记录；下载后用浏览器打开，GitHub 本身显示 HTML 源码。
- [replay.json](replay.json)：实际环境事件回放；可在仓库的 `web/codeworld.html` 中加载。
- [timing.txt](timing.txt)、GPU 记录：运行时间和设备配置；`gpu-start.txt` 仅保留型号、显存和 MIG 配置。`vllm.log` 包含运行路径和服务配置，仅保留在 Nibi 与本地，不公开上传。
- [source.tar.gz](source.tar.gz)、[source.patch](source.patch)、[source-sha256.json](source-sha256.json)：运行时源码快照和校验。

`commit.txt` 指向运行时的基础提交，运行时尚未提交的修改记录在 patch 和源码快照中。同步后整个传输归档的 SHA-256 与 Nibi 一致；[synced-sha256.json](synced-sha256.json) 保存原始 17 个文件的校验值，硬件摘要与原始日志的校验值不同，服务日志不在公开文件中。[public-sha256.json](public-sha256.json) 保存公开版本的文件校验值。硬件和服务日志原件保留在 Nibi 与本地。此说明文件在本地同步后添加。
