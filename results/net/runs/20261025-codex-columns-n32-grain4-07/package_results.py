"""Audit and package the three columns32 runs without inference or git mutations."""
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
OUT = ROOT / "columns"
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
    assert state["status"] == "complete" and state["completed_runs"] == state["planned_runs"] == 3
    with (ROOT / "audit-console.log").open("w") as log:
        subprocess.run([sys.executable, str(ROOT / "audit_results.py")], stdout=log, stderr=subprocess.STDOUT, check=True)
    a, u = read(OUT / "audit.json"), read(OUT / "usage.json")
    assert a["complete"] and u["complete"] and a["formal_runs"] == 3
    rows = sorted(map(json.loads, (OUT / "runs.jsonl").read_text().splitlines()), key=lambda r:r["seed"])
    summary, total = a["summary"], u["all_receipted_usage_totals"]
    ars = {r["seed"]: r for r in a["runs"]}
    pairs = a["prediction_check"]["paired_seeds"]
    lines = ["# 32人peers-columns：不分班干预", "",
             f"最终题正确完成 {a['solved_runs']}/3，节点精确接受 {a['correctly_accepted_tasks']}/195；所有已接受节点的整数答案、父依赖、提交前完整四步apply链均通过审计。", "",
             "固定16×4 DAG加最终题、grain4、32人、种子100/101/102，gpt-6.1-sol/high，两团队并行、总推理并发2。执行源码f9c27c1；运行前冻结的第四预测来自c38db0a，预测原文及哈希保留，未修改实验提示或协议。", "",
             "干预只在原Peers提示中增加COLUMNS_RULE，不在工具层强制。审计全部apply/submit尝试：Lx.K由aK执行、FINAL由a0执行，无跨列或闲置成员计算/提交。实际四层所有者均为a0–a15，a16–a31只执行wait，没有非wait协调操作，也没有第二班。逐事件违规列表（为空）、每层所有者、闲置成员操作和完整消息见columns/coordination-evidence.json。", "",
             "|种子|普通32人T|不分班T|T差|普通交接损失|不分班交接损失|join额外轮次 普通/干预|join存储读取 普通/干预|",
             "|---|---|---|---|---|---|---|---|"]
    for p in pairs:
        bp, cp = p["plain_phase"], p["columns_phase"]
        lines.append(f"|{p['seed']}|{p['plain_T']}|{p['columns_T']}|{p['T_difference']:+}|{p['plain_handoff']:.3f}|{p['columns_handoff']:.3f}|{bp['join_excess']}/{cp['join_excess']}|{bp['join_store_reads']}/{cp['join_store_reads']}|")
    lines += ["", f"不分班平均T={summary['mean_rounds']:.3f}，历史普通对照平均38；平均交接损失={summary['mean_handoff_loss']:.3f}，历史普通对照2.667。每个种子T与交接损失均增加，方向符合冻结预测；这提供干预证据，但并不等于数值精确命中或因果机制已完全隔离。", "",
              "冻结预测是T约44（从存储逐个读汇总答案时约58），交接损失约4.7–5.3。前两组损失约4.67，接近预测下缘；第三组6.33超出范围。实际T为56/56/49，不能写成44轮命中。前两组汇总各读15次存储，多花16轮，第三组读3次、多花4轮；因此总T的增加不能全部归因于层间交接。未事后重拟合或设定新的near/far阈值。", "",
              "交接损失按固定源码netagents.netscale.phases：相邻层最后接受轮次差减每层最短工作5轮，排除L0，平均L1–L3；汇总join单列。历史普通seed100/101的运行器T比轨迹中FINAL接受轮次各多1，seed102残差0；原数据不改写，审计中单列plain_T_minus_final_acceptance_round，不能强行把阶段合计写成历史T。", "",
              "对照是历史普通32人（39140ca，模型源码adf0045），按相同种子标签比较，不是同期随机分配实验。本轮保存对照runs/config/audit和原生轨迹，且不计对照用量。DAG提供者、CLI适配器、工具和Lockstep源码逐字节相同；当前含每次模型调用前裁剪修复，CLI0.164对历史0.163。本轮与历史的trims/overflows均0，但版本和模型服务随时间变化仍是限制；仅3种子，不能宣称普适因果已确证。", "",
              f"下界和分层基线25轮，沿用普通团队的脚本参考31轮：b=25/T={summary['b']:.3f}，a=31/T={summary['a']:.3f}（使用三组平均T）。31轮不是强制固定列条件下重新求出的最优参考，不将a视为受约束策略的最优接近度。团队预算4416、每成员138，保持原套件设置。每团队平均工具调用{summary['mean_tool_calls']:.3f}，成功路径平均tokens {summary['mean_successful_tokens']:,.3f}，全部回执平均tokens {summary['mean_all_receipted_tokens']:,.3f}。", "",
              "|种子|工具调用/预算|成功路径tokens|trims|peak_context估计|overflows|闲置成员wait次数|",
              "|---|---|---|---|---|---|---|"]
    for r in rows:
        ar = ars[r["seed"]]
        lines.append(f"|{r['seed']}|{r['llm_tool_calls']}/{r['call_budget']}|{r['input_tokens']+r['output_tokens']:,}|{ar['context_trims']}|{ar['peak_context']}|{ar['overflows']}|{ar['compliance']['idle_agent_operations'].get('wait',0)}|")
    lines += ["", f"已知回执总用量 {total['total_tokens']:,} tokens = {total['input_tokens']:,} input + {total['output_tokens']:,} output；缓存输入{total.get('cached_input_tokens',0):,}、思考输出{total.get('reasoning_output_tokens',0):,}为子项，不重复相加。原请求只计一次，不重复计算缓存重放；历史对照、开发、编程和聊天排除。", "",
              f"中断调用的已知回执 {u['interrupted_usage_totals']['total_tokens']:,} tokens 已包含在总量；{u['attempts_without_usage_receipt']}条失败记录无用量回执，消耗未知。首次请求曾有超时并在运行器内恢复，最终llm_errors为0不代表没有历史服务故障。约9000万为启动前粗估；实测成功路径已超过该估算，未将其冒充硬预算。", ""]
    ops = Counter()
    for r in rows:
        ops.update(r["ops"])
    lines += [f"原生操作共{sum(ops.values())}次：{dict(ops)}。重复apply {sum(r['duplicate_apply_calls'] for r in a['runs'])}，错误输入apply {sum(len(r['wrong_input_apply_calls']) for r in a['runs'])}，被拒提交{sum(sum(r['rejected_submissions'].values()) for r in a['runs'])}，模型错误{sum(r['llm_errors'] for r in rows)}。所有操作、未成功尝试和中断调用均留档。", "",
              "b≤1仅是本轮实际轨迹证据，整数验证器不强制任意策略查询次数。原summary.md保留，自动事后外推不属于冻结预测。没有运行16人、peers-msgjoin、额外种子或新对照。13项相关测试通过，见tests.xml，不是全套测试声明。", "",
              "复现：解压columns/codex-calls.tar.gz到columns/，执行audit_results.py（不加--allow-incomplete）。脚本从source-f9c27c1.tar.gz加载固定源码，重建答案/四步链、分工遵守、CLI能力与用量、冻结阶段指标和历史对照。package_results.py重建报告及归档；配置、预测、源码、完整调用、失败记录、原生轨迹和SHA均保留。artifacts.json不自哈希。", ""]
    (ROOT / "README.md").write_text("\n".join(lines))
    (OUT / "README.md").write_text("# 32-agent columns intervention\n\nSee ../README.md for audited results, compliance, frozen predictions, historical controls and usage.\n")
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
    source = ROOT / "source-f9c27c1.tar.gz"
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
                      "summary": summary, "archive_files": len(verified)}, indent=2))


if __name__ == "__main__":
    main()
