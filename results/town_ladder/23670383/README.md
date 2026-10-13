# Qwen3-8B 难度阶梯：Nibi 23670383

任务正常结束，Slurm 状态 `COMPLETED`、退出码 `0:0`。模型启动 100 秒，实验 53 秒，任务总用时 2 分 39 秒。采用 `8ab7088` 加运行时记录的状态修复，关闭 thinking，要求工具调用，输出上限 1024 tokens；未设置 `--no-stop`。

**第 1 级三个种子均未完成订单（0/3），没有进入第 2–6 级。**

| 种子 | 交付 | 停止原因 | 工具调用 | 观察到的行为 |
| --- | --- | --- | --- | --- |
| 11 | 0/1 | `max_turns` | study 2、remember 38 | 反复尝试错误系数；记对一台机器，另一台尚未记对就用完 40 次模型调用 |
| 22 | 0/1 | `out_of_budget` | study 4、remember 4 | 错误公式被拒绝后重复研究同一台机器，耗尽 32 行动点 |
| 33 | 0/1 | `out_of_budget` | study 3、remember 2、run 8 | 错误公式被拒绝后重新采样，再重复研究，耗尽 32 行动点 |

三个案例都没有调用 `compute` 或 `submit`。这是行为失败，程序未崩溃。预算耗尽判断来自玩家终止状态和预算轨迹；原始指标里的环境级 `out_of_budget` 计数为零，并不包含这两次玩家退出。

例如种子 11 的 `bakery.grinder` 给出 `0→69、1→53`，应有 `b=69`、`a=(53-69) mod 101=85`。玩家从 `100*x+69`、`99*x+69`、`98*x+69` 等逐个尝试，最终记对这台机器后，又在第二台机器上重复猜系数直到回合上限。记录定位到系数推断与反馈后的反复尝试，尚未涉及多候选链选择或协作。

## 与旧入门试点的差别

第 1 级不只是移除了工具强制步骤：旧 `tutorial.tiny_world` 的系数为 `a=2..5、b=1..7`，新阶梯使用一般宇宙生成器，系数范围更大，观测样例已经出现模 101 回绕；提示、笔记容量也不同。因此旧试点 9/9 与本次 0/3 不能作为单独移除强制步骤的效果估计。后续应先固定同一世界和提示，或单独比较小系数与回绕条件。三种子结果也不等于所有任务或模型的一般能力结论。

## 查看记录

- [summary.json](summary.json)：级别门槛与停止位置。
- [codeworld.jsonl](codeworld.jsonl)：三个案例的原始指标。
- [traces.jsonl](traces.jsonl)：完整动作参数、反馈、预算和终止原因。
- [events.jsonl](events.jsonl)：原始模型输入/输出、工具和环境事件；本次没有启用 thinking。
- [process.html](process.html)：下载后用浏览器打开，可逐次展开查看。
- [replay.json](replay.json)：实际环境事件，供 `web/codeworld.html` 加载。
- `config.json`、`job.sh`、`timing.txt`、`hardware-summary.txt`：配置和用时。
- `source.tar.gz`、`source.patch`、`source-sha256.json`：运行时实际源码快照；`commit.txt` 是基础提交。

从 Nibi 传回的整个归档 SHA-256 为 `34c13c675bb98cebcf61137f2c4ab6e58b09b3a25917412ec04a8713a72d6b96`，与本地解码结果一致。[original-sha256.json](original-sha256.json) 保存全部 18 个原始文件的校验值；[public-sha256.json](public-sha256.json) 保存公开文件的校验值。硬件和运行服务日志原件留在 Nibi 和本地，公开目录仅保留设备配置摘要。
