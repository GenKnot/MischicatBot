from utils.events._base import _e, _c, _cond

EVENTS = []

EVENTS.append(_e(
    "铁甲城擂台生死战",
    "铁甲城的生死擂台今日开放，挑战者与擂主签下生死状，胜者可获得对方全部财物，败者自负生死。",
    [
        _c("上台挑战", next_event={
            "desc": "擂主是一名以体魄著称的修士，皮糙肉厚，普通攻击难以奏效。",
            "choices": [
                _c("以速度和技巧取胜", condition=_cond("comprehension", 8), rewards={"spirit_stones": 200, "reputation": 50, "comprehension": 1}, flavor="你以精妙的技巧找到了擂主的破绽，胜出，声望大涨。灵石 +200，声望 +50，悟性 +1"),
                _c("以速度和技巧取胜", rewards={"lifespan": -15, "reputation": 20}, flavor="你落败，受了重伤，但打出了风采。寿元 -15，声望 +20"),
                _c("以蛮力硬拼", condition=_cond("physique", 9), rewards={"spirit_stones": 200, "reputation": 50, "physique": 1}, flavor="你以更强横的体魄压制了擂主，胜出。灵石 +200，声望 +50，体魄 +1"),
                _c("以蛮力硬拼", rewards={"lifespan": -20}, flavor="擂主体魄极强，你惨败，受了重伤。寿元 -20"),
            ]
        }),
        _c("在旁观战，学习战斗技巧", condition=_cond("comprehension", 6), rewards={"cultivation": 80, "comprehension": 1}, flavor="你从生死战中学到了许多实战技巧。修为 +80，悟性 +1"),
        _c("在旁观战，学习战斗技巧", rewards={"cultivation": 40}, flavor="你观摩了一番，略有收获。修为 +40"),
        _c("不感兴趣，离开", rewards={}, flavor="你继续赶路。"),
    ]
))

EVENTS.append(_e(
    "沙罗城情报商",
    "沙罗城的一家茶馆内，一名神秘人说自己掌握着各方势力的情报，愿意以五十灵石出售一条有价值的消息。",
    [
        _c("购买情报", next_event={
            "desc": "情报商压低声音说：「最近有一支商队会经过某处山谷，携带大量灵石，但也有护卫随行。」",
            "choices": [
                _c("前去拦截商队", condition=_cond("physique", 7), rewards={"spirit_stones": -50, "spirit_stones_gain": 200, "reputation": -30}, flavor="你成功拦截了商队，但此事传出后名声大损。灵石 -50+200，声望 -30"),
                _c("前去拦截商队", rewards={"spirit_stones": -50, "lifespan": -10, "reputation": -20}, flavor="护卫比你想象的强，你受伤逃脱，还损失了购买情报的灵石。寿元 -10，灵石 -50，声望 -20"),
                _c("将情报转卖给商队", condition=_cond("comprehension", 6), rewards={"spirit_stones": 80, "reputation": 15}, flavor="你将情报卖给了商队，让他们提前防备，赚了差价，声望略有提升。灵石 +80，声望 +15"),
                _c("放弃，不想惹麻烦", rewards={"spirit_stones": -50}, flavor="你购买了情报，但没有行动，灵石白花了。灵石 -50"),
            ]
        }),
        _c("拒绝，可能是骗局", rewards={}, flavor="你拒绝了，继续赶路。"),
        _c("打听其他消息", condition=_cond("fortune", 6), rewards={"fortune": 1, "spirit_stones": 40}, flavor="你从情报商口中打听到了一些有价值的消息，机缘略有提升。机缘 +1，灵石 +40"),
        _c("打听其他消息", rewards={}, flavor="你没打听到什么有用的消息。"),
    ]
))

EVENTS.append(_e(
    "黄沙镇沙尘暴",
    "黄沙镇附近突然刮起一场沙尘暴，能见度极低，土灵气随沙尘弥漫，附近的修士纷纷寻找避风之所。",
    [
        _c("以灵力护体，在沙尘中修炼", condition=_cond("physique", 7), rewards={"physique": 1, "cultivation": 80}, flavor="你以强横体魄抵御了沙尘，反而借此机会修炼土灵气，体魄大进。体魄 +1，修为 +80"),
        _c("以灵力护体，在沙尘中修炼", rewards={"lifespan": -5, "cultivation": 40}, flavor="沙尘侵入，你受了些轻伤，但也借助土灵气修炼了一番。寿元 -5，修为 +40"),
        _c("寻找避风山洞", condition=_cond("fortune", 6), rewards={"lifespan": 5, "spirit_stones": 50}, flavor="你找到了一处隐蔽的山洞，洞内还有前人遗留的一些物资。寿元 +5，灵石 +50"),
        _c("寻找避风山洞", rewards={"lifespan": 3}, flavor="你找到了一处还算安全的地方，安然度过了沙尘暴。寿元 +3"),
        _c("感应沙尘中的土灵气", condition=_cond("soul", 6), rewards={"soul": 1, "comprehension": 1}, flavor="你在沙尘中感悟到了一丝土道法则，神识和悟性都有所提升。神识 +1，悟性 +1"),
        _c("感应沙尘中的土灵气", rewards={"cultivation": 30, "lifespan": -2}, flavor="你感应了一番，略有收获，但也受了些轻伤。修为 +30，寿元 -2"),
    ]
))

EVENTS.append(_e(
    "烈风关守将",
    "烈风关的守将拦住了你，说最近关外有妖兽活动，需要检查过往修士的身份，并要求缴纳通行费。",
    [
        _c("缴纳通行费（三十灵石）", rewards={"spirit_stones": -30}, flavor="你缴纳了通行费，顺利通过。灵石 -30"),
        _c("出示身份，要求免费通行", condition=_cond("reputation", 30), rewards={"reputation": 5}, flavor="守将认出了你的名声，免去了通行费，还客气地放行。声望 +5"),
        _c("出示身份，要求免费通行", rewards={"spirit_stones": -30, "reputation": -5}, flavor="守将不认识你，你只好缴费通行，还被嘲讽了几句。灵石 -30，声望 -5"),
        _c("强行闯关", condition=_cond("physique", 8), rewards={"reputation": -20}, flavor="你强行闯过，守将无奈，但此事传出后名声受损。声望 -20"),
        _c("强行闯关", rewards={"lifespan": -8, "spirit_stones": -30}, flavor="守将召来了援兵，你被迫缴费，还受了些轻伤。寿元 -8，灵石 -30"),
        _c("绕道而行", rewards={"lifespan": -2}, flavor="你绕道而行，耗费了不少时间和体力。寿元 -2"),
    ]
))

EVENTS.append(_e(
    "苍穹城雷劫",
    "苍穹城附近，一名修士正在渡雷劫，天空中雷云密布，紫色雷电不断落下，围观者众多。",
    [
        _c("在旁感应雷灵气", condition=_cond("comprehension", 7), rewards={"comprehension": 1, "cultivation": 90}, flavor="你从雷劫中感悟到了一丝雷道法则，悟性大进。悟性 +1，修为 +90"),
        _c("在旁感应雷灵气", rewards={"cultivation": 50}, flavor="雷灵气辅助修炼，修为有所提升。修为 +50"),
        _c("上前协助渡劫者", condition=_cond("physique", 7), rewards={"reputation": 40, "fortune": 1}, flavor="你协助渡劫者抵御了部分雷劫，对方感激不已，机缘大涨。声望 +40，机缘 +1"),
        _c("上前协助渡劫者", rewards={"lifespan": -8, "reputation": 20}, flavor="你被雷劫波及，受了些轻伤，但也赢得了渡劫者的感谢。寿元 -8，声望 +20"),
        _c("趁乱收集散落的雷灵石", condition=_cond("fortune", 6), rewards={"spirit_stones": 80}, flavor="你趁乱收集了一些雷劫散落的雷灵石，价值不菲。灵石 +80"),
        _c("趁乱收集散落的雷灵石", rewards={"lifespan": -5}, flavor="你被雷劫波及，受了些轻伤。寿元 -5"),
    ]
))

EVENTS.append(_e(
    "西域沙漠迷路",
    "在西域荒漠中赶路时，你不知不觉迷失了方向，四周全是一望无际的黄沙，太阳已经偏西。",
    [
        _c("以神识感应方向", condition=_cond("soul", 6), rewards={"soul": 1}, flavor="你以神识感应了周围的灵气流动，找到了正确方向，神识有所提升。神识 +1"),
        _c("以神识感应方向", rewards={"lifespan": -3}, flavor="你感应了许久，勉强找到了方向，但耗费了不少精力。寿元 -3"),
        _c("寻找绿洲", condition=_cond("fortune", 7), rewards={"fortune": 1, "lifespan": 5, "spirit_stones": 60}, flavor="你找到了一处隐藏的绿洲，绿洲中有灵泉和灵草，还发现了前人遗留的物资。机缘 +1，寿元 +5，灵石 +60"),
        _c("寻找绿洲", rewards={"lifespan": -5}, flavor="你在沙漠中兜转许久，耗费了大量体力。寿元 -5"),
        _c("原地等待，节省体力", rewards={"lifespan": -2}, flavor="你耐心等待，直到夜晚星辰出现后辨别方向，安全离开。寿元 -2"),
    ]
))

EVENTS.append(_e(
    "铁甲城武器铺",
    "铁甲城的一家武器铺正在出售一批新铸的法器，铺主说这批法器是用西域特产的玄铁铸造，品质上乘。",
    [
        _c("仔细挑选", next_event={
            "desc": "你在众多法器中发现了一件品相不错的防御法器，铺主报价一百二十灵石。",
            "choices": [
                _c("直接购买", condition=_cond("fortune", 6), rewards={"spirit_stones": -120, "physique": 1, "bone": 1}, flavor="法器品质极佳，装备后根骨和体魄都有所提升。灵石 -120，体魄 +1，根骨 +1"),
                _c("直接购买", rewards={"spirit_stones": -120, "physique": 1}, flavor="法器品质不错，装备后体魄有所提升。灵石 -120，体魄 +1"),
                _c("讨价还价", condition=_cond("comprehension", 6), rewards={"spirit_stones": -80, "physique": 1}, flavor="你以八十灵石买到了法器，物超所值。灵石 -80，体魄 +1"),
                _c("讨价还价", rewards={}, flavor="铺主不肯降价，你只好作罢。"),
            ]
        }),
        _c("打听玄铁的产地", condition=_cond("comprehension", 6), rewards={"comprehension": 1, "spirit_stones": 40}, flavor="你从铺主口中得知了玄铁的产地，悟性有所提升，还顺手做了笔小生意。悟性 +1，灵石 +40"),
        _c("不感兴趣，离开", rewards={}, flavor="你继续赶路。"),
    ]
))

EVENTS.append(_e(
    "西域古道遗迹",
    "西域古道旁，一处被黄沙掩埋的遗迹露出了一角，似乎是某个古老商队的营地。",
    [
        _c("挖掘遗迹", next_event={
            "desc": "你挖开黄沙，发现了一些古老的储物袋和残破的法器，还有一封用古文字写成的信件。",
            "choices": [
                _c("研究古文字信件", condition=_cond("comprehension", 7), rewards={"comprehension": 1, "fortune": 1}, flavor="你从信件中解读出了一处宝藏的线索，悟性和机缘都有所提升。悟性 +1，机缘 +1"),
                _c("研究古文字信件", rewards={"cultivation": 40}, flavor="古文字深奥，你只看出了些皮毛，但也有些收获。修为 +40"),
                _c("收集储物袋中的物品", condition=_cond("fortune", 6), rewards={"spirit_stones": 130, "fortune": 1}, flavor="储物袋中有一些保存完好的古代灵石和法器，价值不菲。灵石 +130，机缘 +1"),
                _c("收集储物袋中的物品", rewards={"spirit_stones": 70}, flavor="储物袋中有一些普通的灵石和材料。灵石 +70"),
            ]
        }),
        _c("在遗迹外感应灵气", condition=_cond("soul", 6), rewards={"soul": 1, "cultivation": 50}, flavor="遗迹中残存的灵气辅助你修炼，神识有所提升。神识 +1，修为 +50"),
        _c("不去理会，继续赶路", rewards={}, flavor="你继续赶路。"),
    ]
))

EVENTS.append(_e(
    "沙罗城消息贩子",
    "沙罗城是西域消息最灵通的地方，街头巷尾都有消息贩子，今日有人说发现了一处无人知晓的灵石矿脉。",
    [
        _c("花钱打听详情", next_event={
            "desc": "消息贩子说矿脉在西域荒漠深处，但附近有妖兽盘踞，需要有实力的修士才能前往。",
            "choices": [
                _c("前往矿脉", condition=_cond("physique", 7), rewards={"spirit_stones": -30, "spirit_stones_gain": 200}, flavor="你击败了妖兽，成功开采了矿脉，大赚一笔。灵石 -30+200"),
                _c("前往矿脉", rewards={"spirit_stones": -30, "lifespan": -8}, flavor="妖兽比你想象的强，你受伤撤退，灵石白花了。灵石 -30，寿元 -8"),
                _c("将消息转卖给他人", condition=_cond("comprehension", 6), rewards={"spirit_stones": 50}, flavor="你将消息转卖给了另一名修士，赚了差价。灵石 +50"),
            ]
        }),
        _c("不理会，可能是骗局", rewards={}, flavor="你继续赶路。"),
        _c("在城中打听其他消息", condition=_cond("fortune", 6), rewards={"fortune": 1, "spirit_stones": 50}, flavor="你从各处打听到了一些有价值的消息，机缘略有提升。机缘 +1，灵石 +50"),
        _c("在城中打听其他消息", rewards={}, flavor="你没打听到什么有用的消息。"),
    ]
))

EVENTS.append(_e(
    "苍穹城雷属灵根修士",
    "苍穹城的广场上，一名雷属变异灵根的修士正在展示自己的雷属功法，引来众多修士围观。",
    [
        _c("上前观摩，感悟雷道", condition=_cond("comprehension", 7), rewards={"comprehension": 1, "cultivation": 80}, flavor="你从雷属修士的演示中悟出了一丝雷道真意，悟性大进。悟性 +1，修为 +80"),
        _c("上前观摩，感悟雷道", rewards={"cultivation": 50}, flavor="你观摩了一番，修为有所提升。修为 +50"),
        _c("上前切磋", condition=_cond("physique", 7), rewards={"physique": 1, "reputation": 25}, flavor="你与雷属修士切磋，虽然落败，但体魄得到了锻炼，声望也有所提升。体魄 +1，声望 +25"),
        _c("上前切磋", rewards={"lifespan": -8, "reputation": 10}, flavor="雷属攻击威力极强，你受了不轻的伤。寿元 -8，声望 +10"),
        _c("不感兴趣，离开", rewards={}, flavor="你继续赶路。"),
    ]
))
