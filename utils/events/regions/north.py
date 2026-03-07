from utils.events._base import _e, _c, _cond

EVENTS = []

EVENTS.append(_e(
    "寒冰城冰窖",
    "寒冰城郊外，一处天然冰窖中传出淡淡的冰灵气，据说里面封存着一些上古时期的冰属灵材。",
    [
        _c("进入冰窖探查", next_event={
            "desc": "冰窖深处，你发现了几块晶莹剔透的寒玉，但周围的寒气足以冻伤筑基以下的修士。",
            "choices": [
                _c("强行采取寒玉", condition=_cond("physique", 7), rewards={"spirit_stones": 150, "physique": 1}, flavor="你凭借强健体魄抵御了寒气，成功取到了寒玉。灵石 +150，体魄 +1"),
                _c("强行采取寒玉", rewards={"lifespan": -12, "spirit_stones": 60}, flavor="寒气侵入骨髓，你受了重伤，只取到了少量寒玉。寿元 -12，灵石 +60"),
                _c("以灵力护体，缓慢前进", condition=_cond("soul", 6), rewards={"spirit_stones": 120, "soul": 1}, flavor="你以神识感应寒气规律，安全取到了寒玉。灵石 +120，神识 +1"),
                _c("以灵力护体，缓慢前进", rewards={"lifespan": -6, "spirit_stones": 80}, flavor="灵力消耗过大，你受了些冻伤，但也取到了部分寒玉。寿元 -6，灵石 +80"),
            ]
        }),
        _c("在冰窖外感应冰灵气", condition=_cond("comprehension", 6), rewards={"cultivation": 70, "comprehension": 1}, flavor="你在冰窖外感应冰灵气，悟出了一丝冰道真意。修为 +70，悟性 +1"),
        _c("在冰窖外感应冰灵气", rewards={"cultivation": 40}, flavor="冰灵气辅助修炼，略有收获。修为 +40"),
        _c("离开，太危险", rewards={}, flavor="你继续赶路。"),
    ]
))

EVENTS.append(_e(
    "北域雪狼群",
    "北域荒原上，一群雪狼正在追逐一名受伤的修士，那修士已经精疲力竭，眼看就要被追上。",
    [
        _c("出手相救", next_event={
            "desc": "你击退了雪狼群，受伤的修士感激涕零，说自己是北冥港的商人，愿意重谢。",
            "choices": [
                _c("接受答谢", condition=_cond("fortune", 6), rewards={"spirit_stones": 120, "reputation": 30, "fortune": 1}, flavor="商人拿出了一批北海灵材作为答谢，价值不菲。灵石 +120，声望 +30，机缘 +1"),
                _c("接受答谢", rewards={"spirit_stones": 70, "reputation": 30}, flavor="商人拿出了些灵石答谢你。灵石 +70，声望 +30"),
                _c("婉拒，举手之劳", rewards={"reputation": 50, "fortune": 1}, flavor="商人感动不已，说日后在北冥港有任何需要尽管来找他。声望 +50，机缘 +1"),
            ]
        }),
        _c("趁机猎杀雪狼，取其皮毛", condition=_cond("physique", 7), rewards={"spirit_stones": 100, "physique": 1}, flavor="你击杀了几只雪狼，取其皮毛换了不少灵石。灵石 +100，体魄 +1"),
        _c("趁机猎杀雪狼，取其皮毛", rewards={"lifespan": -8, "spirit_stones": 50}, flavor="雪狼群比你想象的强，你受了伤，但也取到了些皮毛。寿元 -8，灵石 +50"),
        _c("绕道而行，不想惹麻烦", rewards={}, flavor="你绕道离去，继续赶路。"),
    ]
))

EVENTS.append(_e(
    "幽冥镇鬼火",
    "幽冥镇附近的荒野中，夜间出现了数团幽蓝色的鬼火，在空中飘荡，散发着阴冷的气息。",
    [
        _c("靠近观察", next_event={
            "desc": "鬼火似乎有意识，它们围绕着你转了几圈，然后向某个方向飘去，似乎在引路。",
            "choices": [
                _c("跟随鬼火", condition=_cond("fortune", 7), rewards={"fortune": 1, "spirit_stones": 130}, flavor="鬼火引你来到一处古墓，墓中有前人遗留的灵石和法器。机缘 +1，灵石 +130"),
                _c("跟随鬼火", rewards={"lifespan": -10}, flavor="鬼火将你引入了一处阴气极重的地方，你受了阴寒之伤。寿元 -10"),
                _c("以灵力驱散鬼火", condition=_cond("soul", 7), rewards={"soul": 1, "cultivation": 60}, flavor="你驱散鬼火时感悟到了一丝阴阳之道，神识有所提升。神识 +1，修为 +60"),
                _c("以灵力驱散鬼火", rewards={"lifespan": -5}, flavor="鬼火爆发出阴寒之气，你受了些轻伤。寿元 -5"),
            ]
        }),
        _c("远远观望，不靠近", rewards={"fortune": 1}, flavor="你没有靠近，感觉今日运气会不错。机缘 +1"),
        _c("立刻离开此地", rewards={}, flavor="你加快脚步离开，继续赶路。"),
    ]
))

EVENTS.append(_e(
    "北冥港海兽皮毛",
    "北冥港的市集上，一名猎人正在出售刚猎获的海兽皮毛，皮毛厚实，是制作防寒法器的上好材料。",
    [
        _c("购买皮毛", next_event={
            "desc": "猎人报价一百灵石，说这批皮毛是极品北冥海兽的，防寒效果极佳。",
            "choices": [
                _c("直接购买", condition=_cond("fortune", 6), rewards={"spirit_stones": -100, "bone": 1, "lifespan": 10}, flavor="皮毛品质极佳，制成护具后根骨和寿元都有所提升。灵石 -100，根骨 +1，寿元 +10"),
                _c("直接购买", rewards={"spirit_stones": -100, "physique": 1}, flavor="皮毛制成护具，体魄有所提升。灵石 -100，体魄 +1"),
                _c("讨价还价", condition=_cond("comprehension", 6), rewards={"spirit_stones": -60, "physique": 1}, flavor="你以六十灵石买到了皮毛，物超所值。灵石 -60，体魄 +1"),
                _c("讨价还价", rewards={}, flavor="猎人不肯降价，你只好作罢。"),
            ]
        }),
        _c("打听海兽出没地点", condition=_cond("fortune", 6), rewards={"fortune": 1, "spirit_stones": 80}, flavor="你从猎人口中得知了一处海兽聚集地，前往后收获颇丰。机缘 +1，灵石 +80"),
        _c("打听海兽出没地点", rewards={"lifespan": -5, "spirit_stones": 40}, flavor="你前往海兽聚集地，遭遇了一只强大的海兽，受伤后撤退，只取到了少量材料。寿元 -5，灵石 +40"),
        _c("不感兴趣，离开", rewards={}, flavor="你继续赶路。"),
    ]
))

EVENTS.append(_e(
    "玄冰谷寒流",
    "玄冰谷附近突然刮起一阵极寒寒流，气温骤降，连空气都开始结冰，附近的修士纷纷寻找避寒之所。",
    [
        _c("以内力抵御寒流，就地修炼", condition=_cond("physique", 8), rewards={"physique": 1, "cultivation": 100}, flavor="你以强横体魄抵御了寒流，反而借此机会深入修炼，体魄大进。体魄 +1，修为 +100"),
        _c("以内力抵御寒流，就地修炼", rewards={"lifespan": -12}, flavor="寒流侵入骨髓，你受了重伤。寿元 -12"),
        _c("寻找避寒山洞", condition=_cond("fortune", 6), rewards={"lifespan": 5, "spirit_stones": 60}, flavor="你找到了一处隐蔽的山洞，洞内还有前人遗留的一些物资。寿元 +5，灵石 +60"),
        _c("寻找避寒山洞", rewards={"lifespan": 3}, flavor="你找到了一处还算安全的山洞，安然度过了寒流。寿元 +3"),
        _c("感应寒流中的冰灵气", condition=_cond("soul", 7), rewards={"soul": 1, "comprehension": 1}, flavor="你在寒流中感悟到了一丝冰道法则，神识和悟性都有所提升。神识 +1，悟性 +1"),
        _c("感应寒流中的冰灵气", rewards={"cultivation": 50, "lifespan": -3}, flavor="你感应了一番，略有收获，但也受了些冻伤。修为 +50，寿元 -3"),
    ]
))

EVENTS.append(_e(
    "北域冰封古树",
    "荒原上，一棵被冰封的古树矗立在风雪中，树身晶莹剔透，树洞中隐约有什么东西被封存其中。",
    [
        _c("尝试破冰取物", condition=_cond("physique", 7), rewards={"spirit_stones": 140, "bone": 1}, flavor="你破开冰封，取出了一颗被封存的千年冰灵果，根骨大进。灵石 +140，根骨 +1"),
        _c("尝试破冰取物", rewards={"lifespan": -6, "spirit_stones": 50}, flavor="冰封极为坚硬，你费了很大力气才取出一些普通冰晶。寿元 -6，灵石 +50"),
        _c("以神识感应冰封之物", condition=_cond("soul", 6), rewards={"soul": 1, "fortune": 1}, flavor="你感应到了冰封中蕴含的天地法则，神识和机缘都有所提升。神识 +1，机缘 +1"),
        _c("以神识感应冰封之物", rewards={"cultivation": 40}, flavor="你感应了一番，略有收获。修为 +40"),
        _c("在古树旁打坐修炼", condition=_cond("comprehension", 6), rewards={"cultivation": 70, "comprehension": 1}, flavor="古树散发的冰灵气辅助你修炼，悟出了一丝冰道真意。修为 +70，悟性 +1"),
        _c("在古树旁打坐修炼", rewards={"cultivation": 40}, flavor="冰灵气辅助修炼，略有收获。修为 +40"),
    ]
))

EVENTS.append(_e(
    "雪狼城猎人公会",
    "雪狼城的猎人公会正在发布悬赏，一只变异雪狼在附近出没，悬赏三百灵石，要求提供妖丹为证。",
    [
        _c("接受悬赏，前去猎杀", next_event={
            "desc": "你找到了变异雪狼的踪迹，它体型是普通雪狼的两倍，眼睛散发着诡异的蓝光。",
            "choices": [
                _c("正面迎战", condition=_cond("physique", 8), rewards={"spirit_stones": 300, "physique": 1, "reputation": 40}, flavor="你以强横体魄击败了变异雪狼，获得了丰厚赏金。灵石 +300，体魄 +1，声望 +40"),
                _c("正面迎战", rewards={"lifespan": -15, "spirit_stones": 150, "reputation": 20}, flavor="你受了重伤，但也击败了雪狼，获得了部分赏金。寿元 -15，灵石 +150，声望 +20"),
                _c("设陷阱诱捕", condition=_cond("comprehension", 7), rewards={"spirit_stones": 300, "reputation": 40}, flavor="你巧妙设置陷阱，成功捕获了变异雪狼，获得全额赏金。灵石 +300，声望 +40"),
                _c("设陷阱诱捕", rewards={"lifespan": -5, "spirit_stones": 100}, flavor="陷阱被雪狼识破，你受了伤，只取到了部分材料。寿元 -5，灵石 +100"),
            ]
        }),
        _c("打听变异雪狼的弱点", condition=_cond("comprehension", 6), rewards={"comprehension": 1}, flavor="你从老猎人口中得知了变异雪狼的弱点，悟性有所提升。悟性 +1"),
        _c("不接受，太危险", rewards={}, flavor="你婉拒了悬赏，继续赶路。"),
    ]
))

EVENTS.append(_e(
    "北域极光",
    "北域的夜空中出现了罕见的极光，五彩斑斓，天地间灵气随之涌动，据说这是天地异象，预示着某种机缘。",
    [
        _c("在极光下打坐感悟", condition=_cond("comprehension", 8), rewards={"comprehension": 1, "soul": 1, "cultivation": 120}, flavor="你从极光中感悟到了一丝天地法则，悟性和神识都大幅提升。悟性 +1，神识 +1，修为 +120"),
        _c("在极光下打坐感悟", condition=_cond("comprehension", 6), rewards={"comprehension": 1, "cultivation": 80}, flavor="你从极光中有所感悟，悟性和修为都有所提升。悟性 +1，修为 +80"),
        _c("在极光下打坐感悟", rewards={"cultivation": 50}, flavor="极光辅助修炼，修为有所提升。修为 +50"),
        _c("寻找极光的源头", condition=_cond("fortune", 7), rewards={"fortune": 2, "spirit_stones": 100}, flavor="你找到了极光的源头——一处天地灵气汇聚点，机缘大涨。机缘 +2，灵石 +100"),
        _c("寻找极光的源头", rewards={"lifespan": -3, "cultivation": 40}, flavor="你在寻找途中耗费了不少精力，没有找到源头。寿元 -3，修为 +40"),
    ]
))

EVENTS.append(_e(
    "幽冥镇阴修",
    "幽冥镇的街道上，一名阴修主动搭话，说他有一门阴属功法残卷，愿意以一百灵石出售。",
    [
        _c("购买残卷", next_event={
            "desc": "残卷上记载着一门阴属辅助功法，修炼后可以增强神识，但需要在阴气充沛的地方修炼。",
            "choices": [
                _c("立刻修炼", condition=_cond("soul", 7), rewards={"spirit_stones": -100, "soul": 1, "cultivation": 80}, flavor="幽冥镇阴气充沛，你立刻修炼，神识大进。灵石 -100，神识 +1，修为 +80"),
                _c("立刻修炼", rewards={"spirit_stones": -100, "soul": 1}, flavor="你修炼了残卷，神识略有提升。灵石 -100，神识 +1"),
                _c("带走慢慢研究", rewards={"spirit_stones": -100, "cultivation": 50}, flavor="你将残卷带走，慢慢研究，略有收获。灵石 -100，修为 +50"),
            ]
        }),
        _c("拒绝，阴属功法不适合自己", rewards={}, flavor="你婉拒了，继续赶路。"),
        _c("怀疑是骗局，试探对方", condition=_cond("comprehension", 7), rewards={"comprehension": 1}, flavor="你试探出对方确实有真材实料，悟性有所提升。悟性 +1"),
        _c("怀疑是骗局，试探对方", rewards={"fortune": -1}, flavor="你的怀疑让对方不悦，机缘略有下降。机缘 -1"),
    ]
))

EVENTS.append(_e(
    "北域冰封遗迹",
    "荒原深处，一处被冰雪掩埋的古老遗迹露出了一角，似乎是某个上古修士的居所。",
    [
        _c("挖掘遗迹", next_event={
            "desc": "你挖开冰雪，发现了一间保存完好的石室，里面有一些古老的修炼器具和残破的功法碎简。",
            "choices": [
                _c("研究功法碎简", condition=_cond("comprehension", 7), rewards={"comprehension": 1, "cultivation": 100}, flavor="你从碎简中悟出了一丝上古修炼之道，悟性大进。悟性 +1，修为 +100"),
                _c("研究功法碎简", rewards={"cultivation": 60}, flavor="碎简残缺，你只看出了些皮毛，但也有些收获。修为 +60"),
                _c("收集修炼器具出售", condition=_cond("fortune", 6), rewards={"spirit_stones": 160, "fortune": 1}, flavor="古老的修炼器具价值不菲，你卖了个好价钱。灵石 +160，机缘 +1"),
                _c("收集修炼器具出售", rewards={"spirit_stones": 80}, flavor="器具虽然古老，但品质一般，卖了普通价格。灵石 +80"),
            ]
        }),
        _c("在遗迹外感应灵气", condition=_cond("soul", 6), rewards={"soul": 1, "cultivation": 50}, flavor="遗迹中残存的灵气辅助你修炼，神识有所提升。神识 +1，修为 +50"),
        _c("不去理会，继续赶路", rewards={}, flavor="你继续赶路。"),
    ]
))
