from utils.events._base import _e, _c, _cond

EVENTS = []

EVENTS.append(_e(
    "海族商人",
    "碧波城附近的海岸边，一名海族商人正在摆摊，出售各种来自深海的奇异灵材，散发着浓郁的水灵气。",
    [
        _c("上前询价", next_event={
            "desc": "商人报出价格：一颗深海灵珠五十灵石，据说对水属灵根修士大有裨益。",
            "choices": [
                _c("购买深海灵珠", condition=_cond("fortune", 6), rewards={"spirit_stones": -50, "bone": 1, "lifespan": 10}, flavor="灵珠品质极佳，服下后根骨和寿元都有所提升。灵石 -50，根骨 +1，寿元 +10"),
                _c("购买深海灵珠", rewards={"spirit_stones": -50, "lifespan": 8}, flavor="普通品质的灵珠，略有补益。灵石 -50，寿元 +8"),
                _c("讨价还价", condition=_cond("comprehension", 6), rewards={"spirit_stones": -30, "cultivation": 60}, flavor="你以三十灵石买到了一颗修炼用的海底灵石。灵石 -30，修为 +60"),
                _c("讨价还价", rewards={}, flavor="商人不为所动，你只好作罢。"),
            ]
        }),
        _c("在海边打坐，感受水灵气", condition=_cond("soul", 6), rewards={"cultivation": 80, "soul": 1}, flavor="东域水灵气充沛，你借此深入修炼，神识有所提升。修为 +80，神识 +1"),
        _c("在海边打坐，感受水灵气", rewards={"cultivation": 40}, flavor="水灵气辅助修炼，有些收获。修为 +40"),
        _c("离开，不感兴趣", rewards={}, flavor="你继续赶路。"),
    ]
))

EVENTS.append(_e(
    "炼器坊争执",
    "青云坊的一家铸造坊门口，一名修士正与坊主争执，说自己定制的法器有瑕疵，坊主却不肯退换。",
    [
        _c("上前调解", next_event={
            "desc": "坊主见你出面，态度软化了些，说可以给那名修士打折重铸，但需要有人作保。",
            "choices": [
                _c("愿意作保", condition=_cond("reputation", 20), rewards={"reputation": 25, "spirit_stones": 50}, flavor="坊主感谢你的信誉担保，事后送了你一件小法器作为答谢。声望 +25，灵石 +50"),
                _c("愿意作保", rewards={"reputation": 15}, flavor="事情顺利解决，你的声望略有提升。声望 +15"),
                _c("建议修士另寻他处", rewards={"reputation": 5}, flavor="修士道谢后离去，你也继续赶路。声望 +5"),
            ]
        }),
        _c("趁乱打听坊主的炼器秘法", condition=_cond("comprehension", 7), rewards={"comprehension": 1, "cultivation": 50}, flavor="你从争执中旁听到了一些炼器心得，悟性有所提升。悟性 +1，修为 +50"),
        _c("不理会，继续赶路", rewards={}, flavor="你绕开人群，继续赶路。"),
    ]
))

EVENTS.append(_e(
    "御剑比试",
    "玄风城的广场上，几名剑修正在进行御剑比试，围观者众多，擂主正在招募挑战者。",
    [
        _c("上台挑战", next_event={
            "desc": "擂主是一名炼气期后期的剑修，剑法凌厉，你需要全力以赴。",
            "choices": [
                _c("以速度取胜", condition=_cond("comprehension", 7), rewards={"spirit_stones": 100, "reputation": 30, "comprehension": 1}, flavor="你以精妙的剑法胜出，赢得彩头，声望大涨。灵石 +100，声望 +30，悟性 +1"),
                _c("以速度取胜", rewards={"lifespan": -5, "reputation": 10}, flavor="你落败，但打出了风采，围观者给予掌声。寿元 -5，声望 +10"),
                _c("以力量取胜", condition=_cond("physique", 7), rewards={"spirit_stones": 100, "reputation": 30, "physique": 1}, flavor="你以强横体魄压制对手，胜出。灵石 +100，声望 +30，体魄 +1"),
                _c("以力量取胜", rewards={"lifespan": -8}, flavor="对手剑法灵动，你的蛮力被化解，落败受伤。寿元 -8"),
            ]
        }),
        _c("在旁观看，学习剑法", condition=_cond("comprehension", 6), rewards={"cultivation": 70, "comprehension": 1}, flavor="你从比试中悟出了一丝剑意，受益匪浅。修为 +70，悟性 +1"),
        _c("在旁观看，学习剑法", rewards={"cultivation": 30}, flavor="你观摩了一番，略有收获。修为 +30"),
        _c("不感兴趣，离开", rewards={}, flavor="你对剑道不感兴趣，继续赶路。"),
    ]
))

EVENTS.append(_e(
    "灵石交易所风波",
    "落云城的灵石交易所内，有人高声叫嚷说自己买到了假灵石，现场一片混乱，交易所掌柜正在焦头烂额。",
    [
        _c("帮掌柜维持秩序", next_event={
            "desc": "你协助掌柜平息了骚乱，掌柜感激地说可以给你一个内部优惠价。",
            "choices": [
                _c("购买灵石（八折）", condition=_cond("fortune", 6), rewards={"spirit_stones": 80, "reputation": 20}, flavor="你以优惠价购入了一批品质不错的灵石，还赚了差价。灵石 +80，声望 +20"),
                _c("购买灵石（八折）", rewards={"spirit_stones": 40, "reputation": 20}, flavor="你购入了一批普通灵石，声望略有提升。灵石 +40，声望 +20"),
                _c("婉拒，只是举手之劳", rewards={"reputation": 30, "fortune": 1}, flavor="掌柜感动不已，说日后有需要尽管来找他。声望 +30，机缘 +1"),
            ]
        }),
        _c("趁乱低价收购灵石", condition=_cond("fortune", 7), rewards={"spirit_stones": 100}, flavor="你趁乱以极低价格收购了一批灵石，大赚一笔。灵石 +100"),
        _c("趁乱低价收购灵石", rewards={"spirit_stones": 30, "reputation": -10}, flavor="你的行为被人看见，名声略有影响。灵石 +30，声望 -10"),
        _c("离开，不想卷入", rewards={}, flavor="你绕开混乱，继续赶路。"),
    ]
))

EVENTS.append(_e(
    "天水镇水灵泉",
    "天水镇郊外，一处天然水灵泉正在涌动，灵气充沛，附近的修士都在排队等候汲取泉水。",
    [
        _c("排队等候汲取", next_event={
            "desc": "轮到你时，泉水突然涌出一股异常浓郁的灵气，似乎今日灵泉有所异动。",
            "choices": [
                _c("直接浸泡双手感应", condition=_cond("soul", 7), rewards={"soul": 1, "cultivation": 100}, flavor="你感应到了水灵泉深处的一丝天地法则，神识大进。神识 +1，修为 +100"),
                _c("直接浸泡双手感应", rewards={"cultivation": 60, "lifespan": 10}, flavor="灵泉滋养，修为和寿元都有所提升。修为 +60，寿元 +10"),
                _c("取水装入水囊", rewards={"spirit_stones": 70}, flavor="天水镇的灵泉水在市集上颇受欢迎。灵石 +70"),
            ]
        }),
        _c("不排队，在泉边打坐感应", condition=_cond("comprehension", 6), rewards={"comprehension": 1, "cultivation": 50}, flavor="你在泉边感应水灵气，悟出了一丝水道真意。悟性 +1，修为 +50"),
        _c("不排队，在泉边打坐感应", rewards={"cultivation": 30}, flavor="水灵气辅助修炼，略有收获。修为 +30"),
        _c("离开，不感兴趣", rewards={}, flavor="你继续赶路。"),
    ]
))

EVENTS.append(_e(
    "东域剑会邀请",
    "路上遇到一名信使，说东域每三年一届的剑会即将在玄风城举办，邀请有缘修士参与观摩。",
    [
        _c("前往观摩", next_event={
            "desc": "剑会上高手云集，各种剑法令人眼花缭乱，你在人群中观摩，感悟颇多。",
            "choices": [
                _c("专注感悟剑意", condition=_cond("comprehension", 7), rewards={"comprehension": 1, "cultivation": 80}, flavor="你从众多剑修的演示中悟出了一丝剑道真意。悟性 +1，修为 +80"),
                _c("专注感悟剑意", rewards={"cultivation": 50}, flavor="你观摩了许多剑法，修为有所提升。修为 +50"),
                _c("结交剑修朋友", condition=_cond("fortune", 6), rewards={"reputation": 30, "fortune": 1}, flavor="你结交了几位志同道合的剑修，声望大涨。声望 +30，机缘 +1"),
                _c("结交剑修朋友", rewards={"reputation": 15}, flavor="你结交了几位新朋友。声望 +15"),
            ]
        }),
        _c("婉拒，继续赶路", rewards={}, flavor="你婉拒了邀请，继续赶路。"),
        _c("打听剑会的奖品", condition=_cond("fortune", 6), rewards={"spirit_stones": 60}, flavor="你从打听中得知了一个内幕，提前布局赚了一笔。灵石 +60"),
        _c("打听剑会的奖品", rewards={}, flavor="你没打听到什么有用的消息。"),
    ]
))

EVENTS.append(_e(
    "碧波城海妖袭击",
    "碧波城附近的海岸突然传来警报，一只海妖趁涨潮之际上岸，正在袭击渔村，城中修士纷纷出动。",
    [
        _c("加入讨伐队伍", next_event={
            "desc": "海妖体型庞大，水属灵气护体，普通攻击难以奏效，队伍正在商讨对策。",
            "choices": [
                _c("以火属攻击破其水盾", condition=_cond("physique", 7), rewards={"spirit_stones": 120, "reputation": 40, "physique": 1}, flavor="你的攻击破开了海妖的防御，讨伐成功，获得丰厚赏金。灵石 +120，声望 +40，体魄 +1"),
                _c("以火属攻击破其水盾", rewards={"lifespan": -10, "spirit_stones": 50, "reputation": 20}, flavor="你受了伤，但也出了力，获得部分赏金。寿元 -10，灵石 +50，声望 +20"),
                _c("绕后偷袭要害", condition=_cond("fortune", 7), rewards={"spirit_stones": 150, "reputation": 50}, flavor="你找准时机一击致命，成为此战最大功臣。灵石 +150，声望 +50"),
                _c("绕后偷袭要害", rewards={"lifespan": -8, "reputation": 15}, flavor="海妖察觉了你的意图，你受伤撤退。寿元 -8，声望 +15"),
            ]
        }),
        _c("在远处观战，不参与", condition=_cond("comprehension", 6), rewards={"cultivation": 60}, flavor="你从旁观战中学到了对付水属妖兽的技巧。修为 +60"),
        _c("在远处观战，不参与", rewards={"cultivation": 30}, flavor="你观摩了一番，略有收获。修为 +30"),
        _c("趁乱去渔村捡漏", condition=_cond("fortune", 7), rewards={"spirit_stones": 80}, flavor="你在混乱中捡到了海妖遗落的几颗妖丹。灵石 +80"),
        _c("趁乱去渔村捡漏", rewards={"reputation": -10}, flavor="你的行为被人看见，名声受损。声望 -10"),
    ]
))

EVENTS.append(_e(
    "落云城拍卖内幕",
    "一名神色慌张的修士悄悄拉住你，说他有一份落云城大拍卖的内幕消息，愿意以二十灵石出售。",
    [
        _c("购买消息", next_event={
            "desc": "消息说今日拍卖有一件被低估的宝物，起拍价极低，但识货者寥寥。",
            "choices": [
                _c("按消息出手竞拍", condition=_cond("fortune", 7), rewards={"spirit_stones": -20, "fortune": 2, "bone": 1}, flavor="消息属实，你以低价拍得了一件极品宝物。灵石 -20，机缘 +2，根骨 +1"),
                _c("按消息出手竞拍", rewards={"spirit_stones": -70, "cultivation": 80}, flavor="消息有些偏差，但你还是拍到了一件不错的修炼丹药。灵石 -70，修为 +80"),
                _c("放弃竞拍，转卖消息", condition=_cond("comprehension", 6), rewards={"spirit_stones": 60}, flavor="你将消息转卖给另一名修士，赚了差价。灵石 +60"),
            ]
        }),
        _c("拒绝，可能是骗局", rewards={}, flavor="你拒绝了，继续赶路。"),
        _c("威胁他免费说出消息", condition=_cond("physique", 7), rewards={"spirit_stones": 0, "fortune": -1}, flavor="他被你吓到，说出了消息，但你感觉此举有损机缘。机缘 -1"),
        _c("威胁他免费说出消息", rewards={"lifespan": -3}, flavor="他大喊有人劫道，你狼狈逃脱。寿元 -3"),
    ]
))

EVENTS.append(_e(
    "青云坊法器鉴定",
    "青云坊的一家鉴定铺子门口，一名老修士正在为人鉴定一件古旧法器，围观者众多，争论不休。",
    [
        _c("上前参与讨论", next_event={
            "desc": "老修士见你有兴趣，邀请你也来鉴定一番，说若鉴定准确可以免费学一门鉴定之法。",
            "choices": [
                _c("尝试鉴定", condition=_cond("soul", 7), rewards={"soul": 1, "comprehension": 1}, flavor="你准确鉴定出了法器的品阶和来历，老修士赞叹不已，传授了你鉴定心法。神识 +1，悟性 +1"),
                _c("尝试鉴定", rewards={"cultivation": 40}, flavor="你鉴定有误，但从老修士的讲解中学到了不少。修为 +40"),
                _c("只是旁听", condition=_cond("comprehension", 6), rewards={"comprehension": 1}, flavor="你从旁听中悟出了一些鉴定之道。悟性 +1"),
                _c("只是旁听", rewards={"cultivation": 20}, flavor="你旁听了一番，略有收获。修为 +20"),
            ]
        }),
        _c("趁人不注意，偷偷感应法器", condition=_cond("soul", 6), rewards={"soul": 1}, flavor="你悄悄感应了法器，神识有所提升。神识 +1"),
        _c("不感兴趣，离开", rewards={}, flavor="你继续赶路。"),
    ]
))

EVENTS.append(_e(
    "东域灵脉涌动",
    "东域近日灵脉异动，天地间灵气比平时浓郁数倍，许多修士都在抓紧时机修炼。",
    [
        _c("立刻就地修炼", condition=_cond("comprehension", 7), rewards={"cultivation": 150, "comprehension": 1}, flavor="你抓住灵脉涌动的时机，修为大进，还悟出了一丝天地之道。修为 +150，悟性 +1"),
        _c("立刻就地修炼", rewards={"cultivation": 100}, flavor="你借助浓郁灵气修炼，收获颇丰。修为 +100"),
        _c("寻找灵脉源头", condition=_cond("fortune", 7), rewards={"fortune": 1, "spirit_stones": 120}, flavor="你找到了灵脉涌动的源头，发现了一处小型灵石矿脉。机缘 +1，灵石 +120"),
        _c("寻找灵脉源头", rewards={"lifespan": -3, "cultivation": 50}, flavor="你在寻找途中耗费了不少精力，但也借助灵气修炼了一番。寿元 -3，修为 +50"),
        _c("不理会，继续赶路", rewards={}, flavor="你没有停留，继续赶路。"),
    ]
))
