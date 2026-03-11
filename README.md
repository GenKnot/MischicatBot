# Mischicat 修仙长生路

一个跑在 Discord 上的修仙放置游戏。前缀 `cat!`，数据存 SQLite，Web 管理面板跑在 8080 端口。

贡献者：[@GenKnot](https://github.com/GenKnot) · [@AdoreJc](https://github.com/AdoreJc) · [@yulexun](https://github.com/yulexun)

---

## 申请Discord App

1. 访问 [Discord Developer Portal](https://discord.com/developers/applications)，点击 `New Application/新 APP` 新建一个应用。
2. 进入应用页面，左侧选择 `Bot/机器人`。如 Bot Token 未显示，点击 `Reset Token/重置令牌` 获取 Token（用于 `.env` 里的 `DISCORD_TOKEN`）。
3. 在 `Privileged Gateway Intents/特权网关意图`区，勾选 `PRESENCE INTEN/在线状态意图`、`SERVER MEMBERS INTENT/服务器成员意图`、`MESSAGE CONTENT INTENT/消息内容意图`。
4. 推荐将机器人权限设为 `Administrator/管理员`。
5. 左侧导航选择 `OAuth2` → `OAuth2 URL Generator/生成器`，Scopes/范围 选择 `bot` 和 `applications.commands`（可选）。
6. 下方 `Bot Permissions/机器人权限` 勾选 `Administrator/管理员`。
7. 复制下方生成的 OAuth2 授权链接，用浏览器打开，选择你的服务器，点击授权即可将 Bot 添加进服务器。

## 运行

复制 `.env.example` 改名为 `.env` 或使用 `copy .env.example .env` 命令，填入对应的值：

- `DISCORD_TOKEN` — Bot Token，从 [Discord Developer Portal](https://discord.com/developers/applications) 获取
- `DISCORD_GUILD_ID` — 服务器 ID，开发者模式下右键服务器复制
- `PUBLIC_EVENT_CHANNEL_ID` — 公共事件广播的频道 ID
- `DB_PATH` — 本地用 `sqlite-data/game.db`，Docker 用 `/app/sqlite-data/game.db`
- `COMMAND_PREFIX` — 机器人前缀，默认 `cat!`，根据需求自己改
### 编译版运行

#### 1. 下载 Release
前往 [Release 页面](https://github.com/GenKnot/Mischicat-Bot/releases) 下载对应系统的预编译包。

#### 2. 解压至任意文件夹

#### 3. 按需修改 `.env` 配置（参考上方「运行」步骤）

#### 4. 双击或命令行运行

- **Windows**  
  双击 `mischicat-bot.exe`  
  或命令行进入目录后运行：  
  ```
  mischicat-bot.exe
  ```

- **Linux / MacOS**  
  命令行进入目录后运行：  
  ```
  chmod +x ./mischicat-bot
  ./mischicat-bot
  ```

---

### 源码手动运行

#### Windows

1. 安装 [Python 3.10+](https://www.python.org/downloads/windows/)
2. 进入项目文件夹，安装依赖：  
   ```
   python -m venv venv
   .\venv\Scripts\activate
   pip install -r requirements.txt
   ```
3. 按需填写 `.env` 文件
4. 运行：  
   ```
   python main.py
   ```
   或双击运行脚本
   ```
   run.bat
   ```

#### Linux / macOS

1. 安装 [Python 3.10+](https://www.python.org/downloads/)
2. 进入项目文件夹，安装依赖：  
   ```
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```
3. 按需填写 `.env` 文件
4. 运行：  
   ```
   python3 main.py
   ```

---

填好后启动：Mac / Linux 运行 `./run.sh`，Windows 双击 `run.bat`。

第一次运行会自动创建虚拟环境并安装依赖。Bot 和 Web 面板同时启动，面板地址 `http://localhost:8080`。

## Docker

`git clone https://github.com/GenKnot/Mischicat-Bot.git`

`cd Mischicat-Bot`

`docker compose up -d`

---

## 内容规模

探险事件 **480** 个
通用 226 · 稀有 49 · 地区专属 100 · 城市专属 90 · 宗门/隐世 15

物品 **321** 种
草药 170 · 矿石 40 · 木材 49 · 鱼类 50 · 丹药 69

茶馆任务 **41** 个
普通 16 · 精英 15 · 传说 10

宗门 **15** 个 · 功法 **215** 个 · 城市 **30** 座 · 秘地 **10** 处

---

## 炼丹系统

### 入门考核

前往**中州·丹阁**，缴费500灵石参加入门考核。缴费后获得材料（灵芝草×6、茯苓灵块×3），前往技艺→炼丹自行摸索。练到成功为止，无次数限制。材料用完可花300灵石补充。成功炼出考核丹药即获得一品炼丹师资质。NPC长老态度随境界和声望变化。

### 炼丹流程

**已知丹方**：选择已掌握的丹方，逐组选辅药，确认开炉。

**自由配药**：从背包选草药，用 +1 按钮调整每种用量，投入丹炉。系统自动匹配丹方，匹配不上只说"炉中只剩灰烬"，不透露任何原因。匹配上直接开炉，玩家无法提前知道配方是否命中。

### 品质系统

品质共 12 级：常规 → 一纹 → 二纹 → … → 十纹 → 无暇。品质受炼丹师品级、神识属性、辅药选择、熟练度等因素影响。无异火时品质上限封顶，拥有异火可突破上限。

### 熟练度

每炼制一次积累熟练度，分生疏、熟悉、精通、炉火纯青四个阶段，阶段越高成功率和品质越有优势。

### 丹方解锁

自由配药首次炼成某丹药后，丹方自动记录（包含当次使用的辅药组合）。之后可通过已知丹方路径直接开炉，系统使用记录的组合，不展示其他选项。自由配药路径始终不透露任何配方信息。

### 丹方数量

当前共 **99** 个丹方，覆盖 **69** 种丹药。

### 炼丹师品级

1-9 品，通过炼丹积累经验升级。品级越高可炼制的丹药阶数越高，每日可炼制次数固定，次日重置。

---

## 已完成

- ~~角色创建（10道问题 + 灵根随机 + 起道号）~~
- ~~境界体系（炼气→筑基→结丹→元婴→化神→炼虚→合体→大乘→真仙→金仙→太乙→大罗→道祖）~~
- ~~修炼系统（闭关/停止/领取，按实际时间结算寿元）~~
- ~~突破系统（连续突破，三档失败，筑基/结丹/元婴专属界面）~~
- ~~坐化与轮回（仙葬谷/阴阳奇遇触发轮回重生，属性继承）~~
- ~~奇遇系统（探险中低概率触发，阴阳两界奇遇、隐世宗门发现等特殊事件）~~
- ~~双修系统（处子加成，冷却2年）~~
- ~~宗门系统（15个宗门，正道/邪道/隐世，入门要求各不同）~~
- ~~功法系统（215个功法，7个熟练阶段，属性加成生效）~~
- ~~世界与移动（30座城市 + 10个秘地，五大区域）~~
- ~~探险系统（480个事件，通用/稀有/地区/城市/宗门分类）~~
- ~~战斗系统（PVP，战力对比 + 随机因素，逃跑判定）~~
- ~~组队系统（最多4人，队长移动带队，组队接任务）~~
- ~~茶馆任务（普通16 + 精英15 + 传说10，声望门槛，装备掉落）~~
- ~~采集系统（采矿/采药/伐木/钓鱼，秘地专属，DM通知）~~
- ~~物品系统（321种，丹药/矿石/木材/鱼类/草药，背包/使用/出售）~~
- ~~装备系统（3槽位，5品质，Diablo风格词缀，战力加成）~~
- ~~居所/洞府系统（修炼加成，探险次数加成）~~
- ~~声望系统（任务/探险积累，解锁精英和传说任务）~~
- ~~公共事件：天降灵雨（预告/守城/结算/临阵脱逃判定）~~
- ~~音乐系统（YouTube / 哔哩哔哩点歌，队列，跨平台 cookie）~~
- ~~Web 管理面板（总览/修士列表/玩家详情/事件记录/坐化名单/属性榜/物品图鉴）~~
- ~~各级菜单返回按钮~~
- ~~功法修炼速度加成修复~~
- ~~功法寿元加成生效（溢出上限设计，卸下保护，双修/丹药上限同步修复）~~
- ~~Web 管理面板新增功法大全页面（按品级分组，各阶段加成展开，宗门来源标注）~~
- ~~万宝楼大型拍卖会（每日北美东部时间 20:00，官方出 8 件含功法/丹药/材料/装备，玩家可上架最多 2 件，竞价冻结灵石，成交 8% 手续费，功法得标进背包可学习或交易，结算逐件公告买家/成交价/卖家）~~
- ~~炼丹系统（草药配方，炼制丹药，炼丹师品级1-9品，丹纹品质12级，熟练度系统，每日6次限制）~~
- ~~丹阁考核（中州·丹阁，缴费500灵石，获得材料自行摸索，练到通过为止，材料用完可花300补充）~~
- ~~功法装备上限按境界解锁（炼气5本 · 筑基7本 · 结丹9本 · 元婴12本 · 化神17本 · 炼虚20本 · 合体23本 · 大乘26本 · 真仙29本 · 金仙32本 · 太乙35本 · 大罗38本 · 道祖41本）~~
- ~~排行榜（境界榜 · 战力榜 · 寿元榜 · 声望榜 · 炼丹榜 · 富豪榜，从世界菜单进入）~~
- ~~打工系统（15种工作，5个等级从入门到顶端，立即结算，每日3次，30分钟冷却，每种工作有随机对话）~~
- ~~城市菜单（主菜单「茶馆」改为「城市」，点击进入城市介绍+在场修士，内含茶馆/打工/每日签到/返回按钮，秘地不显示茶馆与打工）~~
- ~~每日签到（城市菜单入口，每日一次，随机奖励：灵石/材料/功法/装备，概率分档，配置文件 `data/checkin_config.json` 可直接调整概率）~~
- ~~赌坊（城市菜单入口，每日10次，押注100/500/1000/5000灵石，大赢×3/赢×2/小赢×1.5/输×0，概率配置文件 `data/gamble_config.json`）~~

---

## 进行中

- 公共事件扩展（神殿试炼 / 妖兽潮 / 秘境开启）

---

## 待做

- 数据库层逐步迁移至 SQLAlchemy async（新功能用 `utils/db_async.py`，旧代码按模块逐步替换，cultivation 和 quest 模块已完成）
- 化神期突破（需补全五行灵根）
- 锻造系统（矿石/木材实际用途，打造武器防具）
- 异火系统（炼丹师专属，获取/驯化异火，大幅提升炼丹品质上限）
- 炼符系统（符箓制作，战斗/辅助效果）
- 炼傀系统（傀儡制作，可派遣采集或守城）
- 阵法系统（布阵、破阵，城市防御/攻击加成）
- 琴棋书画（修身养性，触发特殊奇遇或属性加成）
- 宗门大比（定期跨宗门擂台赛，排名奖励）
- 宗门内部系统（贡献度、晋升、宗门任务）
- 情缘系统（好感度、羁绊事件）
- 结婚系统（双修加成升级，共享洞府）
- 装备强化 / 升级
- 摆摊系统（城市内摆摊出售物品，玩家间自由交易）
- 灵石经济（商店、玩家交易）
- 城市势力攻防战（宗门/玩家势力争夺城市控制权）
- 野兽攻城战（妖兽潮定期冲击城市，全服协力守城）
- 虚天神殿（高难度副本，限定奖励）
- 秘境系统（限时开放的特殊地图，专属事件和掉落）
- 天劫系统（高境界突破时触发雷劫，需抵御方可晋升）
- 灵宠系统（捕捉/培养，战斗辅助或采集加成）
- 体修路线（不走功法，走肉身强化的另一条成长路线）
- 称号系统（完成特定条件解锁，带属性加成）
- 成就系统（记录里程碑，首次突破/坐化/双修等）
- 排行榜定期重置奖励（定期重置并发放奖励）
- 悬赏系统（玩家挂赏金追杀其他玩家）
- 师徒系统（拜师/收徒，传授功法，师父获得徒弟修炼加成）
- 节日活动（限时事件，专属奖励）
- 仙葬谷完整实现（需坐化重生后才能发现入口）
- 网页版游戏界面（Discord OAuth2 登录，游戏逻辑层与 Discord 解耦，网页端复用同一套 utils/）

---

## 项目结构

```
bot.py                        Bot 客户端定义（MischiCat 类）
main.py                       启动入口，同时启动 Bot 和 Web 面板

cogs/                         Discord 命令入口，每个文件对应一个功能模块
  alchemy.py                  炼丹命令（开炉/查丹方/炼丹师品级）
  character.py                角色命令（创建/查看/属性/背包/使用物品）
  cultivation.py              修炼/突破/坐化/轮回/双修命令
  equipment.py                装备命令（穿戴/卸下/查看/出售）
  explore.py                  探险命令（单人/组队探险）
  music.py                    音乐系统（YouTube/B站点歌，队列管理）
  property.py                 居所/洞府命令（购买/升级/查看加成）
  public_events.py            公共事件调度器（灵雨预告/触发/结算，万宝楼定时开拍）
  sect.py                     宗门命令（加入/退出/查看）
  tavern.py                   茶馆/城市/打工/任务命令，含管理员工具
  travel.py                   移动命令（城市间移动，组队带队）

utils/                        游戏逻辑层，不直接依赖 Discord
  events/                     探险事件池（480个事件）
    _base.py                  事件基类与公共工具函数
    common_1~10.py            通用事件（226个，分10个文件）
    rare_1~3.py               稀有/奇遇事件（49个）
    adventure.py              特殊奇遇事件
    sects_events.py           宗门/隐世专属事件（15个）
    regions/                  五大区域专属事件（100个）
      central.py / central_2.py   中州
      east.py / east_2.py         东域
      south.py / south_2.py       南域
      west.py / west_2.py         西域
      north.py / north_2.py       北域
    public/                   公共事件逻辑
      spirit_rain.py          天降灵雨（结晶/感悟/淬体/守城）
      wanbao.py               万宝楼拍卖会（竞价/结算/手续费）

  items/                      物品定义（321种）
    herbs.py                  草药（170种，含品质/售价/采集地）
    materials.py              矿石（40种）
    wood.py                   木材（49种）
    fish.py                   鱼类（50种）
    pills.py                  丹药（69种，含效果/品阶）
    breakthrough.py           突破专属物品（筑基丹/凝丹丹/化婴丹等）
    tools.py                  工具类物品

  quests/                     任务列表
    common.py                 普通任务（16个，无声望门槛）
    elite.py                  精英任务（15个，需声望解锁）
    legendary.py              传说任务（10个，高声望门槛）

  views/                      Discord UI 组件（View/Button/Select）
    menu.py                   主菜单
    city.py                   城市菜单（茶馆/打工/在场修士入口）
    city_players.py           城市在场修士列表
    cultivation.py            修炼/闭关界面
    combat.py                 PVP 战斗结算界面
    character_create.py       角色创建问卷
    alchemy.py                炼丹操作界面（选辅药/开炉/结果）
    dange.py                  丹阁考核界面
    equipment.py              装备管理界面
    gathering.py              采集界面（采矿/采药/伐木/钓鱼）
    jobs.py                   打工界面（选工种/结算/冷却显示）
    checkin.py                每日签到界面（roll奖励/结果展示）
    gamble.py                 赌坊界面（押注按钮/结果展示）
    leaderboard.py            排行榜界面（6种榜单）
    party.py                  组队界面
    sects.py                  宗门界面
    techniques.py             功法界面（学习/卸下/查看加成）
    travel.py                 移动界面
    dual.py                   双修界面
    yinyang.py                阴阳奇遇界面
    crafting.py               锻造界面（预留）
    wanbao.py                 万宝楼竞价界面（玩家端）
    wanbao_public.py          万宝楼公告界面
    public_event_overview.py  公共事件总览
    spirit_rain.py            灵雨活动参与界面
    world.py                  世界地图界面

  alchemy.py                  炼丹逻辑（配方匹配/品质计算/熟练度）
  breakthrough_logic.py       突破判定（成功率/失败惩罚/连续突破）
  buffs.py                    增益效果管理
  character.py                角色数据工具函数
  combat.py                   战斗逻辑（战力计算/PVP判定/逃跑）
  cultivation_logic.py        修炼结算（时间换修为/寿元消耗）
  db.py                       同步 SQLite 操作（旧模块使用）
  db_async.py                 异步 SQLite 操作（新模块使用，逐步迁移中）
  death_rebirth_logic.py      坐化/轮回逻辑（属性继承/仙葬谷/阴阳奇遇）
  dual_cultivation_logic.py   双修逻辑（处子加成/冷却/寿元消耗）
  equipment.py                装备生成/词缀/战力加成
  jobs.py                     打工系统（15种工种，5个等级，立即结算）
  checkin.py                  每日签到逻辑（读config/roll奖励/写数据库）
  gamble.py                   赌坊逻辑（押注/概率结算/每日次数限制）
  player.py                   玩家数据读写（get_player/apply_updates）
  quest_logic.py              任务接取/结算/组队分配逻辑
  realms.py                   境界定义、索引、突破路径
  sects.py                    宗门数据、功法列表、加成计算
  techniques.py               功法数据与熟练度阶段
  world.py                    城市/地图/区域/秘地数据
  ytdlp_helper.py             yt-dlp 封装（音乐下载/流媒体）

web/                          FastAPI 管理面板（端口 8080，只读展示）
  main.py                     路由定义
  templates/                  Jinja2 页面模板
    index.html                总览（在线人数/修炼状态/近期活跃）
    players.html              修士列表（搜索/筛选/排序）
    player_detail.html        玩家详情（属性/背包/装备/功法/任务）
    stats.html                属性榜（多维度排序）
    events.html               事件记录（灵雨/万宝楼历史）
    items.html                物品图鉴（321种，按类型/稀有度筛选）
    techniques.html           功法大全（按品级分组，加成展开）
    world.html                世界地图（城市/宗门/人口分布）
    equipment_preview.html    装备预览工具（管理员用）
    dead.html                 坐化名单
  static/
    style.css                 全局样式
    manifest.json             PWA 配置
    sw.js                     Service Worker

data/                         静态配置文件
  pills.json                  丹药基础属性配置
  recipes.json                炼丹丹方（99个，含主辅药/成功率/品质上限）
  checkin_config.json         每日签到奖励概率配置（可直接修改数字调整概率）
  gamble_config.json          赌坊押注概率配置（可直接修改数字调整概率）

deploy/
  k8s-deployment.yaml         Kubernetes 部署配置

scripts/                      备用启动脚本
  run.bash / run.ps1 / run.py 各平台启动脚本
```

