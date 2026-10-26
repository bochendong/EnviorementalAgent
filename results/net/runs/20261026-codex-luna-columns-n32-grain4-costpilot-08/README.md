# Luna 单次成本试跑：无效并已停止

用户授权仅1组32人 peers-columns、grain4、seed100、gpt-6-luna/high；未启动39组。固定源码f9c27c15b5223a9cd8706ce35a8e2503491f70a5，CLI0.164.0-alpha.11.1，推理总并发2；13项相关CPU测试通过。

启动：2026-10-26 10:38:39 Toronto。停止：2026-10-26T15:10:08.188510-04:00，约4小时31分。主进程已确认退出，应用自动跟进luna已删除。所有原调用、提示、回执与失败记录保留，完整CLI目录压缩在columns/codex-calls.tar.gz，并附SHA256和逐文件哈希。

停止原因：成员a3和a30分别在第33/87个请求调用了禁用的codex/list_mcp_resources。传输审计拒绝该调用，成员退出，但主运行继续等待/通信；不适合继续消耗或作为有效同协议比较。监控此前仅检查主进程和progress，未及时发现成员失败，导致无效运行持续，现已停止，不自动恢复。

- 观察到接受节点27/65，FINAL未完成；完成T不存在。
- 已知总tokens **161,420,649**：成功路径161,179,223，失败但有回执241,426；另有3次无回执调用（含停止时未完成请求），消耗未知。缓存输入和推理输出均为子项，不重复加。
- 历史同题同seed Sol完成65节点，T56、37,012,915 tokens。本轮尚未完成的已知用量已是其4.36倍；这不代表正常完成Luna的固定成本比。
- 周用量同一reset周期：2% →37%，共享账户观察增量35个百分点，剩余63%。整数显示、其他聊天/开发活动和计费延迟不能隔离归因，不能说35%全由本试跑消耗。
- 从保存的原成员对话重建观察结果：27个接受节点整数答案正确，均有完整有序4步apply证据；全局父接受时序因缺失终态原生轨迹不能完整重验。发现22次跨列执行尝试、47次重复apply、54次错误链输入、18次拒绝提交（均仅计可恢复的带结果观察）。

原run_one在返回后才写完整原生trace与终态报告；提前停止后这些文件不存在。audit_results.py从原始prompt中的function_call/function_call_output去重恢复，不伪造终态，记录截断工具结果与最后未观察到的输出缺口。context_trims/overflows终态计数不可用。完整原始调用仍在columns/episodes，成功和失败回执均单独保留。

本轮是看过Sol结果后选择seed100的探索成本试跑，不是原Sol冻结预测的复验，也未证实Luna对本任务可靠。**不建议按现状态扩跑39次；不能据此保证39次成功完成或额度够用。**即使只机械重复本次已中止成本，39次已知tokens约62.95亿，也没有完成成功保证。

复核：使用主仓库.venv/bin/python执行本目录audit_results.py（不发起任何模型调用）。生成columns/audit.json、columns/usage.json、columns/reconstructed-host-observations.jsonl.gz。历史baseline-sol-columns/runs.jsonl/trace仅seed100；该目录audit/usage保留历史3组上下文，不误当seed100统计。开发、聊天和历史tokens均排除本轮。

打包：package_results.py重新运行审计、压缩全部原始CLI调用（包括失败及停止时未完成的记录），逐文件校验压缩包与raw字节一致并扫描凭据。artifacts.json仅列精选文件，原始episodes不逐个加入Git；解压columns/codex-calls.tar.gz到columns/后可重跑审计。artifacts.json不自哈希。主状态status.json原样保留启动时running值；实际中止状态以termination.json和审计报告为准，不伪造completed。
