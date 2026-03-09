from utils.events._base import _e, _c, _cond

EVENTS = []

EVENTS.append(_e(
    "【稀有】凤凰涅槃",
    "荒山深处，你见到一只浴火凤凰的虚影在烈焰中翻腾，火焰中心有一颗赤红色的晶核，散发着惊人的生机与灵气。",
    [
        _c("靠近火焰，尝试取晶核", next_event={
            "desc": "烈焰灼人，你以灵力护体步步逼近，晶核似有灵性，时而靠近时而远离。",
            "choices": [
                _c("以神识与火焰沟通", condition=_cond("soul", 8), rewards={"soul": 2, "lifespan": 80, "cultivation": 350}, flavor="凤凰虚影认可了你，晶核主动飞入你手中，炼化后神识大涨，寿元与修为皆进。神识 +2，寿元 +80，修为 +350"),
                _c("以神识与火焰沟通", rewards={"lifespan": 40, "cultivation": 200}, flavor="你勉强取得一丝涅槃余韵，寿元与修为有所提升。寿元 +40，修为 +200"),
                _c("强闯取核", condition=_cond("physique", 8), rewards={"physique": 2, "bone": 1, "cultivation": 300}, flavor="你以体魄硬抗烈焰，取到晶核炼化，体魄与根骨皆得淬炼。体魄 +2，根骨 +1，修为 +300"),
                _c("强闯取核", rewards={"lifespan": -25, "cultivation": 150}, flavor="烈焰反噬，你重伤而退，只炼化了一缕余火。寿元 -25，修为 +150"),
            ]
        }),
        _c("在火海外围打坐感悟", condition=_cond("comprehension", 7), rewards={"comprehension": 1, "cultivation": 250, "lifespan": 30}, flavor="你从涅槃之火中悟出一丝生机之道，悟性、修为与寿元皆有进境。悟性 +1，修为 +250，寿元 +30"),
        _c("在火海外围打坐感悟", rewards={"cultivation": 150}, flavor="你感悟有限，修为略增。修为 +150"),
        _c("恭敬行礼后离开", rewards={"fortune": 2}, flavor="你未敢亵渎神兽涅槃之地，恭敬离去，冥冥中似得福缘。机缘 +2"),
    ]
))

EVENTS.append(_e(
    "【稀有】星河倒灌",
    "夜半时分，天幕忽然裂开一道缝隙，璀璨星河自裂缝中倾泻而下，落在不远处山谷，将整片山谷映得如同白昼。",
    [
        _c("冲入星河倾泻之处", next_event={
            "desc": "星辉入体，你感到磅礴的星辰之力在经脉中奔涌，需以神识引导方能炼化。",
            "choices": [
                _c("静心引导星辰之力", condition=_cond("soul", 8), rewards={"soul": 2, "cultivation": 450, "lifespan": 50}, flavor="你以神识引导星力归元，修为暴涨，神识大涨，寿元亦得滋养。神识 +2，修为 +450，寿元 +50"),
                _c("静心引导星辰之力", rewards={"cultivation": 280, "lifespan": 25}, flavor="你炼化部分星力，修为大进，寿元略增。修为 +280，寿元 +25"),
                _c("以体魄硬抗星力淬体", condition=_cond("physique", 8), rewards={"physique": 2, "bone": 1, "cultivation": 350}, flavor="星力淬体，你体魄与根骨皆得蜕变，修为猛进。体魄 +2，根骨 +1，修为 +350"),
                _c("以体魄硬抗星力淬体", rewards={"lifespan": -15, "cultivation": 200}, flavor="星力过猛，你受了内伤，但修为仍有大进。寿元 -15，修为 +200"),
            ]
        }),
        _c("在外围收集星辉凝成的灵石", condition=_cond("fortune", 7), rewards={"spirit_stones": 500, "fortune": 1}, flavor="星辉落地后凝成灵晶，你收集了一批，价值不菲。灵石 +500，机缘 +1"),
        _c("在外围收集星辉凝成的灵石", rewards={"spirit_stones": 280}, flavor="你捡到一些星辉灵晶，换得不少灵石。灵石 +280"),
        _c("不敢靠近，只远观感悟", rewards={"comprehension": 1, "cultivation": 120}, flavor="你远观星河异象，心有所悟。悟性 +1，修为 +120"),
    ]
))

EVENTS.append(_e(
    "【稀有】上古剑仙传承",
    "剑冢深处，一柄锈迹斑斑的古剑忽然嗡鸣，剑身浮现出一缕残魂虚影，道：「吾乃上古剑修，陨落于此，可愿承吾剑道？」",
    [
        _c("跪拜受传承", next_event={
            "desc": "剑仙残魂将一缕剑意渡入你识海，你需以悟性化解其中奥义，否则反伤神魂。",
            "choices": [
                _c("全心参悟剑意", condition=_cond("comprehension", 8), rewards={"comprehension": 2, "soul": 1, "cultivation": 400}, flavor="你参透剑意，悟性与神识皆大涨，修为暴涨。悟性 +2，神识 +1，修为 +400"),
                _c("全心参悟剑意", rewards={"comprehension": 1, "cultivation": 250}, flavor="你参悟了部分剑意，悟性与修为皆有进境。悟性 +1，修为 +250"),
                _c("先以神识稳固识海", condition=_cond("soul", 8), rewards={"soul": 2, "cultivation": 350, "lifespan": 40}, flavor="你以神识化解剑意冲击，神识大涨，修为与寿元皆进。神识 +2，修为 +350，寿元 +40"),
                _c("先以神识稳固识海", rewards={"soul": 1, "cultivation": 200}, flavor="你勉强稳住识海，神识与修为有所提升。神识 +1，修为 +200"),
            ]
        }),
        _c("婉拒，只求指点一二", condition=_cond("fortune", 7), rewards={"fortune": 2, "cultivation": 200, "reputation": 30}, flavor="剑仙欣赏你的谦逊，传你一式剑诀并赠你机缘。机缘 +2，修为 +200，声望 +30"),
        _c("婉拒，只求指点一二", rewards={"cultivation": 100}, flavor="剑仙略传皮毛，你有所得。修为 +100"),
        _c("不敢承受，退后离去", rewards={"fortune": 1}, flavor="你恭敬告辞，剑仙虚影叹息一声，送你一缕剑意护身。机缘 +1"),
    ]
))

EVENTS.append(_e(
    "【稀有】九幽裂缝",
    "地动之后，地面裂开一道深不见底的缝隙，阴冷鬼气自其中涌出，但裂缝边缘却凝结着漆黑的「九幽玄晶」，是炼器至宝。",
    [
        _c("冒险靠近裂缝取玄晶", next_event={
            "desc": "鬼气侵体，你需以体魄或神识抵御，方能取到玄晶并全身而退。",
            "choices": [
                _c("以体魄硬抗鬼气", condition=_cond("physique", 8), rewards={"physique": 1, "spirit_stones": 600, "bone": 1, "equipment": {"quality_pool": ["精良", "稀有"], "quality_weights": [65, 35], "chance": 0.2}}, flavor="你强取玄晶，体魄与根骨在鬼气淬炼下有所提升，玄晶售得高价。体魄 +1，灵石 +600，根骨 +1"),
                _c("以体魄硬抗鬼气", rewards={"lifespan": -20, "spirit_stones": 350}, flavor="鬼气伤身，你带伤取到部分玄晶。寿元 -20，灵石 +350"),
                _c("以神识隔绝鬼气再取", condition=_cond("soul", 8), rewards={"soul": 1, "spirit_stones": 550, "cultivation": 200}, flavor="你以神识护体取回玄晶，神识与修为皆有收获。神识 +1，灵石 +550，修为 +200"),
                _c("以神识隔绝鬼气再取", rewards={"spirit_stones": 300, "lifespan": -10}, flavor="你取到少量玄晶，鬼气略伤神魂。灵石 +300，寿元 -10"),
            ]
        }),
        _c("在裂缝边缘打坐，借鬼气炼神", condition=_cond("soul", 7), rewards={"soul": 2, "cultivation": 250}, flavor="你以鬼气磨砺神识，神识大涨，修为亦进。神识 +2，修为 +250"),
        _c("在裂缝边缘打坐，借鬼气炼神", rewards={"soul": 1, "lifespan": -15}, flavor="鬼气反噬，你神识略增但损了寿元。神识 +1，寿元 -15"),
        _c("不敢逗留，速速离开", rewards={}, flavor="你感到凶险，及时退走。"),
    ]
))

EVENTS.append(_e(
    "【稀有】仙丹劫云",
    "远处丹霞冲天，劫云密布，竟有人在荒野中开炉炼仙丹。丹成之刻，天降丹劫，你若靠近可借丹气与劫雷余韵淬体悟道。",
    [
        _c("靠近丹劫边缘感悟", next_event={
            "desc": "丹劫余波阵阵，丹香与雷意交织，你需在合适时机吸纳丹气，并以悟性化解雷意。",
            "choices": [
                _c("先感应丹气再引雷淬体", condition=_cond("comprehension", 8), rewards={"comprehension": 1, "physique": 1, "cultivation": 400, "lifespan": 50}, flavor="你借丹气与雷意淬体悟道，悟性、体魄、修为与寿元皆进。悟性 +1，体魄 +1，修为 +400，寿元 +50"),
                _c("先感应丹气再引雷淬体", rewards={"cultivation": 250, "lifespan": 25}, flavor="你吸纳部分丹气，修为与寿元皆有提升。修为 +250，寿元 +25"),
                _c("只吸纳丹香，不触雷劫", condition=_cond("fortune", 7), rewards={"fortune": 2, "lifespan": 60, "cultivation": 200}, flavor="你谨慎只吸丹香，机缘与寿元大涨，修为亦进。机缘 +2，寿元 +60，修为 +200"),
                _c("只吸纳丹香，不触雷劫", rewards={"lifespan": 35, "cultivation": 150}, flavor="丹香滋养，寿元与修为皆有进境。寿元 +35，修为 +150"),
            ]
        }),
        _c("等丹劫散后向丹师求丹", condition=_cond("reputation", 20), rewards={"lifespan": 80, "spirit_stones": 200}, flavor="丹师感你护法之诚，赠你一颗成丹。寿元 +80，灵石 +200"),
        _c("等丹劫散后向丹师求丹", rewards={"cultivation": 150}, flavor="丹师赠你一些废丹残渣，炼化后修为略增。修为 +150"),
        _c("远远观望，不涉险", rewards={"comprehension": 1}, flavor="你远观丹劫，对天道有一丝感悟。悟性 +1"),
    ]
))

EVENTS.append(_e(
    "【稀有】天书残页",
    "古洞深处，石台上漂浮着三页金灿灿的残纸，纸上符文自行流转，竟是传说中记载天道至理的天书残页。",
    [
        _c("尝试炼化一页天书", next_event={
            "desc": "天书残页择主而附，需以悟性与神识同时达到一定境界，方能承载其重。",
            "choices": [
                _c("以悟性参悟再炼化", condition=_cond("comprehension", 8), rewards={"comprehension": 2, "cultivation": 450, "lifespan": 40}, flavor="你参透残页奥义后炼化，悟性大涨，修为暴涨，寿元亦增。悟性 +2，修为 +450，寿元 +40"),
                _c("以悟性参悟再炼化", rewards={"comprehension": 1, "cultivation": 280}, flavor="你炼化一页，悟性与修为皆有大幅提升。悟性 +1，修为 +280"),
                _c("以神识承载再炼化", condition=_cond("soul", 8), rewards={"soul": 2, "comprehension": 1, "cultivation": 350}, flavor="你以神识承载残页，神识与悟性皆进，修为大进。神识 +2，悟性 +1，修为 +350"),
                _c("以神识承载再炼化", rewards={"soul": 1, "cultivation": 220}, flavor="你勉强炼化，神识与修为皆有提升。神识 +1，修为 +220"),
            ]
        }),
        _c("只观摩不炼化，强记符文", condition=_cond("soul", 7), rewards={"soul": 1, "cultivation": 200, "fortune": 1}, flavor="你强记符文奥义，神识与修为皆进，机缘略增。神识 +1，修为 +200，机缘 +1"),
        _c("只观摩不炼化，强记符文", rewards={"cultivation": 120}, flavor="你记下部分符文，修为略增。修为 +120"),
        _c("不敢妄动，恭敬退出", rewards={"fortune": 2}, flavor="你恐亵渎天书，恭敬退出，冥冥中得福缘。机缘 +2"),
    ]
))

EVENTS.append(_e(
    "【稀有】太虚秘境",
    "虚空忽然荡开涟漪，一道裂缝出现在你面前，裂缝彼端灵气浓郁如液，显然是某处太虚秘境偶然与现世相接。",
    [
        _c("踏入裂缝进入秘境", next_event={
            "desc": "秘境中灵泉、灵药、古修遗物散落各处，但空间不稳，随时可能闭合，你需尽快抉择。",
            "choices": [
                _c("直奔灵气最浓处", condition=_cond("fortune", 8), rewards={"fortune": 2, "cultivation": 500, "lifespan": 60}, flavor="你找到秘境灵眼，吸纳灵液，机缘、修为与寿元皆大涨。机缘 +2，修为 +500，寿元 +60"),
                _c("直奔灵气最浓处", rewards={"cultivation": 320, "lifespan": 35}, flavor="你吸纳了大量灵气，修为与寿元皆有大幅提升。修为 +320，寿元 +35"),
                _c("先搜刮灵药与遗物", condition=_cond("physique", 7), rewards={"spirit_stones": 650, "physique": 1}, flavor="你抢在空间闭合前搜到大量灵药与遗物，体魄在奔波中亦有锻炼。灵石 +650，体魄 +1"),
                _c("先搜刮灵药与遗物", rewards={"spirit_stones": 380, "lifespan": -10}, flavor="你搜到部分宝物，但闭合时被空间之力擦伤。灵石 +380，寿元 -10"),
            ]
        }),
        _c("只在裂缝口吸纳外泄灵气", condition=_cond("soul", 7), rewards={"soul": 1, "cultivation": 280}, flavor="你稳守裂缝口吸纳灵气，神识与修为皆进。神识 +1，修为 +280"),
        _c("只在裂缝口吸纳外泄灵气", rewards={"cultivation": 180}, flavor="你吸纳了部分外泄灵气，修为有所提升。修为 +180"),
        _c("不敢入内，记下位置离开", rewards={"fortune": 1}, flavor="你恐有诈，记下位置后离开。机缘 +1"),
    ]
))

EVENTS.append(_e(
    "【稀有】轮回井",
    "荒废古庙中有一口枯井，井底传来幽幽回响。有传说称此为轮回井，投下灵石或寿元可窥见前世今生，甚至换取一线机缘。",
    [
        _c("投下灵石试探", next_event={
            "desc": "井中泛起涟漪，一股玄奥之力将你神识牵引向下，你仿佛看到无数画面在眼前闪过。",
            "choices": [
                _c("顺应牵引，感悟轮回之意", condition=_cond("soul", 8), rewards={"soul": 2, "comprehension": 1, "lifespan": 70, "cultivation": 250}, flavor="你从轮回幻象中悟出一丝生死之道，神识与悟性大涨，寿元与修为皆进。神识 +2，悟性 +1，寿元 +70，修为 +250"),
                _c("顺应牵引，感悟轮回之意", rewards={"soul": 1, "lifespan": 40, "cultivation": 150}, flavor="你感悟有限，神识与寿元、修为皆有提升。神识 +1，寿元 +40，修为 +150"),
                _c("抵抗牵引，只取井中反馈灵气", condition=_cond("fortune", 7), rewards={"fortune": 2, "spirit_stones": 400}, flavor="你抵抗幻象，井中反哺大量灵气凝成的灵石。机缘 +2，灵石 +400"),
                _c("抵抗牵引，只取井中反馈灵气", rewards={"spirit_stones": 220}, flavor="你取到部分反馈，换得不少灵石。灵石 +220"),
            ]
        }),
        _c("不投灵石，只观井口", rewards={"comprehension": 1}, flavor="你静观轮回井，心有所悟。悟性 +1"),
        _c("敬而远之，离开古庙", rewards={}, flavor="你不敢招惹轮回因果，转身离开。"),
    ]
))

EVENTS.append(_e(
    "【稀有】仙府遗迹",
    "云雾散开，山腰显露出一角坍塌的殿宇，匾额上「碧落仙府」四字依稀可辨。府内禁制残存，但亦有灵光闪烁，显然还有遗宝。",
    [
        _c("破禁入府探索", next_event={
            "desc": "你破开残破禁制进入殿中，正殿有丹炉、经架、灵池，偏殿传来隐约剑鸣。",
            "choices": [
                _c("先取经架玉简", condition=_cond("comprehension", 8), rewards={"comprehension": 2, "cultivation": 400, "soul": 1}, flavor="玉简中乃仙府主人修炼心得，你悟性大涨，修为暴涨，神识亦进。悟性 +2，修为 +400，神识 +1"),
                _c("先取经架玉简", rewards={"comprehension": 1, "cultivation": 260}, flavor="你获得部分心得，悟性与修为皆有大幅提升。悟性 +1，修为 +260"),
                _c("先探灵池", condition=_cond("physique", 7), rewards={"lifespan": 90, "bone": 1, "cultivation": 200}, flavor="灵池中灵液尚存，你浸泡炼化，寿元大涨，根骨与修为皆进。寿元 +90，根骨 +1，修为 +200"),
                _c("先探灵池", rewards={"lifespan": 50, "cultivation": 120}, flavor="灵液稀薄，你仍得不少好处。寿元 +50，修为 +120"),
                _c("循剑鸣入偏殿", condition=_cond("fortune", 7), rewards={"fortune": 2, "spirit_stones": 550, "equipment": {"quality_pool": ["精良", "稀有"], "quality_weights": [60, 40], "chance": 0.25}}, flavor="偏殿有一柄无主飞剑与储物袋，你收获颇丰。机缘 +2，灵石 +550"),
                _c("循剑鸣入偏殿", rewards={"lifespan": -15, "spirit_stones": 280}, flavor="偏殿有剑灵残念，你受伤后取走部分遗物。寿元 -15，灵石 +280"),
            ]
        }),
        _c("只在府外吸纳外泄灵气", rewards={"cultivation": 180, "fortune": 1}, flavor="你未入府，在外炼化外泄灵气，修为与机缘略增。修为 +180，机缘 +1"),
        _c("不敢擅入，离去", rewards={}, flavor="你恐触禁制，恭敬离开。"),
    ]
))

EVENTS.append(_e(
    "【稀有】雷池淬体",
    "山谷深处有一方雷池，池中雷弧跳跃，是上古大能留下的淬体之地。若能承受雷劫洗练，体魄与根骨将脱胎换骨。",
    [
        _c("步入雷池淬体", next_event={
            "desc": "雷弧加身，你浑身剧痛，需以体魄与意志硬抗，撑得越久收获越大。",
            "choices": [
                _c("咬牙坚持到极限", condition=_cond("physique", 8), rewards={"physique": 2, "bone": 2, "cultivation": 350}, flavor="你撑过雷池淬体，体魄与根骨皆得蜕变，修为猛进。体魄 +2，根骨 +2，修为 +350"),
                _c("咬牙坚持到极限", rewards={"physique": 1, "bone": 1, "lifespan": -20}, flavor="你勉强撑过，体魄根骨皆进，但元气大伤。体魄 +1，根骨 +1，寿元 -20"),
                _c("适可而止，浅尝辄止", condition=_cond("soul", 7), rewards={"soul": 1, "physique": 1, "cultivation": 250}, flavor="你以神识引导雷力，体魄与神识皆进，修为大进。神识 +1，体魄 +1，修为 +250"),
                _c("适可而止，浅尝辄止", rewards={"cultivation": 150}, flavor="你吸纳部分雷力，修为有所提升。修为 +150"),
            ]
        }),
        _c("在雷池边借雷意悟道", condition=_cond("comprehension", 7), rewards={"comprehension": 1, "cultivation": 200}, flavor="你从雷意中悟出一丝刚猛之道，悟性与修为皆进。悟性 +1，修为 +200"),
        _c("在雷池边借雷意悟道", rewards={"cultivation": 100}, flavor="你略有所得。修为 +100"),
        _c("不敢入池，离开", rewards={}, flavor="你恐承受不住，转身离开。"),
    ]
))

EVENTS.append(_e(
    "【稀有】悟道石",
    "绝顶之上，一块光滑如镜的巨石矗立，石面映出天地万象。据说坐于石上可沟通天地，悟道一日胜过苦修十年。",
    [
        _c("坐上悟道石感悟", next_event={
            "desc": "石面中景象变幻，时而山河，时而星海，你需以悟性与神识捕捉其中道韵。",
            "choices": [
                _c("专注感悟天地万象", condition=_cond("comprehension", 8), rewards={"comprehension": 2, "soul": 1, "cultivation": 450, "lifespan": 40}, flavor="你悟得一丝天地至理，悟性与神识大涨，修为与寿元皆进。悟性 +2，神识 +1，修为 +450，寿元 +40"),
                _c("专注感悟天地万象", rewards={"comprehension": 1, "cultivation": 280, "lifespan": 20}, flavor="你有所悟，悟性、修为与寿元皆有提升。悟性 +1，修为 +280，寿元 +20"),
                _c("以神识探入石中", condition=_cond("soul", 8), rewards={"soul": 2, "comprehension": 1, "cultivation": 380}, flavor="你神识与石中道韵共鸣，神识大涨，悟性与修为皆进。神识 +2，悟性 +1，修为 +380"),
                _c("以神识探入石中", rewards={"soul": 1, "cultivation": 220}, flavor="你神识有所进境，修为亦增。神识 +1，修为 +220"),
            ]
        }),
        _c("只抚摩石面，不坐上去", rewards={"fortune": 2, "cultivation": 100}, flavor="你与悟道石有一丝感应，机缘与修为略增。机缘 +2，修为 +100"),
        _c("不敢亵渎，行礼后离开", rewards={"fortune": 1}, flavor="你恭敬离去，心有所感。机缘 +1"),
    ]
))

EVENTS.append(_e(
    "【稀有】仙灵赐福",
    "一道七彩光柱自天而降，将你笼罩其中。光柱中传来缥缈仙音：「有缘人，可受吾一缕赐福。」",
    [
        _c("静心接受赐福", condition=_cond("fortune", 8), rewards={"fortune": 3, "lifespan": 80, "cultivation": 350, "bone": 1}, flavor="仙灵赐福入体，机缘暴涨，寿元大涨，修为猛进，根骨亦得蜕变。机缘 +3，寿元 +80，修为 +350，根骨 +1"),
        _c("静心接受赐福", condition=_cond("fortune", 6), rewards={"fortune": 2, "lifespan": 50, "cultivation": 250}, flavor="你承受赐福，机缘、寿元与修为皆有大进。机缘 +2，寿元 +50，修为 +250"),
        _c("静心接受赐福", rewards={"lifespan": 30, "cultivation": 150}, flavor="赐福之力你只承受部分，寿元与修为皆有提升。寿元 +30，修为 +150"),
        _c("请教仙灵修行之道", condition=_cond("comprehension", 8), rewards={"comprehension": 2, "soul": 1, "cultivation": 300}, flavor="仙灵传你几句真言，悟性与神识大涨，修为猛进。悟性 +2，神识 +1，修为 +300"),
        _c("请教仙灵修行之道", rewards={"comprehension": 1, "cultivation": 200}, flavor="仙灵略加点拨，你悟性与修为皆进。悟性 +1，修为 +200"),
        _c("婉拒赐福，只求指点", rewards={"fortune": 2, "reputation": 40}, flavor="仙灵欣赏你的谦逊，赠你机缘与福缘。机缘 +2，声望 +40"),
    ]
))

EVENTS.append(_e(
    "【稀有】上古凶兽遗骸",
    "密林深处，一具巨大的凶兽遗骸横陈于地，骨骼如玉，威压犹存。遗骸心口处有一颗尚未散尽的「兽元晶」。",
    [
        _c("取兽元晶炼化", next_event={
            "desc": "兽元晶中凶煞之气与灵气并存，炼化时需以体魄或神识压制煞气。",
            "choices": [
                _c("以体魄压制煞气炼化", condition=_cond("physique", 8), rewards={"physique": 2, "bone": 1, "cultivation": 400, "equipment": {"quality_pool": ["精良", "稀有"], "quality_weights": [55, 45], "chance": 0.25}}, flavor="你以体魄镇压煞气，炼化兽元晶，体魄与根骨皆得淬炼，修为暴涨。体魄 +2，根骨 +1，修为 +400"),
                _c("以体魄压制煞气炼化", rewards={"physique": 1, "cultivation": 250, "lifespan": -15}, flavor="煞气反噬，你体魄与修为皆进但损了寿元。体魄 +1，修为 +250，寿元 -15"),
                _c("以神识净化煞气再炼化", condition=_cond("soul", 8), rewards={"soul": 2, "cultivation": 350, "lifespan": 30}, flavor="你以神识净化煞气后炼化，神识大涨，修为与寿元皆进。神识 +2，修为 +350，寿元 +30"),
                _c("以神识净化煞气再炼化", rewards={"soul": 1, "cultivation": 220}, flavor="你勉强炼化，神识与修为皆有提升。神识 +1，修为 +220"),
            ]
        }),
        _c("不取兽元晶，只取几根遗骨", condition=_cond("fortune", 7), rewards={"spirit_stones": 520, "fortune": 1}, flavor="上古凶兽遗骨是炼器至宝，你售得高价。灵石 +520，机缘 +1"),
        _c("不取兽元晶，只取几根遗骨", rewards={"spirit_stones": 300}, flavor="你取走部分遗骨，换得不少灵石。灵石 +300"),
        _c("恭敬行礼后离开", rewards={"fortune": 1}, flavor="你恐惊动遗骸残念，恭敬退走。机缘 +1"),
    ]
))

EVENTS.append(_e(
    "【稀有】灵根蜕变",
    "你打坐时忽然感到体内灵根剧烈颤动，天地灵气自主涌入，竟是百年难遇的「灵根蜕变」之机——若把握得当，修炼资质将更上一层。",
    [
        _c("全力引导灵气冲击灵根", next_event={
            "desc": "灵气在灵根中奔涌，你需以悟性把握节奏，以体魄承受冲击，否则可能伤及根基。",
            "choices": [
                _c("以悟性把握蜕变节奏", condition=_cond("comprehension", 8), rewards={"comprehension": 2, "cultivation": 500, "lifespan": 50}, flavor="你把握住蜕变之机，悟性大涨，修为暴涨，寿元亦得滋养。悟性 +2，修为 +500，寿元 +50"),
                _c("以悟性把握蜕变节奏", rewards={"cultivation": 320, "lifespan": 25}, flavor="你引导了部分蜕变，修为与寿元皆有大幅提升。修为 +320，寿元 +25"),
                _c("以体魄硬抗冲击", condition=_cond("physique", 8), rewards={"physique": 1, "bone": 2, "cultivation": 400}, flavor="你以体魄承受灵根蜕变之痛，根骨大涨，体魄与修为皆进。体魄 +1，根骨 +2，修为 +400"),
                _c("以体魄硬抗冲击", rewards={"bone": 1, "cultivation": 250, "lifespan": -20}, flavor="蜕变不完全，根骨与修为皆进但损了寿元。根骨 +1，修为 +250，寿元 -20"),
            ]
        }),
        _c("稳扎稳打，缓慢引导", condition=_cond("soul", 7), rewards={"soul": 1, "cultivation": 300, "lifespan": 40}, flavor="你以神识稳守，蜕变平稳完成，神识、修为与寿元皆进。神识 +1，修为 +300，寿元 +40"),
        _c("稳扎稳打，缓慢引导", rewards={"cultivation": 200, "lifespan": 20}, flavor="你平稳度过蜕变，修为与寿元皆有提升。修为 +200，寿元 +20"),
        _c("不敢冒险，压制蜕变", rewards={"fortune": 1, "cultivation": 80}, flavor="你压制了蜕变，机缘略增，修为小有进境。机缘 +1，修为 +80"),
    ]
))

EVENTS.append(_e(
    "【稀有】仙酿现世",
    "一处荒废酒窖深处，你发现一坛封泥完好的古酒，酒坛上刻「仙酿」二字。据说饮之可洗髓伐毛，延年增寿。",
    [
        _c("启封饮仙酿", next_event={
            "desc": "仙酿入喉，磅礴酒力与灵气在体内炸开，需以体魄与神识共同化解。",
            "choices": [
                _c("运功引导酒力化开", condition=_cond("soul", 7), rewards={"soul": 1, "lifespan": 100, "cultivation": 300, "bone": 1}, flavor="你以神识引导酒力，寿元大涨，修为与根骨皆进，神识亦增。神识 +1，寿元 +100，修为 +300，根骨 +1"),
                _c("运功引导酒力化开", rewards={"lifespan": 60, "cultivation": 200}, flavor="你化解了部分酒力，寿元与修为皆有大幅提升。寿元 +60，修为 +200"),
                _c("以体魄硬抗酒力", condition=_cond("physique", 8), rewards={"physique": 2, "lifespan": 70, "cultivation": 350}, flavor="你以体魄炼化酒力，体魄大涨，寿元与修为皆进。体魄 +2，寿元 +70，修为 +350"),
                _c("以体魄硬抗酒力", rewards={"lifespan": 30, "cultivation": 220}, flavor="酒力过猛，你寿元与修为皆进但略损元气。寿元 +30，修为 +220"),
            ]
        }),
        _c("不饮，将仙酿带走出售", condition=_cond("fortune", 7), rewards={"spirit_stones": 700, "fortune": 1}, flavor="仙酿有价无市，你售得天价。灵石 +700，机缘 +1"),
        _c("不饮，将仙酿带走出售", rewards={"spirit_stones": 450}, flavor="你卖出仙酿，收获颇丰。灵石 +450"),
        _c("只取一小杯尝鲜", rewards={"lifespan": 40, "cultivation": 150}, flavor="你浅尝辄止，寿元与修为皆有提升。寿元 +40，修为 +150"),
    ]
))

EVENTS.append(_e(
    "【稀有】天机碑",
    "荒野中矗立着一面古碑，碑上无字，但若以神识触碰，会浮现与自身相关的只言片语——据说乃天机显化，可窥一线天意。",
    [
        _c("以神识触碰天机碑", next_event={
            "desc": "碑上浮现数行字迹，又迅速模糊，你需在瞬间以悟性与神识记下并参悟。",
            "choices": [
                _c("全力记下并参悟", condition=_cond("comprehension", 8), rewards={"comprehension": 2, "fortune": 2, "cultivation": 350}, flavor="你参透天机碑所示，悟性与机缘皆大涨，修为猛进。悟性 +2，机缘 +2，修为 +350"),
                _c("全力记下并参悟", rewards={"comprehension": 1, "fortune": 1, "cultivation": 220}, flavor="你记下部分天机，悟性、机缘与修为皆有提升。悟性 +1，机缘 +1，修为 +220"),
                _c("只记不悟，留待日后", condition=_cond("soul", 7), rewards={"soul": 1, "lifespan": 50, "fortune": 1}, flavor="你以神识强记天机，神识、寿元与机缘皆进。神识 +1，寿元 +50，机缘 +1"),
                _c("只记不悟，留待日后", rewards={"lifespan": 30, "fortune": 1}, flavor="你记下只言片语，寿元与机缘略增。寿元 +30，机缘 +1"),
            ]
        }),
        _c("只观碑不触", rewards={"fortune": 2}, flavor="你未敢深触天机，但冥冥中得福缘。机缘 +2"),
        _c("敬而远之", rewards={}, flavor="你恐泄露天机遭反噬，转身离开。"),
    ]
))

EVENTS.append(_e(
    "【稀有】仙器残片",
    "古战场废墟中，你发现一块仍散发凛冽剑意的金属残片，显然是某件仙器崩碎后所留，内蕴一丝仙道法则。",
    [
        _c("尝试炼化残片中的仙道法则", next_event={
            "desc": "残片中的剑意与法则极为霸道，需以悟性化解、或以体魄硬抗，方能炼化。",
            "choices": [
                _c("以悟性参悟法则再炼化", condition=_cond("comprehension", 8), rewards={"comprehension": 2, "cultivation": 400, "soul": 1, "equipment": {"quality_pool": ["精良", "稀有"], "quality_weights": [50, 50], "chance": 0.3}}, flavor="你参透残片中的一丝仙道法则，悟性与神识大涨，修为猛进。悟性 +2，修为 +400，神识 +1"),
                _c("以悟性参悟法则再炼化", rewards={"comprehension": 1, "cultivation": 260}, flavor="你炼化部分法则，悟性与修为皆有大幅提升。悟性 +1，修为 +260"),
                _c("以体魄承受剑意淬体", condition=_cond("physique", 8), rewards={"physique": 2, "bone": 1, "cultivation": 350}, flavor="你以体魄承受剑意，体魄与根骨皆得淬炼，修为大涨。体魄 +2，根骨 +1，修为 +350"),
                _c("以体魄承受剑意淬体", rewards={"physique": 1, "cultivation": 200, "lifespan": -15}, flavor="剑意伤身，你体魄与修为皆进但损了寿元。体魄 +1，修为 +200，寿元 -15"),
            ]
        }),
        _c("不炼化，将残片带走出售", condition=_cond("fortune", 7), rewards={"spirit_stones": 600, "fortune": 1}, flavor="仙器残片价值连城，你售得高价。灵石 +600，机缘 +1"),
        _c("不炼化，将残片带走出售", rewards={"spirit_stones": 380}, flavor="你卖出残片，收获不菲。灵石 +380"),
        _c("不敢妄动，离开", rewards={"fortune": 1}, flavor="你恐剑意反噬，收手离开。机缘 +1"),
    ]
))

EVENTS.append(_e(
    "【稀有】道种萌芽",
    "你打坐时忽然感到丹田中有一粒「道种」在微微跳动——据说是前世或机缘所留，今日得灵气滋养，有萌芽之兆。",
    [
        _c("以全部心神催发道种", next_event={
            "desc": "道种萌芽需海量灵气与一丝顿悟，成则修为与根基皆脱胎换骨，败则反伤丹田。",
            "choices": [
                _c("先悟后发，以悟性引导", condition=_cond("comprehension", 8), rewards={"comprehension": 2, "cultivation": 500, "lifespan": 60}, flavor="你悟得契机后催发道种，悟性大涨，修为暴涨，寿元亦增。悟性 +2，修为 +500，寿元 +60"),
                _c("先悟后发，以悟性引导", rewards={"comprehension": 1, "cultivation": 320, "lifespan": 30}, flavor="道种半萌，悟性与修为、寿元皆有大幅提升。悟性 +1，修为 +320，寿元 +30"),
                _c("以神识护持丹田再催发", condition=_cond("soul", 8), rewards={"soul": 2, "cultivation": 420, "bone": 1}, flavor="你以神识护持，道种顺利萌芽，神识大涨，修为与根骨皆进。神识 +2，修为 +420，根骨 +1"),
                _c("以神识护持丹田再催发", rewards={"soul": 1, "cultivation": 280}, flavor="道种萌芽不稳，神识与修为皆有提升。神识 +1，修为 +280"),
            ]
        }),
        _c("不急于催发，只以灵气滋养", condition=_cond("fortune", 7), rewards={"fortune": 2, "lifespan": 50, "cultivation": 200}, flavor="你稳扎稳打滋养道种，机缘、寿元与修为皆进。机缘 +2，寿元 +50，修为 +200"),
        _c("不急于催发，只以灵气滋养", rewards={"lifespan": 30, "cultivation": 150}, flavor="道种略有成长，寿元与修为皆有提升。寿元 +30，修为 +150"),
        _c("不敢妄动，维持现状", rewards={"fortune": 1}, flavor="你恐出差错，只维持现状。机缘 +1"),
    ]
))

EVENTS.append(_e(
    "【稀有】飞升台遗迹",
    "绝巅之上，残破的飞升台半掩于云雾中。台上雷劫痕迹犹在，据说在此感悟可触类旁通，对日后破境大有裨益。",
    [
        _c("登上飞升台感悟", next_event={
            "desc": "台上残留着飞升者与天劫对抗的意境，你需以悟性与神识与之共鸣。",
            "choices": [
                _c("静心感悟飞升意境", condition=_cond("comprehension", 8), rewards={"comprehension": 2, "cultivation": 450, "lifespan": 50}, flavor="你悟得一丝飞升意境，悟性大涨，修为暴涨，寿元亦增。悟性 +2，修为 +450，寿元 +50"),
                _c("静心感悟飞升意境", rewards={"comprehension": 1, "cultivation": 280, "lifespan": 25}, flavor="你有所悟，悟性、修为与寿元皆有提升。悟性 +1，修为 +280，寿元 +25"),
                _c("以神识感应雷劫余韵", condition=_cond("soul", 8), rewards={"soul": 2, "physique": 1, "cultivation": 350}, flavor="你从雷劫余韵中淬炼神识与体魄，神识大涨，体魄与修为皆进。神识 +2，体魄 +1，修为 +350"),
                _c("以神识感应雷劫余韵", rewards={"soul": 1, "cultivation": 220}, flavor="你感应到部分余韵，神识与修为皆有提升。神识 +1，修为 +220"),
            ]
        }),
        _c("只在台下远观", condition=_cond("fortune", 7), rewards={"fortune": 2, "cultivation": 180}, flavor="你远观飞升台，机缘与修为略增。机缘 +2，修为 +180"),
        _c("不敢登台，离去", rewards={}, flavor="你恐触犯飞升者遗意，恭敬离开。"),
    ]
))

EVENTS.append(_e(
    "【稀有】古佛舍利",
    "破败佛寺中，一座石塔塔顶放光。你登塔一看，竟是一枚舍利子，佛光温和，可净心魔、增寿元、助悟道。",
    [
        _c("在舍利旁打坐炼化佛光", next_event={
            "desc": "佛光笼罩周身，你需心无杂念，以神识接纳佛光，否则易生心魔。",
            "choices": [
                _c("心无杂念，接纳佛光", condition=_cond("soul", 8), rewards={"soul": 2, "lifespan": 90, "cultivation": 300}, flavor="佛光净体，神识大涨，寿元大增，修为亦进。神识 +2，寿元 +90，修为 +300"),
                _c("心无杂念，接纳佛光", rewards={"soul": 1, "lifespan": 55, "cultivation": 200}, flavor="你承受部分佛光，神识、寿元与修为皆有提升。神识 +1，寿元 +55，修为 +200"),
                _c("只借佛光悟道，不吸纳", condition=_cond("comprehension", 7), rewards={"comprehension": 2, "lifespan": 40}, flavor="你借佛光悟出一丝禅意，悟性大涨，寿元亦增。悟性 +2，寿元 +40"),
                _c("只借佛光悟道，不吸纳", rewards={"comprehension": 1, "lifespan": 25}, flavor="你略有所悟，悟性与寿元皆有提升。悟性 +1，寿元 +25"),
            ]
        }),
        _c("不取舍利，只行礼瞻仰", rewards={"fortune": 2, "reputation": 25}, flavor="你恭敬瞻仰舍利，未起贪念，冥冥中得福缘与名声。机缘 +2，声望 +25"),
        _c("取走舍利（不炼化）带出", condition=_cond("fortune", 7), rewards={"spirit_stones": 580, "fortune": 1}, flavor="舍利价值连城，你售与佛门，得大量灵石。灵石 +580，机缘 +1"),
        _c("取走舍利（不炼化）带出", rewards={"spirit_stones": 350}, flavor="你卖出舍利，收获颇丰。灵石 +350"),
    ]
))

EVENTS.append(_e(
    "【稀有】时空裂隙",
    "空中忽然撕开一道狭长裂缝，裂缝彼端景象光怪陆离，时间流速似乎与现世不同。有人曾在其中修炼一日，抵外界十日。",
    [
        _c("踏入裂隙修炼", next_event={
            "desc": "裂隙内灵气浓郁且时间流速异常，你需在裂隙闭合前尽可能吸纳灵气并感悟。",
            "choices": [
                _c("全力吸纳灵气修炼", condition=_cond("comprehension", 7), rewards={"cultivation": 550, "comprehension": 1, "lifespan": 30}, flavor="你在裂隙中修炼，修为暴涨，悟性与寿元皆进。修为 +550，悟性 +1，寿元 +30"),
                _c("全力吸纳灵气修炼", rewards={"cultivation": 350, "lifespan": 15}, flavor="你修炼有成，修为与寿元皆有大幅提升。修为 +350，寿元 +15"),
                _c("以神识感悟时空异象", condition=_cond("soul", 8), rewards={"soul": 2, "cultivation": 400, "fortune": 1}, flavor="你从时空异象中悟得一丝法则，神识大涨，修为与机缘皆进。神识 +2，修为 +400，机缘 +1"),
                _c("以神识感悟时空异象", rewards={"soul": 1, "cultivation": 250}, flavor="你感悟有限，神识与修为皆有提升。神识 +1，修为 +250"),
            ]
        }),
        _c("只在裂隙口吸纳外泄灵气", rewards={"cultivation": 220, "fortune": 1}, flavor="你未入内，只在口子处修炼，修为与机缘略增。修为 +220，机缘 +1"),
        _c("不敢入内，记下位置离开", rewards={"fortune": 1}, flavor="你恐裂隙不稳，记下位置后离开。机缘 +1"),
    ]
))

EVENTS.append(_e(
    "【稀有】灵泉之眼",
    "地脉交汇处，一眼灵泉喷涌而出，泉水呈乳白色，灵气浓郁到化液。据说这是灵脉之眼，在此修炼一日抵外界一月。",
    [
        _c("入灵泉中修炼", next_event={
            "desc": "灵液浸体，你需引导灵气归元，否则易被磅礴灵气撑伤经脉。",
            "choices": [
                _c("以神识引导灵气归元", condition=_cond("soul", 8), rewards={"soul": 1, "cultivation": 500, "lifespan": 60}, flavor="你稳稳炼化灵液，神识、修为与寿元皆大涨。神识 +1，修为 +500，寿元 +60"),
                _c("以神识引导灵气归元", rewards={"cultivation": 320, "lifespan": 35}, flavor="你炼化部分灵液，修为与寿元皆有大幅提升。修为 +320，寿元 +35"),
                _c("以体魄承受灵压淬体", condition=_cond("physique", 8), rewards={"physique": 2, "bone": 1, "cultivation": 400}, flavor="你以体魄承受灵压，体魄与根骨皆进，修为猛进。体魄 +2，根骨 +1，修为 +400"),
                _c("以体魄承受灵压淬体", rewards={"physique": 1, "cultivation": 260, "lifespan": -10}, flavor="灵压过猛，你体魄与修为皆进但略损元气。体魄 +1，修为 +260，寿元 -10"),
            ]
        }),
        _c("只取泉水带走", condition=_cond("fortune", 7), rewards={"spirit_stones": 480, "lifespan": 40}, flavor="你装走一批灵泉，售出与自用兼得。灵石 +480，寿元 +40"),
        _c("只取泉水带走", rewards={"spirit_stones": 280, "lifespan": 20}, flavor="你取走部分灵泉，换得灵石并略增寿元。灵石 +280，寿元 +20"),
        _c("不取泉水，只在泉边打坐", rewards={"cultivation": 200}, flavor="你在泉边修炼片刻，修为有所提升。修为 +200"),
    ]
))

EVENTS.append(_e(
    "【稀有】仙缘洞",
    "山洞洞口刻「仙缘」二字，据说入洞者会经历幻境考验，通过者可获洞中前辈所留机缘。",
    [
        _c("入洞接受考验", next_event={
            "desc": "洞中幻境迭生，有时是心魔，有时是抉择，你需以悟性与神识破妄。",
            "choices": [
                _c("以悟性破妄，直指本心", condition=_cond("comprehension", 8), rewards={"comprehension": 2, "soul": 1, "cultivation": 400, "lifespan": 50}, flavor="你破开幻境，悟性与神识大涨，修为与寿元皆进。悟性 +2，神识 +1，修为 +400，寿元 +50"),
                _c("以悟性破妄，直指本心", rewards={"comprehension": 1, "cultivation": 260, "lifespan": 25}, flavor="你通过考验，悟性、修为与寿元皆有提升。悟性 +1，修为 +260，寿元 +25"),
                _c("以神识固守本心，步步为营", condition=_cond("soul", 8), rewards={"soul": 2, "fortune": 1, "cultivation": 350}, flavor="你以神识稳守通过幻境，神识大涨，机缘与修为皆进。神识 +2，机缘 +1，修为 +350"),
                _c("以神识固守本心，步步为营", rewards={"soul": 1, "cultivation": 220}, flavor="你勉强通过，神识与修为皆有提升。神识 +1，修为 +220"),
            ]
        }),
        _c("在洞口观望不入", rewards={"fortune": 1, "cultivation": 80}, flavor="你未入洞，但在洞口感应到一丝机缘与灵气。机缘 +1，修为 +80"),
        _c("不敢入洞，离开", rewards={}, flavor="你恐幻境伤神，转身离开。"),
    ]
))

EVENTS.append(_e(
    "【稀有】混沌初开",
    "某处秘境深处，你目睹了一小片空间从混沌中初开的异象——清浊分离，灵气初生。若能感悟此景，对修行有莫大好处。",
    [
        _c("静心感悟混沌初开之象", next_event={
            "desc": "异象中蕴含一丝开天之意，你需以悟性捕捉那转瞬即逝的道韵。",
            "choices": [
                _c("全力捕捉开天之意", condition=_cond("comprehension", 9), rewards={"comprehension": 3, "cultivation": 500, "lifespan": 60}, flavor="你悟得一丝开天之意，悟性大涨，修为暴涨，寿元亦增。悟性 +3，修为 +500，寿元 +60"),
                _c("全力捕捉开天之意", condition=_cond("comprehension", 7), rewards={"comprehension": 2, "cultivation": 350, "lifespan": 35}, flavor="你有所悟，悟性、修为与寿元皆有大进。悟性 +2，修为 +350，寿元 +35"),
                _c("以神识感应清浊分离", condition=_cond("soul", 8), rewards={"soul": 2, "comprehension": 1, "cultivation": 400}, flavor="你从清浊分离中悟得法则，神识与悟性皆进，修为猛进。神识 +2，悟性 +1，修为 +400"),
                _c("以神识感应清浊分离", rewards={"soul": 1, "cultivation": 250}, flavor="你感悟有限，神识与修为皆有提升。神识 +1，修为 +250"),
            ]
        }),
        _c("只远观不深悟", rewards={"fortune": 2, "cultivation": 150}, flavor="你远观异象，机缘与修为略增。机缘 +2，修为 +150"),
        _c("不敢久视，闭目离开", rewards={"fortune": 1}, flavor="你恐道韵过重伤神，闭目退走。机缘 +1"),
    ]
))

EVENTS.append(_e(
    "【稀有】星辰淬炼",
    "夜空忽然有流星雨倾泻而下，落点就在不远处。星陨之地会形成「星淬灵池」，在其中淬体可脱胎换骨。",
    [
        _c("进入星淬灵池淬体", next_event={
            "desc": "池中星力与灵气交织，淬体时痛楚与收获并存，需以体魄与意志坚持。",
            "choices": [
                _c("咬牙坚持到极限", condition=_cond("physique", 8), rewards={"physique": 2, "bone": 2, "cultivation": 400}, flavor="你撑过星淬，体魄与根骨皆得蜕变，修为猛进。体魄 +2，根骨 +2，修为 +400"),
                _c("咬牙坚持到极限", rewards={"physique": 1, "bone": 1, "lifespan": -20}, flavor="你勉强撑过，体魄根骨皆进但元气大伤。体魄 +1，根骨 +1，寿元 -20"),
                _c("以神识引导星力，循序渐进", condition=_cond("soul", 7), rewards={"soul": 1, "physique": 1, "cultivation": 320, "lifespan": 30}, flavor="你以神识引导星力淬体，神识体魄皆进，修为与寿元亦增。神识 +1，体魄 +1，修为 +320，寿元 +30"),
                _c("以神识引导星力，循序渐进", rewards={"cultivation": 200, "lifespan": 15}, flavor="你稳扎稳打，修为与寿元皆有提升。修为 +200，寿元 +15"),
            ]
        }),
        _c("在池边收集星陨碎片", condition=_cond("fortune", 7), rewards={"spirit_stones": 550, "fortune": 1}, flavor="星陨碎片是炼器至宝，你售得高价。灵石 +550，机缘 +1"),
        _c("在池边收集星陨碎片", rewards={"spirit_stones": 320}, flavor="你捡到部分碎片，换得不少灵石。灵石 +320"),
        _c("不敢入池，离开", rewards={}, flavor="你恐星力过猛，转身离开。"),
    ]
))

EVENTS.append(_e(
    "【稀有】魔渊入口",
    "地裂深处，一道魔气森森的裂缝若隐若现。魔渊中偶有「魔灵晶」被喷出，炼化后可大幅提升战力，但煞气易侵心。",
    [
        _c("在裂缝口守候魔灵晶", next_event={
            "desc": "魔灵晶喷出时煞气逼人，你需以神识或体魄抵御煞气，再决定炼化还是出售。",
            "choices": [
                _c("以神识净化煞气后炼化", condition=_cond("soul", 8), rewards={"soul": 1, "cultivation": 420, "physique": 1}, flavor="你净化煞气后炼化魔灵晶，神识、修为与体魄皆进。神识 +1，修为 +420，体魄 +1"),
                _c("以神识净化煞气后炼化", rewards={"cultivation": 260, "lifespan": -15}, flavor="煞气未净，你修为大进但损了寿元。修为 +260，寿元 -15"),
                _c("不炼化，带出出售", condition=_cond("fortune", 7), rewards={"spirit_stones": 600, "fortune": 1}, flavor="魔灵晶有价无市，你售得高价。灵石 +600，机缘 +1"),
                _c("不炼化，带出出售", rewards={"spirit_stones": 360}, flavor="你卖出魔灵晶，收获不菲。灵石 +360"),
            ]
        }),
        _c("只在远处观望，不靠近", rewards={"comprehension": 1}, flavor="你远观魔渊，对正邪之道有一丝感悟。悟性 +1"),
        _c("速速离开", rewards={}, flavor="你恐魔气侵体，转身离开。"),
    ]
))

EVENTS.append(_e(
    "【稀有】古妖传承",
    "荒山妖洞中，一具大妖遗骸前漂浮着一枚妖丹与一枚玉简。玉简中记载，此妖愿将毕生传承赠予有缘人，不拘人妖。",
    [
        _c("接受古妖传承", next_event={
            "desc": "传承包含妖丹之力与功法感悟，人族炼化需以体魄承受妖力、以悟性化解妖性。",
            "choices": [
                _c("先炼化妖丹再悟功法", condition=_cond("physique", 8), rewards={"physique": 2, "bone": 1, "cultivation": 400, "lifespan": 40}, flavor="你以体魄炼化妖丹，体魄与根骨皆进，修为与寿元亦增。体魄 +2，根骨 +1，修为 +400，寿元 +40"),
                _c("先炼化妖丹再悟功法", rewards={"physique": 1, "cultivation": 260, "lifespan": -10}, flavor="妖力反噬，你体魄与修为皆进但略损寿元。体魄 +1，修为 +260，寿元 -10"),
                _c("只悟功法不炼妖丹", condition=_cond("comprehension", 8), rewards={"comprehension": 2, "cultivation": 350}, flavor="你从玉简中悟得妖族炼体之法，化为己用，悟性大涨，修为猛进。悟性 +2，修为 +350"),
                _c("只悟功法不炼妖丹", rewards={"comprehension": 1, "cultivation": 220}, flavor="你悟得部分功法，悟性与修为皆有提升。悟性 +1，修为 +220"),
            ]
        }),
        _c("只取玉简，不动妖丹", condition=_cond("fortune", 7), rewards={"fortune": 2, "spirit_stones": 400}, flavor="你取走玉简售出，妖丹留与有缘，冥冥中得机缘与灵石。机缘 +2，灵石 +400"),
        _c("只取玉简，不动妖丹", rewards={"spirit_stones": 250}, flavor="你售出玉简，收获颇丰。灵石 +250"),
        _c("恭敬行礼后离开", rewards={"fortune": 1}, flavor="你不愿承妖道，恭敬退走。机缘 +1"),
    ]
))

EVENTS.append(_e(
    "【稀有】天劫余韵",
    "某处曾有修士在此渡劫失败，雷劫散去后留下一片「劫雷余韵」之地。在此感悟可体悟天劫之意，对日后破境极有帮助。",
    [
        _c("进入余韵之地感悟", next_event={
            "desc": "劫雷余韵中既有毁灭之意也有一线生机，你需以悟性与神识从中提炼感悟。",
            "choices": [
                _c("专注感悟毁灭与生机", condition=_cond("comprehension", 8), rewards={"comprehension": 2, "cultivation": 420, "lifespan": 40}, flavor="你悟得劫雷中的生死之意，悟性大涨，修为与寿元皆进。悟性 +2，修为 +420，寿元 +40"),
                _c("专注感悟毁灭与生机", rewards={"comprehension": 1, "cultivation": 270, "lifespan": 20}, flavor="你有所悟，悟性、修为与寿元皆有提升。悟性 +1，修为 +270，寿元 +20"),
                _c("以体魄承受余韵淬体", condition=_cond("physique", 8), rewards={"physique": 2, "bone": 1, "cultivation": 350}, flavor="你以体魄承受余韵淬体，体魄与根骨皆进，修为猛进。体魄 +2，根骨 +1，修为 +350"),
                _c("以体魄承受余韵淬体", rewards={"physique": 1, "cultivation": 220, "lifespan": -15}, flavor="余韵伤身，你体魄与修为皆进但损了寿元。体魄 +1，修为 +220，寿元 -15"),
            ]
        }),
        _c("只在边缘吸纳散逸雷灵", rewards={"cultivation": 200, "fortune": 1}, flavor="你在边缘修炼，修为与机缘略增。修为 +200，机缘 +1"),
        _c("不敢入内，离开", rewards={}, flavor="你恐余韵伤身，转身离开。"),
    ]
))

EVENTS.append(_e(
    "【稀有】仙缘桥",
    "云海之上，一座由灵气凝成的长桥若隐若现，桥那头传来阵阵仙乐。据说走过仙缘桥者，可得天道一丝眷顾。",
    [
        _c("踏上仙缘桥前行", next_event={
            "desc": "桥上幻象丛生，有时是机缘，有时是心魔，你需步步为营，以悟性与神识辨明真假。",
            "choices": [
                _c("以悟性辨明幻象，稳步前行", condition=_cond("comprehension", 8), rewards={"comprehension": 2, "fortune": 2, "cultivation": 380, "lifespan": 50}, flavor="你勘破幻象走到桥心，悟性与机缘皆大涨，修为与寿元亦进。悟性 +2，机缘 +2，修为 +380，寿元 +50"),
                _c("以悟性辨明幻象，稳步前行", rewards={"comprehension": 1, "cultivation": 250, "lifespan": 25}, flavor="你走过半程，悟性、修为与寿元皆有提升。悟性 +1，修为 +250，寿元 +25"),
                _c("以神识固守本心，不为幻象所动", condition=_cond("soul", 8), rewards={"soul": 2, "fortune": 1, "cultivation": 350}, flavor="你以神识守心走过仙缘桥，神识大涨，机缘与修为皆进。神识 +2，机缘 +1，修为 +350"),
                _c("以神识固守本心，不为幻象所动", rewards={"soul": 1, "cultivation": 220}, flavor="你勉强走完全程，神识与修为皆有提升。神识 +1，修为 +220"),
            ]
        }),
        _c("只走数步便退回", rewards={"fortune": 2, "cultivation": 100}, flavor="你浅尝辄止，未贪心深入，反得天道一丝眷顾。机缘 +2，修为 +100"),
        _c("不登桥，只在桥头感悟", rewards={"comprehension": 1}, flavor="你在桥头静悟，心有所得。悟性 +1"),
    ]
))

EVENTS.append(_e(
    "【稀有】灵脉化龙",
    "地脉震动，一条由灵气凝聚而成的「灵脉龙影」自地底冲出，在空中盘旋片刻后缓缓消散，龙影所过之处灵气如雨。",
    [
        _c("冲入灵雨之中吸纳", next_event={
            "desc": "灵雨加身，磅礴灵气灌体，你需以神识或悟性引导归元，否则易撑伤经脉。",
            "choices": [
                _c("以神识引导灵气归元", condition=_cond("soul", 8), rewards={"soul": 1, "cultivation": 480, "lifespan": 55}, flavor="你稳稳炼化灵雨，神识、修为与寿元皆大涨。神识 +1，修为 +480，寿元 +55"),
                _c("以神识引导灵气归元", rewards={"cultivation": 300, "lifespan": 30}, flavor="你炼化部分灵雨，修为与寿元皆有大幅提升。修为 +300，寿元 +30"),
                _c("以悟性感悟龙影中的道韵", condition=_cond("comprehension", 8), rewards={"comprehension": 2, "cultivation": 400, "fortune": 1}, flavor="你从龙影中悟得一丝灵脉化形之道，悟性大涨，修为与机缘皆进。悟性 +2，修为 +400，机缘 +1"),
                _c("以悟性感悟龙影中的道韵", rewards={"comprehension": 1, "cultivation": 260}, flavor="你略有所悟，悟性与修为皆有提升。悟性 +1，修为 +260"),
            ]
        }),
        _c("只在外围收集凝成的灵晶", condition=_cond("fortune", 7), rewards={"spirit_stones": 500, "fortune": 1}, flavor="灵雨落地凝成灵晶，你收集一批，价值不菲。灵石 +500，机缘 +1"),
        _c("只在外围收集凝成的灵晶", rewards={"spirit_stones": 300}, flavor="你捡到部分灵晶，换得不少灵石。灵石 +300"),
        _c("不敢靠近，远观感悟", rewards={"cultivation": 150}, flavor="你远观灵脉化龙，心有所得。修为 +150"),
    ]
))
