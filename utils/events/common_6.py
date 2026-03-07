# 通用事件 81-100（每文件 20 个）
from utils.events._base import _e, _c, _cond

EVENTS = []

EVENTS.append(_e(
    "灵鸦报信",
    "一只灵鸦落在你肩头，爪上绑着一卷纸条。展开一看，是一封匿名信，写着某处有灵药成熟，邀有缘人共采。",
    [
        _c("按信中所指前往", next_event={
            "desc": "你寻至信中地点，果然有一片灵药，但已有两人在场，双方对峙，气氛紧张。",
            "choices": [
                _c("提议三人平分", condition=_cond("comprehension", 6), rewards={"spirit_stones": 80, "reputation": 15}, flavor="你说服双方平分灵药，各自满意，你也得了一份。灵石 +80，声望 +15"),
                _c("提议三人平分", rewards={"spirit_stones": 50}, flavor="双方勉强同意平分，你得了部分灵药。灵石 +50"),
                _c("趁乱抢先采走一部分", condition=_cond("fortune", 7), rewards={"fortune": 1, "spirit_stones": 100}, flavor="你趁二人争执时采走一批灵药，全身而退。机缘 +1，灵石 +100"),
                _c("趁乱抢先采走一部分", rewards={"lifespan": -5, "spirit_stones": 40}, flavor="你被二人发现，受了些伤才脱身。寿元 -5，灵石 +40"),
            ]
        }),
        _c("不信，撕掉纸条", rewards={}, flavor="你当是陷阱，未前往。"),
    ]
))

EVENTS.append(_e(
    "石室机关",
    "山洞深处有一间石室，石门半开，室内有机关转轮与几口箱子。墙上刻着「左三右四，方可无虞」。",
    [
        _c("按刻字转动机关", next_event={
            "desc": "你将转轮左转三圈、右转四圈，石室震动，一口箱子自动打开，另两口仍锁着。",
            "choices": [
                _c("只取已开箱中之物", rewards={"spirit_stones": 90}, flavor="箱中是灵石与几件小法器，你取走后离开。灵石 +90"),
                _c("尝试开另外两口箱", condition=_cond("fortune", 6), rewards={"fortune": 1, "spirit_stones": 150}, flavor="你胡乱试了几次，竟又开了一口，收获颇丰。机缘 +1，灵石 +150"),
                _c("尝试开另外两口箱", rewards={"lifespan": -6}, flavor="你触发了机关，毒箭射出，你受伤而退。寿元 -6"),
            ]
        }),
        _c("不碰机关，只观望", rewards={"cultivation": 30}, flavor="你观察机关结构，略有所悟。修为 +30"),
        _c("退出石室", rewards={}, flavor="你不想冒险，退出山洞。"),
    ]
))

EVENTS.append(_e(
    "花海迷途",
    "你误入一片奇异花海，花香浓郁，辨不清方向。据说有人在此迷路数日才出得去。",
    [
        _c("以神识辨路", next_event={
            "desc": "你闭目以神识感应灵气流向，花海中的灵气有强有弱，似乎指向某处。",
            "choices": [
                _c("朝灵气最浓处走", condition=_cond("soul", 7), rewards={"soul": 1, "spirit_stones": 60}, flavor="你找到花海中心的灵泉，取了一壶灵泉水后循路而出。神识 +1，灵石 +60"),
                _c("朝灵气最浓处走", rewards={"lifespan": -3, "cultivation": 40}, flavor="你兜转许久才找到出路，略损精力。寿元 -3，修为 +40"),
                _c("朝灵气最弱处走", condition=_cond("comprehension", 6), rewards={"comprehension": 1}, flavor="你推断边缘灵气弱，果然很快走出，并悟出一丝辨位之法。悟性 +1"),
                _c("朝灵气最弱处走", rewards={"lifespan": -2}, flavor="你走对了方向，不久出花海。寿元 -2"),
            ]
        }),
        _c("做标记慢慢探路", rewards={"lifespan": -4}, flavor="你花了很久才摸出花海。寿元 -4"),
        _c("原地打坐，等花香散", condition=_cond("physique", 6), rewards={"physique": 1, "cultivation": 50}, flavor="你以体魄抗住花香，静坐一夜后日出雾散，你顺利走出。体魄 +1，修为 +50"),
        _c("原地打坐，等花香散", rewards={"lifespan": -2}, flavor="你等到次日，勉强辨清方向离开。寿元 -2"),
    ]
))

EVENTS.append(_e(
    "斗鸡赌局",
    "巷子里有人围成一圈斗灵鸡，庄家吆喝下注。一只赤羽灵鸡连赢三场，众人纷纷押它。",
    [
        _c("押赤羽灵鸡", condition=_cond("fortune", 6), rewards={"spirit_stones": 60}, flavor="赤羽再胜，你小赚一笔。灵石 +60"),
        _c("押赤羽灵鸡", rewards={"spirit_stones": -30}, flavor="赤羽此局落败，你输了赌注。灵石 -30"),
        _c("押对家", condition=_cond("fortune", 7), rewards={"spirit_stones": 80}, flavor="你反其道而行，对家爆冷胜出。灵石 +80"),
        _c("押对家", rewards={"spirit_stones": -25}, flavor="对家不敌，你输了。灵石 -25"),
        _c("不赌，只看热闹", rewards={}, flavor="你围观片刻后离开。"),
    ]
))

EVENTS.append(_e(
    "灵马认主",
    "荒野中一匹通体雪白的灵马拦在你面前，既不攻击也不离去，只是盯着你看，似在打量。",
    [
        _c("缓缓靠近，伸手抚其鬃毛", next_event={
            "desc": "灵马嗅了嗅你的手，低鸣一声。你若能取得它的信任，或可暂时同行一程。",
            "choices": [
                _c("以灵力温和渡入其体", condition=_cond("soul", 6), rewards={"soul": 1, "cultivation": 70}, flavor="灵马接纳了你，与你同行一段路，途中你借其灵性感悟，神识与修为皆进。神识 +1，修为 +70"),
                _c("以灵力温和渡入其体", rewards={"cultivation": 40}, flavor="灵马允你同行，你略有所得。修为 +40"),
                _c("喂它灵草", condition=_cond("fortune", 6), rewards={"fortune": 1, "lifespan": 15}, flavor="灵马食后欢鸣，吐出一颗灵珠相赠。机缘 +1，寿元 +15"),
                _c("喂它灵草", rewards={"lifespan": 8}, flavor="灵马食后温顺许多，与你亲近片刻后离去。寿元 +8"),
            ]
        }),
        _c("不招惹，绕行", rewards={}, flavor="你绕开灵马离开。"),
    ]
))

EVENTS.append(_e(
    "古锁秘匣",
    "废墟中你发现一只金属秘匣，匣上有古锁，锁孔形状古怪。据说此类古锁需以特定灵力顺序方能打开。",
    [
        _c("尝试以灵力探锁", next_event={
            "desc": "你将灵力注入锁孔，锁内机关微微作响。需以神识感应锁芯，或凭机缘试出顺序。",
            "choices": [
                _c("以神识感应锁芯结构", condition=_cond("soul", 7), rewards={"soul": 1, "spirit_stones": 110}, flavor="你探明结构后打开秘匣，内有不少灵石与一枚玉简。神识 +1，灵石 +110"),
                _c("以神识感应锁芯结构", rewards={"spirit_stones": 50}, flavor="你勉强打开匣子，内有一些灵石。灵石 +50"),
                _c("胡乱试几次", condition=_cond("fortune", 7), rewards={"fortune": 1, "spirit_stones": 90}, flavor="你误打误撞打开古锁，收获不菲。机缘 +1，灵石 +90"),
                _c("胡乱试几次", rewards={"lifespan": -2}, flavor="锁内机关反噬，你指尖一痛。寿元 -2"),
            ]
        }),
        _c("将秘匣带走，日后研究", rewards={"spirit_stones": 40}, flavor="你带走秘匣，到城中请人打开，分得部分财物。灵石 +40"),
        _c("不碰秘匣", rewards={}, flavor="你恐有机关，未动秘匣。"),
    ]
))

EVENTS.append(_e(
    "瘴林边缘",
    "前方是一片瘴气缭绕的密林，林外立着一块碑：「瘴林凶险，入者自负。」林边却有几株灵草生长，未受瘴气侵染。",
    [
        _c("只采林边灵草", condition=_cond("fortune", 6), rewards={"spirit_stones": 55, "lifespan": 5}, flavor="你采到灵草，并发现草根处有一颗小灵珠。灵石 +55，寿元 +5"),
        _c("只采林边灵草", rewards={"spirit_stones": 35}, flavor="你采了几株灵草便离开。灵石 +35"),
        _c("深入瘴林边缘数步", next_event={
            "desc": "你屏息进入数步，瘴气渐浓，可见范围内又有几株更好的灵草。",
            "choices": [
                _c("采了便退", condition=_cond("physique", 6), rewards={"physique": 1, "spirit_stones": 85}, flavor="你速采速退，体魄在瘴气中略有锻炼。体魄 +1，灵石 +85"),
                _c("采了便退", rewards={"lifespan": -5, "spirit_stones": 60}, flavor="你采到灵草但吸入少许瘴气。寿元 -5，灵石 +60"),
                _c("再往深处几步", condition=_cond("fortune", 7), rewards={"fortune": 1, "spirit_stones": 120}, flavor="你多走几步，采到一株珍稀灵草。机缘 +1，灵石 +120"),
                _c("再往深处几步", rewards={"lifespan": -10}, flavor="你迷了方向，费尽力气才退出，元气大伤。寿元 -10"),
            ]
        }),
        _c("不靠近瘴林", rewards={}, flavor="你未冒险，转身离开。"),
    ]
))

EVENTS.append(_e(
    "说书摊",
    "街角有个说书摊，说书人正讲到某位剑仙一剑斩妖的段子。他醒木一拍：「欲知后事，且听下回。诸位赏个茶钱？」",
    [
        _c("打赏灵石，求续讲", next_event={
            "desc": "说书人收下灵石，压低声音道：「下一段里有一式剑诀的传闻，据说是从古墓石刻上抄来的。」",
            "choices": [
                _c("追问剑诀传闻", condition=_cond("fortune", 6), rewards={"cultivation": 80, "fortune": 1}, flavor="说书人透露了一处古墓方位，你按图索骥找到残刻，修为与机缘皆进。修为 +80，机缘 +1"),
                _c("追问剑诀传闻", rewards={"cultivation": 40}, flavor="说书人只说了些传闻，你当故事听，略有所得。修为 +40"),
                _c("不再多问，明日再来", rewards={"reputation": 10}, flavor="说书人觉得你识趣，对你印象不错。声望 +10"),
            ]
        }),
        _c("不打赏，只旁听", rewards={"cultivation": 25}, flavor="你听了一段，心境略有所得。修为 +25"),
        _c("离开", rewards={}, flavor="你离开说书摊。"),
    ]
))

EVENTS.append(_e(
    "灵蜂巢穴",
    "树梢挂着一个巨大的灵蜂巢，蜂群进出忙碌。巢下有灵蜜滴落，若能取到灵蜜，价值不菲，但灵蜂蜇人极痛。",
    [
        _c("以烟熏驱蜂后取蜜", next_event={
            "desc": "你点燃湿草生烟，灵蜂纷纷离巢。但巢内蜂王未出，你若伸手取蜜，可能惊动蜂王。",
            "choices": [
                _c("快速取蜜便退", condition=_cond("physique", 7), rewards={"physique": 1, "spirit_stones": 100}, flavor="你速取速退，蜂王未及反应。灵蜜售得高价，体魄在应对中亦有锻炼。体魄 +1，灵石 +100"),
                _c("快速取蜜便退", rewards={"lifespan": -6, "spirit_stones": 60}, flavor="你被蜇了几口，仍取到部分灵蜜。寿元 -6，灵石 +60"),
                _c("只取巢外已滴落的蜜", rewards={"spirit_stones": 50}, flavor="你只收集了滴落的蜜，未动蜂巢。灵石 +50"),
            ]
        }),
        _c("不招惹蜂巢", rewards={}, flavor="你绕道离开。"),
    ]
))

EVENTS.append(_e(
    "符纸飘落",
    "一张符纸从空中飘落，正好落在你手中。符上朱砂未干，似乎是有人刚画完便失手掉落。",
    [
        _c("以神识感应符纸", next_event={
            "desc": "符纸中蕴含一丝灵力走向，你若能参悟，或可学到一点符道皮毛；若胡乱激发，可能引发符力反噬。",
            "choices": [
                _c("静心参悟符纹", condition=_cond("comprehension", 6), rewards={"comprehension": 1, "cultivation": 70}, flavor="你悟出符中几分奥义，悟性与修为皆进。悟性 +1，修为 +70"),
                _c("静心参悟符纹", rewards={"cultivation": 40}, flavor="你略有所得。修为 +40"),
                _c("将符纸激发", condition=_cond("soul", 6), rewards={"soul": 1}, flavor="符纸化作一道护身灵光没入你体，神识略增。神识 +1"),
                _c("将符纸激发", rewards={"lifespan": -3}, flavor="符力反噬，你受了轻伤。寿元 -3"),
            ]
        }),
        _c("将符纸收好，不激发", rewards={"spirit_stones": 35}, flavor="你到城中将符纸卖给符师。灵石 +35"),
        _c("扔掉符纸", rewards={}, flavor="你随手扔掉符纸，继续赶路。"),
    ]
))

EVENTS.append(_e(
    "石人试炼",
    "山路旁立着两尊石人，一尊持剑，一尊持盾。碑文写：「过石人阵者，可得赏。」石人似乎会感应来人而动。",
    [
        _c("闯石人阵", next_event={
            "desc": "你刚踏入，两尊石人同时启动，一攻一守。需在数招内破阵或撑过一定时间。",
            "choices": [
                _c("先破持剑石人", condition=_cond("physique", 7), rewards={"physique": 1, "spirit_stones": 80}, flavor="你以体魄硬撼持剑石人，破阵后得赏。体魄 +1，灵石 +80"),
                _c("先破持剑石人", rewards={"lifespan": -5, "spirit_stones": 40}, flavor="你与石人缠斗受伤，勉强破阵得半赏。寿元 -5，灵石 +40"),
                _c("以巧劲寻破绽", condition=_cond("comprehension", 6), rewards={"comprehension": 1, "cultivation": 60}, flavor="你看出石人配合的破绽，破阵后悟性略增。悟性 +1，修为 +60"),
                _c("以巧劲寻破绽", rewards={"cultivation": 45}, flavor="你破阵略慢，仍得赏。修为 +45"),
            ]
        }),
        _c("不闯阵，离开", rewards={}, flavor="你自觉实力不足，未闯阵。"),
    ]
))

EVENTS.append(_e(
    "灵童指路",
    "一个约莫十来岁的灵童蹲在路口玩石子，见你走来，抬头道：「叔叔（阿姨）要去哪儿？前面岔路多，我可以指路，但要给我一块灵石。」",
    [
        _c("给灵石请他指路", next_event={
            "desc": "灵童收下灵石，笑嘻嘻道：「左边那条近但有妖兽，右边那条远但安全。还有一条小路，听说有宝贝，但我没去过。」",
            "choices": [
                _c("走左边近路", condition=_cond("physique", 7), rewards={"physique": 1, "cultivation": 50}, flavor="你击退拦路妖兽，体魄与修为皆进。体魄 +1，修为 +50"),
                _c("走左边近路", rewards={"lifespan": -6}, flavor="妖兽凶猛，你受伤后逃回。寿元 -6"),
                _c("走右边远路", rewards={"lifespan": 5}, flavor="你平安抵达，略费时辰但精神恢复。寿元 +5"),
                _c("走小路寻宝", condition=_cond("fortune", 6), rewards={"fortune": 1, "spirit_stones": 70}, flavor="你在小路上发现一处隐蔽灵泉，取了一壶。机缘 +1，灵石 +70"),
                _c("走小路寻宝", rewards={"lifespan": -2}, flavor="小路崎岖难行，你白走一遭。寿元 -2"),
            ]
        }),
        _c("不给灵石，自己选路", rewards={}, flavor="你未理会灵童，自行选了一条路。"),
    ]
))

EVENTS.append(_e(
    "旧剑重铸",
    "铁匠铺里，老师傅指着角落里一把断剑道：「这是客人遗下的，料子不错。你若出材料费，我可以帮你重铸成短刃。」",
    [
        _c("出材料费重铸", next_event={
            "desc": "老师傅收下灵石，三日后来取。他道：「铸成什么样，看你的缘法和我的状态。」",
            "choices": [
                _c("三日后取刃", condition=_cond("fortune", 6), rewards={"physique": 1, "spirit_stones": -40}, flavor="短刃铸成，品质上乘，你持之修炼体魄略增。体魄 +1，灵石 -40"),
                _c("三日后取刃", rewards={"spirit_stones": -40}, flavor="短刃铸成，品质普通。灵石 -40"),
                _c("留下帮忙拉风箱", condition=_cond("physique", 6), rewards={"physique": 1, "spirit_stones": -25}, flavor="你帮忙三日，老师傅少收你钱，短刃也铸得不错。体魄 +1，灵石 -25"),
                _c("留下帮忙拉风箱", rewards={"spirit_stones": -30}, flavor="你帮了忙，老师傅略减费用。灵石 -30"),
            ]
        }),
        _c("不铸，离开", rewards={}, flavor="你婉拒后离开。"),
    ]
))

EVENTS.append(_e(
    "灵雾幻象",
    "山谷中忽然起雾，雾中隐约有人影、兽影闪过，又似有楼台殿阁。据说灵雾会映出心中执念，久留易迷失。",
    [
        _c("闭目守心，缓步前行", condition=_cond("soul", 7), rewards={"soul": 1, "cultivation": 80}, flavor="你以神识守心，不为幻象所动，走出灵雾后神识与修为皆进。神识 +1，修为 +80"),
        _c("闭目守心，缓步前行", rewards={"cultivation": 45}, flavor="你勉强不为幻象所惑，走出灵雾。修为 +45"),
        _c("追随幻象中的一道人影", next_event={
            "desc": "你追着人影深入雾中，人影时隐时现，最终停在一处石壁前，石壁上刻着模糊字迹。",
            "choices": [
                _c("上前辨认字迹", condition=_cond("comprehension", 6), rewards={"comprehension": 1, "cultivation": 70}, flavor="你辨出是半篇心法残诀，参悟后悟性与修为皆进。悟性 +1，修为 +70"),
                _c("上前辨认字迹", rewards={"lifespan": -4}, flavor="你盯得太久，幻象反噬，头疼欲裂。寿元 -4"),
                _c("不辨字迹，立刻退走", rewards={"lifespan": -2}, flavor="你及时收神退出灵雾。寿元 -2"),
            ]
        }),
        _c("原地不动，等雾散", rewards={"lifespan": -1}, flavor="你等雾散后离开，略感疲惫。寿元 -1"),
    ]
))

EVENTS.append(_e(
    "灵稻丰收",
    "田边农人正在收灵稻，见你路过，喊道：「道友可愿帮半日忙？管饭，再给一袋灵米。」",
    [
        _c("答应帮忙", next_event={
            "desc": "你下田收割灵稻，半日下来腰酸背痛，但农人热情，饭菜里加了不少灵蔬。",
            "choices": [
                _c("收下一袋灵米", rewards={"cultivation": 50, "lifespan": 5}, flavor="你带回灵米，日后煮食可增修为与寿元。修为 +50，寿元 +5"),
                _c("婉拒灵米，只求一顿饭", condition=_cond("comprehension", 6), rewards={"comprehension": 1, "reputation": 15}, flavor="农人觉得你心善，多与你聊了些种植之道，悟性与声望皆进。悟性 +1，声望 +15"),
                _c("婉拒灵米，只求一顿饭", rewards={"reputation": 10}, flavor="农人感激，你声望略增。声望 +10"),
            ]
        }),
        _c("婉拒，继续赶路", rewards={}, flavor="你拱手告辞。"),
    ]
))

EVENTS.append(_e(
    "古镜照影",
    "破屋中有一面铜镜，镜面斑驳。你无意中照了照，镜中影像竟与你动作不同步，延迟了一息。",
    [
        _c("以神识探镜", next_event={
            "desc": "你将神识探入镜面，镜中似有另一重空间，你的倒影在其中回头看了你一眼。",
            "choices": [
                _c("与镜中影对视", condition=_cond("soul", 7), rewards={"soul": 1, "cultivation": 75}, flavor="你与镜中影神识相接，竟获得一丝感悟。神识 +1，修为 +75"),
                _c("与镜中影对视", rewards={"lifespan": -3}, flavor="镜中影忽然张口，你神识一痛。寿元 -3"),
                _c("立刻收神退开", rewards={"fortune": 1}, flavor="你及时收神，未遭反噬，冥冥中似得福缘。机缘 +1"),
            ]
        }),
        _c("不再照镜，离开", rewards={}, flavor="你不再看镜，退出破屋。"),
    ]
))

EVENTS.append(_e(
    "灵蛇蜕皮",
    "草丛中有一条灵蛇正在蜕皮，蛇身脆弱，见你靠近便缩成一团。蛇蜕是炼丹良材，但取之可能激怒灵蛇。",
    [
        _c("等蛇蜕完再取蛇蜕", next_event={
            "desc": "你静候片刻，灵蛇蜕完皮后缓缓游走。地上留下一张完整的蛇蜕。",
            "choices": [
                _c("取走蛇蜕", rewards={"spirit_stones": 70}, flavor="你取走蛇蜕，到城中卖了个好价。灵石 +70"),
                _c("取一半蛇蜕，留一半", condition=_cond("fortune", 6), rewards={"fortune": 1, "spirit_stones": 50}, flavor="你只取半张，灵蛇回头望你一眼，似有灵性。机缘 +1，灵石 +50"),
                _c("不取，让蛇蜕留于原地", rewards={"reputation": 5}, flavor="你未动蛇蜕，悄然离开。声望 +5"),
            ]
        }),
        _c("趁其蜕皮时强取", condition=_cond("physique", 6), rewards={"physique": 1, "spirit_stones": 55}, flavor="你速取蛇蜕，灵蛇反击咬了你一口，你击退它后离开。体魄 +1，灵石 +55"),
        _c("趁其蜕皮时强取", rewards={"lifespan": -8}, flavor="灵蛇暴起，你中毒受伤。寿元 -8"),
        _c("不打扰，离开", rewards={}, flavor="你绕开灵蛇离开。"),
    ]
))

EVENTS.append(_e(
    "灵灯引魂",
    "夜路上有人提着一盏灵灯独行，灯焰幽蓝。那人道：「跟灯走，可避邪祟；灭灯走，可遇机缘。道友自选。」",
    [
        _c("跟灯走", rewards={"lifespan": 5}, flavor="你随灵灯行了一程，一路平安，心神安宁。寿元 +5"),
        _c("灭灯自走", next_event={
            "desc": "你吹灭灵灯，独行于夜路。黑暗中隐约有磷火与低语，你需稳住心神。",
            "choices": [
                _c("以神识护体前行", condition=_cond("soul", 6), rewards={"soul": 1, "cultivation": 65}, flavor="你神识稳固，邪祟不侵，反在夜行中有所悟。神识 +1，修为 +65"),
                _c("以神识护体前行", rewards={"cultivation": 35}, flavor="你平安走过夜路。修为 +35"),
                _c("循磷火方向探去", condition=_cond("fortune", 7), rewards={"fortune": 1, "spirit_stones": 80}, flavor="磷火指引你找到一处无主坟前的供品，中有灵石。机缘 +1，灵石 +80"),
                _c("循磷火方向探去", rewards={"lifespan": -4}, flavor="你被阴气所侵，略损元气。寿元 -4"),
            ]
        }),
        _c("不与提灯人同行，另择路", rewards={}, flavor="你选了别的路离开。"),
    ]
))

EVENTS.append(_e(
    "灵泉分流",
    "山涧在此分为两股，一股温热一股冰凉。据说两股交汇处有「阴阳泉眼」，在此修炼可事半功倍。",
    [
        _c("在交汇处打坐", next_event={
            "desc": "你在阴阳泉眼处盘坐，冷热二流交替冲刷周身，需以功法引导方能化用。",
            "choices": [
                _c("以神识引导二气", condition=_cond("soul", 7), rewards={"soul": 1, "cultivation": 90}, flavor="你以神识调和阴阳二气，修为与神识皆进。神识 +1，修为 +90"),
                _c("以神识引导二气", rewards={"cultivation": 55}, flavor="你略有所得。修为 +55"),
                _c("以体魄硬抗冷热", condition=_cond("physique", 6), rewards={"physique": 1, "lifespan": 10}, flavor="你以体魄承受冷热交替，体魄与寿元皆进。体魄 +1，寿元 +10"),
                _c("以体魄硬抗冷热", rewards={"lifespan": 5}, flavor="你撑了一炷香，略有收获。寿元 +5"),
            ]
        }),
        _c("只取一壶泉水带走", rewards={"spirit_stones": 30}, flavor="你装了一壶灵泉水，可售或自用。灵石 +30"),
        _c("不逗留，离开", rewards={}, flavor="你未在泉边修炼，继续赶路。"),
    ]
))

EVENTS.append(_e(
    "灵鹊搭桥",
    "一群灵鹊聚在断崖边，衔枝搭成一道窄桥。鹊桥仅容一人通过，且不知能撑多久。",
    [
        _c("踏鹊桥过崖", next_event={
            "desc": "你踏上鹊桥，灵鹊啾鸣，桥身微颤。需心无杂念、步法轻盈，方能安稳通过。",
            "choices": [
                _c("凝神稳步而过", condition=_cond("soul", 6), rewards={"soul": 1, "cultivation": 60}, flavor="你心无杂念走过鹊桥，神识与修为皆进。神识 +1，修为 +60"),
                _c("凝神稳步而过", rewards={"cultivation": 35}, flavor="你安稳过崖。修为 +35"),
                _c("快步冲过", condition=_cond("physique", 6), rewards={"physique": 1}, flavor="你快步冲过，鹊桥在你身后塌落。体魄 +1"),
                _c("快步冲过", rewards={"lifespan": -6}, flavor="你踏断数枝，险些坠崖，勉强爬回。寿元 -6"),
            ]
        }),
        _c("不冒险，绕路下崖", rewards={"lifespan": -3}, flavor="你绕了远路。寿元 -3"),
    ]
))

EVENTS.append(_e(
    "灵植争执",
    "两名修士为一株灵草的归属争执不下，灵草长在二人地界交界处。他们见你路过，齐声道：「道友来评评理！」",
    [
        _c("提议二人平分或抽签", condition=_cond("comprehension", 6), rewards={"reputation": 20, "spirit_stones": 30}, flavor="你说服二人抽签决定，二人各送你一点谢礼。声望 +20，灵石 +30"),
        _c("提议二人平分或抽签", rewards={"reputation": 10}, flavor="二人勉强接受你的提议。声望 +10"),
        _c("说谁先发现归谁", rewards={"reputation": -10}, flavor="二人都不服，反而迁怒于你。声望 -10"),
        _c("不掺和，离开", rewards={}, flavor="你拱手离开，不涉纠纷。"),
    ]
))

EVENTS.append(_e(
    "灵鼓擂响",
    "山寨口架着一面大鼓，有修士在擂鼓聚众。鼓声震人心魄，有人道：「擂鼓三通可试胆魄，通过者能入寨领赏。」",
    [
        _c("上前试鼓", next_event={
            "desc": "你站在鼓前，擂鼓者连擂三通，每通鼓声都直冲识海。你需稳住心神不乱。",
            "choices": [
                _c("以神识抵御鼓声", condition=_cond("soul", 7), rewards={"soul": 1, "spirit_stones": 70}, flavor="你神识稳固，三通鼓罢面不改色，入寨领赏。神识 +1，灵石 +70"),
                _c("以神识抵御鼓声", rewards={"spirit_stones": 40}, flavor="你勉强撑过三通鼓，领了半赏。灵石 +40"),
                _c("以体魄硬抗", condition=_cond("physique", 6), rewards={"physique": 1, "cultivation": 50}, flavor="你以体魄硬抗鼓声，过关后体魄与修为略增。体魄 +1，修为 +50"),
                _c("以体魄硬抗", rewards={"lifespan": -4}, flavor="鼓声震得你气血翻涌，未过关。寿元 -4"),
            ]
        }),
        _c("不试，离开", rewards={}, flavor="你未擂鼓，转身离开。"),
    ]
))
