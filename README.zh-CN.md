# World Seeds（世界种子）

[English](README.md) | [中文](README.zh-CN.md)

![种子镇的浏览器界面：一周期限的小镇告示板、时钟、金币和操作栏](docs/images/play_mode.png)

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

## 新方向：CodeWorld，开发者 agent 网络

详见 [docs/codeworld.md](docs/codeworld.md)（含中文）。目标是一个 agent 网络：整体知识量超过任何单个 agent 能装下的量，为以后多 agent 并行、跨领域开发打基础。CodeWorld 是一个程序化生成的软件生态：模块暴露函数，签名公开、行为隐藏；项目是功能需求，要用到多个模块的函数；开发者的笔记本容量有限，靠实验或问同事来学规律。它检验一个命题：只有当世界大到一个人装不下时，网络才会胜过等算力的单个 agent，而且前提是网络知道"谁知道什么"。规则开发者的结果：64 个函数、每人能记 16 条规律时，按模块负责人提问的 4 人团队完成 0.96 的项目，拿全队算力的单人 0.32，同一团队随机提问 0.27。

同一个世界也可以当城市来看：**SeedVille Workshops**（`web/codeworld.html`）在由多张相连地图（小镇、农场、海滩、山区）组成的小镇里回放记录下来的冲刺：工坊（模块）是能看到内部的房间，学徒走到机器（函数）前研究，师傅（负责人）回答提问，学徒沿最短路线在地图之间走动。标准小镇（48 台机器、每人记 12 条、4 个学徒）里师傅制完成全部订单，拿全队时间的单个学徒 46%；三个街区（12 张地图、144 台机器、12 个学徒）时单人只有 2%。

```bash
python scripts/build_codeworld_web.py && python -m http.server -d web 8000   # 打开 http://localhost:8000/codeworld.html
```

![SeedVille Workshops](docs/images/workshops_town.png)

```bash
python scripts/run_codeworld.py --out results/codeworld/core && python scripts/analyze_codeworld.py results/codeworld/core
```

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

## 截图

| | |
|---|---|
| ![农场](docs/images/farm.png) | ![小镇广场](docs/images/town_board.png) |
| **你的农场。** 四块土壤不同的地、种子包、浇水壶。作物种错了土或季节，过一夜就会失败，而这次失败本身就是证据。 | **小镇广场。** 告示板上列着本周的请求；村民中午会聚到这里（或者别的地方，取决于宇宙）。 |
| ![庄稼](docs/images/crops.png) | ![送礼](docs/images/interior.png) |
| **庄稼在夜里生长**，前提是浇了水，土壤和季节也都对。 | **送礼。** 医生 Mira 很喜欢黄色的金属锭：这个宇宙里医生喜欢金属类，跟常识不一样。 |
| ![完成请求](docs/images/request_done.png) | ![图书馆](docs/images/library.png) |
| **完成一个请求。** 友情到了 2，请求被划掉，并拿到金币。 | **图书馆。** 按主题分类的书架上存着以前小镇学到的东西，读书要花时间。 |
| ![问村民](docs/images/ask_villager.png) | ![小镇地图](docs/images/town_map.png) |
| **问村民。** 花店老板会讲土壤，但有些村民一直会说错。 | **小镇地图**（按 `M`）：农场、广场、小巷、山上和海边，以及每一户人家和每个工作地点。 |

## 怎么玩

你是刚搬来的农夫。在 `board` 玩法里，你有**一周时间**完成告示板上的 4 个请求，每完成一个得 4 金币。

1. **四处看看。** 每个地方都会显示那里的人和物品。细节要放大看（`in <id>` / `zoom_in`）才看得到：一块地是什么土、一个村民的职业和友情值、一件物品属于哪一类。
2. **种地。** 拿上种子和浇水壶，在地里 `plant`，每天 `water`，然后 `sleep`。每种作物要对应的土壤和季节，任何一个不对，过一夜就会枯萎或休眠。成熟的地收获一次能得到三个作物。
3. **交朋友。** 给村民 `give` 他们喜欢的东西。喜欢什么由隐藏规律决定：要么看衣服颜色，要么看职业偏好的类别，而且哪个职业喜欢哪一类，每个宇宙都不一样。
4. **拿东西和买东西。** 有的请求要的东西在另一个村民手上（关系够好他才会给你），有的要去商店买（金币来自之前完成的请求）。
5. **找人。** 村民早上和晚上在家，中午会去某个地方（广场、商店、家里或工作地点，取决于宇宙）。
6. **交差。** 请求满足后，跟发请求的村民 `talk`。

真正的限制是时间：每个动作花掉一天 12 格中的一格，作物还要过夜才能长大。会玩的人第一天就把庄稼种下，等它长的时候去做别的请求。同一个宇宙里所有小镇的规律都一样，所以在一个镇学到的东西，到下一个镇还有用。

## 适合做什么研究

| 研究问题 | 种子镇怎么测量 |
|---|---|
| agent 能不能通过亲手干预**发现因果规律**，而不是靠已有知识？ | 每个宇宙的规律都打乱（宇宙 0 符合常识，1–5 不符合）；学到的种子逐条和真实规律比对打分 |
| **世界模型**：应该学什么样的表示？拿它来做规划有没有用？ | `predict` 让 agent 行动前先问学到的种子；引擎对任意（状态, 动作）都能给出精确的下一状态，所以世界模型的预测可以精确核对 |
| **组合泛化** | 在 1–2 块积木的小镇上训练，在没见过的 3–4 块组合上测试（`compgen`） |
| **记忆**：存在脑子里、日志里、检索库里，还是存在世界里？ | `none` / `trajectory` / `retrieval` / `seed` / `library`，以及会保留状态的世界（`persistence`） |
| 世界变化时的**持续学习** | `law_shift`（规律中途改变；带遗忘 vs 不带遗忘） |
| **信任**：别的 agent 的记忆有一部分是错的，怎么用 | 错误率可控的笔记和村民证词（`--source-errors`） |
| 多个 agent 的**协作与记忆共享** | 同一块告示板上的团队（`team`）；最多 1,024 个 agent 在并行小镇里组成 hive，带分组、整合、验证和出错的 agent（`hive`） |
| **探索与课程学习** | 通过变异种子生成新世界（`curriculum`）；hive 里的调度者把 agent 派去探索最不确定的规律 |
| **自进化 agent 与奖励作弊（reward hacking）** | 一代代 agent 继承的是"怎么学"（一组基因，或由 LLM 写的策略手册），按真实成绩或按自我评估选择，再到没见过的宇宙里测试（`evolve`） |
| **把记忆画成一张图**：长任务和视觉语言模型的上下文 | 用固定大小、多分辨率的"画布"代替对话记录，可以是文字，也可以是图片（`--context canvas / image`） |
| **现实条件下做科研** | 有噪声的实验、便宜但会错的快速筛选、混杂因素、发表偏倚，以及把同一套规律讲成药物研发（`--noise`、`--screen-error`、`--confounder`、`--publication-bias`、`--skin drug`） |

## 它新在哪里

现有的大多数 agent 环境只有一套固定规则，而且通常是语言模型在预训练里早就学过的日常规则：文字冒险游戏、ALFWorld 这类家务任务、类 Minecraft 的合成游戏、对星露谷这类真实游戏的仿真。另一类是学出来的模拟器（语言世界模型），能预测很多领域的环境反馈，但没有精确的标准答案可以拿来打分。

据我们所知，种子镇是第一个同时具备下面这些特点的环境：

- **世界由种子长出来，隐藏的因果规律可以随意打乱。** 每个宇宙规律不同，成功靠发现而不是回忆；agent 相信的每条规律都能判定为对、错或未知，评估的不只是任务有没有完成。
- **组合式积木。** 种地、送礼、商店、作息可以自由组合，所以"能不能泛化到没见过的组合"是一个可控实验；更大的宇宙（`--n-crops 64`，138 条规律，带长尾）留出了扩展空间。
- **放大（zoom）。** 世界是分层的（地图、地点、物体），细节只有放大看才感知得到，所以注意力、以及由不确定性驱动的查看，都是任务的一部分。
- **记忆可以存在世界里。** 会保留的田地和友情、按主题分类的图书馆、其他 agent 写的笔记、村民的证词，每一种的可靠性都可以控制。
- **很多 agent，一份记忆。** 从同一块告示板上的两个队友，到 1,024 个 agent 的 hive，用的正是大规模 agent 集群的那些开关（分组、整合者、引导、验证），而且全部可以对照真实规律来衡量。
- **便宜、看得见。** 纯 Python，CPU 上每步只要毫秒级，能同时开几千个小镇；可以接任何兼容 OpenAI 接口的 LLM；每一局都能在像素风的浏览器客户端里回放。

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
| `hive` | 很多 agent 在并行的多个小镇里共享同一份记忆：分组、整合、验证、调度、出错的 agent、溯源、规律变化 |
| `evolve` | 一代代 agent 继承"怎么学"；按真实成绩还是自我评估选择；迁移到没见过的宇宙 |

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
- 前沿研究的开关：`--context`、`--zoom-budget`、`--noise`、`--screen-error`、`--confounder`、`--publication-bias`、`--skin`、`--festival`、`--roles`、`--hive-faulty-mode`、`--hive-shift-wave`。

结果写在 `<out>/` 目录下：

- `episodes.jsonl`：每局一行。
- `traces.jsonl`：工具调用记录，需要加 `--save-traces`。
- `seeds/`：学到的种子。
- `hive.jsonl`：hive 实验每轮一行。

汇总和回放：

```bash
python scripts/analyze.py <out> --by condition variant phase --curve
python scripts/analyze_hive.py <out> --curve
python scripts/analyze_evolve.py <out>              # evolve：每一代的成绩、作弊差距、迁移
python scripts/export_replay.py <out> --list        # 把某一局 LLM 的过程导出成浏览器回放
```

## 前沿研究（frontier studies）

下面每一项都把 agent 研究里的一个开放问题变成同一个环境上的一个开关。详细说明和目前 CPU 上的结果见
[docs/experiments.md#frontier-studies](docs/experiments.md#frontier-studies)（英文）。

| 开关 | 研究的问题 | 目前规则 agent（CPU）的结果 |
|---|---|---|
| `solo_matched`（团队）、`serial`（hive） | 同样的算力下，团队真的比一个 agent 强吗？ | 并行的 agent 学到的规律和"一个 agent 依次玩同样的世界"一样多（127 vs 126 条）；团队的优势来自共享知识，以及必须两个人才能完成的任务 |
| `--zoom-budget k` | 仔细看东西要花注意力，会怎样？ | 规则 agent 几乎不受影响；这个开关主要是给 LLM 的 |
| `--context canvas` / `image` | 用固定大小的记忆画布（当前位置清晰，越早越模糊，外加 agent 自己改写的笔记）代替对话记录；给视觉语言模型时画成图片 | LLM 实验（`slurm/submit_frontier.sh`、`slurm/submit_vision.sh`） |
| `--noise`、`--screen-error`、`--confounder`、`--publication-bias` | 实验有噪声、快速筛选便宜但会错、原因被混杂、只发表阳性结果时，agent 还能做好科研吗？ | 发表偏倚让图书馆自信地记下错误规律；快速筛选拖慢学习，只是因为学习者把它当成了证据（权重为 0 时没有害处） |
| `--skin drug` | 同一套规律讲成化合物、靶点和实验方案：换成科研的说法，agent 的行为会变吗？ | LLM 实验（规则 agent 不读文字） |
| `--protocol evolve` | 继承"怎么学"能让 agent 一代比一代强吗？按自我评估选择会导致奖励作弊吗？能迁移吗？ | 按"自称知道多少"选择，错误的说法翻倍，真实成绩没有提高；进化后的学习者在没见过的宇宙里学得更快 |
| `--festival`、`--roles` | 只有团队才能完成的任务（用新鲜作物做一道菜、两个人一起去拜访），以及各自只能感知一部分信息（土壤 / 人 / 货物） | 给了同样算力的单个 agent 也只完成 0.60，团队 0.91 |
| `--hive-faulty-mode groups`、`hive_provenance`、`--hive-audit replicate`、`--hive-shift-wave`、`hive_regional` | 说谎的 agent 口径一致且占多数时，hive 还能找到真相吗？某个地区的规律变了，共享记忆会怎样？ | 溯源加上由 agent 在真实世界里复现的抽查，把错误规律从 8.5 条降到 2 条；按地区分开的记忆让规律变化后的错误认知减半 |

那一节最后是一个已经可以直接跑的迁移研究：种子镇上的分数，对不同 agent 配置的排名，和真实科研基准的排名一致吗？`scripts/run_labbench.py` 用同一个服务器跑 LAB-Bench 选择题，其他基准（例如 BixBench）的分数直接填数字，`scripts/transfer_analysis.py` 给出排名相关系数、bootstrap 置信区间，以及控制协变量后的偏相关。

## 在 Nibi 上运行（Compute Canada / Alliance）

1. **初次设置**（在登录节点上做一次）。脚本会在 `$SCRATCH` 下建两个虚拟环境（一个给 vLLM 服务，一个给 agent），下载 Qwen3-8B，并跑一遍测试：
   ```bash
   git clone https://github.com/bochendong/EnviorementalAgent.git ~/EnviorementalAgent
   cd ~/EnviorementalAgent && bash slurm/setup_nibi.sh
   ```
   如果 pip 装的 vLLM 有问题，可以改用官方容器：`SERVER_MODE=apptainer bash slurm/setup_nibi.sh`，之后提交任务时也加上 `SERVER_MODE=apptainer`。
2. **填你的账号**：把 `slurm/serve_and_run.sh`、`slurm/frontier_cpu.sh` 和 `slurm/hive_cpu.sh` 里的 `def-CHANGE_ME` 改成你的 allocation。
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
5. **前沿研究**（LLM 任务、视觉语言模型任务和一个 CPU 扫描任务）：
   ```bash
   PILOT=1 bash slurm/submit_frontier.sh        # 先跑小规模版本
   bash slurm/submit_frontier.sh                # 可用 STUDIES="context realism skin team evolve hive perception" 选择
   MODEL_ID=Qwen/Qwen3-VL-8B-Instruct bash slurm/setup_nibi.sh && bash slurm/submit_vision.sh
   sbatch slurm/frontier_cpu.sh
   ```
6. **迁移研究**（每个模型一个 GPU 任务：一组种子镇实验加 LAB-Bench）：`bash slurm/submit_transfer.sh`，然后 `python scripts/transfer_analysis.py <study.json>`。
7. **在浏览器里看**：在登录节点上运行 `python scripts/serve_ui.py`，本地执行 `ssh -L 8765:localhost:8765 nibi`，然后打开 http://localhost:8765。

**换模型**：`MODEL_ID=Qwen/Qwen3-30B-A3B-FP8 bash slurm/setup_nibi.sh`，提交时也用同一个 `MODEL_ID`。计算节点不能联网，所以模型权重必须先用 setup 脚本下载好。

## 目录结构

```
worldseeds/
  envs.py         环境注册：dungeon | town | board
  experiment/     实验：配置（按主题分组，命令行参数由它自动生成）、运行器、各实验协议（classic、team、hive、evolve）、记忆、结果记录
  agent.py        LLM agent（Agents SDK）：工具、提示词、单局循环、LLM 整理器
  canvas.py       画布记忆：固定大小、多分辨率的上下文，加上可改写的笔记
  render.py       给视觉语言模型的图片（随缩放层级变化的视图，画布渲染成页面）
  skin.py         同一个世界换一种讲法（药物研发）
  evolve.py       自进化：基因、策略手册、导师、存档
  transfer.py     迁移研究：种子镇能力分数、LAB-Bench、排名统计
  llm.py          兼容 OpenAI 接口的模型配置（vLLM / Qwen3）
  memory.py       学到的种子（证据、predict），检索与轨迹两种基线记忆
  hive.py         多个 agent 共享一份记忆：分组、整合者、验证、调度、口径一致的说谎者、溯源与抽查、按新旧取舍
  similarity.py   世界之间按干预的相似度 vs 按外观的相似度
  laws.py seed.py world.py oracle.py heuristic.py     dungeon 环境
  town/           种子镇
    seed.py       宇宙规律、小镇种子、作物（大宇宙、长尾）
    world.py      小镇本体：时钟、作物、村民、告示板、图书馆书架、村民证词、噪声、快速筛选、天气、注意力预算、节日请求、角色
    agents.py     oracle 求解器、学到的 TownSeedMemory、规则 agent
    library.py    图书馆（主题书架、署名笔记）
    sources.py    带可控错误率的二手信息
    team.py       多个 agent 在同一个镇里（算力对齐的时钟、各自感知不同信息的角色）
    replay.py     给浏览器客户端的回放
scripts/          run_experiment、analyze、analyze_hive、analyze_evolve、screen_study、run_labbench、
                  transfer_analysis、play、serve_ui、build_web、export_replay
slurm/            env、setup_nibi、serve_and_run、pilot_board、submit_all、hive_cpu、
                  submit_frontier、submit_vision、frontier_cpu、submit_transfer、transfer_job、start_vllm
web/              Phaser 3 客户端（game.js、index.html）、像素美术和地图、美术生成工具（web/tools）
tests/            全部测试（不需要 GPU）
docs/             研究计划、研究方案评审、详细实验说明
```

## 更多文档

- [docs/experiments.md](docs/experiments.md)：每个环境、实验协议和记忆条件的详细说明，以及目前规则 agent 的结果（英文）。
- [docs/research_plan.md](docs/research_plan.md)：对研究想法的评审和第一篇论文的方案（英文）。
- [docs/world_seeds_program_seed.md](docs/world_seeds_program_seed.md)：研究计划原文。
