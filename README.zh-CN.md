# World Seeds（世界种子）

[English](README.md) | [中文](README.zh-CN.md)

World Seeds 是一个研究环境，研究的是 agent 能不能**弄懂一个世界的运行规律，并记住它**。

- 每个世界都由一颗紧凑的"种子"（seed）长出来，种子里藏着这个世界的规律，agent 看不到。
- agent 在世界里探索，需要时放大（zoom in）去看细节，然后行动。
- 一局结束后，它把看到的东西巩固（consolidate）成一颗学到的种子，也就是它自己的世界模型。
- 到下一个世界时，这颗学到的种子会帮上忙。

```
世界种子 --生长--> 懒生成、可放大、会保留状态的世界 --放大 / 行动--> 事件
    ^                                                             |
    |              （隐藏规律：agent 永远读不到）                    v
学到的种子（世界模型） <------------  巩固（只用 agent 亲眼看到的东西）
```

所有东西在笔记本 CPU 上就能跑。LLM agent 用 [OpenAI Agents SDK](https://github.com/openai/openai-agents-python)
实现，可以接任何兼容 OpenAI 接口的模型服务。默认用免费的 **Qwen3-8B，由 vLLM 提供服务**。仓库里有现成的
SLURM 脚本，可以直接在 Nibi 集群（Compute Canada / Alliance）上跑完整实验。

## 环境介绍

**SeedVille（种子镇）** 是一个星露谷风格的小镇：

- 地点：你的农场、广场、杂货店、森林、山上和海边。
- 人物：8 个村民，各有职业、家和工作地点。
- 时间：每天 12 格时间，庄稼在夜里生长，村民会在镇上走动。

每个**宇宙**都有自己的一套隐藏规律：

| 积木（block） | 加入的玩法 | 隐藏规律 |
|---|---|---|
| farming 种地 | 播种、浇水、收获 | 每种作物需要什么土壤、什么季节 |
| gifting 送礼 | 送对方喜欢的礼物来交朋友 | 村民喜欢的礼物是按衣服颜色，还是按自己职业偏好的类别 |
| shop 商店 | 用有限的金币买需要的东西 | （无） |
| schedule 作息 | 村民中午会去别的地方 | 中午大家都去哪儿 |

宇宙 0 符合常识（面包师喜欢食物）。宇宙 1 及以后的规律都是打乱的，语言模型靠已有知识帮不上忙，只能自己去发现。

| 环境（env） | 一局的目标 |
|---|---|
| `town` | 拿到某个村民的奖杯（满足他的要求后，跟他说话就会给你） |
| `board` | 一周内完成**小镇告示板**上 4 个村民的请求：送新鲜作物、交朋友、从另一个村民那里拿东西转交、用赚来的金币买东西 |
| `dungeon` | 控制更严格的对照环境：房间、门、钥匙、罐子、开关、机器、巨石 |

记忆也可以存在小镇**里面**，有这几种形式：

- **图书馆**：书架按主题分类。
- **笔记**：其他 agent 写下的经验。
- **村民**：会告诉你他们行业里的经验，但有人会说错。
- **队友**：和你在同一个镇里一起干活。
- **hive（蜂群）**：很多 agent 分别在很多个小镇里，共享同一份记忆。

## 快速开始（CPU 就行，不需要 GPU）

```bash
git clone https://github.com/bochendong/EnviorementalAgent.git && cd EnviorementalAgent
pip install -r requirements.txt
pytest -q                                   # 跑全部测试，约 10 秒
```

**自己用文字玩**。可用的指令：

- `look`：看当前视图；
- `in <id>`：放大看某个东西；
- `out`：缩小回上一层；
- 任意动作，比如 `go plaza`、`take s1`、`plant p1 s1`、`give v3 i2`、`talk v3`、`ask v3`、`sleep`；
- `quit`：退出。

```bash
python scripts/play.py --env board --mode human --blocks farming gifting schedule --universe 2
python scripts/play.py --env board --mode oracle --blocks farming gifting shop schedule   # 看 oracle 怎么解
```

**在浏览器里玩**（用 Phaser 3 做的像素风客户端）。可以看录好的回放，也可以连真实引擎自己玩，按 `M` 打开小镇地图。

```bash
python scripts/serve_ui.py                  # 然后打开 http://localhost:8765
```

**用内置的规则 agent 跑一个实验**（不需要 LLM，用来检查整套流程）：

```bash
python scripts/run_experiment.py --env board --policy heuristic --protocol compgen \
       --conditions none seed oracle library --universes 1 --max-actions 200 --out results/smoke
python scripts/analyze.py results/smoke --by condition phase
```

## 接入 LLM

任何兼容 OpenAI 接口的服务都可以，比如本地的 vLLM：

```bash
vllm serve Qwen/Qwen3-8B --served-model-name qwen3-8b \
     --enable-auto-tool-choice --tool-call-parser hermes
export WS_BASE_URL=http://localhost:8000/v1 WS_MODEL=qwen3-8b WS_API_KEY=EMPTY
python scripts/play.py --env board --mode llm --condition none --verbose      # 跑一局
python scripts/run_experiment.py --env board --protocol compgen \
       --conditions none seed oracle --universes 1 --n-train 8 --n-test 4 \
       --max-actions 200 --max-turns 320 --save-traces --out results/qwen_try
```

| 环境变量 | 默认值 | 含义 |
|---|---|---|
| `WS_BASE_URL` | `http://localhost:8000/v1` | 兼容 OpenAI 接口的服务地址 |
| `WS_MODEL` | `qwen3-8b` | 服务里的模型名 |
| `WS_API_KEY` | `EMPTY` | API key（vLLM 不检查） |
| `WS_THINKING` | `0` | 设为 `1` 保留 Qwen3 的思考模式 |
| `WS_TOOL_CHOICE` | `required` | 如果服务不支持 `required`，改成 `auto` |

agent 的基本工具是 `observe`、`zoom_in`、`zoom_out`、`act`。按实验条件不同，还会多出：

- `predict`：行动前先问学到的种子会发生什么；
- `recall`：查询情景记忆；
- `write_note`：在图书馆写笔记；
- `tell`：给队友发消息。

## 实验

`scripts/run_experiment.py --protocol <实验协议> --conditions <记忆条件> ...`

| 协议（protocol） | 研究的问题 |
|---|---|
| `compgen` | 在只有 1–2 块积木的小镇里训练，记忆在没见过的 3–4 块组合里还有用吗？ |
| `persistence` | 会保留状态的世界（你种的地、你交的朋友）本身能不能充当记忆？ |
| `law_shift` | 规律变了以后，带"遗忘"的种子能不能更快恢复？ |
| `multiagent` | 多个 agent 合并种子，是否比各自学更快？ |
| `curriculum` | 通过变异种子生成新世界，是否比均匀随机采样更好？ |
| `team` | 多个 agent 合作完成同一块告示板：单人、各自干、图书馆、发消息、合并种子 |
| `hive` | 很多 agent 在并行的多个小镇里共享同一份记忆：分组、整合、验证、调度、出错的 agent |

| 记忆条件（condition） | agent 从一个世界带到下一个世界的东西 |
|---|---|
| `none` | 什么都不带 |
| `trajectory` | 最近几局的日志 |
| `retrieval` | 可以检索的情景记忆（`recall`） |
| `seed` | 学到的种子，外加 `predict` |
| `seed_llm` | 种子，外加 LLM 整理出的文字规则 |
| `oracle` | 真实规律（上限） |
| `library` / `library_flat` | 什么都不带；记忆在镇上图书馆的书架上（按主题分类 / 一堆不分类） |
| `testimony` | 什么都不带；可以问村民（`--source-errors` 会让其中一部分人说错） |

常用参数：

- `--source-errors 0 0.25 0.5`：笔记和证词的错误率，每个值一组实验。
- `--n-crops 64`：更大的宇宙，共 138 条规律，稀有作物形成长尾。
- `--hive-sizes 1 4 16 64`：hive 的 agent 数量。
- `--hive-faulty 0 0.25`：hive 里出错 agent 的比例。
- `--views zoom flat`、`--repeats`、`--save-traces`。

结果写在 `<out>/` 目录下：

- `episodes.jsonl`：每局一行。
- `traces.jsonl`：工具调用记录，需要加 `--save-traces`。
- `seeds/`：学到的种子。
- `hive.jsonl`：hive 实验每轮一行。

汇总和回放：

```bash
python scripts/analyze.py <out> --by condition variant phase --curve
python scripts/analyze_hive.py <out> --curve
python scripts/export_replay.py <out> --list        # 把某一局 LLM 的过程导出成浏览器回放
```

## 在 Nibi 上运行（Compute Canada / Alliance）

1. **初次设置**（在登录节点上做一次）。脚本会在 `$SCRATCH` 下建两个虚拟环境（一个给 vLLM 服务，一个给 agent），下载 Qwen3-8B，并跑一遍测试：
   ```bash
   git clone https://github.com/bochendong/EnviorementalAgent.git ~/EnviorementalAgent
   cd ~/EnviorementalAgent && bash slurm/setup_nibi.sh
   ```
   如果 pip 装的 vLLM 有问题，可以改用官方容器：`SERVER_MODE=apptainer bash slurm/setup_nibi.sh`，之后提交任务时也加上 `SERVER_MODE=apptainer`。
2. **填你的账号**：把 `slurm/serve_and_run.sh` 和 `slurm/hive_cpu.sh` 里的 `def-CHANGE_ME` 改成你的 allocation。
3. **先跑试点**（4 个 GPU 任务，几个小时）：
   - 告示板难度；
   - 有错误的笔记和证词；
   - 两人团队；
   - 小规模 hive。
   ```bash
   bash slurm/pilot_board.sh
   python scripts/analyze.py $SCRATCH/worldseeds/results/qwen3-8b/pilot/* --by protocol condition variant phase
   python scripts/analyze_hive.py $SCRATCH/worldseeds/results/qwen3-8b/pilot/hive
   ```
   如果连"直接给真实规律"的条件都接近 0，说明告示板太难，跑全量之前先调简单些：在 `worldseeds/envs.py` 的 `_board()` 里减少请求数或增加天数。
4. **全量实验**：80 个 GPU 任务，覆盖 5 个宇宙，每个任务在自己的 GPU 上启动一个 vLLM。另外有一个只用 CPU 的大规模 hive 任务：
   ```bash
   bash slurm/submit_all.sh                     # 可用 ENVS=board / UNIVERSES="1 2" / MODEL_ID=... 缩小范围
   sbatch slurm/hive_cpu.sh                     # 1 到 1024 个 agent，约 5 小时
   python scripts/analyze.py $SCRATCH/worldseeds/results/qwen3-8b --curve
   ```
5. **在浏览器里看**：在登录节点上运行 `python scripts/serve_ui.py`，本地执行 `ssh -L 8765:localhost:8765 nibi`，然后打开 http://localhost:8765。

**换模型**：`MODEL_ID=Qwen/Qwen3-30B-A3B-FP8 bash slurm/setup_nibi.sh`，提交时也用同一个 `MODEL_ID`。计算节点不能联网，所以模型权重必须先用 setup 脚本下载好。

## 目录结构

```
worldseeds/
  envs.py         环境注册：dungeon | town | board
  experiment.py   所有实验协议（compgen ... team、hive）和结果记录
  agent.py        LLM agent（Agents SDK）：工具、提示词、单局循环、LLM 整理器
  llm.py          兼容 OpenAI 接口的模型配置（vLLM / Qwen3）
  memory.py       学到的种子（证据、predict），检索与轨迹两种基线记忆
  hive.py         多个 agent 共享一份记忆：分组、整合者、验证、调度
  similarity.py   世界之间按干预的相似度 vs 按外观的相似度
  laws.py seed.py world.py oracle.py heuristic.py     dungeon 环境
  town/           种子镇
    seed.py       宇宙规律、小镇种子、作物（大宇宙、长尾）
    world.py      小镇本体：时钟、作物、村民、告示板、图书馆书架、村民证词
    agents.py     oracle 求解器、学到的 TownSeedMemory、规则 agent
    library.py    图书馆（主题书架、署名笔记）
    sources.py    带可控错误率的二手信息
    team.py       多个 agent 在同一个镇里
    replay.py     给浏览器客户端的回放
scripts/          run_experiment、analyze、analyze_hive、play、serve_ui、build_web、export_replay
slurm/            env、setup_nibi、serve_and_run、pilot_board、submit_all、hive_cpu
web/              Phaser 3 客户端（game.js、index.html）、像素美术和地图、美术生成工具（web/tools）
tests/            全部测试（不需要 GPU）
docs/             研究计划、研究方案评审、详细实验说明
```

## 更多文档

- [docs/experiments.md](docs/experiments.md)：每个环境、实验协议和记忆条件的详细说明，以及目前规则 agent 的结果（英文）。
- [docs/research_plan.md](docs/research_plan.md)：对研究想法的评审和第一篇论文的方案（英文）。
- [docs/world_seeds_program_seed.md](docs/world_seeds_program_seed.md)：研究计划原文。
