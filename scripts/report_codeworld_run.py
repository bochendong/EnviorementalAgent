"""Write a local HTML dialogue viewer from flushed experiment events; no model calls."""
import argparse
import collections
import html
import json
from pathlib import Path


def report(root):
    root = Path(root)
    path = root / "events.jsonl"
    groups = collections.defaultdict(list)
    for line in path.read_text().splitlines():
        row = json.loads(line)
        key = (row.get("universe"), row.get("variant"), row.get("sprint"), row.get("dev"))
        groups[key].append(row)
    escape = html.escape
    body = []
    for key, rows in groups.items():
        title = " / ".join(str(k) for k in key if k is not None) or "Experiment metadata"
        body.append(f'<section><h2>{escape(title)}</h2>')
        for row in rows:
            kind = row["kind"]
            if kind == "http_response" and isinstance(row.get("body"), dict):
                for choice in row["body"].get("choices", []):
                    message = choice.get("message", {})
                    for name in ("reasoning_content", "reasoning", "content"):
                        if message.get(name):
                            body.append(f'<h3>{escape(name)}</h3><pre>{escape(str(message[name]))}</pre>')
            text = json.dumps(row, ensure_ascii=False, indent=2)
            label = f"#{row['seq']} {kind}"
            if kind == "tool_result":
                label += " — " + row["tool"] + ": " + row["out"][:100]
            body.append(f'<details><summary>{escape(label)}</summary><pre>{escape(text)}</pre></details>')
        body.append('</section>')
    document = '''<!doctype html><html lang="zh"><meta charset="utf-8"><title>Qwen experiment record</title>
<style>body{max-width:1100px;margin:35px auto;font:16px/1.6 system-ui;padding:0 20px;background:#faf9f6;color:#222}
section{background:white;padding:20px;margin:24px 0;border:1px solid #ddd;border-radius:10px}
pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:13px}summary{cursor:pointer;padding:6px}h3{color:#315a78}</style>
<h1>Qwen 实验过程记录</h1><p>按宇宙、方案、轮次和玩家分组。点击展开完整输入、原始响应、动作反馈和异常。
推理文字只代表服务实际返回的模型输出；没有返回时不会补写。事件序号可用于还原多玩家交错顺序。
小镇动画请在工坊页面加载同目录的 replay.json。</p>'''+"\n".join(body)+"</html>"
    (root / "process.html").write_text(document)
    print(f"process viewer -> {root / 'process.html'}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("directory")
    report(ap.parse_args().directory)
