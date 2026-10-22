# 在本地用 Codex 运行 netscale-pilot

最新完成的 [DAG grain 1正式试跑及逐节点核验](../results/net/runs/20261022-codex-dag-pilot-02/netscale-pilot/README.md)基于 `cb69623`，12组均正确完成全部任务，包含b、η、平均token用量及完整调用归档。

> 2026-10-22 之后，netscale 换成了 DAG 环境（`worldseeds/net/providers/dag.py`）：隐藏函数加整数答案，粒度为 1 和 4，共 24 组。下文所说的 16×4 递推 DAG 和 915 次调用，是第一次试跑（`results/net/runs/20261022-codex-netscale-pilot-01`）的设置。那次试跑里，递推题可以直接提交闭式表达式，单人比参考团队还快，所以它的 T_ref 和 η 不作为结论，只保留行为观察。

对应网络规模实验：固定 16×4 DAG，1、2、4、8 名 `peers` 智能体，各运行种子 100、101、102，共 12 组。每组团队共享 915 次工具调用额度，各成员均分。

已完成的正式试跑见 [2026年10月22日结果与用量](../results/net/runs/20261022-codex-netscale-pilot-01/netscale-pilot/README.md)，包含原始汇总、轨迹、完整调用归档及 Word 精简报告。

## 原协议与模型替换

直接调用原来的 `evaluate.run_one(DESIGNS["peers"], ...)`，复用：

- `testset.SUITES["netscale-pilot"]` 的任务、种子、网络配置和调用预算；
- `designs.Member` 与 `designs.Peers` 的提示、历史、工具和运行流程；
- `Lockstep` 的同步计时，每个成员每次只提交一个操作；
- `scaling.run` 的同题理想团队参考与 `netscale.table` 的原始汇总。

替换的是 Agents SDK 的 `Model`：`CodexCLIModel` 将当前成员的原始说明、对话和工具参数说明送入 Codex CLI，返回一次工具选择，由原来的 SDK FunctionTool 执行。没有额外的任务分配策略、指定分工、笔记机制或批量动作。Codex 没有获得环境对象、参考答案或参考团队的程序输出。

模型为 `gpt-6.1-sol`，思考设置固定为 `high`，使用现有 Codex 登录。Qwen 专用的 `WS_THINKING` 不适用于这个后端；本实验不能替代 Qwen3-8B 的模型复现。环境、调度与记录在本机运行，模型推理通过 Codex 服务完成。

每次 CLI 调用在仓库外的临时目录执行，文件、终端、浏览器、插件、记忆和额外智能体工具关闭；返回事件出现额外工具使用即拒绝运行结果。这是输入和工具使用约束，不是容器级隔离。

## 运行

需安装项目环境的 SymPy 和 Agents SDK。无需启动 vLLM，也无需新增 OpenAI API key。

```bash
.venv/bin/python -m netagents.codex_netscale \
  --model gpt-6.1-sol --reasoning-effort high \
  --parallel-runs 2 --inference-concurrency 2 \
  --out results/net/runs/my-codex-run/netscale-pilot
```

默认只跑 grain 1 的 12 组；加 `--grains 1 4` 跑完整 24 组，或者之后用 `--grains 4` 写进另一个目录补跑。`parallel-runs` 控制同时执行的独立团队；`inference-concurrency` 限制实际模型请求数。即使推理在服务端排队，每组仍按原来的同步轮次计时，慢成员会让本轮等待，不把服务排队时间换算成模拟轮数。

各团队在独立进程的主线程中运行，保留数学提供者原来的 SIGALRM 超时限制。Codex CLI 的超时与满载错误最多重试三次；失效请求单独保存。出现未恢复的模型接口错误时，停止后续推理，不把它登记为有效实验中的任务失败。

## 恢复

在相同命令后加 `--resume`。已经完成的团队直接跳过；中断团队从初始环境重放已缓存、且输入完全相同的 Codex 决策，然后继续调用模型。缓存输入发生变化则拒绝复用。模型、思考设置、任务规模、种子、依赖版本和 Git 提交必须一致。

## 观察结果

- `config.json`：模型、依赖、Git 提交和运行设置。
- `sources/`：本次运行的模型适配器、原设计、时钟、任务集、评估和参考团队代码快照。
- `pending_plan.json`：待运行的规模、种子、DAG 参数与工具调用预算。
- `status.json`：整体完成数量与状态。
- `episodes/nN-seedS/progress.json`：当前各成员的请求数、操作分布，以及已在工具回传中看到的成功提交；成功提交数可能暂时比最终结果少一项，以最终 `result.json` 为准。
- `episodes/nN-seedS/calls/`：每个成员的提示、JSON 选择、CLI 事件和用量。中断请求保存在单独目录。
- `traces/`：原环境事件轨迹。
- `runs.jsonl`：格式与原评估器一致的有效运行结果。
- `summary.md`：每组完成后自动更新，包含原来的 **Network scale** 一节。

也可使用原命令重算扩展性表：

```bash
.venv/bin/python -m netagents.netscale results/net/runs/my-codex-run/netscale-pilot
```

单人结果未完成时，T、加速比和 η 尚不完整；不得用开发连通检查或小镇完成率替代这些指标。旧 Hive 小镇结果保存在独立目录，不纳入本实验。

原数学验证器接受等价的符号表达式，例如 `Mod(...)`。Codex 可能直接构造表达式并提交，省去参考程序中的计算操作。因此 `T_ref` 是原脚本策略的参考轮数，不是所有合法策略的严格下界，`T_ref / T` 可能大于 1。正式运行保持这一原有规则；分析时须结合动作分布解释，不能将大于 1 的比值视为同步计时出错。

## 验证

```bash
.venv/bin/python -m pytest tests/test_codex_cli_model.py \
  tests/test_netagents.py::test_scaling_reference_obeys_brent_and_solves \
  tests/test_netagents.py::test_lockstep_rounds_wait_for_every_working_agent \
  tests/test_netagents.py::test_peers_run_in_lockstep_against_the_reference \
  tests/test_netagents.py::test_netscale_table_and_usl_fit -q
```

这些自动检查不使用真实 Codex 推理。真实模型的开发连通检查与正式 12 组运行分别存放，避免混入统计。
