from utils.events._base import _e, _c, _cond

EVENTS = []

EVENTS.append(_e(
    "【稀有】洞天福地",
    "山间云雾中，你无意间踏入了一处结界，里面是一片与世隔绝的洞天福地，灵气浓郁程度是外界的十倍，一株株珍稀灵草随处可见。",
    [
        _c("在此闭关修炼", condition=_cond("comprehension", 7), rewards={"cultivation": 600, "comprehension": 2, "lifespan": 50}, flavor="你在洞天福地中闭关，灵气如潮水般涌入，修为暴涨，悟性大幅提升，寿元也得到了极大滋养。修为 +600，悟性 +2，寿元 +50"),
        _c("在此闭关修炼", rewards={"cultivation": 400, "lifespan": 30}, flavor="你在洞天福地中修炼，收获颇丰，修为大进，寿元也有所增长。修为 +400，寿元 +30"),
        _c("采集灵草带走", condition=_cond("fortune", 7), rewards={"spirit_stones": 600, "fortune": 2}, flavor="你采集了大量珍稀灵草，带到城中换得了大量灵石，机缘大涨。灵石 +600，机缘 +2"),
        _c("采集灵草带走", rewards={"spirit_stones": 350}, flavor="你采集了一批灵草，换了不少灵石。灵石 +350"),
        _c("寻找洞天的主人", condition=_cond("soul", 8), rewards={"soul": 2, "fortune": 2, "lifespan": 40}, flavor="你以神识感应，发现洞天深处有一缕残存的意志，从中获得了大量感悟，神识和机缘都大幅提升。神识 +2，机缘 +2，寿元 +40"),
        _c("寻找洞天的主人", rewards={"soul": 1, "cultivation": 200}, flavor="你感应到了一丝残存的意志，神识有所提升，修为也有所增长。神识 +1，修为 +200"),
    ]
))

EVENTS.append(_e(
    "【稀有】神龙现身",
    "大河之上，水面突然翻腾，一条通体金色的神龙破水而出，在空中盘旋片刻后，将目光落在了你身上。",
    [
        _c("跪拜行礼，表达敬意", next_event={
            "desc": "神龙低下头颅，从口中吐出一颗龙珠，悬浮在你面前，散发着令人窒息的磅礴灵气。",
            "choices": [
                _c("接受龙珠", condition=_cond("fortune", 9), rewards={"fortune": 3, "bone": 2, "lifespan": 100, "cultivation": 400}, flavor="龙珠入体，金光冲破百脉，你感到根骨彻底蜕变，寿元暴涨，修为猛进，机缘大涨。机缘 +3，根骨 +2，寿元 +100，修为 +400"),
                _c("接受龙珠", rewards={"fortune": 2, "bone": 1, "lifespan": 60, "cultivation": 250}, flavor="龙珠入体，你感到根骨有所提升，寿元大涨，修为猛进。机缘 +2，根骨 +1，寿元 +60，修为 +250"),
                _c("婉拒，不敢承受", rewards={"fortune": 2, "lifespan": 30}, flavor="神龙似乎欣赏你的谦逊，将龙珠收回，但散出一缕龙气滋养了你。机缘 +2，寿元 +30"),
            ]
        }),
        _c("以神识感应神龙", condition=_cond("soul", 9), rewards={"soul": 2, "comprehension": 2, "cultivation": 300}, flavor="你以神识感应神龙，从中感悟到了一丝龙道法则，神识和悟性都大幅提升。神识 +2，悟性 +2，修为 +300"),
        _c("以神识感应神龙", rewards={"soul": 1, "cultivation": 150}, flavor="你感应到了神龙散发的灵气，神识有所提升。神识 +1，修为 +150"),
        _c("转身离去，不敢打扰", rewards={"fortune": 1, "lifespan": 10}, flavor="神龙似乎感受到了你的敬畏，散出一缕龙气滋养了你。机缘 +1，寿元 +10"),
    ]
))

EVENTS.append(_e(
    "【稀有】仙界碎片",
    "荒野中，你发现了一块散发着仙气的碎片，那是传说中仙界飞升时留下的空间碎片，蕴含着极为纯粹的仙灵之气。",
    [
        _c("直接吸纳仙灵之气", condition=_cond("physique", 8), rewards={"cultivation": 500, "physique": 2, "lifespan": 60}, flavor="你以强横体魄吸纳了仙灵之气，修为暴涨，体魄大幅提升，寿元也得到了极大滋养。修为 +500，体魄 +2，寿元 +60"),
        _c("直接吸纳仙灵之气", rewards={"cultivation": 300, "lifespan": 30, "lifespan_cost": 15}, flavor="仙灵之气过于纯粹，你强行吸纳，受了些内伤，但收获依然惊人。修为 +300，寿元 +15"),
        _c("以神识感应碎片", condition=_cond("soul", 8), rewards={"soul": 2, "comprehension": 2, "lifespan": 50}, flavor="你以神识感应仙界碎片，从中感悟到了一丝仙道法则，神识和悟性都大幅提升，寿元也得到了滋养。神识 +2，悟性 +2，寿元 +50"),
        _c("以神识感应碎片", rewards={"soul": 1, "comprehension": 1, "lifespan": 30}, flavor="你感应到了仙灵之气，神识和悟性都有所提升，寿元也有所增长。神识 +1，悟性 +1，寿元 +30"),
        _c("将碎片带走出售", condition=_cond("fortune", 7), rewards={"spirit_stones": 800, "fortune": 1}, flavor="仙界碎片价值连城，你带到城中，被一位元婴期大修士高价收购。灵石 +800，机缘 +1"),
        _c("将碎片带走出售", rewards={"spirit_stones": 500}, flavor="仙界碎片稀世罕见，卖了个极好的价格。灵石 +500"),
    ]
))

EVENTS.append(_e(
    "【稀有】命运之轮",
    "荒野中，一个古老的石台上刻着一个巨大的轮盘，轮盘上有各种符文，中央有一根指针，似乎在等待人来拨动。",
    [
        _c("拨动指针，听天由命", next_event={
            "desc": "指针开始旋转，越转越快，最终停在了一个符文上，那个符文开始发光。",
            "choices": [
                _c("接受命运的安排", condition=_cond("fortune", 8), rewards={"fortune": 3, "lifespan": 80, "cultivation": 400, "bone": 1}, flavor="命运之轮给予了你最丰厚的馈赠，机缘暴涨，寿元大涨，修为猛进，根骨也得到了蜕变。机缘 +3，寿元 +80，修为 +400，根骨 +1"),
                _c("接受命运的安排", condition=_cond("fortune", 6), rewards={"fortune": 2, "lifespan": 50, "cultivation": 250}, flavor="命运之轮给予了你丰厚的馈赠，机缘大涨，寿元和修为都大幅提升。机缘 +2，寿元 +50，修为 +250"),
                _c("接受命运的安排", rewards={"lifespan": -20, "cultivation": 100}, flavor="命运之轮给予了你考验，你受了些损失，但也有所收获。寿元 -20，修为 +100"),
            ]
        }),
        _c("研究轮盘上的符文", condition=_cond("comprehension", 8), rewards={"comprehension": 2, "soul": 1, "cultivation": 300}, flavor="你从轮盘符文中悟出了一丝命运之道，悟性和神识都大幅提升，修为暴涨。悟性 +2，神识 +1，修为 +300"),
        _c("研究轮盘上的符文", rewards={"comprehension": 1, "cultivation": 150}, flavor="你研究了符文，悟性有所提升，修为也有所增长。悟性 +1，修为 +150"),
        _c("不去触碰，原路离去", rewards={"fortune": 1}, flavor="你感到此地有些不寻常，谨慎离去，机缘略有提升。机缘 +1"),
    ]
))

EVENTS.append(_e(
    "【稀有】上古炼丹炉",
    "深山中，一座巨大的炼丹炉矗立在山顶，炉身刻满了上古符文，炉内的丹火历经千年仍未熄灭，炉口散发着浓郁的丹香。",
    [
        _c("尝试激活炼丹炉", next_event={
            "desc": "你将灵力注入炼丹炉，炉内的丹火猛然升腾，炉身开始震动，似乎在自动炼制什么东西。",
            "choices": [
                _c("等待炼制完成", condition=_cond("fortune", 8), rewards={"lifespan": 80, "cultivation": 300, "bone": 1, "soul": 1}, flavor="炼丹炉炼制出了一颗品质极佳的上古丹药，服下后寿元暴涨，修为猛进，根骨和神识都得到了提升。寿元 +80，修为 +300，根骨 +1，神识 +1"),
                _c("等待炼制完成", rewards={"lifespan": 50, "cultivation": 200}, flavor="炼丹炉炼制出了一颗普通的上古丹药，服下后寿元大涨，修为大进。寿元 +50，修为 +200"),
                _c("中途打断，取出材料", condition=_cond("physique", 7), rewards={"spirit_stones": 400}, flavor="你取出了半成品的丹药材料，虽然没有炼成，但材料本身价值不菲。灵石 +400"),
                _c("中途打断，取出材料", rewards={"spirit_stones": 200, "lifespan": -10}, flavor="炼丹炉爆发出反噬，你受了些轻伤，但也取到了一些材料。灵石 +200，寿元 -10"),
            ]
        }),
        _c("在炼丹炉旁感悟丹道", condition=_cond("soul", 7), rewards={"soul": 1, "comprehension": 1, "cultivation": 250}, flavor="你从炼丹炉散发的丹道气息中感悟到了一丝炼丹之道，神识和悟性都有所提升，修为大进。神识 +1，悟性 +1，修为 +250"),
        _c("在炼丹炉旁感悟丹道", rewards={"cultivation": 150, "soul": 1}, flavor="你感悟了丹道气息，神识有所提升，修为也有所增长。神识 +1，修为 +150"),
        _c("不去触碰，原路离去", rewards={"fortune": 1}, flavor="你感到此地有些不寻常，谨慎离去，机缘略有提升。机缘 +1"),
    ]
))

EVENTS.append(_e(
    "【稀有】天道感应",
    "修炼途中，你突然感到天地间有一股无形的力量在注视着你，随即一道金色的光芒从天而降，笼罩在你周身。",
    [
        _c("静心感悟，与天道共鸣", condition=_cond("comprehension", 9), rewards={"comprehension": 3, "soul": 2, "cultivation": 500, "lifespan": 60}, flavor="你与天道产生了共鸣，感悟到了极深的天地法则，悟性和神识都大幅提升，修为暴涨，寿元也得到了极大滋养。悟性 +3，神识 +2，修为 +500，寿元 +60"),
        _c("静心感悟，与天道共鸣", condition=_cond("comprehension", 7), rewards={"comprehension": 2, "soul": 1, "cultivation": 350, "lifespan": 40}, flavor="你感悟到了天地法则，悟性和神识都大幅提升，修为暴涨，寿元也得到了滋养。悟性 +2，神识 +1，修为 +350，寿元 +40"),
        _c("静心感悟，与天道共鸣", rewards={"comprehension": 1, "cultivation": 200, "lifespan": 20}, flavor="你感悟到了一丝天地法则，悟性有所提升，修为大进，寿元也有所增长。悟性 +1，修为 +200，寿元 +20"),
        _c("以神识感应天道意志", condition=_cond("soul", 9), rewards={"soul": 3, "fortune": 2, "lifespan": 50}, flavor="你以神识感应天道意志，神识大幅提升，机缘暴涨，寿元也得到了极大滋养。神识 +3，机缘 +2，寿元 +50"),
        _c("以神识感应天道意志", rewards={"soul": 1, "fortune": 1, "lifespan": 20}, flavor="你感应到了天道意志，神识和机缘都有所提升，寿元也有所增长。神识 +1，机缘 +1，寿元 +20"),
    ]
))

EVENTS.append(_e(
    "【稀有】前世记忆碎片",
    "打坐修炼时，你突然陷入了一段奇异的梦境，梦中你是另一个人，拥有着截然不同的修炼经历，醒来后记忆犹新。",
    [
        _c("深入感悟梦中记忆", condition=_cond("soul", 8), rewards={"soul": 2, "comprehension": 2, "cultivation": 400, "lifespan": 40}, flavor="你从前世记忆中获得了大量修炼感悟，神识和悟性都大幅提升，修为暴涨，寿元也得到了滋养。神识 +2，悟性 +2，修为 +400，寿元 +40"),
        _c("深入感悟梦中记忆", condition=_cond("soul", 6), rewards={"soul": 1, "comprehension": 1, "cultivation": 250}, flavor="你从前世记忆中获得了一些修炼感悟，神识和悟性都有所提升，修为大进。神识 +1，悟性 +1，修为 +250"),
        _c("深入感悟梦中记忆", rewards={"cultivation": 150, "lifespan": -5}, flavor="记忆太过模糊，你来不及充分感悟，还受了些反噬。修为 +150，寿元 -5"),
        _c("寻找梦中记忆的线索", condition=_cond("fortune", 8), rewards={"fortune": 3, "spirit_stones": 400, "lifespan": 30}, flavor="你根据梦中记忆找到了前世遗留的宝藏，机缘暴涨，收获颇丰。机缘 +3，灵石 +400，寿元 +30"),
        _c("寻找梦中记忆的线索", rewards={"fortune": 1, "spirit_stones": 150}, flavor="你找到了一些线索，机缘略有提升，也有些收获。机缘 +1，灵石 +150"),
    ]
))

EVENTS.append(_e(
    "【稀有】天地至宝现世",
    "天空中突然出现了一道彩虹，彩虹的尽头落在了附近的山谷中，据说这是天地至宝现世的征兆，附近的修士都在赶往山谷。",
    [
        _c("全速赶往山谷", next_event={
            "desc": "你赶到山谷，发现一颗散发着五彩光芒的宝珠悬浮在空中，周围已经聚集了数名修士，都在虎视眈眈。",
            "choices": [
                _c("趁乱抢夺宝珠", condition=_cond("physique", 8), rewards={"fortune": 3, "bone": 2, "lifespan": 80, "cultivation": 300}, flavor="你以迅雷不及掩耳之势抢到了宝珠，宝珠入体，机缘暴涨，根骨蜕变，寿元大涨，修为猛进。机缘 +3，根骨 +2，寿元 +80，修为 +300"),
                _c("趁乱抢夺宝珠", rewards={"lifespan": -20, "reputation": -30}, flavor="你被其他修士联手阻拦，受了重伤，名声大损，宝珠也被他人抢走。寿元 -20，声望 -30"),
                _c("以机缘感应宝珠", condition=_cond("fortune", 9), rewards={"fortune": 3, "bone": 2, "lifespan": 80, "cultivation": 300}, flavor="宝珠似乎感应到了你的机缘，主动飞向你，其他修士无可奈何。机缘 +3，根骨 +2，寿元 +80，修为 +300"),
                _c("以机缘感应宝珠", rewards={"fortune": 1, "lifespan": 20}, flavor="宝珠散出一缕灵气滋养了你，但最终飞向了他人。机缘 +1，寿元 +20"),
            ]
        }),
        _c("不去凑热闹，在外围感应", condition=_cond("comprehension", 7), rewards={"comprehension": 1, "cultivation": 200, "lifespan": 20}, flavor="你在外围感应宝珠散发的灵气，悟性有所提升，修为大进，寿元也有所增长。悟性 +1，修为 +200，寿元 +20"),
        _c("不去凑热闹，在外围感应", rewards={"cultivation": 100, "lifespan": 10}, flavor="你在外围感应了一番，略有收获。修为 +100，寿元 +10"),
    ]
))

EVENTS.append(_e(
    "【稀有】长生秘法",
    "一处废弃的道观中，你在神像底座下发现了一个暗格，里面有一卷泛黄的古籍，封面上写着「长生秘法」四个大字。",
    [
        _c("立刻研读古籍", next_event={
            "desc": "古籍中记载着一门专注于延寿的秘法，修炼后可以大幅延长寿元，但需要消耗大量修为作为代价。",
            "choices": [
                _c("修炼长生秘法（消耗修为）", condition=_cond("soul", 7), rewards={"lifespan": 150, "cultivation": -200, "soul": 1}, flavor="你修炼了长生秘法，寿元暴涨，神识也有所提升，代价是消耗了部分修为。寿元 +150，修为 -200，神识 +1"),
                _c("修炼长生秘法（消耗修为）", rewards={"lifespan": 100, "cultivation": -150}, flavor="你修炼了长生秘法，寿元大涨，代价是消耗了部分修为。寿元 +100，修为 -150"),
                _c("只研读，不修炼", condition=_cond("comprehension", 7), rewards={"comprehension": 1, "lifespan": 30, "cultivation": 150}, flavor="你研读了秘法，从中悟出了一丝延寿之道，悟性有所提升，寿元和修为都有所增长。悟性 +1，寿元 +30，修为 +150"),
                _c("只研读，不修炼", rewards={"lifespan": 20, "cultivation": 80}, flavor="你研读了秘法，寿元和修为都有所增长。寿元 +20，修为 +80"),
            ]
        }),
        _c("将古籍带走出售", condition=_cond("fortune", 7), rewards={"spirit_stones": 600, "fortune": 1}, flavor="长生秘法价值连城，你带到城中，被一位高阶修士高价收购。灵石 +600，机缘 +1"),
        _c("将古籍带走出售", rewards={"spirit_stones": 350}, flavor="古籍卖了个不错的价格。灵石 +350"),
        _c("不去触碰，原路离去", rewards={"fortune": 1}, flavor="你感到此地有些不寻常，谨慎离去，机缘略有提升。机缘 +1"),
    ]
))
