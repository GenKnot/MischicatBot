from utils.events._base import _e, _c, _cond

EVENTS = []

EVENTS.append(_e(
    "【稀有】仙人遗蜕",
    "荒野深处，你发现一具盘坐于巨石之上的枯骨，周身灵气凝而不散，显然是某位大能坐化后留下的遗蜕，石台上还摆着一个古朴玉瓶。",
    [
        _c("恭敬行礼，取走玉瓶", next_event={
            "desc": "玉瓶入手，瓶身温热，隐约有灵气流动。你打开瓶塞，一股浓郁的丹香扑面而来，里面躺着三颗散发金光的丹药。",
            "choices": [
                _c("一口吞下三颗", condition=_cond("physique", 8), rewards={"lifespan": 80, "cultivation": 300, "bone": 2}, flavor="丹药在体内炸开，金光冲破百脉，寿元大涨，修为猛进，根骨也得到了蜕变。寿元 +80，修为 +300，根骨 +2"),
                _c("一口吞下三颗", rewards={"lifespan": 40, "cultivation": 200}, flavor="丹力过于磅礴，你强行压制，受了些内伤，但收获依然惊人。寿元 +40，修为 +200"),
                _c("慢慢服下，一颗一颗来", rewards={"lifespan": 60, "cultivation": 250, "comprehension": 1}, flavor="你稳稳吸收了三颗丹药，寿元和修为都大幅提升，还悟出了一丝天地之道。寿元 +60，修为 +250，悟性 +1"),
            ]
        }),
        _c("感应遗蜕中残存的意志", condition=_cond("soul", 8), rewards={"soul": 2, "comprehension": 1, "cultivation": 200}, flavor="你以神识感应，竟从遗蜕中接收到了一缕残存的修炼感悟，神识和悟性都大幅提升。神识 +2，悟性 +1，修为 +200"),
        _c("感应遗蜕中残存的意志", rewards={"soul": 1, "cultivation": 100}, flavor="你感应到了一丝残存的意志，神识有所提升。神识 +1，修为 +100"),
        _c("不敢打扰，恭敬离去", rewards={"fortune": 2}, flavor="你恭敬地行了一礼，转身离去。走出数步，背后传来一阵温暖的灵气，似乎是某种祝福。机缘 +2"),
    ]
))

EVENTS.append(_e(
    "【稀有】天外陨石",
    "一道流光划破天际，轰然坠落在不远处，你赶到现场，发现一块散发着奇异光芒的陨石，周围的土地都被灵气浸透。",
    [
        _c("立刻上前触碰陨石", next_event={
            "desc": "陨石表面滚烫，但灵气极为纯粹，你感到一股力量在向你涌来，似乎在考验你的承受能力。",
            "choices": [
                _c("全力吸纳灵气", condition=_cond("physique", 8), rewards={"cultivation": 400, "physique": 2, "bone": 1}, flavor="你以强横体魄吸纳了陨石中的全部灵气，修为暴涨，体魄和根骨都得到了蜕变。修为 +400，体魄 +2，根骨 +1"),
                _c("全力吸纳灵气", rewards={"cultivation": 200, "lifespan": -20}, flavor="灵气过于磅礴，你强行吸纳，受了内伤，但修为也大幅提升。修为 +200，寿元 -20"),
                _c("缓慢感应，不强行吸纳", condition=_cond("soul", 7), rewards={"cultivation": 300, "soul": 1, "comprehension": 1}, flavor="你以神识引导，稳稳吸纳了陨石灵气，神识和悟性都有所提升。修为 +300，神识 +1，悟性 +1"),
                _c("缓慢感应，不强行吸纳", rewards={"cultivation": 180, "spirit_stones": 100}, flavor="你吸纳了部分灵气，剩余的凝结成了灵石。修为 +180，灵石 +100"),
            ]
        }),
        _c("将陨石带走出售", condition=_cond("physique", 7), rewards={"spirit_stones": 500}, flavor="陨石材质罕见，你费力搬运到城中，被一位炼器大师高价收购。灵石 +500"),
        _c("将陨石带走出售", rewards={"spirit_stones": 300, "lifespan": -5}, flavor="陨石沉重，搬运途中你耗费了大量体力，但卖价依然不菲。灵石 +300，寿元 -5"),
        _c("在陨石旁打坐感应", rewards={"cultivation": 150, "fortune": 1}, flavor="你在陨石旁感应了一番，修为有所提升，机缘也好了些。修为 +150，机缘 +1"),
    ]
))

EVENTS.append(_e(
    "【稀有】上古功法残简",
    "一处隐秘山洞中，你发现了一批被封存在冰晶里的玉简，封印已经松动，玉简上的文字散发着古老的气息。",
    [
        _c("打破冰晶，取出玉简", next_event={
            "desc": "玉简共有三枚，分别散发着不同颜色的光芒，你只能选择一枚研读，其余的在你触碰后化为飞灰。",
            "choices": [
                _c("选择金色玉简（修炼心法）", condition=_cond("comprehension", 7), rewards={"cultivation": 500, "comprehension": 2}, flavor="金色玉简中记载着一门上古修炼心法，你悉心研读，修为暴涨，悟性大幅提升。修为 +500，悟性 +2"),
                _c("选择金色玉简（修炼心法）", rewards={"cultivation": 300, "comprehension": 1}, flavor="你研读了心法，虽然只领悟了皮毛，但收获依然惊人。修为 +300，悟性 +1"),
                _c("选择蓝色玉简（神识功法）", condition=_cond("soul", 7), rewards={"soul": 2, "cultivation": 300, "lifespan": 30}, flavor="蓝色玉简中记载着一门神识修炼功法，你研读后神识大幅提升，寿元也得到了滋养。神识 +2，修为 +300，寿元 +30"),
                _c("选择蓝色玉简（神识功法）", rewards={"soul": 1, "cultivation": 200}, flavor="你研读了神识功法，神识有所提升。神识 +1，修为 +200"),
                _c("选择红色玉简（体魄功法）", condition=_cond("physique", 7), rewards={"physique": 2, "bone": 1, "cultivation": 300}, flavor="红色玉简中记载着一门体魄淬炼功法，你修炼后体魄和根骨都得到了蜕变。体魄 +2，根骨 +1，修为 +300"),
                _c("选择红色玉简（体魄功法）", rewards={"physique": 1, "cultivation": 200}, flavor="你修炼了体魄功法，体魄有所提升。体魄 +1，修为 +200"),
            ]
        }),
        _c("以神识感应冰晶封印", condition=_cond("soul", 8), rewards={"soul": 1, "fortune": 2}, flavor="你感应到了封印中蕴含的阵法之道，神识有所提升，机缘大涨。神识 +1，机缘 +2"),
        _c("不去触碰，原路离去", rewards={"fortune": 1}, flavor="你感到此地有些不寻常，谨慎离去，机缘略有提升。机缘 +1"),
    ]
))

EVENTS.append(_e(
    "【稀有】千年灵兽认主",
    "深山之中，一只通体雪白、额头有金色纹路的灵兽挡住了你的去路，它打量着你，眼神中带着某种期待。",
    [
        _c("缓慢靠近，伸出手", next_event={
            "desc": "灵兽嗅了嗅你的手，随后将头轻轻靠在你掌心，发出低沉的鸣叫，似乎在等待你的决定。",
            "choices": [
                _c("接受它的认主", condition=_cond("fortune", 8), rewards={"fortune": 3, "lifespan": 50, "cultivation": 200}, flavor="灵兽与你心神相连，你感到一股磅礴的机缘涌来，寿元和修为都大幅提升。机缘 +3，寿元 +50，修为 +200"),
                _c("接受它的认主", rewards={"fortune": 2, "lifespan": 30, "cultivation": 100}, flavor="灵兽认主成功，你感到机缘有所提升，寿元和修为也有所增长。机缘 +2，寿元 +30，修为 +100"),
                _c("婉拒，不想被束缚", rewards={"fortune": 1, "spirit_stones": 200}, flavor="灵兽似乎理解了你的意思，从嘴中吐出一颗灵珠后离去。机缘 +1，灵石 +200"),
            ]
        }),
        _c("以食物引诱它", condition=_cond("fortune", 7), rewards={"fortune": 2, "lifespan": 40}, flavor="灵兽接受了你的食物，临别时舔了舔你的手，你感到一股温暖的灵气涌入体内。机缘 +2，寿元 +40"),
        _c("以食物引诱它", rewards={"fortune": 1, "lifespan": 20}, flavor="灵兽接受了食物，给了你一些回报。机缘 +1，寿元 +20"),
        _c("绕道而行，不去打扰", rewards={"fortune": 1}, flavor="你绕道离去，走出数步后回头，灵兽正静静地看着你，眼神意味深长。机缘 +1"),
    ]
))

EVENTS.append(_e(
    "【稀有】天地灵眼开启",
    "修炼途中，你突然感到眉心一阵剧烈跳动，天地间的灵气在你眼中变得清晰可见，这是传说中的灵眼短暂开启。",
    [
        _c("顺势感悟，深入修炼", condition=_cond("soul", 8), rewards={"soul": 2, "comprehension": 2, "cultivation": 300}, flavor="你抓住灵眼开启的时机，深入感悟天地法则，神识和悟性都大幅提升，修为暴涨。神识 +2，悟性 +2，修为 +300"),
        _c("顺势感悟，深入修炼", condition=_cond("soul", 6), rewards={"soul": 1, "comprehension": 1, "cultivation": 200}, flavor="你感悟了天地法则，神识和悟性都有所提升，修为大进。神识 +1，悟性 +1，修为 +200"),
        _c("顺势感悟，深入修炼", rewards={"cultivation": 150, "lifespan": -5}, flavor="灵眼开启时间太短，你来不及充分感悟，还受了些反噬。修为 +150，寿元 -5"),
        _c("寻找附近的灵脉", condition=_cond("fortune", 7), rewards={"fortune": 2, "spirit_stones": 300}, flavor="借助灵眼，你看到了附近隐藏的灵脉，找到了一处无人知晓的灵石矿脉。机缘 +2，灵石 +300"),
        _c("寻找附近的灵脉", rewards={"spirit_stones": 150, "fortune": 1}, flavor="你找到了一些灵石，机缘略有提升。灵石 +150，机缘 +1"),
    ]
))

EVENTS.append(_e(
    "【稀有】渡劫散修的传承",
    "荒野中，一名正在渡劫的散修突然向你求助，说他渡劫失败，时日无多，愿意将毕生传承托付给有缘人。",
    [
        _c("接受传承", next_event={
            "desc": "散修将一枚储满毕生感悟的玉简递给你，说：「我修炼数百年，所悟皆在此中，望你善加利用。」",
            "choices": [
                _c("立刻感悟玉简", condition=_cond("comprehension", 7), rewards={"comprehension": 2, "soul": 1, "cultivation": 400, "lifespan": 50}, flavor="玉简中蕴含着散修数百年的修炼感悟，悟性和神识都大幅提升，修为暴涨，寿元也得到了滋养。悟性 +2，神识 +1，修为 +400，寿元 +50"),
                _c("立刻感悟玉简", rewards={"comprehension": 1, "cultivation": 250, "lifespan": 30}, flavor="你感悟了玉简，悟性有所提升，修为大进，寿元也有所增长。悟性 +1，修为 +250，寿元 +30"),
                _c("先救治散修，再感悟", condition=_cond("fortune", 7), rewards={"fortune": 2, "comprehension": 1, "cultivation": 300, "lifespan": 60}, flavor="你先救治了散修，他感激之下又额外传授了你一门延寿秘法，机缘大涨。机缘 +2，悟性 +1，修为 +300，寿元 +60"),
                _c("先救治散修，再感悟", rewards={"comprehension": 1, "cultivation": 200, "lifespan": 40}, flavor="你救治了散修，他感激地传授了你更多感悟。悟性 +1，修为 +200，寿元 +40"),
            ]
        }),
        _c("婉拒，不想承担因果", rewards={"fortune": 1}, flavor="你婉拒了，散修点头，说你有自己的道，机缘略有提升。机缘 +1"),
        _c("帮助散修渡劫", condition=_cond("physique", 8), rewards={"reputation": 50, "fortune": 2, "lifespan": 30}, flavor="你协助散修渡过了劫难，他感激涕零，赠予你大量好处，声望大涨。声望 +50，机缘 +2，寿元 +30"),
        _c("帮助散修渡劫", rewards={"lifespan": -15, "reputation": 30, "fortune": 1}, flavor="你被劫雷波及，受了重伤，但散修感激你的相助，赠予你一些好处。寿元 -15，声望 +30，机缘 +1"),
    ]
))

EVENTS.append(_e(
    "【稀有】万年灵药",
    "深山绝壁之上，一株散发着七彩光芒的灵药映入眼帘，周围的空气都因它而变得清甜，这是传说中的万年灵药。",
    [
        _c("不惜一切采摘", next_event={
            "desc": "灵药有灵性，你靠近时它开始颤动，似乎在抗拒，但也似乎在考验你的诚意。",
            "choices": [
                _c("以诚心感化", condition=_cond("fortune", 8), rewards={"lifespan": 100, "bone": 2, "cultivation": 300}, flavor="灵药感受到了你的诚意，主动落入你手中，服下后寿元暴涨，根骨得到了彻底蜕变。寿元 +100，根骨 +2，修为 +300"),
                _c("以诚心感化", rewards={"lifespan": 60, "bone": 1, "cultivation": 200}, flavor="灵药被你的诚意打动，你服下后寿元大涨，根骨也有所提升。寿元 +60，根骨 +1，修为 +200"),
                _c("强行采摘", condition=_cond("physique", 8), rewards={"lifespan": 30, "spirit_stones": 200}, flavor="你强行采摘，灵药爆发出强烈的反噬，你受了重伤，但灵药到手，价值连城。寿元 +30，灵石 +200"),
                _c("强行采摘", rewards={"lifespan": -30}, flavor="灵药的反噬远超你的想象，你被弹飞，受了重伤，灵药也消失不见。寿元 -30"),
            ]
        }),
        _c("在灵药旁打坐感应", condition=_cond("comprehension", 7), rewards={"comprehension": 1, "lifespan": 40, "cultivation": 200}, flavor="你在灵药旁感应天地灵气，悟性有所提升，寿元和修为都大幅增长。悟性 +1，寿元 +40，修为 +200"),
        _c("在灵药旁打坐感应", rewards={"lifespan": 25, "cultivation": 120}, flavor="灵药散发的灵气滋养了你，寿元和修为都有所提升。寿元 +25，修为 +120"),
        _c("不去打扰，恭敬离去", rewards={"fortune": 2, "lifespan": 15}, flavor="你恭敬地行礼离去，灵药似乎感受到了你的尊重，散出一缕灵气滋养了你。机缘 +2，寿元 +15"),
    ]
))

EVENTS.append(_e(
    "【稀有】古战场英魂",
    "古战场遗址中，夜幕降临时，无数英魂的残影在空中飘荡，其中一道残影比其他的都要清晰，似乎还保留着意识。",
    [
        _c("与清晰的残影交流", next_event={
            "desc": "残影是一位上古修士，他说自己在此守候了千年，等待一位有缘人，愿意将自己的战斗经验传授给你。",
            "choices": [
                _c("接受战斗经验传授", condition=_cond("comprehension", 7), rewards={"comprehension": 2, "physique": 1, "cultivation": 350}, flavor="上古修士的战斗经验如洪流般涌入你的意识，悟性大幅提升，体魄也得到了锻炼，修为暴涨。悟性 +2，体魄 +1，修为 +350"),
                _c("接受战斗经验传授", rewards={"comprehension": 1, "cultivation": 200}, flavor="你接受了部分战斗经验，悟性有所提升，修为大进。悟性 +1，修为 +200"),
                _c("请求他传授延寿之法", condition=_cond("soul", 7), rewards={"soul": 1, "lifespan": 80, "cultivation": 150}, flavor="上古修士传授了你一门延寿秘法，神识有所提升，寿元大幅增长。神识 +1，寿元 +80，修为 +150"),
                _c("请求他传授延寿之法", rewards={"lifespan": 50, "cultivation": 100}, flavor="上古修士传授了你一些延寿之法，寿元有所增长。寿元 +50，修为 +100"),
            ]
        }),
        _c("在古战场中打坐感悟", condition=_cond("soul", 7), rewards={"soul": 1, "comprehension": 1, "cultivation": 200}, flavor="你从古战场残存的战意中感悟到了一丝天地法则，神识和悟性都有所提升。神识 +1，悟性 +1，修为 +200"),
        _c("收集古战场的遗物", condition=_cond("fortune", 7), rewards={"spirit_stones": 400, "fortune": 1}, flavor="你在古战场中发现了大量上古修士遗留的法器碎片和灵石，价值连城。灵石 +400，机缘 +1"),
        _c("收集古战场的遗物", rewards={"spirit_stones": 200}, flavor="你收集了一些遗物，换了不少灵石。灵石 +200"),
    ]
))

EVENTS.append(_e(
    "【稀有】天机老人",
    "一处偏僻的茶馆中，一位鹤发童颜的老人正在独自品茶，他见到你后，笑道：「老夫等你许久了，坐下来喝杯茶吧。」",
    [
        _c("坐下来喝茶", next_event={
            "desc": "老人为你倒了一杯茶，茶水入喉，你感到一股奇异的暖流遍布全身，思维前所未有地清晰。",
            "choices": [
                _c("请教修炼之道", condition=_cond("comprehension", 7), rewards={"comprehension": 2, "soul": 1, "cultivation": 300, "lifespan": 40}, flavor="老人娓娓道来，你如醍醐灌顶，悟性和神识都大幅提升，修为暴涨，寿元也得到了滋养。悟性 +2，神识 +1，修为 +300，寿元 +40"),
                _c("请教修炼之道", rewards={"comprehension": 1, "cultivation": 200, "lifespan": 25}, flavor="老人传授了你一些修炼心得，悟性有所提升，修为大进，寿元也有所增长。悟性 +1，修为 +200，寿元 +25"),
                _c("请教机缘之道", condition=_cond("fortune", 7), rewards={"fortune": 3, "lifespan": 30}, flavor="老人笑着说了几句话，你若有所悟，机缘大涨，寿元也有所增长。机缘 +3，寿元 +30"),
                _c("请教机缘之道", rewards={"fortune": 2, "lifespan": 20}, flavor="老人传授了你一些把握机缘的方法，机缘有所提升。机缘 +2，寿元 +20"),
            ]
        }),
        _c("婉拒，继续赶路", rewards={"fortune": 1}, flavor="你婉拒了，老人点头，说：「缘分未到，也罢。」机缘 +1"),
        _c("警惕地打量老人", condition=_cond("soul", 8), rewards={"soul": 1, "fortune": 2}, flavor="你以神识感应，发现老人深不可测，你的警惕让他赞赏，神识和机缘都有所提升。神识 +1，机缘 +2"),
        _c("警惕地打量老人", rewards={"fortune": 1}, flavor="你感应不出老人的深浅，机缘略有提升。机缘 +1"),
    ]
))

EVENTS.append(_e(
    "【稀有】灵脉爆发",
    "你所在之处突然地动山摇，脚下的灵脉爆发出前所未有的灵气，金色的光柱冲天而起，方圆百里的修士都能感受到。",
    [
        _c("立刻盘坐，全力吸纳", condition=_cond("comprehension", 8), rewards={"cultivation": 500, "comprehension": 2, "lifespan": 30}, flavor="你抓住千载难逢的时机，全力吸纳灵脉爆发的灵气，修为暴涨，悟性大幅提升，寿元也得到了滋养。修为 +500，悟性 +2，寿元 +30"),
        _c("立刻盘坐，全力吸纳", condition=_cond("comprehension", 6), rewards={"cultivation": 350, "comprehension": 1, "lifespan": 20}, flavor="你吸纳了大量灵气，修为大进，悟性有所提升，寿元也有所增长。修为 +350，悟性 +1，寿元 +20"),
        _c("立刻盘坐，全力吸纳", rewards={"cultivation": 200, "lifespan": -10}, flavor="灵气过于磅礴，你强行吸纳，受了些内伤，但修为也大幅提升。修为 +200，寿元 -10"),
        _c("寻找灵脉核心", condition=_cond("fortune", 8), rewards={"fortune": 3, "spirit_stones": 500, "bone": 1}, flavor="你找到了灵脉爆发的核心，发现了一颗凝聚了灵脉精华的灵晶，机缘暴涨，根骨也得到了蜕变。机缘 +3，灵石 +500，根骨 +1"),
        _c("寻找灵脉核心", rewards={"spirit_stones": 300, "fortune": 1}, flavor="你找到了一些灵脉爆发散落的灵石，收获颇丰。灵石 +300，机缘 +1"),
    ]
))
