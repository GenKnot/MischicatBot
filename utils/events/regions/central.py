from utils.events._base import _e, _c, _cond

EVENTS = []

EVENTS.append(_e(
    "天京城宗门招募",
    "天京城的广场上，天玄门正在举行公开招募，考核内容是当场展示修炼成果，通过者可获得一件入门礼物。",
    [
        _c("参加考核", next_event={
            "desc": "考核官让你展示修炼成果，并回答几个关于修炼心法的问题。",
            "choices": [
                _c("认真作答，展示实力", condition=_cond("comprehension", 7), rewards={"reputation": 40, "cultivation": 80, "comprehension": 1}, flavor="你表现出色，考核官赞叹不已，声望大涨。声望 +40，修为 +80，悟性 +1"),
                _c("认真作答，展示实力", rewards={"reputation": 20, "cultivation": 50}, flavor="你表现还不错，获得了一些认可。声望 +20，修为 +50"),
                _c("随便应付，不想加入", rewards={"reputation": -5}, flavor="考核官摇头，你的表现让人失望。声望 -5"),
            ]
        }),
        _c("在旁观看，不参加", condition=_cond("comprehension", 6), rewards={"cultivation": 50, "comprehension": 1}, flavor="你从考核中学到了一些修炼技巧，悟性有所提升。修为 +50，悟性 +1"),
        _c("在旁观看，不参加", rewards={"cultivation": 30}, flavor="你观摩了一番，略有收获。修为 +30"),
        _c("不感兴趣，离开", rewards={}, flavor="你继续赶路。"),
    ]
))

EVENTS.append(_e(
    "万宝楼大拍卖",
    "万宝楼今日举行月度大拍卖，据说有一件来历不明的上古法器将在今日拍出，吸引了无数修士前来。",
    [
        _c("进场参与竞拍", next_event={
            "desc": "上古法器起拍价五百灵石，竞拍者众多，价格不断攀升。",
            "choices": [
                _c("出价五百灵石", condition=_cond("fortune", 8), rewards={"spirit_stones": -500, "fortune": 3, "bone": 1}, flavor="你以起拍价拍得，法器品质极佳，机缘和根骨都大幅提升。灵石 -500，机缘 +3，根骨 +1"),
                _c("出价五百灵石", rewards={"spirit_stones": -500, "cultivation": 150}, flavor="法器是一件修炼辅助器，修为大进。灵石 -500，修为 +150"),
                _c("放弃竞拍，观望其他拍品", condition=_cond("fortune", 6), rewards={"spirit_stones": 100, "fortune": 1}, flavor="你在其他拍品中发现了一件被低估的宝物，低价拍得后转手大赚。灵石 +100，机缘 +1"),
                _c("放弃竞拍，观望其他拍品", rewards={"spirit_stones": 40}, flavor="你拍到了一件普通的修炼丹药，物有所值。灵石 +40"),
            ]
        }),
        _c("在拍卖会外打听消息", condition=_cond("comprehension", 6), rewards={"spirit_stones": 80, "comprehension": 1}, flavor="你从知情者口中得知了一个内幕，提前布局赚了一笔。灵石 +80，悟性 +1"),
        _c("在拍卖会外打听消息", rewards={}, flavor="你没打听到什么有用的消息。"),
        _c("不感兴趣，离开", rewards={}, flavor="你继续赶路。"),
    ]
))

EVENTS.append(_e(
    "灵虚城政治风波",
    "灵虚城近日各大势力暗流涌动，街头巷尾都在议论某个大宗门的内部纷争，消息真假难辨。",
    [
        _c("打听详情", next_event={
            "desc": "你从一名知情者口中得知，某宗门的两位长老正在争夺掌门之位，双方都在拉拢外部势力。",
            "choices": [
                _c("支持其中一方，收取报酬", condition=_cond("fortune", 7), rewards={"spirit_stones": 150, "reputation": 20, "fortune": 1}, flavor="你支持的一方最终胜出，你获得了丰厚报酬，机缘也有所提升。灵石 +150，声望 +20，机缘 +1"),
                _c("支持其中一方，收取报酬", rewards={"spirit_stones": 80, "reputation": -20}, flavor="你支持的一方落败，你只拿到了部分报酬，名声也受损。灵石 +80，声望 -20"),
                _c("置身事外，不参与", rewards={"reputation": 10}, flavor="你明智地置身事外，声望略有提升。声望 +10"),
            ]
        }),
        _c("不理会，继续赶路", rewards={}, flavor="你继续赶路。"),
        _c("将消息出售给情报商", condition=_cond("comprehension", 6), rewards={"spirit_stones": 60}, flavor="你将打听到的消息卖给了情报商，赚了一笔。灵石 +60"),
        _c("将消息出售给情报商", rewards={"spirit_stones": 20}, flavor="情报商说这消息他早就知道了，只给了你一点辛苦费。灵石 +20"),
    ]
))

EVENTS.append(_e(
    "清虚城道观论道",
    "清虚城的一座古老道观正在举行论道大会，各路修士齐聚一堂，探讨修炼之道，旁听者免费。",
    [
        _c("进入道观旁听", next_event={
            "desc": "论道进行到精彩处，一位老道长提出了一个关于修炼瓶颈的问题，邀请在场修士作答。",
            "choices": [
                _c("上前作答", condition=_cond("comprehension", 8), rewards={"comprehension": 1, "soul": 1, "reputation": 30}, flavor="你的回答令老道长赞叹，众人刮目相看，悟性和神识都有所提升。悟性 +1，神识 +1，声望 +30"),
                _c("上前作答", rewards={"comprehension": 1, "reputation": 15}, flavor="你的回答有些见地，获得了一些认可。悟性 +1，声望 +15"),
                _c("只是旁听，不发言", condition=_cond("comprehension", 6), rewards={"comprehension": 1, "cultivation": 60}, flavor="你从论道中悟出了一丝修炼之道，悟性有所提升。悟性 +1，修为 +60"),
                _c("只是旁听，不发言", rewards={"cultivation": 40}, flavor="你旁听了一番，略有收获。修为 +40"),
            ]
        }),
        _c("在道观外打坐感应道韵", condition=_cond("soul", 6), rewards={"soul": 1, "cultivation": 50}, flavor="道观中散发的道韵辅助你修炼，神识有所提升。神识 +1，修为 +50"),
        _c("不感兴趣，离开", rewards={}, flavor="你继续赶路。"),
    ]
))

EVENTS.append(_e(
    "御剑城飞剑传说",
    "御剑城城头悬挂着一柄无主飞剑，据说是开城祖师留下的，至今无人能够认主，城中修士都在尝试。",
    [
        _c("尝试认主飞剑", next_event={
            "desc": "你将灵力注入飞剑，飞剑微微颤动，似乎在感应你的资质。",
            "choices": [
                _c("全力注入灵力", condition=_cond("comprehension", 9), rewards={"comprehension": 1, "fortune": 2, "cultivation": 100}, flavor="飞剑与你产生了共鸣，虽然没有认主，但你从中感悟到了极深的剑道真意。悟性 +1，机缘 +2，修为 +100"),
                _c("全力注入灵力", condition=_cond("comprehension", 7), rewards={"comprehension": 1, "cultivation": 60}, flavor="飞剑有所回应，你从中感悟到了一丝剑道真意。悟性 +1，修为 +60"),
                _c("全力注入灵力", rewards={"cultivation": 30}, flavor="飞剑没有回应，但你从尝试中略有收获。修为 +30"),
            ]
        }),
        _c("在旁观看他人尝试", condition=_cond("comprehension", 6), rewards={"comprehension": 1, "cultivation": 50}, flavor="你从他人的尝试中悟出了一丝剑道真意。悟性 +1，修为 +50"),
        _c("在旁观看他人尝试", rewards={"cultivation": 30}, flavor="你观摩了一番，略有收获。修为 +30"),
        _c("不感兴趣，离开", rewards={}, flavor="你继续赶路。"),
    ]
))

EVENTS.append(_e(
    "问道城修仙大会",
    "问道城一年一度的修仙大会今日开幕，各路散修齐聚，交流修炼心得，还有各种灵材和法器的交易。",
    [
        _c("参与交流，分享心得", condition=_cond("comprehension", 7), rewards={"comprehension": 1, "reputation": 30, "cultivation": 70}, flavor="你的心得引发了众多修士的共鸣，声望大涨，悟性也有所提升。悟性 +1，声望 +30，修为 +70"),
        _c("参与交流，分享心得", rewards={"reputation": 15, "cultivation": 40}, flavor="你分享了一些心得，获得了一些认可。声望 +15，修为 +40"),
        _c("在市集上淘宝", condition=_cond("fortune", 7), rewards={"fortune": 1, "spirit_stones": 120}, flavor="你在市集上发现了一件被低估的宝物，低价买入后大赚一笔。机缘 +1，灵石 +120"),
        _c("在市集上淘宝", rewards={"spirit_stones": 50}, flavor="你在市集上买到了一些实用的灵材，物有所值。灵石 +50"),
        _c("只是旁听，不参与", rewards={"cultivation": 40}, flavor="你旁听了一番，略有收获。修为 +40"),
    ]
))

EVENTS.append(_e(
    "紫霄城灵气漩涡",
    "紫霄城中心突然出现了一个灵气漩涡，紫色灵气从四面八方汇聚，这是极为罕见的天地异象。",
    [
        _c("冲入漩涡中心修炼", condition=_cond("physique", 8), rewards={"cultivation": 200, "physique": 1, "comprehension": 1}, flavor="你以强横体魄抵御了灵气冲击，在漩涡中心修炼，修为大进。修为 +200，体魄 +1，悟性 +1"),
        _c("冲入漩涡中心修炼", rewards={"cultivation": 100, "lifespan": -10}, flavor="灵气冲击过于强烈，你受了内伤，但修为也大幅提升。修为 +100，寿元 -10"),
        _c("在漩涡边缘修炼", condition=_cond("comprehension", 7), rewards={"cultivation": 120, "comprehension": 1}, flavor="你在漩涡边缘感悟灵气，修为大进，还悟出了一丝天地之道。修为 +120，悟性 +1"),
        _c("在漩涡边缘修炼", rewards={"cultivation": 80}, flavor="漩涡边缘的灵气辅助修炼，收获颇丰。修为 +80"),
        _c("远远观望，不靠近", rewards={"cultivation": 30}, flavor="你在远处感应了一番，略有收获。修为 +30"),
    ]
))

EVENTS.append(_e(
    "归元镇初入中州",
    "归元镇是中州的门户，许多初入中州的修士都会在此歇脚，镇上的老修士们乐于为新来者指点迷津。",
    [
        _c("向老修士请教", next_event={
            "desc": "一位白发老修士见你初来乍到，主动搭话，说可以为你指点中州的修炼圣地和注意事项。",
            "choices": [
                _c("认真聆听", condition=_cond("comprehension", 6), rewards={"comprehension": 1, "fortune": 1}, flavor="老修士的指点让你受益匪浅，悟性和机缘都有所提升。悟性 +1，机缘 +1"),
                _c("认真聆听", rewards={"fortune": 1}, flavor="老修士的指点让你对中州有了更多了解，机缘略有提升。机缘 +1"),
                _c("随便应付", rewards={}, flavor="老修士摇头，不再多言。"),
            ]
        }),
        _c("在镇上打听消息", condition=_cond("fortune", 6), rewards={"fortune": 1, "spirit_stones": 50}, flavor="你从各处打听到了一些有价值的消息，机缘略有提升。机缘 +1，灵石 +50"),
        _c("在镇上打听消息", rewards={"cultivation": 20}, flavor="你打听到了一些皮毛，略有收获。修为 +20"),
        _c("直接离开，继续赶路", rewards={}, flavor="你继续赶路。"),
    ]
))

EVENTS.append(_e(
    "凌霄城入城考验",
    "凌霄城建于云端，需要御剑飞行方可抵达，城门口的守卫说入城需要展示御剑能力。",
    [
        _c("展示御剑能力", condition=_cond("comprehension", 7), rewards={"reputation": 30, "comprehension": 1}, flavor="你的御剑技术令守卫赞叹，顺利入城，声望大涨。声望 +30，悟性 +1"),
        _c("展示御剑能力", condition=_cond("comprehension", 5), rewards={"reputation": 10}, flavor="你勉强通过了考验，顺利入城。声望 +10"),
        _c("展示御剑能力", rewards={"reputation": -5}, flavor="你的御剑技术不足，被守卫婉拒入城。声望 -5"),
        _c("绕道寻找其他入口", condition=_cond("fortune", 7), rewards={"fortune": 1, "spirit_stones": 80}, flavor="你找到了一处隐秘的入口，还在途中发现了一些前人遗留的灵石。机缘 +1，灵石 +80"),
        _c("绕道寻找其他入口", rewards={"lifespan": -3}, flavor="你在云端兜转许久，耗费了大量体力，最终还是没找到入口。寿元 -3"),
    ]
))

EVENTS.append(_e(
    "太虚城地脉感应",
    "太虚城建于上古大能的洞府之上，地脉灵气源源不断，城中随处可以感受到强烈的天地灵气。",
    [
        _c("在地脉汇聚处打坐修炼", condition=_cond("comprehension", 8), rewards={"comprehension": 1, "soul": 1, "cultivation": 150}, flavor="你在地脉汇聚处感悟天地法则，悟性和神识都大幅提升，修为大进。悟性 +1，神识 +1，修为 +150"),
        _c("在地脉汇聚处打坐修炼", condition=_cond("comprehension", 6), rewards={"comprehension": 1, "cultivation": 100}, flavor="你在地脉汇聚处修炼，悟性和修为都有所提升。悟性 +1，修为 +100"),
        _c("在地脉汇聚处打坐修炼", rewards={"cultivation": 70}, flavor="地脉灵气辅助修炼，收获颇丰。修为 +70"),
        _c("寻找地脉的源头", condition=_cond("fortune", 8), rewards={"fortune": 2, "spirit_stones": 150}, flavor="你找到了地脉的源头，发现了一处隐藏的灵石矿脉，机缘大涨。机缘 +2，灵石 +150"),
        _c("寻找地脉的源头", rewards={"lifespan": -3, "cultivation": 50}, flavor="你在寻找途中耗费了不少精力，没有找到源头，但也借助地脉灵气修炼了一番。寿元 -3，修为 +50"),
    ]
))
