"""Audit and package the six width8 runs without inference or git mutations."""
from collections import Counter
from datetime import datetime
import gzip
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tarfile
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "netscale-slack"
PATTERNS = [rb"sk-(?:proj-)?[A-Za-z0-9_-]{24,}", rb"gh[pousr]_[A-Za-z0-9]{30,}",
            rb"github_pat_[A-Za-z0-9_]{40,}", rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"]


def read(p):
    return json.loads(p.read_text())


def save(p, d):
    p.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n")


def digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def scan(data, name):
    if name.endswith(".gz"):
        data = gzip.decompress(data)
    assert not any(re.search(p, data) for p in PATTERNS), f"Possible credential: {name}"


def main():
    state = read(OUT / "status.json")
    assert state["status"] == "complete" and state["completed_runs"] == state["planned_runs"] == 6
    with (ROOT / "audit-console.log").open("w") as log:
        subprocess.run([sys.executable, str(ROOT / "audit_results.py")], stdout=log, stderr=subprocess.STDOUT, check=True)
    a, u = read(OUT / "audit.json"), read(OUT / "usage.json")
    assert a["complete"] and u["complete"] and a["formal_runs"] == 6
    rows = sorted(map(json.loads, (OUT / "runs.jsonl").read_text().splitlines()), key=lambda r: (r["agents"], r["seed"]))
    ar = {(r["agents"], r["seed"]): r for r in a["runs"]}
    s8, s16 = a["by_team_size"]
    total = u["all_receipted_usage_totals"]
    lines = ["# 宽8 DAG grain4：8人与16人样本外检验", "",
             f"正确完成最终题 {a['solved_runs']}/6，精确接受节点 {a['correctly_accepted_tasks']}/198；全部已接受节点的整数答案、父依赖和提交前完整四步apply链通过审计。", "",
             "固定宽8、深4、grain4，每组33节点；人数8/16，各种子100/101/102。gpt-6.1-sol/high，两团队并行、总推理并发2。执行源码4f768d7；预测在2bc81ba提交，运行前原样冻结，未修改提示、策略或预测。", "",
             "|种子|T8|T16|T8/T16|交接损失8人|交接损失16人|join额外轮次8/16|join存储读取8/16|",
             "|---|---|---|---|---|---|---|---|"]
    for p in a["prediction_check"]["paired_seeds"]:
        x, y = ar[8, p["seed"]], ar[16, p["seed"]]
        lines.append(f"|{p['seed']}|{p['T8']}|{p['T16']}|{p['T8_over_T16']:.3f}|{p['handoff8']:.3f}|{p['handoff16']:.3f}|{x['phase']['join_excess']}/{y['phase']['join_excess']}|{x['phase']['join_store_reads']}/{y['phase']['join_store_reads']}|")
    lines += ["", "交接损失按冻结源码netagents.netscale.phases计算：后一层最后接受轮次减前层最后接受轮次，再减该层最短工作轮次；排除L0，平均L1至L3。join单列，未混入交接指标。", "",
              f"平均T：8人{s8['mean_rounds']:.3f}、16人{s16['mean_rounds']:.3f}；交接损失分别{s8['mean_handoff_loss']:.3f}和{s16['mean_handoff_loss']:.3f}。三个种子T16<T8、交接损失16人低于8人均成立；这支持本次预先写下的方向性预测。", "",
              "冻结数值为T8=42、T16=37，交接损失约4.5/2.7轮。实测T分别比预测低3.333/2.333轮，交接损失也低于预测值；方向成立不等于精确数值命中，未设定新的显著性或near/far阈值，也未重新拟合挑选说法。", "",
              "轨迹证据：8人三个种子均由a0–a7按列完成所有层。16人三个种子均由a0–a7完成L0/L2，a8–a15完成L1/L3；实际接受任务的成员与此相符，而非仅有口头分工。完整逐层所有者和原始消息见coordination-evidence.json。每人数只有3个种子，团队同时可能改变通信和汇总方式，尚不能单独确证第二班降低交接损失的因果作用。", "",
              "所有运行的join都未从共享存储拉取答案（join_store_reads=0），所以关于逐个读存储会增加汇总成本的次要预测，本轮没有提供可检验样本。传答案按put/send自动标签仅为启发式；16人seed102有9次put但没有join存储读取，不能据此推断汇总机制。", "",
              "|人数|正确完成|平均T|b=25/T|a=T_ref/T|平均工具调用|成功路径平均tokens|全部回执平均tokens|",
              "|---|---|---|---|---|---|---|---|"]
    for s in (s8, s16):
        lines.append(f"|{s['agents']}|{s['solved']}/{s['runs']}|{s['mean_rounds']:.3f}|{s['b']:.3f}|{s['a']:.3f}|{s['mean_tool_calls']:.3f}|{s['mean_total_tokens']:,.3f}|{s['mean_all_receipted_tokens']:,.3f}|")
    lines += ["", "两种人数的理论下界和分层工作基线均25轮，参考分别33/31轮。没有同宽8的单人LLM基线，eta与单人加速比不报告，不借用历史宽16的330轮。T8/T16按种子列出；平均T之比为 " + f"{s8['mean_rounds']/s16['mean_rounds']:.3f}" + "，表示16人相对8人的速度比。", "",
              f"已知回执总量 {total['total_tokens']:,} tokens = {total['input_tokens']:,} input + {total['output_tokens']:,} output。缓存输入{total.get('cached_input_tokens',0):,}与思考输出{total.get('reasoning_output_tokens',0):,}是子项，不重复加。只计各原请求一次，编程、聊天、开发和历史实验排除；失败无回执记录{u['attempts_without_usage_receipt']}条，未记录的消耗不能凭空补计。启动前约7000万是估算，实测由回执给出。", "",
              f"成功路径回执{u['totals']['total_tokens']:,} tokens，另有两条重连/403中断调用记录最终带用量回执，共{u['interrupted_usage_totals']['total_tokens']:,} tokens，均纳入上述总量和全部回执平均值。最终模型错误为0不代表历史没有服务重连。工具调用和下表tokens为被正式轨迹采用的成功路径，未采用的中断回执另列在usage.json。", "",
              "逐组用量：", "", "|人数|种子|工具调用/团队预算|tokens|trims|peak_context估计|overflows|", "|---|---|---|---|---|---|---|"]
    for r in rows:
        audit = ar[r["agents"], r["seed"]]
        lines.append(f"|{r['agents']}|{r['seed']}|{r['llm_tool_calls']}/{r['call_budget']}|{r['input_tokens']+r['output_tokens']:,}|{audit['context_trims']}|{audit['peak_context']}|{audit['overflows']}|")
    ops = Counter()
    for r in rows:
        ops.update(r["ops"])
    lines += ["", f"原生操作共{sum(ops.values())}次：{dict(ops)}。重复apply {sum(r['duplicate_apply_calls'] for r in a['runs'])}，错误输入apply {sum(len(r['wrong_input_apply_calls']) for r in a['runs'])}，被拒提交{sum(sum(r['rejected_submissions'].values()) for r in a['runs'])}，最终模型错误{sum(r['llm_errors'] for r in rows)}。源码含每次调用前裁剪修复，版本和裁剪/overflow计数均保留；不以接口成功替代答案正确。", "",
              "b≤1是本轮实际轨迹观察；整数验证器并不强制任意策略查询次数。原summary.md保留，其中自动事后外推不属于本轮冻结预测。未运行4人、12人或额外种子。启动前12项相关测试通过，见tests.xml，不是全套测试声明。", "",
              "复现：解压netscale-slack/codex-calls.tar.gz到netscale-slack/，执行audit_results.py（不加--allow-incomplete）。审计从source-4f768d7.tar.gz加载固定源码，核对全部6组、四步链、CLI能力与usage回执、交接指标和逐种子预测对照。package_results.py可重建报告和归档；完整原生轨迹、配置、源码和预测均保留，artifacts.json本身不自哈希。", ""]
    (ROOT / "README.md").write_text("\n".join(lines))
    (OUT / "README.md").write_text("# Width8 grain4, sizes8/16\n\nSee ../README.md for results, frozen predictions, trace evidence, usage and limits.\n")
    archive = OUT / "codex-calls.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(OUT / "episodes", arcname="episodes")
    archive.with_name(archive.name + ".sha256").write_text(digest(archive) + "  " + archive.name + "\n")
    checked = 0
    for f in ROOT.rglob("*"):
        if not f.is_file() or "__pycache__" in f.parts or f.name.endswith(".tar.gz"):
            continue
        scan(f.read_bytes(), str(f.relative_to(ROOT)))
        checked += 1
    verified = set()
    with tarfile.open(archive) as tar:
        for m in tar:
            if not m.isfile():
                continue
            data = tar.extractfile(m).read()
            assert data == (OUT / m.name).read_bytes(), m.name
            scan(data, m.name)
            verified.add(m.name)
    assert verified == {str(f.relative_to(OUT)) for f in (OUT / "episodes").rglob("*") if f.is_file()}
    source = ROOT / "source-4f768d7.tar.gz"
    assert digest(source) == read(ROOT / "launch.json")["source_sha256"]
    with tarfile.open(source) as tar:
        for m in tar:
            if m.isfile():
                scan(tar.extractfile(m).read(), m.name)
    save(ROOT / "verification.json", {"archive_files_byte_verified": len(verified), "credential_scan_files": checked,
                                      "credential_scan_matches": 0, "source_archive_hash_verified": True})
    files = [f for f in ROOT.rglob("*") if f.is_file() and not f.is_relative_to(OUT / "episodes")
             and "__pycache__" not in f.parts and f.name != "artifacts.json"]
    save(ROOT / "artifacts.json", {"complete": True, "source_commit": a["source_commit"],
         "packaged_at_toronto": datetime.now(ZoneInfo("America/Toronto")).isoformat(),
         "files": {str(f.relative_to(ROOT)): {"bytes": f.stat().st_size, "sha256": digest(f)} for f in sorted(files)}})
    print(json.dumps({"solved": a["solved_runs"], "nodes": a["correctly_accepted_tasks"], "tokens": total["total_tokens"],
                      "prediction_check": a["prediction_check"], "archive_files": len(verified)}, indent=2))


if __name__ == "__main__":
    main()
