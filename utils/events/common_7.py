from utils.events._base import _e, _c, _cond

EVENTS = []

EVENTS.append(_e(
    "灵龟驮碑",
    "溪流中一只灵龟驮着一块小石碑缓缓爬行。碑上刻着几行古字，据说灵龟会择人而停，停时便可观碑。",
    [
        _c("静候灵龟靠近", next_event={
            "desc": "灵龟在你面前停下，将碑身侧向你。碑上字迹古朴，需以悟性参悟。",
            "choices": [
                _c("凝神参悟碑文", condition=_cond("comprehension", 7), rewards={"comprehension": 1, "cultivation": 85}, flavor="你悟出碑中一丝道意，悟性与修为皆进。悟性 +1，修为 +85"),
                _c("凝神参悟碑文", rewards={"cultivation": 50}, flavor="你略有所得。修为 +50"),
                _c("以神识拓印碑文", condition=_cond("soul", 6), rewards={"soul": 1, "cultivation": 60}, flavor="你以神识强记碑文，日后可慢慢参悟。神识 +1，修为 +60"),
                _c("以神识拓印碑文", rewards={"cultivation": 35}, flavor="你记下部分碑文。修为 +35"),
            ]
        }),
        _c("不打扰灵龟，离开", rewards={"fortune": 1}, flavor="你未惊动灵龟，悄然离开，冥冥中似得福缘。机缘 +1"),
    ]
))

EVENTS.append(_e(
    "灵矿碎屑",
    "矿洞外堆着大量废石，矿工说内里偶有灵矿碎屑混在废石中，谁捡到算谁的。不少人在废石堆里翻找。",
    [
        _c("在废石堆中翻找", next_event={
            "desc": "你翻了一阵，手心被碎石划破几处。有人找到了一小块灵矿，欢呼出声。",
            "choices": [
                _c("继续耐心翻找", condition=_cond("fortune", 6), rewards={"fortune": 1, "spirit_stones": 65}, flavor="你终于翻到一块灵矿碎屑，售出得利。机缘 +1，灵石 +65"),
                _c("继续耐心翻找", rewards={"spirit_stones": 35}, flavor="你翻到几块含灵气的碎石，勉强能卖点钱。灵石 +35"),
                _c("以神识感应灵气", condition=_cond("soul", 6), rewards={"soul": 1, "spirit_stones": 55}, flavor="你以神识辨出灵矿位置，省时省力。神识 +1，灵石 +55"),
                _c("以神识感应灵气", rewards={"spirit_stones": 25}, flavor="你感应到几处微弱灵气，取到少许。灵石 +25"),
            ]
        }),
        _c("不翻找，离开", rewards={}, flavor="你对废石堆无兴趣，径自离开。"),
    ]
))

EVENTS.append(_e(
    "灵笛招兽",
    "林中有修士正在吹笛，笛声悠扬，引来几只灵兽驻足倾听。他见你路过，停下笛声道：「道友可会吹笛？若能让灵兽起舞，我赠你一支灵笛。」",
    [
        _c("借笛试吹", next_event={
            "desc": "你接过灵笛吹了几声，灵兽们侧耳倾听。需以神识或悟性融入笛音，方能引动灵兽。",
            "choices": [
                _c("以神识融入笛音", condition=_cond("soul", 7), rewards={"soul": 1, "spirit_stones": 60}, flavor="灵兽闻音起舞，修士兑现承诺赠你灵笛，你售出得灵石。神识 +1，灵石 +60"),
                _c("以神识融入笛音", rewards={"spirit_stones": 30}, flavor="灵兽略有反应，修士赠你少许灵石。灵石 +30"),
                _c("随意吹奏", condition=_cond("fortune", 6), rewards={"fortune": 1}, flavor="你误打误撞吹出一段旋律，灵兽竟也动了动。修士赠你一支普通笛子。机缘 +1"),
                _c("随意吹奏", rewards={}, flavor="灵兽无动于衷，修士收回笛子。"),
            ]
        }),
        _c("不会吹笛，婉拒", rewards={}, flavor="你拱手告辞。"),
    ]
))

EVENTS.append(_e(
    "灵火余烬",
    "某处曾有人在此炼丹或炼器，地上留有一圈灵火余烬，余烬中仍有微弱火灵之气。在此打坐或可借余火悟道。",
    [
        _c("在余烬旁打坐", next_event={
            "desc": "你盘坐于余烬旁，火灵之气丝丝缕缕渗入体内。需以功法引导，否则易灼伤经脉。",
            "choices": [
                _c("以神识引导火灵", condition=_cond("soul", 6), rewards={"soul": 1, "cultivation": 75}, flavor="你稳稳炼化火灵之气，神识与修为皆进。神识 +1，修为 +75"),
                _c("以神识引导火灵", rewards={"cultivation": 45}, flavor="你炼化部分火灵，修为略增。修为 +45"),
                _c("以体魄硬抗火灵淬体", condition=_cond("physique", 6), rewards={"physique": 1, "cultivation": 55}, flavor="你以体魄承受火灵淬体，体魄与修为皆进。体魄 +1，修为 +55"),
                _c("以体魄硬抗火灵淬体", rewards={"lifespan": -3, "cultivation": 30}, flavor="火灵略伤经脉，你有所得但损了元气。寿元 -3，修为 +30"),
            ]
        }),
        _c("不打坐，只取一点余烬", rewards={"spirit_stones": 40}, flavor="你取了一撮余烬，可作炼器辅料出售。灵石 +40"),
        _c("离开", rewards={}, flavor="你未在余烬旁逗留。"),
    ]
))

EVENTS.append(_e(
    "灵符残页",
    "地上散落着几张残破的灵符，符上朱砂已淡。若以灵力激发，或能发挥残存威力，也可能直接报废。",
    [
        _c("拾起一张尝试激发", next_event={
            "desc": "你将灵力注入残符，符纸微微发亮。需以神识控制力度，否则可能炸符。",
            "choices": [
                _c("小心控制灵力", condition=_cond("soul", 6), rewards={"soul": 1, "spirit_stones": 50}, flavor="残符化作一道护身灵光，你有所悟，并将另几张残符售出。神识 +1，灵石 +50"),
                _c("小心控制灵力", rewards={"spirit_stones": 30}, flavor="残符激发后化为灰烬，你另几张售出得少许灵石。灵石 +30"),
                _c("全力激发", condition=_cond("fortune", 6), rewards={"fortune": 1, "cultivation": 50}, flavor="残符竟完整激发，你从中悟出一丝符道。机缘 +1，修为 +50"),
                _c("全力激发", rewards={"lifespan": -2}, flavor="残符炸裂，你被符力擦伤。寿元 -2"),
            ]
        }),
        _c("不激发，只带走残符", rewards={"spirit_stones": 35}, flavor="你将残符带到城中卖给符师。灵石 +35"),
        _c("不捡，离开", rewards={}, flavor="你未动残符，径自离开。"),
    ]
))

EVENTS.append(_e(
    "灵泉争饮",
    "山泉边围着几只灵兽与数名修士，都在等泉眼涌出灵泉。下一波涌泉即将到来，谁先谁后可能引发冲突。",
    [
        _c("排队等候", condition=_cond("fortune", 6), rewards={"lifespan": 12, "fortune": 1}, flavor="轮到你时灵泉正旺，你饮后神清气爽。寿元 +12，机缘 +1"),
        _c("排队等候", rewards={"lifespan": 8}, flavor="你饮到一些灵泉，略有补益。寿元 +8"),
        _c("提议众人与灵兽各让一步", condition=_cond("comprehension", 6), rewards={"reputation": 20, "lifespan": 10}, flavor="你说服众人与灵兽轮流取水，秩序井然，众人赞你。声望 +20，寿元 +10"),
        _c("提议众人与灵兽各让一步", rewards={"reputation": 10}, flavor="众人勉强接受，你略得名声。声望 +10"),
        _c("不争，离开", rewards={}, flavor="你未参与争饮，继续赶路。"),
    ]
))

EVENTS.append(_e(
    "灵幡招魂",
    "荒地上插着几杆破旧灵幡，幡上符文明灭。据说此地曾为古战场，灵幡是后人超度亡魂所立。有人言在此静心可感亡魂执念，或得或失。",
    [
        _c("在灵幡间静坐", next_event={
            "desc": "你闭目静坐，耳畔似有金戈铁马之声，又似有低语呢喃。需守稳心神，方能从中提炼一丝执念感悟。",
            "choices": [
                _c("以神识接纳执念而不迷失", condition=_cond("soul", 7), rewards={"soul": 1, "cultivation": 80}, flavor="你从亡魂执念中悟出一式残招，神识与修为皆进。神识 +1，修为 +80"),
                _c("以神识接纳执念而不迷失", rewards={"cultivation": 45}, flavor="你略有所得。修为 +45"),
                _c("只感其意，不纳其念", condition=_cond("comprehension", 6), rewards={"comprehension": 1}, flavor="你悟出执念中的一丝战意，化为己用。悟性 +1"),
                _c("只感其意，不纳其念", rewards={"lifespan": -3}, flavor="你心神略受冲击，速速退走。寿元 -3"),
            ]
        }),
        _c("不靠近灵幡", rewards={}, flavor="你绕开灵幡离开。"),
    ]
))

EVENTS.append(_e(
    "灵果未熟",
    "枝头挂着一颗灵果，尚差数日才熟透。若现在摘取，药效大减；若等，可能被他人或灵兽抢先。",
    [
        _c("现在摘取", rewards={"spirit_stones": 40, "lifespan": 5}, flavor="你摘下半熟灵果，售出与自用各半，略有补益。灵石 +40，寿元 +5"),
        _c("在树下守候数日", next_event={
            "desc": "你守在树下，第三日灵果转红，香气四溢。同时一只灵猴也盯上了灵果。",
            "choices": [
                _c("与灵猴争夺", condition=_cond("physique", 7), rewards={"physique": 1, "lifespan": 20, "cultivation": 40}, flavor="你击退灵猴摘得熟果，服下后体魄、寿元与修为皆进。体魄 +1，寿元 +20，修为 +40"),
                _c("与灵猴争夺", rewards={"lifespan": -5, "cultivation": 30}, flavor="灵猴凶猛，你带伤摘得半颗灵果。寿元 -5，修为 +30"),
                _c("分灵猴一半", condition=_cond("fortune", 6), rewards={"fortune": 1, "lifespan": 18}, flavor="灵猴与你各得一半，食后灵猴赠你一枚灵核。机缘 +1，寿元 +18"),
                _c("分灵猴一半", rewards={"lifespan": 12}, flavor="你与灵猴分食，各有收获。寿元 +12"),
            ]
        }),
        _c("不守不等，离开", rewards={}, flavor="你未打灵果主意，径自离开。"),
    ]
))

EVENTS.append(_e(
    "灵签问运",
    "庙前有修士摆摊解签，道：「抽一签，可问近日机缘、修行、凶吉。一签五灵石。」",
    [
        _c("付灵石抽一签", next_event={
            "desc": "你抽中一签，解签人道：「此签主吉中带险，宜往东南，忌贪多。」",
            "choices": [
                _c("再付灵石问细解", condition=_cond("fortune", 6), rewards={"spirit_stones": -10, "fortune": 1, "cultivation": 50}, flavor="解签人细说东南有一处灵地，你按言前往，果有所得。灵石 -10，机缘 +1，修为 +50"),
                _c("再付灵石问细解", rewards={"spirit_stones": -10}, flavor="解签人又说了些泛泛之辞。灵石 -10"),
                _c("谢过便走", rewards={}, flavor="你记下「东南」二字，未再深问。"),
            ]
        }),
        _c("不抽签，离开", rewards={}, flavor="你对问签无兴趣，径自离开。"),
    ]
))

EVENTS.append(_e(
    "灵犬寻宝",
    "一只灵犬拦住你，叼着你的衣角往某个方向扯，似要带你去某处。它颈上有项圈，应是有人饲养。",
    [
        _c("跟着灵犬走", next_event={
            "desc": "灵犬将你引到一处乱石堆，在石堆旁刨土，刨出一个小布袋。袋中有些灵石和一张字条：「谢过道友相助，此犬常走失，袋中灵石权当谢礼。」",
            "choices": [
                _c("取走布袋，带灵犬找主人", condition=_cond("fortune", 6), rewards={"fortune": 1, "spirit_stones": 80, "reputation": 15}, flavor="你找到主人，主人额外赠你谢礼。机缘 +1，灵石 +80，声望 +15"),
                _c("取走布袋，带灵犬找主人", rewards={"spirit_stones": 60}, flavor="你将灵犬送回，主人赠你袋中灵石。灵石 +60"),
                _c("只取部分灵石，留袋与犬", rewards={"reputation": 20, "spirit_stones": 40}, flavor="你只取少许灵石，将袋与犬留在原地，主人后来寻到，对你感激。声望 +20，灵石 +40"),
            ]
        }),
        _c("不跟，甩开灵犬", rewards={}, flavor="你未随灵犬，径自离开。"),
    ]
))

EVENTS.append(_e(
    "灵雨过后",
    "一场灵雨刚停，地上积水未退，草木挂着水珠，灵气氤氲。据说灵雨后的水珠与草木可短暂存留精纯灵气。",
    [
        _c("收集草叶上的灵露", next_event={
            "desc": "你以瓶罐收集灵露，需轻手轻脚，否则灵露易散。收集多寡看手法与机缘。",
            "choices": [
                _c("以神识轻取灵露", condition=_cond("soul", 6), rewards={"soul": 1, "spirit_stones": 55}, flavor="你以神识控取，收集到不少灵露，售出得利。神识 +1，灵石 +55"),
                _c("以神识轻取灵露", rewards={"spirit_stones": 35}, flavor="你收集到一些灵露。灵石 +35"),
                _c("直接以手拂取", condition=_cond("fortune", 6), rewards={"fortune": 1, "lifespan": 10}, flavor="你拂取时灵露未散，饮下后寿元略增。机缘 +1，寿元 +10"),
                _c("直接以手拂取", rewards={"lifespan": 5}, flavor="你取到少许灵露饮下。寿元 +5"),
            ]
        }),
        _c("在灵雨中打坐片刻（回忆）", rewards={"cultivation": 40}, flavor="你回想灵雨时的感悟，略有所得。修为 +40"),
        _c("不收集，离开", rewards={}, flavor="你未收集灵露，继续赶路。"),
    ]
))

EVENTS.append(_e(
    "灵碑留名",
    "山道旁有一块留名碑，碑上刻满历代修士的名字。据说在碑上留名者可借碑中残存的愿力，得一丝福缘。",
    [
        _c("在碑上留名", next_event={
            "desc": "你以指力或灵力在碑上刻下名字。碑身微震，一缕若有若无的气息拂过你身。",
            "choices": [
                _c("静心感应愿力", condition=_cond("soul", 6), rewards={"soul": 1, "fortune": 1}, flavor="你从愿力中感应到一丝祝福，神识与机缘皆进。神识 +1，机缘 +1"),
                _c("静心感应愿力", rewards={"fortune": 1}, flavor="你略有所感。机缘 +1"),
                _c("留名后恭敬行礼", rewards={"reputation": 10}, flavor="你留名后对碑行礼，路人见之赞你有礼。声望 +10"),
            ]
        }),
        _c("不留名，只观碑", rewards={"cultivation": 25}, flavor="你观碑上留名，略有所悟。修为 +25"),
        _c("离开", rewards={}, flavor="你未在碑前逗留。"),
    ]
))

EVENTS.append(_e(
    "灵棺古墓",
    "荒野中露出一角石棺，棺盖已斜，似被人开过。棺内空空，但棺底刻有符文，隐约有灵气残留。",
    [
        _c("观察棺底符文", next_event={
            "desc": "你细看符文，似与阵法或封印有关。若以神识或悟性参悟，或有所得；若胡乱触碰，可能触发残阵。",
            "choices": [
                _c("以神识感应符文", condition=_cond("soul", 6), rewards={"soul": 1, "cultivation": 65}, flavor="你从符文中悟出一丝阵法之理，神识与修为皆进。神识 +1，修为 +65"),
                _c("以神识感应符文", rewards={"cultivation": 40}, flavor="你略有所得。修为 +40"),
                _c("以灵力轻触符文", condition=_cond("fortune", 6), rewards={"fortune": 1, "spirit_stones": 50}, flavor="符文反馈一缕灵气，凝成小块灵晶。机缘 +1，灵石 +50"),
                _c("以灵力轻触符文", rewards={"lifespan": -4}, flavor="符文反噬，你受了轻伤。寿元 -4"),
            ]
        }),
        _c("不碰古棺，离开", rewards={}, flavor="你未动古棺，绕道离开。"),
    ]
))

EVENTS.append(_e(
    "灵宴邀请",
    "路遇一名修士，他道：「前方敝舍设了灵宴，道友若有暇，可来一聚。席间有灵酒灵果，不取分文。」",
    [
        _c("应邀赴宴", next_event={
            "desc": "灵宴上宾主尽欢，灵酒灵果入口即化。席间有人提议以助兴为名，切磋论道。",
            "choices": [
                _c("参与切磋", condition=_cond("physique", 6), rewards={"physique": 1, "reputation": 15}, flavor="你在切磋中不落下风，众人赞你，体魄亦有所得。体魄 +1，声望 +15"),
                _c("参与切磋", rewards={"cultivation": 50}, flavor="你虽落败，但从对方招式中有所悟。修为 +50"),
                _c("只论道不切磋", condition=_cond("comprehension", 6), rewards={"comprehension": 1, "lifespan": 10}, flavor="你与众人论道，悟性与寿元皆进。悟性 +1，寿元 +10"),
                _c("只论道不切磋", rewards={"lifespan": 8}, flavor="你饮了灵酒灵果，寿元略增。寿元 +8"),
            ]
        }),
        _c("婉拒邀请", rewards={}, flavor="你拱手辞谢，继续赶路。"),
    ]
))

EVENTS.append(_e(
    "灵雾锁江",
    "江面被灵雾封锁，渡船停摆。对岸隐约可见，若强行渡江，需以神识辨路或体魄硬闯。",
    [
        _c("以神识辨路渡江", condition=_cond("soul", 7), rewards={"soul": 1, "cultivation": 60}, flavor="你以神识辨明方向，安然渡江，神识与修为皆进。神识 +1，修为 +60"),
        _c("以神识辨路渡江", rewards={"cultivation": 35}, flavor="你勉强辨路渡江。修为 +35"),
        _c("凭体魄强渡", condition=_cond("physique", 6), rewards={"physique": 1}, flavor="你凭体魄与耐力游过江面，体魄略增。体魄 +1"),
        _c("凭体魄强渡", rewards={"lifespan": -5}, flavor="你在雾中迷失方向，险些溺水。寿元 -5"),
        _c("等雾散再渡", rewards={"lifespan": -2}, flavor="你等到雾散，多费了半日。寿元 -2"),
    ]
))

EVENTS.append(_e(
    "灵珠蒙尘",
    "摊位上有一颗沾满灰尘的珠子，摊主说不知来历，便宜卖。珠子在灰尘下隐约有灵光。",
    [
        _c("买下灵珠", next_event={
            "desc": "你付钱取珠，拭去灰尘后灵光更显。需以灵力或神识温养，方能辨明珠中奥妙。",
            "choices": [
                _c("以灵力温养", condition=_cond("soul", 6), rewards={"soul": 1, "cultivation": 55}, flavor="灵珠认主，反哺你一丝灵气，神识与修为皆进。神识 +1，修为 +55"),
                _c("以灵力温养", rewards={"cultivation": 35}, flavor="灵珠略有反应，你略有所得。修为 +35"),
                _c("不温养，直接售出", condition=_cond("fortune", 6), rewards={"fortune": 1, "spirit_stones": 70}, flavor="你将灵珠卖给识货之人，卖得高价。机缘 +1，灵石 +70"),
                _c("不温养，直接售出", rewards={"spirit_stones": 45}, flavor="你售出灵珠，小赚一笔。灵石 +45"),
            ]
        }),
        _c("不买，离开", rewards={}, flavor="你对蒙尘珠无兴趣，径自离开。"),
    ]
))

EVENTS.append(_e(
    "灵契残卷",
    "旧书堆里有一份残破的灵契，契上写的是某处灵地的使用权，地契年代久远，不知是否仍有效。",
    [
        _c("按灵契所指前往灵地", next_event={
            "desc": "你寻至契上所载地点，发现是一片荒废灵田，杂草丛生，但地脉中仍有微弱灵气。",
            "choices": [
                _c("尝试开垦灵田", condition=_cond("physique", 6), rewards={"physique": 1, "cultivation": 60}, flavor="你清理灵田、引灵泉，体魄在劳作中有所得，灵田略复灵气。体魄 +1，修为 +60"),
                _c("尝试开垦灵田", rewards={"cultivation": 40}, flavor="你略作整理，灵田稍有起色。修为 +40"),
                _c("将灵契转卖", condition=_cond("fortune", 6), rewards={"fortune": 1, "spirit_stones": 80}, flavor="有人信契，出价买下此地。机缘 +1，灵石 +80"),
                _c("将灵契转卖", rewards={"spirit_stones": 50}, flavor="你以低价将灵契转手。灵石 +50"),
            ]
        }),
        _c("不按契寻地，只留契", rewards={"spirit_stones": 20}, flavor="你将灵契当古物卖出。灵石 +20"),
    ]
))

EVENTS.append(_e(
    "灵幡镇邪",
    "村口立着几杆灵幡，村民说此地近日邪祟作怪，灵幡是请修士所立。你若能加固灵幡或驱邪，村民愿酬谢。",
    [
        _c("检查灵幡并加固", next_event={
            "desc": "你发现灵幡符文已有破损，需以灵力补全。补全时若神识不足，可能引动邪气反噬。",
            "choices": [
                _c("以神识补全符文", condition=_cond("soul", 6), rewards={"soul": 1, "spirit_stones": 70, "reputation": 20}, flavor="你补全符文，邪祟退散，村民重谢。神识 +1，灵石 +70，声望 +20"),
                _c("以神识补全符文", rewards={"spirit_stones": 45}, flavor="你勉强补全，邪祟略减。灵石 +45"),
                _c("提议村民迁离几日", rewards={"reputation": 15}, flavor="你建议村民暂避，你独守灵幡数日，邪祟渐散。声望 +15"),
            ]
        }),
        _c("不接活，离开", rewards={}, flavor="你婉拒后离开。"),
    ]
))

EVENTS.append(_e(
    "灵泉竞拍",
    "坊市中有人兜售「灵泉取水权」，一日内可至某处灵泉取水一壶，价高者得。目前出价已到五十灵石。",
    [
        _c("出价六十灵石", condition=_cond("fortune", 6), rewards={"spirit_stones": -60, "lifespan": 25, "cultivation": 50}, flavor="你拍得取水权，灵泉品质上乘，服后寿元与修为皆进。灵石 -60，寿元 +25，修为 +50"),
        _c("出价六十灵石", rewards={"spirit_stones": -60, "lifespan": 15}, flavor="你拍得取水权，灵泉物有所值。灵石 -60，寿元 +15"),
        _c("不竞拍，离开", rewards={}, flavor="你觉得太贵，未参与竞拍。"),
    ]
))

EVENTS.append(_e(
    "灵兽斗会",
    "城中举办灵兽斗会，观众可押注。一只不起眼的小兽连克强敌，众人开始押它。庄家赔率已变。",
    [
        _c("押小兽", condition=_cond("fortune", 6), rewards={"spirit_stones": 55}, flavor="小兽再胜，你小赚。灵石 +55"),
        _c("押小兽", rewards={"spirit_stones": -25}, flavor="小兽此局落败，你输了。灵石 -25"),
        _c("押小兽的对手", condition=_cond("fortune", 7), rewards={"spirit_stones": 70}, flavor="对手爆冷胜出，你赚了一笔。灵石 +70"),
        _c("押小兽的对手", rewards={"spirit_stones": -20}, flavor="对手不敌，你输了。灵石 -20"),
        _c("不押注，只看", rewards={}, flavor="你只看热闹，未下注。"),
    ]
))

EVENTS.append(_e(
    "灵植认主",
    "一株灵植无风自动，叶片指向你。据说有些灵植会择主而依，若以精血或灵力与之结契，或可收为灵宠。",
    [
        _c("以一滴精血试结契", next_event={
            "desc": "你将精血滴在灵植根上，灵植微微发光。需以神识与之沟通，方能定契。",
            "choices": [
                _c("以神识沟通灵植", condition=_cond("soul", 7), rewards={"soul": 1, "lifespan": 15, "cultivation": 50}, flavor="灵植认主，反哺你生机与灵气。神识 +1，寿元 +15，修为 +50"),
                _c("以神识沟通灵植", rewards={"lifespan": 10}, flavor="灵植略有回应，你寿元略增。寿元 +10"),
                _c("不强行结契，收手", rewards={"fortune": 1}, flavor="你未强求，灵植赠你一片灵叶后萎去。机缘 +1"),
            ]
        }),
        _c("不结契，离开", rewards={}, flavor="你未与灵植结契，径自离开。"),
    ]
))

EVENTS.append(_e(
    "灵舟渡口",
    "渡口停着一艘灵舟，船公道：「此舟可渡灵江，江心有灵漩，靠近者可借灵漩修炼片刻，但需多付十灵石。」",
    [
        _c("多付十灵石，请船公靠近灵漩", next_event={
            "desc": "灵舟驶近灵漩，漩中灵气翻涌。你需在舟上抓紧时间吸纳灵气，船公只等一炷香。",
            "choices": [
                _c("全力吸纳灵漩之气", condition=_cond("soul", 6), rewards={"soul": 1, "cultivation": 80}, flavor="你在一炷香内吸纳不少灵气，神识与修为皆进。神识 +1，修为 +80"),
                _c("全力吸纳灵漩之气", rewards={"cultivation": 50}, flavor="你吸纳部分灵气。修为 +50"),
                _c("只感其意不强吸", condition=_cond("comprehension", 6), rewards={"comprehension": 1, "cultivation": 55}, flavor="你从灵漩运转中悟出一丝道意。悟性 +1，修为 +55"),
                _c("只感其意不强吸", rewards={"cultivation": 35}, flavor="你略有所得。修为 +35"),
            ]
        }),
        _c("不靠近灵漩，正常渡江", rewards={"lifespan": 5}, flavor="你正常渡江，略作休息。寿元 +5"),
    ]
))
