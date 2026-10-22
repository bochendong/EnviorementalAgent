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
OUT = ROOT / "netscale-pilot"


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


def main():
    status = read(OUT / "status.json")
    assert status["status"] == "complete" and status["completed_runs"] == status["planned_runs"] == 12
    with (ROOT / "audit-console.log").open("w") as log:
        subprocess.run([sys.executable, str(ROOT / "audit_results.py")], stdout=log, stderr=subprocess.STDOUT, check=True)
    audit, usage = read(OUT / "audit.json"), read(OUT / "usage.json")
    assert audit["complete"] and usage["complete"] and audit["formal_runs"] == 12
    rows = [json.loads(s) for s in (OUT / "runs.jsonl").read_text().splitlines() if s]
    assert all(r["llm_errors"] == 0 for r in rows)

    patterns = [rb"sk-(?:proj-)?[A-Za-z0-9_-]{24,}", rb"gh[pousr]_[A-Za-z0-9]{30,}",
                rb"github_pat_[A-Za-z0-9_]{40,}", rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"]
    checked = 0
    for folder in (OUT / "episodes", ROOT / "development-smoke", ROOT / "failure-snapshots"):
        for path in folder.rglob("*"):
            if not path.is_file() or path.suffix in (".gz", ".pyc"):
                continue
            data = path.read_bytes()
            assert not any(re.search(p, data) for p in patterns), f"Possible credential in {path.relative_to(ROOT)}"
            checked += 1
    archive(OUT / "episodes", OUT / "codex-calls.tar.gz")
    archive(ROOT / "development-smoke", ROOT / "development-calls.tar.gz")

    ops = Counter()
    for row in rows:
        ops.update(row["ops"])
    rejected = Counter()
    for run in audit["runs"]:
        rejected.update(run["rejected_submissions"])
    stats = audit["by_team_size"]
    old = read(ROOT / "grain1-reference-1953d3c.json")["by_team_size"]
    old8, new8 = old[-1], stats[-1]
    lines = ["# Codex DAG grain 4：正式结果", "",
             f"12/12 组正确完成；{audit['correctly_accepted_tasks']}/780 个节点的整数答案、父依赖和提交前完整四步 apply 链通过核验。最终重放结果无模型错误；中途额度中断及其失败记录单列保留。", "",
             "固定 16×4 DAG 加最终题，1/2/4/8 人各 3 个种子（100/101/102）。模型 gpt-6.1-sol，high；两组并行，总推理并发 2。源码和参考均固定 1953d3c；原 Peers、Lockstep、预算与提示未修改。", "",
             "|人数|T：种子100/101/102|平均T|T_lb|b|T_ref|a|eta|提速|平均工具调用|平均tokens|传答案方式（启发式标签）|",
             "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for s in stats:
        rs = sorted((r for r in rows if r["agents"] == s["agents"]), key=lambda r: r["seed"])
        ts = "/".join(str(r["solved_step"]) for r in rs)
        labels = ", ".join(f"{k}×{v}" for k, v in Counter(sharing(r) for r in rs).items())
        lines.append(f"|{s['agents']}|{ts}|{s['mean_rounds']:.2f}|{s['lower_bound']}|{s['b']:.3f}|{s['mean_reference_rounds']:.0f}|{s['a']:.3f}|{s['eta']:.3f}|{s['speedup']:.2f}|{s['mean_tool_calls']:.2f}|{s['mean_total_tokens']:,.0f}|{labels}|")
    total = usage["all_receipted_usage_totals"]
    lines += ["", "T 为正确完成最终题的同步轮次。b=T_lb/T，a=T_ref/T，eta=a(N)/a(1)，提速=T(1)/T(N)。表内均值按三个种子计算；完成率指精确整数验证通过，非仅发起提交。", "",
              f"8 人对照：grain 1 的 b={old8['b']:.3f}、a={old8['a']:.3f}、eta={old8['eta']:.3f}、提速={old8['speedup']:.2f}；grain 4 分别为 {new8['b']:.3f}、{new8['a']:.3f}、{new8['eta']:.3f}、{new8['speedup']:.2f}。两组均使用 1953d3c 参考。", "",
              "这是两轮观察的比较：grain 1 的模型源码为 cb69623，grain 4 为修复链重复后的 1953d3c，函数值也改变，故不是严格相同题目的配对实验。每人数仅 3 个种子；传答案标签来自 put/send 计数启发式，混合通信需要结合轨迹阅读，不能单独证明通信方式的因果作用。旧递推题试跑的参考效率不纳入结论。", "",
              f"正式调用回执总用量：{total['total_tokens']:,} tokens = {total['input_tokens']:,} input + {total['output_tokens']:,} output。其中缓存输入 {total.get('cached_input_tokens',0):,}、思考输出 {total.get('reasoning_output_tokens',0):,} 均为子项，不重复相加。缓存重放不另计新用量。失败或中断但无回执的 {usage['attempts_without_usage_receipt']} 次记录消耗未知；开发小检查、编程、报告与聊天用量排除。分组平均值对应最终成功调用回执，其他失败回执单列见 usage.json。", "",
              f"工具动作合计 {sum(ops.values()):,} 次：" + ", ".join(f"{k}={v}" for k,v in sorted(ops.items())) + "。",
              f"重复 apply 查询 {sum(r['duplicate_apply_calls'] for r in audit['runs'])} 次；被拒提交原因：{dict(rejected)}。错误输入的 apply 共 {sum(len(r['wrong_input_apply_calls']) for r in audit['runs'])} 次。", "",
              "审计证明的是本轮观察到的完整 apply 链与 b≤1。整数验证器不强制查询次数，不能将其表述为对任意猜测策略的形式保证。USL 拟合及逐节点链证据见 audit.json；小规模拟合不用于断言普适拐点。", "",
              "复现：解压 netscale-pilot/codex-calls.tar.gz 至 netscale-pilot/，再用主仓库 .venv/bin/python 执行 audit_results.py（不加 --allow-incomplete）。脚本读取 source-1953d3c.tar.gz，重建审计与用量。原 summary.md 保留；配置、轨迹、源码、完整调用压缩包和 SHA256 一并保存。", "",
              "运行曾于 10/12 组时因额度停止；用户确认恢复后，只对缺失两组重放缓存并继续。blocked.json 是当时的历史快照；failure-snapshots/ 保存旧状态、结果和失败轨迹，launch.json 保存原 PID、续跑 PID 及授权记录。", "",
              "开发验证另列：种子 0 的 3 题真实模型检查全对、16 轮，完整链通过；开发种子 0/1/2 的 195 条链无重复值。9 项相关测试通过；广测 64 通过、2 跳过、12 失败，失败涉及 RDKit/网站沙箱环境，不宣称全套通过。开发调用归档与正式调用分开。", ""]
    (ROOT / "README.md").write_text("\n".join(lines))
    (OUT / "README.md").write_text("# Audited grain 4 pilot\n\nSee ../README.md for the concise table, formulas, grain 1 comparison, usage scope and replay instructions. status.json, audit.json and usage.json are final 12-run files. codex-calls.tar.gz contains the complete formal episode records, including preserved interrupted attempts.\n")

    selected = [p for p in ROOT.rglob("*") if p.is_file()
                and not p.is_relative_to(OUT / "episodes")
                and not p.is_relative_to(ROOT / "development-smoke")
                and "__pycache__" not in p.relative_to(ROOT).parts
                and p.name != "artifacts.json"]
    manifest = {"complete": True, "source_commit": audit["source_commit"],
                "packaged_at_toronto": datetime.now(ZoneInfo("America/Toronto")).isoformat(),
                "credential_pattern_scan_files": checked, "credential_pattern_scan_matches": 0,
                "formal_runs": len(rows), "native_tool_calls": sum(ops.values()),
                "files": {str(p.relative_to(ROOT)): {"bytes": p.stat().st_size, "sha256": digest(p)} for p in sorted(selected)}}
    save(ROOT / "artifacts.json", manifest)
    print(json.dumps({"complete": True, "runs": len(rows), "tokens": total["total_tokens"],
                      "formal_archive_bytes": (OUT / "codex-calls.tar.gz").stat().st_size,
                      "selected_files": len(selected) + 1}, indent=2))


if __name__ == "__main__":
    main()
