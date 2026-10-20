# 机器人内容的扩写指南（给人，也给任何 AI）

机器人世界里**文字内容全是数据文件**，运行时只查表、不调用大模型。扩写内容不用改代码，校验会拦住格式错误。

| 内容 | 文件 | 谁来写 | 怎么扩写 |
|---|---|---|---|
| **NPC 对话**（8 个性格 × 27 个场景 × 4 个好感档位） | `data/bot_dialogues/<原型>.json` 与批次文件 `<原型>.<批次名>.json` | AI | `scripts/dialogue_tool.py`（下面第 1 节） |
| 性格的**角色卡**（说话方式、口头禅、对玩家的态度） | `data/bot_voices.json` | 人 + AI | 直接改；是 AI 提示词的素材，决定声音是否统一 |
| **说话特质池**（出身 / 说话习惯 / 星座 / 嗜好 / 往事 / 口头禅 / 内向外向） | `data/bot_traits/<池>.json` 与批次文件 `<池>.<批次名>.json` | AI | `dialogue_tool.py traits-prompt / traits-merge`（第 2 节） |
| 机器人的**行为画像**（守序 / 冲动 / 义气 / 记仇 / 关系容量 / 偏离概率，出身加减） | `data/bot_profiles.json` | 人 | 直接改数字；新增原型要补一份（测试会查） |
| 机器人的**关系网**配置（性格亲和度、结识概率、反目 / 和解 / 结拜的概率） | `data/bot_ties.json` | 人 | 直接改数字；新增原型要补它和每个原型的亲和度 |
| **拦路遭遇**配置（触发概率、冷却、处置权重、回应倍数、买命价、劫财比例） | `data/bot_ambush.json` | 人 | 直接改数字；新增原型要补 `outcome` 和 `buyout.accept` |
| **主动搭话的台词**（条件化文案库：场景 × 任意条件组合） | `data/bot_chatter/<场景>.json` 与批次文件 `<场景>.<批次名>.json` | AI | `scripts/dialogue_tool.py chatter-prompt / chatter-merge`（第 6 节） |
| **主动搭话**的节奏配置（每天上限、冷却、各契机的概率与延迟、回应的好感变化） | `data/bot_chatter_config.json` | 人 | 直接改数字 |
| **机器人请求 / 委托**配置（借灵石 / 借物品 / 送信 / 陪采集的模板、开口概率、还钱的性格系数） | `data/bot_requests.json` | 人 | 同一种 kind 的新模板只改数据（并写 `request_ask_<模板名>` 台词）；新 kind 要写代码 |
| **玩家向机器人求助**的配置（答应概率、借期、宽限、催债 / 翻脸的好感变化） | `data/bot_requests.json` 的 `player_ask` | 人 | 直接改数字 |
| **失踪调查**配置（问话概率 / 回答对进度的影响 / 每天进度 / 放弃期） | `data/bot_investigation.json` | 人 | 直接改数字 |
| **机器人恩怨**（仇敌 / 复仇动手概率、胜负、结果权重按性格、击杀上限、传闻概率） | `data/bot_feuds.json` | 人 | 直接改数字；传闻文案在 `data/rumors.json` 的 `bot_feud_*` / `bot_quarrel` / `bot_sworn` |
| **管理员调参**（在游戏里改上面这些 json 里的数字 / 开关，立即生效，可恢复默认） | `cat!调参` 系列命令 | 管理员 | 文件里的值是默认值；文字内容不能这样改 |
| **AI 润色**（默认关；Qwen / DeepSeek 二选一、场景名单、日调用上限、超时） | `data/llm_polish.json` | 人 | 密钥放环境变量 `DASHSCOPE_API_KEY` / `DEEPSEEK_API_KEY`，失败自动退回模板台词 |
| **仇恨账本**配置（各种冒犯的轻重、原因模板、蹲守年数、续期概率、化解价格） | `data/bot_grudges.json` | 人 | 直接改数字 / 模板；新增原型要补 `windows` 和 `renew` |
| **江湖传闻**模板（22+ 个事件种类） | `data/rumors.json` | AI | `data/rumor_templates_README.md` |
| **天骄的称号和背景** | `data/bot_legends.json` | AI | 每个原型的 `epithets` / `backstories` 追加；占位符只有 `{home}` |
| 机器人**道号**词库 | `data/bot_names.json` | AI | 追加姓 / 名用字即可 |
| 性格原型本身（数值范围、喜好池） | `data/bot_archetypes.json` | 人 | 见第 3 节 |

## 1. 用 AI 扩写 NPC 对话（推荐流程）

```bash
.venv/bin/python scripts/dialogue_tool.py coverage                        # 1. 看缺口：每个原型写够了多少格子
.venv/bin/python scripts/dialogue_tool.py prompt 阴鸷 > prompt.txt        # 2. 出提示词（带角色卡、已有台词、规则、输出格式）
#    把 prompt.txt 整段粘贴给任意 AI，让它只返回 JSON，存成 reply.json
.venv/bin/python scripts/dialogue_tool.py merge 阴鸷 reply.json --batch 20261012-gpt   # 3. 校验并合并
.venv/bin/python scripts/dialogue_tool.py check                           # 4. 全量校验
```

- **`--batch 批次名`**：台词写到独立文件 `阴鸷.20261012-gpt.json`，不同 AI / 不同时间互不覆盖，查找时自动合并；不满意直接删掉那个文件即可。
- **校验不过一律不写**，工具会列出具体哪句、什么问题，把错误贴回给 AI 让它修正再 `merge` 一次。
- 已有的句子自动去重；提示词里附带了已有台词，AI 会保持同一个声音、避免重复。
- 只想补某些格子：`prompt 豪爽 --scenes greet,gift_love --tiers 陌生,至交 -n 6`。
- **角色卡决定质量**：想让某个性格更有个性，先改 `data/bot_voices.json` 里那张卡（口头禅、对玩家的态度、要避免的东西），再出提示词。
- 不同模型写出来的『思路』不一样是好事；只要 `check` 通过，就可以混着用。

## 2. 让每个机器人说话都不一样：特质池（纯文案，不影响数值）

骨架台词（场景 × 档位 × 性格）之外，每个机器人出生时各抽一份**特质**：内向外向（由健谈数值决定）、星座、出身、1~2 个说话习惯、1~2 个口头禅、
一个嗜好、一件往事。说话时 `utils/bot_voice.py` 按特质改写骨架台词（换称呼和词汇、加语气词和口头禅、长短增减、偶尔插一句嗜好或往事），
所以同一性格的 100 个机器人也不会说同一句话。组合数在十万以上。

```bash
.venv/bin/python scripts/dialogue_tool.py sample 豪爽 greet 陌生 -n 12      # 抽 12 个豪爽的机器人，看他们各自怎么打招呼（检验多样性）
.venv/bin/python scripts/dialogue_tool.py traits-prompt origins -n 8        # 出一份『再写 8 个出身』的提示词（含规则说明、已有条目、示例、格式）
.venv/bin/python scripts/dialogue_tool.py traits-merge origins reply.json --batch gpt-1012   # 校验并合并（不过不写；已有的跳过）
```

- 池：`origins`（出身）、`habits`（说话习惯）、`zodiac`（星座）、`hobbies`（嗜好）、`pasts`（往事）、`catchphrases`（口头禅）。
- 每个条目的 `weights` 决定哪些性格更可能抽到它（`{"迂腐": 3, "憨直": 0.2}`，没写 = 1，0 = 抽不到）。
- **改写规则**写在条目的 `rules` 里（全部可选，只改占位符之外的文字）：
  `swap`（词语替换，如 `{"道友": "老哥"}`）、`punct`（标点替换）、`end_particles`（句末语气词，单字）、`prefix` / `suffix`（句首 / 句尾补话，≤14 字）、
  `ellipsis_p`（话说一半）、`max_clauses`（只留前几句）、`tiers` / `scenes`（限定好感档位 / 场景），概率键 `*_p` 在 0~1 之间。规则要『轻』：不同条目的规则会叠加。
- 嗜好 / 往事不用规则，写 `remarks`（≥2 条，≤40 字，不含花括号），在熟识以上的好感里偶尔被提起；仇视档和遗言 / 杀戮场景从不插话。
- 资料页给玩家看『出身 · 星座 · 内向外向』，嗜好和往事让玩家自己从对话里发现。

## 3. 扩写其它内容

- **传闻模板**：每个种类建议 8~15 条，格式与提示词模板见 `data/rumor_templates_README.md`；改完跑 `pytest tests/test_rumors.py`。
- **天骄称号 / 背景**：往 `data/bot_legends.json` 对应原型下追加；称号 ≤ 8 字，背景 ≤ 80 字，只能用 `{home}`；
  同一批生成的天骄称号尽量不重复，所以称号越多越好。
- **道号**：`data/bot_names.json`，每项一个字。

## 4. 新增一个性格原型

一个性格要在这几处都有数据，漏了哪一处 `tests/test_dialogue_tools.py::test_每个性格原型的配套数据都齐全` 就会红：

1. `data/bot_archetypes.json`：四个数值范围（善意 / 贪婪 / 好胜 / 健谈）和喜欢 / 讨厌的物品类别池；
2. `data/bot_economy.json`：`money.<原型>`（随身比例、日常开销比例）、`combat.reaction.<原型>`（被擒获后放走 / 劫财 / 杀的权重）；
3. `data/bot_legends.json`：`epithets.<原型>`（≥3 个称号）、`backstories.<原型>`（≥3 条背景）；
4. `data/bot_voices.json`：`archetypes.<原型>` 角色卡；
5. 台词：`scripts/dialogue_tool.py prompt <原型>` → AI → `merge`（没写的格子自动回退到通用台词，所以可以慢慢补）。

## 5. 新增一个对话场景

1. `utils/bot_dialogue.py::SCENES` 加场景名；
2. `data/bot_dialogues/_default.json` 补齐 4 个档位（通用台词必须完整）；
3. `data/bot_voices.json` 的 `scenes` 里写 `when`（什么时候说）和 `beat`（情绪 / 要点）；
4. 在触发的地方调用 `bot_social.say("场景名", 玩家id, 机器人id)`；
5. 各原型的台词用 `coverage` / `prompt` 慢慢补。

## 6. 条件化文案库：机器人主动搭话（到城 / 突破道贺 / 公共事件 / 冲突后放话 / 回应）

和第 1 节的『场景 × 档位 × 性格』固定三维不同，这里每条**规则**自己声明适用条件，台词按条件挑；条件越多的规则被抽中的权重越大（×2 每多一个条件），没写条件的规则是兜底。

**文件**：`data/bot_chatter/<场景>.json`（主文件）和 `<场景>.<批次名>.json`（批次文件，AI 批量写这里，自动合并）。**格式**：

```json
{"scene": "chatter_arrive",
 "rules": [
   {"when": {"archetype": ["阴鸷"], "tier": ["陌生"], "realm_gap": ["higher"]}, "weight": 1, "lines": ["呵，{player}，来{city}做什么？"]},
   {"lines": ["{player}，好久不见。"]}
 ]}
```

**场景**（`utils/bot_chatter_lines.py::SCENES`）：`chatter_arrive`（到城，可用 `{city}`）· `chatter_congrats`（突破大境界，`{realm}`，按 `attitude`：真心 / 酸 / 不服 / 觊觎）·
`chatter_event_before / after`（公共事件，`{event}` `{city}`）· `chatter_conflict_self`（被劫 / 被废后它自己放话，`kind`）· `chatter_conflict_friend`（替朋友出头，`{victim}`，`kind` `bond`）·
`chatter_mediate`（劝架，`{victim}`）· `reply_warm / ok / neutral / cold`（玩家用按钮回应后它的一句）。`{player}` `{bot}` 永远可用。

**条件**（`when` 里每个键的值是列表：键之间『且』，列表里『或』）：`archetype` 性格 · `tier` 好感档位 · `relation` 它和玩家的关系（结拜 / 同门 / 朋友 / 相识 / 仇敌 / 无）·
`tags` 阵营与行为标签（守序善良 … 混乱邪恶、冲动、谨慎、重义气、记仇；满足任一即可）· `origin` 出身 · `zodiac` 星座 · `introversion` 内向外向 · `realm_gap`（它的大境界相对玩家：higher / equal / lower）·
`attitude` · `event`（灵雨 / 兽潮 / 拍卖）· `kind`（rob_fail / rob / cripple / kill）· `bond`（它和受害者的关系，或 self）。

**铁律**：每个场景至少有一条无条件的兜底规则；每句 ≤ 80 字（建议 ≤ 40）；台词只负责说，不许诺任何游戏结果；占位符只能用场景允许的。

```bash
.venv/bin/python scripts/dialogue_tool.py chatter-coverage                      # 覆盖表
.venv/bin/python scripts/dialogue_tool.py chatter-prompt chatter_arrive -n 8     # 出一份给 AI 的提示词（含条件取值、角色卡、已有台词）
.venv/bin/python scripts/dialogue_tool.py chatter-merge chatter_arrive reply.json --batch gpt-1013   # 校验并并入（重复台词跳过，不合格整份退回）
.venv/bin/python scripts/dialogue_tool.py check                                  # 校验所有文案（含这个库）
```

**新增一个场景**：在 `SCENES` 加一项（允许的占位符）、在 `SCENE_INFO` 写『什么时候 / 要做什么』、建 `data/bot_chatter/<场景>.json`（至少一条兜底），再在 `utils/bot_chatter.py` 接上触发点。
