from utils.events._base import _e, _c, _cond

EVENTS = []

EVENTS.append(_e(
    "青云宗弟子",
    "路上遇到一名青云宗的外门弟子，他正在外出历练，见到你后主动搭话，说可以切磋一番。",
    [
        _c("接受切磋", next_event={
            "desc": "青云宗弟子御剑而来，剑法凌厉，你需要全力以赴。",
            "choices": [
                _c("以悟性取胜", condition=_cond("comprehension", 7), rewards={"comprehension": 1, "reputation": 25}, flavor="你以精妙的应对化解了对方的剑法，胜出，悟性有所提升。悟性 +1，声望 +25"),
                _c("以悟性取胜", rewards={"lifespan": -5, "cultivation": 50}, flavor="你落败，但从对方的剑法中学到了不少。寿元 -5，修为 +50"),
                _c("以体魄取胜", condition=_cond("physique", 7), rewards={"physique": 1, "reputation": 25}, flavor="你以强横体魄压制了对方的剑法，胜出。体魄 +1，声望 +25"),
                _c("以体魄取胜", rewards={"lifespan": -8}, flavor="对方剑法灵动，你的蛮力被化解，落败受伤。寿元 -8"),
            ]
        }),
        _c("婉拒，只是闲聊", condition=_cond("comprehension", 6), rewards={"comprehension": 1}, flavor="你从闲聊中得知了一些青云宗的修炼心法，悟性有所提升。悟性 +1"),
        _c("婉拒，只是闲聊", rewards={"reputation": 10}, flavor="你结交了一位新朋友，声望略有提升。声望 +10"),
        _c("不理会，继续赶路", rewards={}, flavor="你继续赶路。"),
    ]
))

EVENTS.append(_e(
    "血煞门招募",
    "铁甲城附近，几名血煞门的弟子正在招募新人，说只要能在擂台上撑过三招，就可以加入血煞门。",
    [
        _c("上台应战", next_event={
            "desc": "血煞门弟子出手凶猛，招招致命，毫无保留。",
            "choices": [
                _c("撑过三招", condition=_cond("physique", 7), rewards={"physique": 1, "reputation": 20}, flavor="你撑过了三招，血煞门弟子点头认可，体魄得到了锻炼。体魄 +1，声望 +20"),
                _c("撑过三招", rewards={"lifespan": -10, "reputation": 10}, flavor="你没能撑过三招，受了重伤，但打出了风采。寿元 -10，声望 +10"),
                _c("主动反击，争取胜出", condition=_cond("physique", 9), rewards={"physique": 1, "reputation": 40}, flavor="你不仅撑过了三招，还反败为胜，血煞门弟子刮目相看。体魄 +1，声望 +40"),
                _c("主动反击，争取胜出", rewards={"lifespan": -15}, flavor="血煞门弟子实力远超你，你惨败，受了重伤。寿元 -15"),
            ]
        }),
        _c("在旁观看，不参与", condition=_cond("comprehension", 6), rewards={"cultivation": 60, "comprehension": 1}, flavor="你从比试中学到了一些血煞门的战斗技巧。修为 +60，悟性 +1"),
        _c("在旁观看，不参与", rewards={"cultivation": 30}, flavor="你观摩了一番，略有收获。修为 +30"),
        _c("不感兴趣，离开", rewards={}, flavor="你继续赶路。"),
    ]
))

EVENTS.append(_e(
    "灵药宗采药任务",
    "丹霞谷附近，一名灵药宗的弟子说他的采药任务还差几株灵草，愿意出价购买，或者请你帮忙采摘。",
    [
        _c("帮忙采摘灵草", next_event={
            "desc": "灵草生长在山壁上，需要攀爬才能采到，弟子说采到后可以分你一半报酬。",
            "choices": [
                _c("攀爬采摘", condition=_cond("physique", 6), rewards={"spirit_stones": 80, "reputation": 15}, flavor="你成功采到了灵草，与弟子平分了报酬，声望略有提升。灵石 +80，声望 +15"),
                _c("攀爬采摘", rewards={"lifespan": -4, "spirit_stones": 40}, flavor="你受了些轻伤，但也采到了灵草，分到了部分报酬。寿元 -4，灵石 +40"),
                _c("以神识感应灵草位置", condition=_cond("soul", 6), rewards={"spirit_stones": 90, "soul": 1}, flavor="你以神识感应到了更多灵草的位置，收获更丰。灵石 +90，神识 +1"),
                _c("以神识感应灵草位置", rewards={"spirit_stones": 60}, flavor="你感应到了灵草位置，顺利采摘。灵石 +60"),
            ]
        }),
        _c("出售自己采到的灵草", condition=_cond("fortune", 6), rewards={"spirit_stones": 100}, flavor="你恰好有几株灵草，以好价钱卖给了弟子。灵石 +100"),
        _c("出售自己采到的灵草", rewards={"spirit_stones": 60}, flavor="你卖出了灵草，价格一般。灵石 +60"),
        _c("不感兴趣，离开", rewards={}, flavor="你继续赶路。"),
    ]
))

EVENTS.append(_e(
    "鬼修宗阴修",
    "幽冥镇附近的荒野中，一名鬼修宗的弟子正在修炼，他察觉到你的存在后，主动说可以传授你一门阴属辅助功法。",
    [
        _c("接受传授", next_event={
            "desc": "阴修说这门功法可以增强神识，但修炼时需要在阴气充沛的地方，否则效果减半。",
            "choices": [
                _c("立刻在此修炼", condition=_cond("soul", 7), rewards={"soul": 1, "cultivation": 80}, flavor="幽冥镇附近阴气充沛，你立刻修炼，神识大进。神识 +1，修为 +80"),
                _c("立刻在此修炼", rewards={"soul": 1, "lifespan": -3}, flavor="阴气侵体，你受了些轻伤，但神识也有所提升。神识 +1，寿元 -3"),
                _c("带走功法，日后再修炼", rewards={"cultivation": 40}, flavor="你将功法记下，日后再修炼，略有收获。修为 +40"),
            ]
        }),
        _c("拒绝，阴属功法不适合自己", rewards={}, flavor="你婉拒了，继续赶路。"),
        _c("试探对方的实力", condition=_cond("physique", 7), rewards={"physique": 1, "reputation": 15}, flavor="你与阴修切磋了一番，体魄得到了锻炼，声望略有提升。体魄 +1，声望 +15"),
        _c("试探对方的实力", rewards={"lifespan": -8}, flavor="阴修的摄魂术让你吃了大亏，受了不轻的伤。寿元 -8"),
    ]
))

EVENTS.append(_e(
    "合欢宗弟子邀约",
    "望月楼附近，一名合欢宗的弟子主动搭话，态度亲切，说合欢宗欢迎有缘人前往参观。",
    [
        _c("接受邀请，前往参观", next_event={
            "desc": "合欢宗的驻地布置得极为雅致，弟子说宗门的双修功法天下无双，但需要机缘足够才能修炼。",
            "choices": [
                _c("打听双修功法", condition=_cond("fortune", 7), rewards={"fortune": 1, "cultivation": 60}, flavor="你从弟子口中得知了一些双修功法的皮毛，机缘和修为都有所提升。机缘 +1，修为 +60"),
                _c("打听双修功法", rewards={"cultivation": 30}, flavor="弟子说得含糊，你只了解了些皮毛。修为 +30"),
                _c("只是参观，不打听", rewards={"reputation": 10, "fortune": 1}, flavor="你礼貌地参观了一番，声望和机缘略有提升。声望 +10，机缘 +1"),
            ]
        }),
        _c("婉拒，继续赶路", rewards={}, flavor="你婉拒了，继续赶路。"),
        _c("打听合欢宗的入门要求", condition=_cond("fortune", 6), rewards={"fortune": 1}, flavor="你从弟子口中得知了入门要求，机缘略有提升。机缘 +1"),
        _c("打听合欢宗的入门要求", rewards={}, flavor="弟子说得含糊，你没打听到什么有用的消息。"),
    ]
))

EVENTS.append(_e(
    "魔焰教火修",
    "赤炎城附近，一名魔焰教的弟子正在修炼，火焰在他周围燃烧，灵气波动极为强烈。",
    [
        _c("上前观摩", next_event={
            "desc": "火修察觉到你的存在，停下修炼，打量了你一番，说可以让你感受一下魔焰功法的威力。",
            "choices": [
                _c("接受感受", condition=_cond("physique", 7), rewards={"physique": 1, "cultivation": 70}, flavor="你以强横体魄抵御了魔焰的冲击，体魄得到了锻炼，修为也有所提升。体魄 +1，修为 +70"),
                _c("接受感受", rewards={"lifespan": -8}, flavor="魔焰威力极强，你受了不轻的灼伤。寿元 -8"),
                _c("只是观摩，不接受", condition=_cond("comprehension", 6), rewards={"comprehension": 1, "cultivation": 50}, flavor="你从观摩中悟出了一丝火道真意，悟性有所提升。悟性 +1，修为 +50"),
                _c("只是观摩，不接受", rewards={"cultivation": 30}, flavor="你观摩了一番，略有收获。修为 +30"),
            ]
        }),
        _c("不理会，继续赶路", rewards={}, flavor="你继续赶路。"),
    ]
))

EVENTS.append(_e(
    "玄冰派冰修",
    "寒冰城附近，一名玄冰派的弟子正在修炼，冰晶在他周围飞舞，寒气逼人。",
    [
        _c("上前切磋", next_event={
            "desc": "冰修见你主动上前，点头应战，冰属灵气护体，防御极强。",
            "choices": [
                _c("以火属攻击破冰", condition=_cond("physique", 7), rewards={"physique": 1, "reputation": 20}, flavor="你找到了破解冰属防御的方法，胜出，体魄得到了锻炼。体魄 +1，声望 +20"),
                _c("以火属攻击破冰", rewards={"lifespan": -6, "cultivation": 50}, flavor="你落败，但从对方的冰属功法中学到了不少。寿元 -6，修为 +50"),
                _c("以速度周旋", condition=_cond("comprehension", 7), rewards={"comprehension": 1, "reputation": 20}, flavor="你以灵动的身法周旋，找到了冰修的破绽，胜出。悟性 +1，声望 +20"),
                _c("以速度周旋", rewards={"lifespan": -5, "cultivation": 40}, flavor="冰修的冰甲防御极强，你的攻击难以奏效，落败。寿元 -5，修为 +40"),
            ]
        }),
        _c("在旁感应冰灵气", condition=_cond("soul", 6), rewards={"soul": 1, "cultivation": 50}, flavor="你感应了冰修散发的冰灵气，神识有所提升。神识 +1，修为 +50"),
        _c("不感兴趣，离开", rewards={}, flavor="你继续赶路。"),
    ]
))

EVENTS.append(_e(
    "御剑阁考核",
    "御剑阁在各地设有考核点，今日恰好路过，考核官说只要悟性足够，可以参加入阁考核。",
    [
        _c("参加考核", next_event={
            "desc": "考核内容是感悟一块刻有剑意的玉简，考核官说感悟越深，评价越高。",
            "choices": [
                _c("全力感悟", condition=_cond("comprehension", 8), rewards={"comprehension": 1, "soul": 1, "reputation": 40}, flavor="你从玉简中感悟到了极深的剑意，考核官大喜，悟性和神识都大幅提升。悟性 +1，神识 +1，声望 +40"),
                _c("全力感悟", condition=_cond("comprehension", 6), rewards={"comprehension": 1, "reputation": 20}, flavor="你从玉简中有所感悟，考核官点头认可。悟性 +1，声望 +20"),
                _c("全力感悟", rewards={"cultivation": 30}, flavor="你感悟有限，考核官摇头，但你也略有收获。修为 +30"),
            ]
        }),
        _c("不参加，只是旁观", condition=_cond("comprehension", 6), rewards={"comprehension": 1, "cultivation": 40}, flavor="你从旁观中感悟到了一丝剑意，悟性有所提升。悟性 +1，修为 +40"),
        _c("不参加，只是旁观", rewards={"cultivation": 20}, flavor="你旁观了一番，略有收获。修为 +20"),
        _c("不感兴趣，离开", rewards={}, flavor="你继续赶路。"),
    ]
))

EVENTS.append(_e(
    "噬魂阁神识修士",
    "幽冥海附近，一名噬魂阁的弟子正在修炼神识，他的神识波动极为强烈，让附近的修士都感到不适。",
    [
        _c("上前询问神识修炼之法", next_event={
            "desc": "噬魂阁弟子打量了你一番，说可以传授你一门神识感应之法，但需要你以一百灵石作为交换。",
            "choices": [
                _c("支付灵石，学习功法", condition=_cond("soul", 7), rewards={"spirit_stones": -100, "soul": 1, "cultivation": 80}, flavor="你学到了神识感应之法，神识大进，修为也有所提升。灵石 -100，神识 +1，修为 +80"),
                _c("支付灵石，学习功法", rewards={"spirit_stones": -100, "soul": 1}, flavor="你学到了神识感应之法，神识略有提升。灵石 -100，神识 +1"),
                _c("拒绝，太贵了", rewards={}, flavor="你婉拒了，继续赶路。"),
            ]
        }),
        _c("远远感应他的神识波动", condition=_cond("soul", 6), rewards={"soul": 1, "cultivation": 50}, flavor="你感应了噬魂阁弟子的神识波动，神识有所提升。神识 +1，修为 +50"),
        _c("远远感应他的神识波动", rewards={"lifespan": -3}, flavor="神识波动过于强烈，你受了些轻伤。寿元 -3"),
        _c("不理会，继续赶路", rewards={}, flavor="你继续赶路。"),
    ]
))

EVENTS.append(_e(
    "天玄门巡逻队",
    "天京城附近，天玄门的巡逻队正在例行巡逻，队长见到你后，说最近有邪修在附近活动，询问你是否见过可疑人物。",
    [
        _c("如实回答，提供线索", condition=_cond("fortune", 6), rewards={"reputation": 30, "fortune": 1}, flavor="你提供的线索帮助巡逻队找到了邪修，队长感谢你，声望大涨。声望 +30，机缘 +1"),
        _c("如实回答，提供线索", rewards={"reputation": 15}, flavor="你提供了一些线索，队长道谢，声望略有提升。声望 +15"),
        _c("说没见过，不想惹麻烦", rewards={}, flavor="你撒了个谎，巡逻队离去，你继续赶路。"),
        _c("主动协助巡逻", condition=_cond("physique", 7), rewards={"reputation": 40, "spirit_stones": 80}, flavor="你协助巡逻队找到并击败了邪修，获得了丰厚报酬，声望大涨。声望 +40，灵石 +80"),
        _c("主动协助巡逻", rewards={"lifespan": -5, "reputation": 20}, flavor="你协助巡逻，遭遇了邪修，受了些轻伤，但也赢得了认可。寿元 -5，声望 +20"),
    ]
))
