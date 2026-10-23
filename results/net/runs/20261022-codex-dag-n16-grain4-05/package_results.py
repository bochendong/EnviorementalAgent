"""Audit and package the completed pilot; no inference and no git mutations."""
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
OUT = ROOT / "netscale"


def read(path):
    return json.loads(path.read_text())


def save(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sharing(row):
    # The classifier in the fixed source, also used in the native summary.
    if row["agents"] == 1:
        return "none"
    if row["ops"].get("put", 0) > row["ops"].get("send", 0):
        return "store"
    return "batch" if row["ops"].get("send", 0) < 0.75 * row["tasks"] else "broadcast"


def archive(source, target):
    with tarfile.open(target, "w:gz") as tar:
        tar.add(source, arcname=source.name)
    target.with_name(target.name + ".sha256").write_text(digest(target) + "  " + target.name + "\n")


def fmt(x, digits=3):
    return "-" if x is None else f"{x:.{digits}f}"


def main():
    status = read(OUT / "status.json")
    assert status["status"] == "complete" and status["completed_runs"] == status["planned_runs"] == 3
    with (ROOT / "audit-console.log").open("w") as log:
        subprocess.run([sys.executable, str(ROOT / "audit_results.py")], stdout=log, stderr=subprocess.STDOUT, check=True)
    audit, usage = read(OUT / "audit.json"), read(OUT / "usage.json")
    assert audit["complete"] and usage["complete"] and audit["formal_runs"] == 3
    rows = sorted([json.loads(s) for s in (OUT / "runs.jsonl").read_text().splitlines() if s], key=lambda r:r["seed"])
    assert all(r["llm_errors"] == 0 for r in rows)
    patterns = [rb"sk-(?:proj-)?[A-Za-z0-9_-]{24,}", rb"gh[pousr]_[A-Za-z0-9]{30,}",
                rb"github_pat_[A-Za-z0-9_]{40,}", rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"]
    checked = 0
    for path in ROOT.rglob("*"):
        if not path.is_file() or path.suffix in (".gz", ".pyc"):
            continue
        assert not any(re.search(p, path.read_bytes()) for p in patterns), f"Possible credential in {path.relative_to(ROOT)}"
        checked += 1
    archive(OUT / "episodes", OUT / "codex-calls.tar.gz")
    if (ROOT / "failure-snapshots").exists():
        archive(ROOT / "failure-snapshots", ROOT / "failure-snapshots.tar.gz")
    s=audit["by_team_size"][0]
    total=usage["all_receipted_usage_totals"]
    pred=audit["prediction_check"]
    ops=Counter()
    for row in rows: ops.update(row["ops"])
    lines=["# 16 人 DAG grain 4：预测检验结果", "",
           f"共3组终止，正确完成最终题 {audit['solved_runs']}/3；精确接受节点 {audit['correctly_accepted_tasks']}/195。所有已接受节点的整数答案、父依赖和提交前完整4步 apply链均通过核验。未完成运行单列，不能视为完整完成时间。", "",
           "固定16×4 DAG加最终题，16人，grain4，种子100/101/102；gpt-6.1-sol/high，两组并行，总推理并发2。源码、模型提示和参考固定a064fb7。每成员预算168次，团队2688次。历史32人结果单列比较。", "",
           "|种子|最终题正确完成|正确节点|完成T|观察轮次|工具调用|回执tokens|通信启发式标签|",
           "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"|{r['seed']}|{r['solved']}|{r['done']}/65|{r.get('solved_step') if r['solved'] else '-'}|{r['steps']}|{r['llm_tool_calls']}/{r['call_budget']}|{r['input_tokens']+r['output_tokens']:,}|{sharing(r)}|")
    lines += ["", f"成功运行的平均 T={fmt(s['mean_rounds'],2)}，b={fmt(s['b'])}，a={fmt(s['a'])}，eta={fmt(s['eta'])}，相对单人提速={fmt(s['speedup'],2)}；每次团队平均工具调用 {s['mean_tool_calls']:.2f}，平均回执tokens {s['mean_total_tokens']:,.0f}。", "",
              "b=25/T，a=33/T，eta=a/(325/330)，speedup=330/T，L=(T−25)/5。单人基线来自已提交的grain4数据（7073561，模型源码1953d3c），基线用量不计入本轮。", "",
              "预测在本轮启动前已提交于a064fb7，并原样保存在predictions-a064fb7.md及preregistration.json：修正后的BSP 40轮（区间39–50），加入32人数据后拟合的USL 46轮。", "",
              f"本轮成功平均T与BSP预测的绝对距离为 {fmt(pred['absolute_error_BSP'],2)} 轮，与USL预测的距离为 {fmt(pred['absolute_error_USL'],2)} 轮；实际平均每层额外开销L={fmt(pred['observed_mean_L'])}。距离仅在3组均完整正确完成时给出。", "",
              "原预测未规定near/far的正式统计阈值，因此报告距离与逐组波动，不将较小距离自动当作统计显著支持。未用新数据重写预测或重新拟合后选择说法。历史32人平均38轮；两种人数的结果比较并未单独隔离空闲成员的因果作用。原summary.md里的自动事后外推不属于预注册预测。每人数只有3个种子，不能据此断言普适扩展规律或准确拐点。", "",
              "按相同种子标签比较（seed:T16/T32/差值）为 " + ", ".join(f"{x['seed']}:{x['T16']}/{x['T32']}/{x['difference']}" for x in pred['T16_vs_T32']['by_seed']) + "。这是观察比较，不能单独证明空闲成员吸收协调开销。", "",
              "历史中断：第三组seed102曾因额度耗尽及部分403错误停止；用户要求继续后，额度查询确认允许正常使用，按原配置从缓存恢复。前两组未重跑，原失败状态、结果、原生轨迹和失败调用保存在failure-snapshots，blocked.json仅为历史快照。", "",
              f"正式成功调用回执共 {total['total_tokens']:,} tokens = {total['input_tokens']:,} input + {total['output_tokens']:,} output；其中缓存输入 {total.get('cached_input_tokens',0):,}、思考输出 {total.get('reasoning_output_tokens',0):,} 为子项，不重复相加。缓存重放只计原请求一次。失败无回执的 {usage['attempts_without_usage_receipt']} 次记录消耗未知；开发、编程、聊天和历史基线用量排除。", "",
              f"原生工具共 {sum(ops.values())} 次：{dict(ops)}。重复apply查询 {sum(x['duplicate_apply_calls'] for x in audit['runs'])} 次，错误输入apply {sum(len(x['wrong_input_apply_calls']) for x in audit['runs'])} 次。被拒提交原因逐组见audit.json；最终模型错误为0不抹去历史服务失败记录。", "",
              "混合通信逐组计数（seed:put/send）为 " + ", ".join(f"{r['seed']}:{r['ops'].get('put',0)}/{r['ops'].get('send',0)}" for r in rows) + "。因此broadcast只是计数启发式标签，不能理解为纯广播或每题单独广播。", "",
              "b≤1以本轮实际轨迹为证据；整数验证器并不强制任意策略的查询次数。传答案标签是put/send计数的启发式，混合协议需结合原始轨迹阅读。", "",
              "复现：解压netscale/codex-calls.tar.gz到netscale/，用主仓库.venv/bin/python执行audit_results.py，不加--allow-incomplete。脚本加载source-a064fb7.tar.gz，重建审计、用量与冻结预测的距离。原summary.md、配置、源码、轨迹、完整CLI调用和SHA256均保留。启动前10项相关测试通过，测试报告见tests.xml。", ""]
    (ROOT/"README.md").write_text("\n".join(lines))
    (OUT/"README.md").write_text("# 16-agent fixed grain4 result\n\nSee ../README.md for the frozen-prediction comparison, baseline, caveats and usage; audit.json and usage.json contain the three-run audit.\n")
    selected=[p for p in ROOT.rglob("*") if p.is_file() and not p.is_relative_to(OUT/"episodes")
              and not (p.is_relative_to(ROOT/"failure-snapshots") and "calls" in p.relative_to(ROOT/"failure-snapshots").parts)
              and "__pycache__" not in p.relative_to(ROOT).parts and p.name!="artifacts.json"]
    save(ROOT/"artifacts.json", {"complete":True,"source_commit":audit["source_commit"],
         "packaged_at_toronto":datetime.now(ZoneInfo("America/Toronto")).isoformat(),
         "credential_scan_files":checked,"credential_scan_matches":0,
         "files":{str(p.relative_to(ROOT)):{"bytes":p.stat().st_size,"sha256":digest(p)} for p in sorted(selected)}})
    print(json.dumps({"runs":3,"solved":audit["solved_runs"],"tokens":total["total_tokens"],"prediction_check":pred},indent=2))


if __name__=="__main__":
    main()
