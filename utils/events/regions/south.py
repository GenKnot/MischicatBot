from utils.events._base import _e, _c, _cond

EVENTS = []

EVENTS.append(_e(
    "丹师收徒",
    "丹霞谷入口处，一位白须丹师正在张贴告示，说要收一名记名弟子协助采药，报酬是传授一门初级炼丹之法。",
    [
        _c("上前毛遂自荐", next_event={
            "desc": "丹师打量了你一番，出了一道考题：让你辨认三株灵草的名称和药性。",
            "choices": [
                _c("认真辨认", condition=_cond("soul", 6), rewards={"soul": 1, "cultivation": 80, "spirit_stones": 60}, flavor="你全部答对，丹师大喜，传授了你炼丹心得，还给了些报酬。神识 +1，修为 +80，灵石 +60"),
                _c("认真辨认", rewards={"spirit_stones": 30, "cultivation": 40}, flavor="你答对了一部分，丹师给了些报酬，但没有传授功法。灵石 +30，修为 +40"),
                _c("随便应付", rewards={"reputation": -5}, flavor="丹师摇头，让你离去。声望 -5"),
            ]
        }),
        _c("在旁观看，不上前", condition=_cond("comprehension", 6), rewards={"comprehension": 1}, flavor="你从丹师的考题中学到了一些辨药之法。悟性 +1"),
        _c("不感兴趣，离开", rewards={}, flavor="你继续赶路。"),
    ]
))

EVENTS.append(_e(
    "火山灵气爆发",
    "赤炎城附近的火山突然喷发出一股浓郁的火灵气，天空被染成橙红色，附近修士纷纷驻足感应。",
    [
        _c("就地修炼，吸纳火灵气", condition=_cond("physique", 7), rewards={"cultivation": 120, "physique": 1}, flavor="你体魄强健，成功吸纳了大量火灵气，修为和体魄都有所提升。修为 +120，体魄 +1"),
        _c("就地修炼，吸纳火灵气", rewards={"cultivation": 70, "lifespan": -5}, flavor="火灵气过于炽烈，你吸纳时受了些内伤，但修为也有所提升。修为 +70，寿元 -5"),
        _c("寻找火灵气最浓处", condition=_cond("fortune", 7), rewards={"fortune": 1, "spirit_stones": 100}, flavor="你找到了火灵气的汇聚点，发现了一株极品火灵草。机缘 +1，灵石 +100"),
        _c("寻找火灵气最浓处", rewards={"lifespan": -8}, flavor="火灵气过于炽烈，你被灼伤，狼狈撤退。寿元 -8"),
        _c("远远观望，不靠近", rewards={"cultivation": 30}, flavor="你在远处感应了一番，略有收获。修为 +30"),
    ]
))

EVENTS.append(_e(
    "望月楼占卜",
    "望月楼内，一位据说能窥天机的占卜师正在为人占卜，排队者众多，收费五十灵石一次。",
    [
        _c("排队占卜", next_event={
            "desc": "轮到你时，占卜师闭目掐算，良久后睁眼说：「你近日将有一场机缘，但需主动把握。」",
            "choices": [
                _c("追问详情", condition=_cond("fortune", 7), rewards={"spirit_stones": -50, "fortune": 2}, flavor="占卜师多说了几句，你从中得到了重要提示，机缘大涨。灵石 -50，机缘 +2"),
                _c("追问详情", rewards={"spirit_stones": -50, "fortune": 1}, flavor="占卜师只是重复了一遍，你只好离去。灵石 -50，机缘 +1"),
                _c("感谢后离去", rewards={"spirit_stones": -50, "fortune": 1}, flavor="你记住了占卜师的话，感觉今日运气会不错。灵石 -50，机缘 +1"),
            ]
        }),
        _c("不占卜，在楼内打听消息", condition=_cond("comprehension", 6), rewards={"spirit_stones": 50}, flavor="你从其他修士的闲谈中得知了一个有价值的消息。灵石 +50"),
        _c("不占卜，在楼内打听消息", rewards={}, flavor="你没打听到什么有用的消息。"),
        _c("离开，不信这些", rewards={}, flavor="你继续赶路。"),
    ]
))

EVENTS.append(_e(
    "翠微城药农",
    "翠微城郊外，一名老药农正在采摘灵草，他见到你后说最近山里出现了一种奇异的灵草，但附近有妖兽守护。",
    [
        _c("帮助老药农驱逐妖兽", next_event={
            "desc": "妖兽是一只木属灵兽，体型不大但速度极快，老药农说击败后可以平分灵草。",
            "choices": [
                _c("正面迎战", condition=_cond("physique", 6), rewards={"spirit_stones": 80, "physique": 1}, flavor="你击败了灵兽，与老药农平分了灵草，换得不少灵石。灵石 +80，体魄 +1"),
                _c("正面迎战", rewards={"lifespan": -6, "spirit_stones": 40}, flavor="你受了伤，但也击退了灵兽，分到了部分灵草。寿元 -6，灵石 +40"),
                _c("以食物引开灵兽", condition=_cond("fortune", 6), rewards={"spirit_stones": 90, "fortune": 1}, flavor="你巧妙地引开了灵兽，老药农顺利采到灵草，分给你更多。灵石 +90，机缘 +1"),
                _c("以食物引开灵兽", rewards={"spirit_stones": 50}, flavor="灵兽被引开，你们顺利采到了灵草。灵石 +50"),
            ]
        }),
        _c("独自去采灵草，不帮老药农", condition=_cond("physique", 7), rewards={"spirit_stones": 120}, flavor="你独自击败妖兽，采到了全部灵草。灵石 +120"),
        _c("独自去采灵草，不帮老药农", rewards={"lifespan": -8, "reputation": -10}, flavor="你被妖兽击伤，还被老药农指责，名声受损。寿元 -8，声望 -10"),
        _c("不感兴趣，离开", rewards={}, flavor="你继续赶路。"),
    ]
))

EVENTS.append(_e(
    "炎阳城丹药市集",
    "炎阳城每月一次的丹药市集今日开市，各种丹药琳琅满目，香气四溢，修士们摩肩接踵。",
    [
        _c("仔细挑选丹药", next_event={
            "desc": "你在众多摊位中发现了一颗品相不错的培元丹，摊主报价八十灵石。",
            "choices": [
                _c("直接购买", condition=_cond("fortune", 6), rewards={"spirit_stones": -80, "lifespan": 25, "cultivation": 60}, flavor="丹药品质极佳，服下后寿元和修为都有所提升。灵石 -80，寿元 +25，修为 +60"),
                _c("直接购买", rewards={"spirit_stones": -80, "lifespan": 15}, flavor="普通品质的培元丹，略有补益。灵石 -80，寿元 +15"),
                _c("讨价还价", condition=_cond("comprehension", 6), rewards={"spirit_stones": -50, "lifespan": 15}, flavor="你以五十灵石买到了丹药，物有所值。灵石 -50，寿元 +15"),
                _c("讨价还价", rewards={}, flavor="摊主不肯降价，你只好作罢。"),
            ]
        }),
        _c("在市集上打听丹方", condition=_cond("soul", 6), rewards={"soul": 1, "cultivation": 50}, flavor="你从一位丹师口中打听到了一个初级丹方，神识有所提升。神识 +1，修为 +50"),
        _c("在市集上打听丹方", rewards={"cultivation": 20}, flavor="你打听到了一些皮毛，略有收获。修为 +20"),
        _c("离开，不感兴趣", rewards={}, flavor="你继续赶路。"),
    ]
))

EVENTS.append(_e(
    "南域毒虫",
    "南域森林中，你突然感到脚踝一阵刺痛，低头一看，一只拇指大小的毒虫正在咬你，毒液已经渗入。",
    [
        _c("立刻运功逼毒", condition=_cond("physique", 7), rewards={"physique": 1}, flavor="你体魄强健，轻松将毒素逼出，体魄反而得到了锻炼。体魄 +1"),
        _c("立刻运功逼毒", rewards={"lifespan": -8}, flavor="毒素侵入经脉，你费了好大力气才将其逼出，元气大伤。寿元 -8"),
        _c("寻找解毒草药", condition=_cond("comprehension", 6), rewards={"comprehension": 1}, flavor="你凭借药草知识找到了解毒草药，还从中悟出了一些药理。悟性 +1"),
        _c("寻找解毒草药", rewards={"lifespan": -5, "spirit_stones": -20}, flavor="你找到了解毒草药，但耗费了不少时间和灵石。寿元 -5，灵石 -20"),
        _c("捕捉毒虫，带去城中出售", condition=_cond("fortune", 6), rewards={"spirit_stones": 60, "lifespan": -3}, flavor="你忍痛捕捉了毒虫，带去城中卖给了炼毒师，换了不少灵石。灵石 +60，寿元 -3"),
        _c("捕捉毒虫，带去城中出售", rewards={"lifespan": -10}, flavor="毒虫挣扎时再次咬了你，毒素加深，你狼狈逃脱。寿元 -10"),
    ]
))

EVENTS.append(_e(
    "丹霞谷采药",
    "丹霞谷内灵草遍地，你发现了几株品相不错的灵草，但采摘时需要小心，否则会破坏药性。",
    [
        _c("仔细采摘，保留药性", condition=_cond("soul", 6), rewards={"spirit_stones": 100, "soul": 1}, flavor="你细心采摘，保留了灵草的完整药性，卖了个好价钱。灵石 +100，神识 +1"),
        _c("仔细采摘，保留药性", rewards={"spirit_stones": 60}, flavor="你采摘时略有失误，但灵草还是卖了不错的价格。灵石 +60"),
        _c("快速采摘，不管药性", rewards={"spirit_stones": 30}, flavor="你快速采摘，药性有所损失，卖价一般。灵石 +30"),
        _c("寻找更珍贵的灵草", condition=_cond("fortune", 7), rewards={"spirit_stones": 180, "fortune": 1}, flavor="你在深处发现了一株极品灵草，价值不菲。灵石 +180，机缘 +1"),
        _c("寻找更珍贵的灵草", rewards={"lifespan": -3, "spirit_stones": 40}, flavor="你深入寻找，耗费了不少精力，只找到了普通灵草。寿元 -3，灵石 +40"),
    ]
))

EVENTS.append(_e(
    "南域古丹炉",
    "荒野中，你发现了一座废弃的古丹炉，炉身刻满了古老的炼丹符文，炉内还有残余的丹火未熄。",
    [
        _c("研究炉身符文", condition=_cond("soul", 7), rewards={"soul": 1, "comprehension": 1}, flavor="你从古老符文中悟出了一丝炼丹之道，神识和悟性都有所提升。神识 +1，悟性 +1"),
        _c("研究炉身符文", rewards={"cultivation": 50}, flavor="符文深奥，你只看出了些皮毛，但也有些收获。修为 +50"),
        _c("尝试激活丹炉", condition=_cond("fortune", 7), rewards={"fortune": 1, "spirit_stones": 150}, flavor="丹炉激活后，炉内残余的丹药凝结成形，你收获了几颗品质不错的丹药。机缘 +1，灵石 +150"),
        _c("尝试激活丹炉", rewards={"lifespan": -5}, flavor="丹炉爆发出一股热浪，你被灼伤。寿元 -5"),
        _c("将丹炉带走出售", condition=_cond("physique", 6), rewards={"spirit_stones": 120}, flavor="古丹炉虽然废弃，但材质不凡，卖给了一位收藏家。灵石 +120"),
        _c("将丹炉带走出售", rewards={"lifespan": -2}, flavor="丹炉太重，你搬运时耗费了大量体力。寿元 -2，灵石 +60"),
    ]
))

EVENTS.append(_e(
    "赤炎城擂台",
    "赤炎城的擂台今日开放，任何修士都可上台挑战，胜者可获得一颗火属丹药作为奖励。",
    [
        _c("上台挑战", next_event={
            "desc": "对手是一名火属灵根的修士，火灵气护体，攻击力极强。",
            "choices": [
                _c("以速度周旋，寻找破绽", condition=_cond("comprehension", 7), rewards={"spirit_stones": 80, "reputation": 25, "comprehension": 1}, flavor="你以灵动的身法找到了对手的破绽，胜出。灵石 +80，声望 +25，悟性 +1"),
                _c("以速度周旋，寻找破绽", rewards={"lifespan": -6, "reputation": 10}, flavor="你落败，但打出了风采。寿元 -6，声望 +10"),
                _c("以强攻压制", condition=_cond("physique", 8), rewards={"spirit_stones": 80, "reputation": 25, "physique": 1}, flavor="你以强横体魄压制了对手的火灵气，胜出。灵石 +80，声望 +25，体魄 +1"),
                _c("以强攻压制", rewards={"lifespan": -10}, flavor="对手的火灵气灼伤了你，你惨败。寿元 -10"),
            ]
        }),
        _c("在旁观战，学习火属功法", condition=_cond("comprehension", 6), rewards={"cultivation": 60, "comprehension": 1}, flavor="你从比试中学到了一些火属攻击技巧。修为 +60，悟性 +1"),
        _c("在旁观战，学习火属功法", rewards={"cultivation": 30}, flavor="你观摩了一番，略有收获。修为 +30"),
        _c("不感兴趣，离开", rewards={}, flavor="你继续赶路。"),
    ]
))

EVENTS.append(_e(
    "南域灵雨",
    "南域突降一场罕见的灵雨，雨水中蕴含着浓郁的木灵气，落在身上有一种说不出的舒适感。",
    [
        _c("在灵雨中打坐修炼", condition=_cond("comprehension", 7), rewards={"cultivation": 100, "comprehension": 1, "lifespan": 10}, flavor="你在灵雨中感悟木道，修为大进，寿元也得到了滋养。修为 +100，悟性 +1，寿元 +10"),
        _c("在灵雨中打坐修炼", rewards={"cultivation": 60, "lifespan": 8}, flavor="灵雨滋养，修为和寿元都有所提升。修为 +60，寿元 +8"),
        _c("收集灵雨水", rewards={"spirit_stones": 70}, flavor="灵雨水在市集上颇受欢迎，你收集了一些换了灵石。灵石 +70"),
        _c("在灵雨中沐浴", condition=_cond("fortune", 6), rewards={"lifespan": 15, "bone": 1}, flavor="灵雨滋润了你的根骨，寿元大幅提升。寿元 +15，根骨 +1"),
        _c("在灵雨中沐浴", rewards={"lifespan": 10}, flavor="灵雨滋润，寿元有所恢复。寿元 +10"),
    ]
))
