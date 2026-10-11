# 江湖传闻的模板

传闻 = 事件种类 + 模板 + 变量。种类、分值、模板都在 `data/rumors.json`，运行时只查表，**不调用大模型**。
格式校验在 `tests/test_rumors.py`（`utils/rumors.py::validate_config`），CI 会拦住格式错误。

## 事件种类（`kinds`）

每个种类：`score`（基础分，决定能不能上频道广播）、`negative`（丢脸 / 不幸的事，同一个真人每天最多广播 1 条）、
`vars`（模板里允许用的占位符）、`templates`（模板，**至少 2 条，建议 8~15 条**，重复看到同一句会腻）。

| 种类 | 什么时候 | 占位符 | 负面 |
|---|---|---|---|
| `breakthrough_minor` / `breakthrough_major` | 小层突破 / 跨大境突破成功 | name city realm | |
| `breakthrough_fail` | 突破失败 | name city realm | ✓ |
| `death_old` / `death_breakthrough` / `death_quest` | 寿尽坐化 / 突破失败而死 / 任务中陨落 | name city (realm) | ✓ |
| `kill_human` | 真人被真人击杀（主角是被杀的人，`target` 是凶手） | name target city | ✓ |
| `rob_bot` / `cripple_bot` / `kill_bot` | 真人打劫 / 废修为 / 击杀散修（主角是真人，`target` 是散修） | name target city (amount) | |
| `bot_robs_human` / `bot_kills_human` | 真人败给散修被劫 / 被杀（主角是真人，`target` 是散修） | name target city (amount) | ✓ |
| `alchemy_great` / `alchemy_levelup` / `alchemy_fail` | 炼出高品质丹药 / 炼丹师升品 / 炉毁或丹毒反噬 | name pill quality / level / city | fail ✓ |
| `forge_great` / `forge_fail` | 锻出史诗或传说装备 / 锻造失败 | name item quality / — | fail ✓ |
| `rare_event` / `adventure_chain` | 探险遇到稀有事件 / 触发奇遇链 | name title city / name chain city | |
| `rebirth` | 坐化后重入轮回 | name | |

## 占位符

`{name}`（主角道号，**每条模板必须出现**）、`{city}`、`{realm}`、`{target}`（另一方）、`{amount}`（灵石）、`{pill}`、`{quality}`、`{item}`、
`{title}`（稀有事件名）、`{chain}`（奇遇名）、`{level}`（品级）。每个种类只能用它 `vars` 里声明的那几个。

## 文风约束

- 每条不超过 90 字，一句话。
- **真人全部实名**（已定）：笑点放在『事』上，不要放在『人』上。✓「丹房的屋顶这回是真没了」 ✗「{name}真是个废物」。
- **死亡用郑重口吻**（「陨落于……，江湖少了一位好汉」「愿其安息」），不调侃。
- 不要写成确定的因果（「因为没带丹药所以失败」）；传闻是『听闻』『据说』，可以留白。
- 不要出现真实人名、政治、成人内容。
- `negative: true` 的种类尤其注意分寸，它们会点名真人。

## 给 AI 的提示词模板

> 你在为一款中文修仙文字游戏写「江湖传闻」。事件：「{种类说明}」，可用的占位符：{vars}（其中 {name} 每条必须出现）。
> 请写 {N} 条传闻模板，只输出 JSON 字符串数组。每条不超过 40 字，一句话，口吻像茶馆里的闲谈（「听闻」「据说」），
> {负面种类：笑点在事上不在人，不羞辱 / 死亡种类：郑重，不调侃}。每条风格尽量不同。
