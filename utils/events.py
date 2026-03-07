EVENTS = []

def _e(title, desc, choices):
    return {"title": title, "desc": desc, "choices": choices}

def _c(label, next_event=None, condition=None, rewards=None, flavor=None):
    return {"label": label, "next": next_event, "condition": condition, "rewards": rewards or {}, "flavor": flavor or ""}

def _cond(stat, val):
    return {"stat": stat, "val": val}


EVENTS.append(_e(
    "神秘洞穴",
    "在山间游历时，你发现一处隐于藤蔓之后的洞穴，洞口隐约有灵气流动，不知深浅。",
    [
        _c("拔剑在手，直接闯入", next_event={
            "desc": "洞内昏暗，灵气浓郁，深处传来低沉的喘息声。你握紧手中剑，继续前行还是就此止步？",
            "choices": [
                _c("继续深入，一探究竟",
                   condition=_cond("physique", 7),
                   rewards={"spirit_stones": 100},
                   flavor="你击败了洞中妖兽，发现了一处小型灵石矿脉。灵石 +100"),
                _c("继续深入，一探究竟",
                   rewards={"lifespan": -8, "spirit_stones": 20},
                   flavor="妖兽凶猛，你受伤逃出，所幸捡到几块散落的灵石。寿元 -8，灵石 +20"),
                _c("原路退出，不值得冒险",
                   rewards={},
                   flavor="你谨慎退出，安然无恙。"),
            ]
        }),
        _c("在洞口静候片刻，观察动静", next_event={
            "desc": "片刻后，一只灵狐从洞中跑出，见到你后停下打量，似乎在评估你的善意。",
            "choices": [
                _c("拿出食物引诱它靠近",
                   condition=_cond("fortune", 6),
                   rewards={"spirit_stones": 80},
                   flavor="灵狐带你找到一处灵草丛，采摘后售出颇为值钱。灵石 +80"),
                _c("拿出食物引诱它靠近",
                   rewards={},
                   flavor="灵狐嗅了嗅，转身跑掉了。"),
                _c("跟着灵狐进入洞穴",
                   condition=_cond("comprehension", 7),
                   rewards={"cultivation": 80},
                   flavor="洞内深处有前人留下的功法残卷，你悉心研读，修为大进。修为 +80"),
                _c("跟着灵狐进入洞穴",
                   rewards={"spirit_stones": 30},
                   flavor="洞内只有些普通灵石，聊胜于无。灵石 +30"),
            ]
        }),
        _c("绕行洞穴一圈，寻找其他入口",
           condition=_cond("fortune", 7),
           rewards={"lifespan": 20},
           flavor="你发现了一处隐藏侧洞，内有一颗品质不错的丹药，服下后神清气爽。寿元 +20"),
        _c("绕行洞穴一圈，寻找其他入口",
           rewards={"lifespan": -1},
           flavor="绕了一圈什么都没有，略感疲惫。寿元 -1"),
        _c("转身离去，多一事不如少一事",
           rewards={"fortune": 1},
           flavor="你转身离去，走了几步却隐约感觉背后有目光注视。也许是错觉，也许不是。机缘 +1"),
    ]
))


EVENTS.append(_e(
    "受伤的灵兽",
    "山道旁，一只受伤的灵兽正在哀鸣，伤口渗血，眼神中带着警惕与恐惧。",
    [
        _c("上前救治它", next_event={
            "desc": "灵兽在你的救治下渐渐平静，它舔了舔你的手，随后跑进了林中。片刻后它叼着什么东西回来了。",
            "choices": [
                _c("接受它带来的东西",
                   condition=_cond("fortune", 6),
                   rewards={"spirit_stones": 120, "fortune": 1},
                   flavor="竟是一颗品相极佳的灵珠，价值不菲。灵石 +120，机缘 +1"),
                _c("接受它带来的东西",
                   rewards={"spirit_stones": 50},
                   flavor="是几块普通灵石，聊表心意。灵石 +50"),
            ]
        }),
        _c("绕道而行，不想惹麻烦",
           rewards={},
           flavor="你绕道离开，心中隐隐有些不安。"),
        _c("将其击杀，取其妖丹",
           condition=_cond("physique", 6),
           rewards={"spirit_stones": 60, "lifespan": -3},
           flavor="灵兽垂死挣扎，你受了些轻伤，但妖丹换了不少灵石。灵石 +60，寿元 -3"),
        _c("将其击杀，取其妖丹",
           rewards={"lifespan": -10},
           flavor="灵兽爆发出惊人的战力，你狼狈逃脱，伤势不轻。寿元 -10"),
    ]
))

EVENTS.append(_e(
    "神秘老人",
    "路边坐着一位衣衫褴褛的老人，他抬头看了你一眼，笑道：「有缘人，老夫这里有样东西，不知你可有兴趣？」",
    [
        _c("停下来听他说", next_event={
            "desc": "老人从怀中掏出一个布包，里面是一颗散发着淡淡光芒的丹药。「五十灵石，你要不要？」",
            "choices": [
                _c("掏出灵石购买",
                   condition=_cond("soul", 6),
                   rewards={"spirit_stones": -50, "lifespan": 30, "comprehension": 1},
                   flavor="丹药入口，一股暖流遍布全身，竟是一颗难得的益寿延年丹。寿元 +30，悟性 +1"),
                _c("掏出灵石购买",
                   rewards={"spirit_stones": -50, "lifespan": 10},
                   flavor="普通的培元丹，但也物有所值。寿元 +10"),
                _c("婉言拒绝",
                   rewards={},
                   flavor="老人点点头，不再多言。你总觉得他的眼神意味深长。"),
            ]
        }),
        _c("不理会，继续赶路",
           rewards={"fortune": 1},
           flavor="走出几步，身后传来老人的笑声：「有缘再见。」莫名地，你感觉今日运气会不错。机缘 +1"),
        _c("警惕地打量他，试探问道",
           condition=_cond("comprehension", 7),
           rewards={"comprehension": 1},
           flavor="你察觉此人深藏不露，两人交谈片刻，你受益良多。悟性 +1"),
        _c("警惕地打量他，试探问道",
           rewards={},
           flavor="老人只是笑而不语，你问不出什么，只好离去。"),
    ]
))

EVENTS.append(_e(
    "山贼劫道",
    "前方山路突然窜出数名彪悍汉子，为首者横刀立马：「此路是我开，此树是我栽，要想过此路，留下买路财！」",
    [
        _c("拔剑迎战", next_event={
            "desc": "山贼们见你不惧，一拥而上。你奋力拼杀，局势渐渐明朗。",
            "choices": [
                _c("全力出击，一举击溃",
                   condition=_cond("physique", 7),
                   rewards={"spirit_stones": 80, "physique": 1},
                   flavor="山贼溃败，你缴获了他们的财物，体魄也在战斗中得到锻炼。灵石 +80，体魄 +1"),
                _c("全力出击，一举击溃",
                   rewards={"lifespan": -6, "spirit_stones": -30},
                   flavor="你击退了山贼，但自身也受了伤，还丢失了部分灵石。寿元 -6，灵石 -30"),
            ]
        }),
        _c("掏出灵石打发他们",
           rewards={"spirit_stones": -40},
           flavor="破财消灾，山贼们拿了灵石便散去了。灵石 -40"),
        _c("施展身法，绕道而行",
           condition=_cond("fortune", 7),
           rewards={"fortune": 1},
           flavor="你轻松甩开山贼，还顺手捡到了他们之前劫来的一个钱袋。机缘 +1，灵石 +50"),
        _c("施展身法，绕道而行",
           rewards={"lifespan": -2},
           flavor="你勉强逃脱，但在慌乱中扭伤了脚踝。寿元 -2"),
    ]
))

EVENTS.append(_e(
    "废弃道观",
    "山间有一座废弃的道观，门扉半掩，里面隐约有灵气残留，不知荒废了多少年。",
    [
        _c("推门进入探索", next_event={
            "desc": "道观内尘埃遍布，正殿供奉的神像已经残破。角落里有一个落满灰尘的书架。",
            "choices": [
                _c("仔细翻找书架",
                   condition=_cond("comprehension", 6),
                   rewards={"cultivation": 100, "soul": 1},
                   flavor="你发现了一本残缺的修炼心得，虽不完整，但字字珠玑。修为 +100，神识 +1"),
                _c("仔细翻找书架",
                   rewards={"cultivation": 40},
                   flavor="只找到几页残破的功法碎片，勉强有些参考价值。修为 +40"),
                _c("在正殿打坐冥想",
                   condition=_cond("soul", 6),
                   rewards={"soul": 1, "lifespan": 5},
                   flavor="残存的道韵让你心神宁静，神识得到了些许提升。神识 +1，寿元 +5"),
                _c("在正殿打坐冥想",
                   rewards={"cultivation": 30},
                   flavor="灵气稀薄，但静心修炼片刻也有些收获。修为 +30"),
            ]
        }),
        _c("在门口观望，不进入",
           rewards={"fortune": 1},
           flavor="你没有进入，却在门口的石阶下发现了一个小布袋，里面有几枚灵石。机缘 +1，灵石 +30"),
        _c("转身离去",
           rewards={},
           flavor="你感觉此地阴气略重，还是离开为妙。"),
    ]
))


EVENTS.append(_e(
    "灵泉",
    "林间深处，你发现一处隐秘的灵泉，泉水清澈，灵气氤氲，泉边野花盛开，宛如仙境。",
    [
        _c("脱衣入泉沐浴", next_event={
            "desc": "泉水温热，灵气从毛孔渗入，你感到前所未有的舒畅。沐浴片刻后，你察觉泉底似乎有什么东西。",
            "choices": [
                _c("潜入泉底探查",
                   condition=_cond("fortune", 7),
                   rewards={"lifespan": 20, "bone": 1},
                   flavor="泉底有一块温润的灵玉，长期浸泡在灵泉中已有灵性。根骨 +1，寿元 +20"),
                _c("潜入泉底探查",
                   rewards={"lifespan": 15},
                   flavor="只是普通的泉底石块，但灵泉本身已让你受益不少。寿元 +15"),
                _c("不去理会，继续享受",
                   rewards={"lifespan": 20},
                   flavor="你尽情沐浴，神清气爽，寿元得到了恢复。寿元 +20"),
            ]
        }),
        _c("掬水饮用",
           condition=_cond("fortune", 6),
           rewards={"lifespan": 10, "comprehension": 1},
           flavor="灵泉入喉，甘甜清冽，你感到思维前所未有地清晰。寿元 +10，悟性 +1"),
        _c("掬水饮用",
           rewards={"lifespan": 8},
           flavor="灵泉甘甜，略有补益。寿元 +8"),
        _c("取些泉水装入水囊带走",
           rewards={"spirit_stones": 60},
           flavor="灵泉水在市集上颇受欢迎，你换得了不少灵石。灵石 +60"),
    ]
))

EVENTS.append(_e(
    "迷雾山林",
    "前方山路突然被一片浓雾笼罩，能见度极低，方向难辨，你不知不觉已经迷失在其中。",
    [
        _c("静下心来，感应灵气方向", next_event={
            "desc": "你闭目感应，隐约察觉到灵气流动的方向，顺着走去，雾中出现了一个模糊的身影。",
            "choices": [
                _c("上前询问",
                   condition=_cond("fortune", 6),
                   rewards={"fortune": 1, "spirit_stones": 50},
                   flavor="竟是一位迷路的丹师，他感激你的帮助，赠予你一颗丹药换成灵石。机缘 +1，灵石 +50"),
                _c("上前询问",
                   rewards={"lifespan": -3},
                   flavor="那只是一只迷路的妖兽，你仓皇逃脱，受了些轻伤。寿元 -3"),
                _c("绕开身影，自行寻路",
                   rewards={"lifespan": -2},
                   flavor="你在迷雾中兜转许久才走出，耗费了不少精力。寿元 -2"),
            ]
        }),
        _c("原路返回，等雾散再走",
           rewards={"lifespan": -1},
           flavor="你耐心等待，雾气散去后继续赶路，只是耽误了些时间。寿元 -1"),
        _c("强行闯入，凭感觉走",
           condition=_cond("physique", 7),
           rewards={"physique": 1},
           flavor="你凭借强健的体魄硬闯迷雾，虽然走了不少弯路，但体魄得到了锻炼。体魄 +1"),
        _c("强行闯入，凭感觉走",
           rewards={"lifespan": -5},
           flavor="你在迷雾中迷失了很久，精疲力竭才走出。寿元 -5"),
    ]
))

EVENTS.append(_e(
    "集市奇遇",
    "途经一处热闹的集市，各色摊贩叫卖声此起彼伏，一个不起眼的角落里，一位老者正在兜售一个蒙着黑布的笼子。",
    [
        _c("上前询问笼中是何物", next_event={
            "desc": "老者掀开黑布，里面是一只通体雪白的小兽，眼睛如红宝石般明亮，正好奇地打量着你。「一百灵石，有缘人才能买。」",
            "choices": [
                _c("掏出一百灵石购买",
                   condition=_cond("fortune", 7),
                   rewards={"spirit_stones": -100, "fortune": 2},
                   flavor="小兽与你亲昵异常，似乎与你有缘，日后必有大用。灵石 -100，机缘 +2"),
                _c("掏出一百灵石购买",
                   rewards={"spirit_stones": -100, "fortune": 1},
                   flavor="小兽乖巧可爱，虽不知有何用处，但机缘似乎好了些。灵石 -100，机缘 +1"),
                _c("讨价还价，五十灵石",
                   condition=_cond("fortune", 6),
                   rewards={"spirit_stones": -50, "fortune": 1},
                   flavor="老者犹豫片刻，点头答应了。机缘 +1，灵石 -50"),
                _c("讨价还价，五十灵石",
                   rewards={},
                   flavor="老者摇头，你只好作罢。"),
                _c("不感兴趣，离开",
                   rewards={},
                   flavor="你转身离去，总觉得错过了什么。"),
            ]
        }),
        _c("在集市上随意逛逛",
           condition=_cond("fortune", 6),
           rewards={"spirit_stones": 70},
           flavor="你在一个不起眼的摊位上发现了一件被低估的灵器，转手卖出大赚一笔。灵石 +70"),
        _c("在集市上随意逛逛",
           rewards={"spirit_stones": -20},
           flavor="你被热情的摊贩拉着买了些用处不大的东西。灵石 -20"),
        _c("直接离开，不感兴趣",
           rewards={},
           flavor="你匆匆离去，集市的喧嚣渐渐远去。"),
    ]
))

EVENTS.append(_e(
    "悬崖采药",
    "悬崖峭壁上，一株散发着淡淡金光的灵草映入眼帘，那是难得一见的金芝，价值不菲。",
    [
        _c("徒手攀爬悬崖采摘", next_event={
            "desc": "你奋力攀爬，距离灵草越来越近，但崖壁湿滑，脚下一松……",
            "choices": [
                _c("稳住身形，继续攀爬",
                   condition=_cond("physique", 7),
                   rewards={"spirit_stones": 150, "physique": 1},
                   flavor="你成功采到金芝，体魄也在极限挑战中得到提升。灵石 +150，体魄 +1"),
                _c("稳住身形，继续攀爬",
                   rewards={"lifespan": -10, "spirit_stones": 80},
                   flavor="你跌落后被藤蔓挂住，惊魂未定，但金芝已在手中。寿元 -10，灵石 +80"),
                _c("放弃，原路返回",
                   rewards={"lifespan": -2},
                   flavor="你谨慎退回，虽然安全，但心有不甘。寿元 -2"),
            ]
        }),
        _c("寻找其他路径绕上去",
           condition=_cond("comprehension", 6),
           rewards={"spirit_stones": 150},
           flavor="你找到了一条隐蔽的山路，轻松采到了金芝。灵石 +150"),
        _c("寻找其他路径绕上去",
           rewards={"lifespan": -3},
           flavor="绕路耗费了大量时间和体力，最终还是没找到上去的路。寿元 -3"),
        _c("放弃，此地太危险",
           rewards={},
           flavor="你叹了口气，转身离去。"),
    ]
))

EVENTS.append(_e(
    "古井",
    "荒野中有一口古井，井沿上刻满了看不懂的符文，井底隐约有微光闪烁。",
    [
        _c("俯身查看井底", next_event={
            "desc": "井底的光芒越来越亮，你感到一股神秘的力量在牵引着你。",
            "choices": [
                _c("顺着绳子下井",
                   condition=_cond("fortune", 7),
                   rewards={"spirit_stones": 200, "bone": 1},
                   flavor="井底有一个古老的储物袋，内有大量灵石和一块温润的根骨玉。灵石 +200，根骨 +1"),
                _c("顺着绳子下井",
                   rewards={"lifespan": -8},
                   flavor="井底阴气极重，你强撑着爬上来，元气大伤。寿元 -8"),
                _c("投入一枚灵石试探",
                   condition=_cond("soul", 6),
                   rewards={"soul": 1},
                   flavor="灵石落入井底，激起一圈涟漪，你从中感悟到了一丝天地法则。神识 +1"),
                _c("投入一枚灵石试探",
                   rewards={"spirit_stones": -1},
                   flavor="灵石落入井底，什么都没发生。"),
            ]
        }),
        _c("研究井沿上的符文",
           condition=_cond("comprehension", 7),
           rewards={"comprehension": 1, "cultivation": 50},
           flavor="你花了些时间研究符文，竟从中悟出了一丝阵法之道。悟性 +1，修为 +50"),
        _c("研究井沿上的符文",
           rewards={"cultivation": 20},
           flavor="符文深奥难懂，你只看出了些皮毛。修为 +20"),
        _c("绕道而行，不去招惹",
           rewards={},
           flavor="你绕开古井继续赶路，心中隐隐觉得此地不寻常。"),
    ]
))


EVENTS.append(_e(
    "落难修士",
    "路边躺着一位受了重伤的修士，气息奄奄，身旁散落着几件法器碎片，显然刚经历了一场恶战。",
    [
        _c("上前救治", next_event={
            "desc": "修士在你的帮助下渐渐恢复了些许意识，他感激地看着你，从怀中掏出一个玉简。",
            "choices": [
                _c("接受玉简",
                   condition=_cond("comprehension", 6),
                   rewards={"cultivation": 120, "reputation": 20},
                   flavor="玉简中记载着一段珍贵的修炼心得，你受益匪浅。修为 +120，声望 +20"),
                _c("接受玉简",
                   rewards={"spirit_stones": 80, "reputation": 20},
                   flavor="玉简中是一张藏宝图，你按图索骥找到了一处灵石藏匿处。灵石 +80，声望 +20"),
                _c("婉拒，只是举手之劳",
                   rewards={"fortune": 1, "reputation": 30},
                   flavor="修士感动不已，临别时说了一句：「此恩必报。」机缘 +1，声望 +30"),
            ]
        }),
        _c("搜刮他身上的财物后离去",
           condition=_cond("physique", 6),
           rewards={"spirit_stones": 100, "reputation": -30},
           flavor="你搜刮了他的财物，但此事若传出去，名声必然受损。灵石 +100，声望 -30"),
        _c("搜刮他身上的财物后离去",
           rewards={"spirit_stones": 60, "lifespan": -5, "reputation": -30},
           flavor="修士突然爆发，你受了伤才抢到些财物，声望大损。灵石 +60，寿元 -5，声望 -30"),
        _c("绕道而行，不想惹麻烦",
           rewards={},
           flavor="你绕道离去，心中隐隐有些不安。"),
    ]
))

EVENTS.append(_e(
    "毒雾山谷",
    "山谷中弥漫着淡紫色的雾气，隐约有异香传来，令人心神迷醉，但经验告诉你这可能是毒雾。",
    [
        _c("捂住口鼻，强行穿越", next_event={
            "desc": "毒雾比你想象的更浓，你感到头晕目眩，但谷中隐约有什么东西在发光。",
            "choices": [
                _c("坚持走向光源",
                   condition=_cond("physique", 7),
                   rewards={"spirit_stones": 180, "lifespan": -5},
                   flavor="你强撑着找到了光源——一株极品灵草，代价是中了些毒。灵石 +180，寿元 -5"),
                _c("坚持走向光源",
                   rewards={"lifespan": -15},
                   flavor="毒素侵入经脉，你拼命运功逼毒，元气大伤。寿元 -15"),
                _c("立刻退出山谷",
                   rewards={"lifespan": -3},
                   flavor="你及时退出，只中了些轻毒，休息片刻便恢复了。寿元 -3"),
            ]
        }),
        _c("绕道而行",
           rewards={"lifespan": -1},
           flavor="绕路耗费了不少时间，但安全无虞。寿元 -1"),
        _c("在谷口观察，寻找规律",
           condition=_cond("comprehension", 7),
           rewards={"spirit_stones": 150},
           flavor="你发现毒雾有间歇性消散的规律，趁机进入采到了灵草。灵石 +150"),
        _c("在谷口观察，寻找规律",
           rewards={},
           flavor="你观察了许久，没有发现什么规律，只好放弃。"),
    ]
))

EVENTS.append(_e(
    "对弈老者",
    "茶馆中，一位白发老者正在独自摆弄棋局，见你路过，抬头笑道：「小友，可愿与老夫对弈一局？」",
    [
        _c("欣然应战", next_event={
            "desc": "棋局进行到中盘，你发现老者棋力深不可测，但棋局中似乎隐藏着某种道理。",
            "choices": [
                _c("专注于棋局，用心感悟",
                   condition=_cond("comprehension", 7),
                   rewards={"comprehension": 1, "soul": 1},
                   flavor="你从棋局中悟出了一丝天地之道，受益匪浅。悟性 +1，神识 +1"),
                _c("专注于棋局，用心感悟",
                   rewards={"comprehension": 1},
                   flavor="虽然输了棋，但你从中学到了不少。悟性 +1"),
                _c("故意输棋，观察老者反应",
                   condition=_cond("fortune", 7),
                   rewards={"fortune": 1, "spirit_stones": 50},
                   flavor="老者哈哈大笑，说你是个聪明人，临别赠你一个锦囊。机缘 +1，灵石 +50"),
                _c("故意输棋，观察老者反应",
                   rewards={},
                   flavor="老者只是平静地收起棋子，什么都没说。"),
            ]
        }),
        _c("婉言拒绝，继续赶路",
           rewards={},
           flavor="老者点点头，不再多言。"),
        _c("下注对弈，赌上灵石",
           condition=_cond("comprehension", 8),
           rewards={"spirit_stones": 100},
           flavor="你棋高一筹，赢得了赌注。灵石 +100"),
        _c("下注对弈，赌上灵石",
           rewards={"spirit_stones": -60},
           flavor="老者棋力远超你，你输得心服口服。灵石 -60"),
    ]
))

EVENTS.append(_e(
    "暴风雪",
    "天色骤变，一场突如其来的暴风雪席卷而来，前方道路已被大雪封堵，附近有一座破旧的木屋。",
    [
        _c("进入木屋避雪", next_event={
            "desc": "木屋内已有一人，是一位同样避雪的修士，他正在生火取暖，见你进来，点头示意。",
            "choices": [
                _c("友好交谈，互通有无",
                   condition=_cond("fortune", 6),
                   rewards={"spirit_stones": 60, "reputation": 15},
                   flavor="对方是一位经验丰富的散修，交流中你获益良多，临别还互赠了些灵石。灵石 +60，声望 +15"),
                _c("友好交谈，互通有无",
                   rewards={"cultivation": 40},
                   flavor="两人交流修炼心得，各有收获。修为 +40"),
                _c("保持警惕，各自休息",
                   rewards={"lifespan": 5},
                   flavor="你谨慎地休息了一夜，第二天雪停后继续赶路，精神恢复了些。寿元 +5"),
            ]
        }),
        _c("强行在风雪中赶路",
           condition=_cond("physique", 8),
           rewards={"physique": 1},
           flavor="你凭借强健的体魄硬闯风雪，体魄得到了极大锻炼。体魄 +1"),
        _c("强行在风雪中赶路",
           rewards={"lifespan": -10, "bone": -1},
           flavor="严寒侵入骨髓，你冻伤了根基，元气大伤。寿元 -10，根骨 -1"),
        _c("就地打坐，以内力抵御严寒",
           condition=_cond("soul", 6),
           rewards={"soul": 1, "cultivation": 60},
           flavor="你以内力抵御严寒，反而借此机会深入修炼，有所感悟。神识 +1，修为 +60"),
        _c("就地打坐，以内力抵御严寒",
           rewards={"lifespan": -5},
           flavor="内力不足以完全抵御严寒，你还是受了些冻伤。寿元 -5"),
    ]
))


EVENTS.append(_e(
    "拍卖会",
    "途经一处城镇，恰逢一年一度的小型拍卖会，门口的告示上写着今日有一件来历不明的宝物拍卖。",
    [
        _c("进场参与竞拍", next_event={
            "desc": "拍卖台上摆着一个古朴的玉盒，主持人说里面是一件「机缘之物」，起拍价一百灵石。",
            "choices": [
                _c("出价一百灵石",
                   condition=_cond("fortune", 7),
                   rewards={"spirit_stones": -100, "fortune": 2, "bone": 1},
                   flavor="玉盒中是一枚天材地宝，对你的根骨和机缘都有极大裨益。灵石 -100，机缘 +2，根骨 +1"),
                _c("出价一百灵石",
                   rewards={"spirit_stones": -100, "cultivation": 80},
                   flavor="玉盒中是一颗修炼丹药，服下后修为大进。灵石 -100，修为 +80"),
                _c("出价两百灵石，志在必得",
                   condition=_cond("fortune", 8),
                   rewards={"spirit_stones": -200, "fortune": 3},
                   flavor="你以高价拍得，玉盒中的宝物让你机缘大涨。灵石 -200，机缘 +3"),
                _c("出价两百灵石，志在必得",
                   rewards={"spirit_stones": -200, "lifespan": 30},
                   flavor="宝物是一颗延寿丹，物有所值。灵石 -200，寿元 +30"),
                _c("放弃竞拍，观望",
                   rewards={},
                   flavor="你没有出手，宝物被他人拍走。"),
            ]
        }),
        _c("在会场外打听消息",
           condition=_cond("fortune", 6),
           rewards={"spirit_stones": 80},
           flavor="你从一位知情者口中得知了一个内幕消息，提前布局赚了一笔。灵石 +80"),
        _c("在会场外打听消息",
           rewards={},
           flavor="你没打听到什么有用的消息。"),
        _c("直接离开",
           rewards={},
           flavor="你对拍卖会不感兴趣，继续赶路。"),
    ]
))

EVENTS.append(_e(
    "渡口等船",
    "你来到一处渡口，船家说要等到明日才能开船，渡口旁有几位修士也在等候。",
    [
        _c("与等候的修士们交流", next_event={
            "desc": "其中一位修士主动搭话，自称是某宗门的外门弟子，正在外出历练，他提议大家互相切磋。",
            "choices": [
                _c("接受切磋",
                   condition=_cond("physique", 7),
                   rewards={"physique": 1, "reputation": 20},
                   flavor="你在切磋中胜出，赢得了众人的尊重。体魄 +1，声望 +20"),
                _c("接受切磋",
                   rewards={"lifespan": -3, "cultivation": 50},
                   flavor="你虽然落败，但从对手的招式中学到了不少。寿元 -3，修为 +50"),
                _c("婉拒切磋，只是闲聊",
                   condition=_cond("comprehension", 6),
                   rewards={"comprehension": 1},
                   flavor="你从闲聊中获得了不少修炼感悟。悟性 +1"),
                _c("婉拒切磋，只是闲聊",
                   rewards={"reputation": 10},
                   flavor="你结交了几位新朋友，声望略有提升。声望 +10"),
            ]
        }),
        _c("独自打坐修炼",
           condition=_cond("soul", 6),
           rewards={"cultivation": 70, "soul": 1},
           flavor="你借此机会静心修炼，神识有所提升。修为 +70，神识 +1"),
        _c("独自打坐修炼",
           rewards={"cultivation": 40},
           flavor="你静心修炼，有些收获。修为 +40"),
        _c("在渡口附近探索",
           condition=_cond("fortune", 6),
           rewards={"spirit_stones": 60},
           flavor="你在河边发现了一些被水流冲来的灵材，换了些灵石。灵石 +60"),
        _c("在渡口附近探索",
           rewards={},
           flavor="你在附近转了转，什么都没发现。"),
    ]
))

EVENTS.append(_e(
    "废弃矿洞",
    "山壁上有一处废弃的矿洞，洞口的木架已经腐朽，但洞内隐约有灵石的光泽。",
    [
        _c("进入矿洞挖掘", next_event={
            "desc": "你进入矿洞，发现里面比想象中深得多，深处的矿壁上确实有灵石矿脉，但洞顶不时有碎石落下。",
            "choices": [
                _c("快速挖掘，尽快离开",
                   condition=_cond("physique", 6),
                   rewards={"spirit_stones": 120},
                   flavor="你快速挖出了一批灵石，在洞顶塌陷前安全撤出。灵石 +120"),
                _c("快速挖掘，尽快离开",
                   rewards={"spirit_stones": 60, "lifespan": -5},
                   flavor="你挖到了些灵石，但撤退时被落石砸中，受了些伤。灵石 +60，寿元 -5"),
                _c("仔细探查，寻找最佳矿脉",
                   condition=_cond("comprehension", 7),
                   rewards={"spirit_stones": 200},
                   flavor="你找到了一处品质极佳的灵石矿脉，收获颇丰。灵石 +200"),
                _c("仔细探查，寻找最佳矿脉",
                   rewards={"spirit_stones": 40, "lifespan": -8},
                   flavor="你在矿洞中耗费太多时间，洞顶塌陷，你狼狈逃出。灵石 +40，寿元 -8"),
            ]
        }),
        _c("在洞口观察，不进入",
           condition=_cond("comprehension", 6),
           rewards={"spirit_stones": 50},
           flavor="你在洞口发现了前人遗落的一个储物袋，里面有些灵石。灵石 +50"),
        _c("在洞口观察，不进入",
           rewards={},
           flavor="你观察了一番，觉得风险太大，放弃了。"),
        _c("直接离开",
           rewards={},
           flavor="你没有进入，继续赶路。"),
    ]
))

EVENTS.append(_e(
    "神秘符箓",
    "路边的树干上贴着一张泛黄的符箓，符文奇异，散发着微弱的灵光，不知是何人所留。",
    [
        _c("取下符箓研究", next_event={
            "desc": "符箓在你手中微微发热，符文开始流动，似乎在等待你做出选择。",
            "choices": [
                _c("将灵力注入符箓",
                   condition=_cond("soul", 7),
                   rewards={"soul": 1, "cultivation": 80},
                   flavor="符箓爆发出耀眼的光芒，你从中感悟到了一丝符道真意。神识 +1，修为 +80"),
                _c("将灵力注入符箓",
                   rewards={"lifespan": -5},
                   flavor="符箓突然爆炸，你受了些轻伤。寿元 -5"),
                _c("将符箓收入储物袋",
                   condition=_cond("fortune", 6),
                   rewards={"spirit_stones": 100},
                   flavor="你将符箓带到城中，被一位符师高价收购。灵石 +100"),
                _c("将符箓收入储物袋",
                   rewards={"spirit_stones": 30},
                   flavor="符箓品质一般，只卖了些普通价格。灵石 +30"),
            ]
        }),
        _c("不去理会，绕道而行",
           rewards={},
           flavor="你绕道而行，符箓的灵光渐渐消失在视野中。"),
        _c("将符箓撕毁",
           condition=_cond("physique", 6),
           rewards={"physique": 1},
           flavor="符箓爆发出一股冲击力，你硬抗了下来，体魄得到了锻炼。体魄 +1"),
        _c("将符箓撕毁",
           rewards={"lifespan": -3},
           flavor="符箓爆炸，你受了些轻伤。寿元 -3"),
    ]
))


EVENTS.append(_e(
    "迷路孩童",
    "山道上，一个约莫七八岁的孩童独自坐在路边哭泣，说自己迷路了，找不到回家的路。",
    [
        _c("帮助孩童找到家人", next_event={
            "desc": "你带着孩童走了许久，终于找到了他的家。孩童的父母感激涕零，非要答谢你。",
            "choices": [
                _c("接受答谢",
                   condition=_cond("fortune", 6),
                   rewards={"spirit_stones": 80, "reputation": 20, "fortune": 1},
                   flavor="孩童父母拿出了家中珍藏的灵石和一件小法器答谢你。灵石 +80，声望 +20，机缘 +1"),
                _c("接受答谢",
                   rewards={"spirit_stones": 40, "reputation": 20},
                   flavor="孩童父母拿出了些灵石答谢你。灵石 +40，声望 +20"),
                _c("婉拒答谢，举手之劳",
                   rewards={"reputation": 40, "fortune": 1},
                   flavor="孩童父母感动不已，你的善举在附近传为美谈。声望 +40，机缘 +1"),
            ]
        }),
        _c("指引方向，让孩童自己回去",
           rewards={"reputation": 5},
           flavor="你指了个大概方向，孩童道谢后跑去了。声望 +5"),
        _c("不理会，继续赶路",
           rewards={"fortune": -1},
           flavor="你视而不见地走过，心中隐隐有些不安，似乎错过了什么。机缘 -1"),
    ]
))

EVENTS.append(_e(
    "古树异象",
    "山间有一棵参天古树，树龄不知几百年，树干上有一个奇异的树洞，洞内散发着淡淡的木灵气。",
    [
        _c("将手伸入树洞", next_event={
            "desc": "你的手触碰到了一个温润的物体，似乎是一颗果实，但同时你感到一股意识在审视着你。",
            "choices": [
                _c("取出果实",
                   condition=_cond("fortune", 7),
                   rewards={"lifespan": 25, "bone": 1},
                   flavor="是一颗千年灵果，服下后根骨得到了滋养。寿元 +25，根骨 +1"),
                _c("取出果实",
                   rewards={"lifespan": 15},
                   flavor="是一颗普通的灵果，但也有些补益。寿元 +15"),
                _c("将果实放回，退手",
                   rewards={"fortune": 1},
                   flavor="古树似乎对你的尊重表示认可，你感到运气好了些。机缘 +1"),
            ]
        }),
        _c("在古树下打坐冥想",
           condition=_cond("comprehension", 6),
           rewards={"comprehension": 1, "cultivation": 60},
           flavor="古树的木灵气辅助你修炼，你若有所悟。悟性 +1，修为 +60"),
        _c("在古树下打坐冥想",
           rewards={"cultivation": 30},
           flavor="木灵气有些补益，修为略有提升。修为 +30"),
        _c("砍下一截树枝带走",
           condition=_cond("physique", 5),
           rewards={"spirit_stones": 70},
           flavor="古树木质坚硬，是上好的炼器材料，卖了个好价钱。灵石 +70"),
        _c("砍下一截树枝带走",
           rewards={"lifespan": -5},
           flavor="古树突然爆发出一股木灵气将你弹飞，你受了些轻伤。寿元 -5"),
    ]
))

EVENTS.append(_e(
    "法宝争夺",
    "前方传来激烈的打斗声，两名修士正在争夺一件散发着金光的法宝，双方都已精疲力竭。",
    [
        _c("趁乱出手，抢夺法宝", next_event={
            "desc": "你突然出手，两名修士都被打了个措手不及，法宝落入你手中，但两人随即将怒火转向了你。",
            "choices": [
                _c("迅速逃离",
                   condition=_cond("physique", 7),
                   rewards={"spirit_stones": 150, "reputation": -20},
                   flavor="你凭借速度甩开了两人，法宝到手，但名声受损。灵石 +150，声望 -20"),
                _c("迅速逃离",
                   rewards={"lifespan": -12, "reputation": -20},
                   flavor="你没能逃脱，被两人联手痛打，法宝也丢了。寿元 -12，声望 -20"),
                _c("以法宝为筹码谈判",
                   condition=_cond("comprehension", 7),
                   rewards={"spirit_stones": 100, "reputation": -10},
                   flavor="你凭借口才从两人手中各要了些好处，三方各退一步。灵石 +100，声望 -10"),
            ]
        }),
        _c("在旁观看，等分出胜负",
           condition=_cond("fortune", 7),
           rewards={"spirit_stones": 80},
           flavor="胜者精疲力竭，你趁机捡走了战场上散落的灵石和法器碎片。灵石 +80"),
        _c("在旁观看，等分出胜负",
           rewards={"cultivation": 40},
           flavor="你从旁观战中学到了些战斗技巧。修为 +40"),
        _c("上前劝架，平息纷争",
           condition=_cond("reputation", 30),
           rewards={"reputation": 30, "fortune": 1},
           flavor="你的声望让两人都给了几分面子，纷争平息，双方各自感谢了你。声望 +30，机缘 +1"),
        _c("上前劝架，平息纷争",
           rewards={"lifespan": -5},
           flavor="两人不买账，你反而被波及受了些伤。寿元 -5"),
    ]
))

EVENTS.append(_e(
    "算命摊",
    "路边有一个算命摊，摊主是一位蒙着面纱的神秘女子，她抬头看了你一眼，说：「你今日必有一劫。」",
    [
        _c("付钱请她细说", next_event={
            "desc": "女子掐指一算，说：「你今日若向东行，必遇凶险；若向西行，或有奇遇。」",
            "choices": [
                _c("向西行",
                   condition=_cond("fortune", 6),
                   rewards={"fortune": 1, "spirit_stones": 100},
                   flavor="你向西行，果然遇到了一处无人知晓的灵石矿脉。机缘 +1，灵石 +100"),
                _c("向西行",
                   rewards={"spirit_stones": 30},
                   flavor="你向西行，只找到了些普通灵石。灵石 +30"),
                _c("向东行，不信邪",
                   condition=_cond("physique", 7),
                   rewards={"physique": 1},
                   flavor="你遇到了一只妖兽，但将其击败，体魄得到了锻炼。体魄 +1"),
                _c("向东行，不信邪",
                   rewards={"lifespan": -8},
                   flavor="你遇到了一只强大的妖兽，狼狈逃脱，受伤不轻。寿元 -8"),
            ]
        }),
        _c("不理会，继续赶路",
           condition=_cond("fortune", 5),
           rewards={},
           flavor="你没有理会，平安无事地继续赶路。"),
        _c("不理会，继续赶路",
           rewards={"lifespan": -3},
           flavor="你没有理会，果然遭遇了些小麻烦。寿元 -3"),
        _c("嘲笑她是骗子",
           rewards={"fortune": -1},
           flavor="女子淡淡一笑，你总觉得今日运气差了些。机缘 -1"),
    ]
))


EVENTS.append(_e(
    "破庙古镜",
    "破庙正殿中央，一面古朴的铜镜静静矗立，镜面尘封已久，但隐约能看到镜中有影像流动。",
    [
        _c("擦拭铜镜，照出自身", next_event={
            "desc": "镜中出现了你的影像，但随即出现了另一个画面——是你未来的某个场景，模糊难辨。",
            "choices": [
                _c("凝神细看，试图看清",
                   condition=_cond("soul", 7),
                   rewards={"soul": 1, "fortune": 1},
                   flavor="你从模糊的画面中捕捉到了一丝天机，神识和机缘都有所提升。神识 +1，机缘 +1"),
                _c("凝神细看，试图看清",
                   rewards={"soul": 1},
                   flavor="你看到了些模糊的画面，神识略有提升。神识 +1"),
                _c("立刻移开视线",
                   rewards={"fortune": 1},
                   flavor="你及时移开视线，感觉躲过了什么，机缘好了些。机缘 +1"),
            ]
        }),
        _c("将铜镜带走",
           condition=_cond("fortune", 7),
           rewards={"spirit_stones": 200},
           flavor="你将铜镜带到城中，被一位识货的修士高价收购。灵石 +200"),
        _c("将铜镜带走",
           rewards={"spirit_stones": 50, "lifespan": -3},
           flavor="铜镜沉重，搬运途中你受了些损耗，卖价也一般。灵石 +50，寿元 -3"),
        _c("不去理会，离开破庙",
           rewards={},
           flavor="你没有理会铜镜，转身离去。"),
    ]
))

EVENTS.append(_e(
    "灵兽蛋",
    "林间草丛中，你发现了一个散发着淡淡灵光的蛋，约有拳头大小，温热异常，显然是某种灵兽的蛋。",
    [
        _c("将蛋带走", next_event={
            "desc": "你将蛋放入储物袋，走了没多远，感到蛋在微微颤动，似乎快要孵化了。",
            "choices": [
                _c("停下来等待孵化",
                   condition=_cond("fortune", 7),
                   rewards={"fortune": 2, "spirit_stones": 50},
                   flavor="蛋孵化出一只罕见的灵兽幼崽，与你亲昵异常，机缘大涨。机缘 +2，灵石 +50"),
                _c("停下来等待孵化",
                   rewards={"spirit_stones": 80},
                   flavor="孵化出一只普通灵兽，你将其卖给了灵兽商人。灵石 +80"),
                _c("将蛋卖给路过的商人",
                   rewards={"spirit_stones": 100},
                   flavor="商人出了个不错的价格，你欣然成交。灵石 +100"),
            ]
        }),
        _c("将蛋放回原处",
           rewards={"fortune": 1},
           flavor="你将蛋轻轻放回草丛，感觉做了件好事，机缘好了些。机缘 +1"),
        _c("直接离开，不去理会",
           rewards={},
           flavor="你没有理会，继续赶路。"),
    ]
))

EVENTS.append(_e(
    "野果误食",
    "赶路途中腹中饥饿，路边有一丛结满果实的灌木，果实色泽鲜艳，香气扑鼻，但你不确定是否有毒。",
    [
        _c("直接摘来吃",
           condition=_cond("physique", 7),
           rewards={"lifespan": 5},
           flavor="你体魄强健，轻松化解了果实中的微毒，反而吸收了其中的灵气。寿元 +5"),
        _c("直接摘来吃",
           rewards={"lifespan": -6, "physique": -1},
           flavor="果实有毒，你上吐下泻，虚弱了好几天，根基受损。寿元 -6，体魄 -1"),
        _c("仔细辨别后再决定",
           condition=_cond("comprehension", 6),
           rewards={"lifespan": 8},
           flavor="你辨别出这是一种罕见的灵果，服下后颇有补益。寿元 +8"),
        _c("仔细辨别后再决定",
           rewards={},
           flavor="你辨别不出，为了安全起见放弃了。"),
        _c("不吃，继续赶路",
           rewards={},
           flavor="你忍着饥饿继续赶路，安全无虞。"),
    ]
))

EVENTS.append(_e(
    "山顶日出",
    "你登上一座山峰，恰逢日出，金色的阳光洒满大地，天地间灵气随之涌动，这一刻仿佛天地都在呼吸。",
    [
        _c("静心感悟，与天地共鸣",
           condition=_cond("comprehension", 7),
           rewards={"comprehension": 1, "cultivation": 80},
           flavor="你从日出中感悟到了一丝天地之道，悟性和修为都有所提升。悟性 +1，修为 +80"),
        _c("静心感悟，与天地共鸣",
           rewards={"cultivation": 50},
           flavor="你感受到了天地灵气的涌动，修为有所提升。修为 +50"),
        _c("运功修炼，借助灵气",
           condition=_cond("soul", 6),
           rewards={"soul": 1, "lifespan": 10},
           flavor="你借助日出时的灵气涌动修炼，神识和寿元都有所恢复。神识 +1，寿元 +10"),
        _c("运功修炼，借助灵气",
           rewards={"cultivation": 40},
           flavor="你借助灵气修炼，有些收获。修为 +40"),
        _c("欣赏风景，放松心情",
           rewards={"fortune": 1},
           flavor="你难得地放松了心情，感觉今日运气会不错。机缘 +1"),
    ]
))


EVENTS.append(_e(
    "夜宿荒野",
    "天色已晚，附近没有城镇，你只能在荒野中露宿，四周虫鸣鸟叫，偶尔传来远处妖兽的嚎叫。",
    [
        _c("布置简单的防御阵法", next_event={
            "desc": "夜半时分，你感到有什么东西在阵法外徘徊，似乎在试探。",
            "choices": [
                _c("保持警惕，静待天明",
                   condition=_cond("soul", 6),
                   rewards={"soul": 1},
                   flavor="你在警戒中度过了一夜，神识得到了锻炼。神识 +1"),
                _c("保持警惕，静待天明",
                   rewards={"lifespan": -2},
                   flavor="你一夜未眠，精神疲惫，略有损耗。寿元 -2"),
                _c("主动出击，驱逐来者",
                   condition=_cond("physique", 7),
                   rewards={"physique": 1, "spirit_stones": 40},
                   flavor="你击退了一只妖兽，取其妖丹换了些灵石。体魄 +1，灵石 +40"),
                _c("主动出击，驱逐来者",
                   rewards={"lifespan": -6},
                   flavor="妖兽比你想象的强，你受伤后才将其驱走。寿元 -6"),
            ]
        }),
        _c("找一处隐蔽的地方休息",
           condition=_cond("fortune", 6),
           rewards={"lifespan": 5, "fortune": 1},
           flavor="你找到了一处极为隐蔽的山洞，安然度过了一夜，还发现了前人留下的一些物资。寿元 +5，机缘 +1"),
        _c("找一处隐蔽的地方休息",
           rewards={"lifespan": 3},
           flavor="你找到了一处还算安全的地方，休息了一夜。寿元 +3"),
        _c("彻夜修炼，不去睡觉",
           condition=_cond("comprehension", 6),
           rewards={"cultivation": 60},
           flavor="夜间灵气充沛，你借机修炼，收获颇丰。修为 +60"),
        _c("彻夜修炼，不去睡觉",
           rewards={"lifespan": -3, "cultivation": 30},
           flavor="你修炼了一夜，但精力消耗过大。寿元 -3，修为 +30"),
    ]
))

EVENTS.append(_e(
    "神秘商队",
    "一支神秘的商队从你身旁经过，领队是一位气质不凡的中年人，他的马车上装满了用黑布遮盖的货物。",
    [
        _c("上前搭话，询问货物", next_event={
            "desc": "领队打量了你一眼，说：「我们贩卖的是各地的奇珍异宝，你若有兴趣，可以看看。」他掀开一角黑布，里面是各种灵材。",
            "choices": [
                _c("购买一件灵材（100灵石）",
                   condition=_cond("fortune", 7),
                   rewards={"spirit_stones": -100, "bone": 1, "comprehension": 1},
                   flavor="你买到了一件极品灵材，对根骨和悟性都有极大裨益。灵石 -100，根骨 +1，悟性 +1"),
                _c("购买一件灵材（100灵石）",
                   rewards={"spirit_stones": -100, "cultivation": 100},
                   flavor="你买到了一颗修炼丹药，修为大进。灵石 -100，修为 +100"),
                _c("讨价还价",
                   condition=_cond("comprehension", 6),
                   rewards={"spirit_stones": -60, "lifespan": 20},
                   flavor="你以六十灵石买到了一颗延寿丹，物超所值。灵石 -60，寿元 +20"),
                _c("讨价还价",
                   rewards={},
                   flavor="领队不为所动，你只好作罢。"),
                _c("不感兴趣，离开",
                   rewards={},
                   flavor="你婉拒了领队，继续赶路。"),
            ]
        }),
        _c("跟随商队同行一段",
           condition=_cond("fortune", 6),
           rewards={"fortune": 1, "spirit_stones": 50},
           flavor="同行途中，你从商队成员口中得知了一些有价值的消息，还顺手做了笔小生意。机缘 +1，灵石 +50"),
        _c("跟随商队同行一段",
           rewards={"reputation": 10},
           flavor="同行途中，你结交了几位新朋友。声望 +10"),
        _c("不理会，继续赶路",
           rewards={},
           flavor="你没有理会商队，继续赶路。"),
    ]
))

