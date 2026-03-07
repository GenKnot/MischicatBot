from utils.events._base import _e, _c, _cond

EVENTS = []

EVENTS.append(_e(
    "河畔钓叟",
    "河边一位老叟正在垂钓，鱼篓空空，他却气定神闲。见你路过，他笑道：「小友可会钓鱼？老朽这里多了一根竿。」",
    [
        _c("接过鱼竿试试手气", next_event={
            "desc": "你抛竿入水，许久无动静。老叟道：「钓鱼如修道，急不得。」正说着，浮漂沉了下去。",
            "choices": [
                _c("稳扎稳打，慢慢收线", condition=_cond("soul", 6), rewards={"soul": 1, "spirit_stones": 60}, flavor="你钓起一尾灵鲤，老叟赠你几块灵石。神识 +1，灵石 +60"),
                _c("稳扎稳打，慢慢收线", rewards={"spirit_stones": 25}, flavor="你钓起一尾普通鱼，老叟留鱼赠你几枚灵石。灵石 +25"),
                _c("猛力提竿", condition=_cond("physique", 6), rewards={"physique": 1, "spirit_stones": 40}, flavor="鱼大力沉，你硬拉上岸，老叟赞你体魄不错。体魄 +1，灵石 +40"),
                _c("猛力提竿", rewards={"lifespan": -1}, flavor="鱼脱钩了，你险些栽进河里。寿元 -1"),
            ]
        }),
        _c("与老叟闲聊几句", condition=_cond("comprehension", 6), rewards={"comprehension": 1, "cultivation": 50}, flavor="老叟随口几句，竟暗含修炼至理。悟性 +1，修为 +50"),
        _c("与老叟闲聊几句", rewards={"reputation": 5}, flavor="你们聊得投机，老叟对你印象不错。声望 +5"),
        _c("婉拒，继续赶路", rewards={}, flavor="你拱手告辞，继续前行。"),
    ]
))

EVENTS.append(_e(
    "林间棋局",
    "林中有两人对弈，棋盘边还空着一个石凳。其中一人抬头道：「道友可懂棋？我这位朋友正缺对手。」",
    [
        _c("坐下对弈一局", next_event={
            "desc": "棋至中盘，对方攻势凌厉，你需谨慎应对。旁观者在一旁不语。",
            "choices": [
                _c("专心计算，力求不败", condition=_cond("comprehension", 7), rewards={"comprehension": 1, "cultivation": 80}, flavor="你稳守反击，最终和棋。对方赞你悟性不错，赠你一句修炼心得。悟性 +1，修为 +80"),
                _c("专心计算，力求不败", rewards={"cultivation": 40}, flavor="你力战不敌，但从中有所得。修为 +40"),
                _c("故意露破绽，试探对方", condition=_cond("fortune", 6), rewards={"fortune": 1, "spirit_stones": 50}, flavor="对方未中计，反而欣赏你的机变，赠你灵石。机缘 +1，灵石 +50"),
                _c("故意露破绽，试探对方", rewards={}, flavor="对方轻松取胜，你略感尴尬。"),
            ]
        }),
        _c("只在旁观看", rewards={"cultivation": 30}, flavor="你观棋不语，略有所悟。修为 +30"),
        _c("不会下棋，告辞", rewards={}, flavor="你婉拒后离开。"),
    ]
))

EVENTS.append(_e(
    "破旧驿站",
    "山路旁有一间破旧驿站，招牌歪斜，里面隐约有灯火。掌柜在门口招呼：「客官，住店还是打尖？今夜只怕要变天。」",
    [
        _c("住店歇脚", next_event={
            "desc": "掌柜领你进了一间厢房。夜半时分，你听到隔壁传来低声交谈，似乎在商量什么见不得光的事。",
            "choices": [
                _c("屏息偷听", condition=_cond("soul", 6), rewards={"spirit_stones": 70, "reputation": -5}, flavor="你听出是一伙贼人分赃，记下线索后报官，得了赏银但贼人记恨。灵石 +70，声望 -5"),
                _c("屏息偷听", rewards={}, flavor="你听不真切，只好作罢。"),
                _c("闭目养神，不理会", rewards={"lifespan": 5}, flavor="你休息了一夜，精神恢复。寿元 +5"),
            ]
        }),
        _c("只买些干粮便走", rewards={"spirit_stones": -10, "lifespan": 3}, flavor="你买了干粮继续赶路，略解疲惫。灵石 -10，寿元 +3"),
        _c("不进去，露宿野外", condition=_cond("physique", 6), rewards={"physique": 1}, flavor="你在野外露宿，体魄得到锻炼。体魄 +1"),
        _c("不进去，露宿野外", rewards={"lifespan": -2}, flavor="夜风寒凉，你睡得不好。寿元 -2"),
    ]
))

EVENTS.append(_e(
    "石桥断处",
    "前方石桥从中断裂，桥下河水湍急。对岸隐约可见山路延续，若要绕行恐怕要多走大半日。",
    [
        _c("尝试跃过断桥", next_event={
            "desc": "你退后几步助跑，纵身一跃。断口约两丈余，落地时需稳住身形。",
            "choices": [
                _c("全力一跃", condition=_cond("physique", 7), rewards={"physique": 1, "cultivation": 40}, flavor="你稳稳落在对岸，体魄与修为皆有所得。体魄 +1，修为 +40"),
                _c("全力一跃", rewards={"lifespan": -5, "spirit_stones": 20}, flavor="你险些落水，抓住对岸石块爬了上去，丢了部分行李。寿元 -5，灵石 +20"),
                _c("以灵力轻身再跃", condition=_cond("soul", 6), rewards={"soul": 1, "cultivation": 50}, flavor="你以神识控身，轻飘飘落于对岸。神识 +1，修为 +50"),
                _c("以灵力轻身再跃", rewards={"lifespan": -3}, flavor="灵力不稳，你落水后勉强爬上岸。寿元 -3"),
            ]
        }),
        _c("绕路而行", rewards={"lifespan": -2}, flavor="你多花了大半日绕路，略感疲惫。寿元 -2"),
        _c("在桥头等是否有船经过", condition=_cond("fortune", 6), rewards={"fortune": 1, "spirit_stones": 30}, flavor="不久有渔舟经过，载你过河，船家还送你几条鱼换灵石。机缘 +1，灵石 +30"),
        _c("在桥头等是否有船经过", rewards={"lifespan": -1}, flavor="等了许久无船，你只好绕路。寿元 -1"),
    ]
))

EVENTS.append(_e(
    "灵植被盗",
    "一位药农拦住你，焦急道：「道友可曾见人往这边跑？我家灵田昨夜被偷，贼人往这个方向逃了！」",
    [
        _c("答应帮忙追踪", next_event={
            "desc": "你沿药农所指方向追出一段，发现地上有零星灵土和脚印，通向一片密林。",
            "choices": [
                _c("入林搜查", condition=_cond("soul", 6), rewards={"spirit_stones": 80, "reputation": 25}, flavor="你以神识感应到贼人藏身处，将其擒获，灵植追回。药农重谢。灵石 +80，声望 +25"),
                _c("入林搜查", rewards={"reputation": 10}, flavor="你搜了一圈未果，药农仍感激你的热心。声望 +10"),
                _c("在林外蹲守", condition=_cond("fortune", 6), rewards={"fortune": 1, "spirit_stones": 50}, flavor="贼人按捺不住出林，被你逮个正着。机缘 +1，灵石 +50"),
                _c("在林外蹲守", rewards={"lifespan": -1}, flavor="你守到日落无果，只好回报药农。寿元 -1"),
            ]
        }),
        _c("说没看见，继续赶路", rewards={}, flavor="你摇头离开。"),
    ]
))

EVENTS.append(_e(
    "溪边浣女",
    "溪水边，一名女子正在浣洗衣物，身旁放着一个竹篮，篮中似乎有灵草。她见你走近，抬头微微一笑。",
    [
        _c("上前询问灵草来历", next_event={
            "desc": "女子道：「是奴家自家种的，道友若需要，可以灵石来换。」她掀开篮上的布，露出几株品相不错的灵草。",
            "choices": [
                _c("买下几株灵草", condition=_cond("fortune", 6), rewards={"spirit_stones": -30, "lifespan": 15, "cultivation": 40}, flavor="灵草品质上乘，你服下后寿元与修为皆增。灵石 -30，寿元 +15，修为 +40"),
                _c("买下几株灵草", rewards={"spirit_stones": -30, "cultivation": 25}, flavor="灵草物有所值。灵石 -30，修为 +25"),
                _c("婉拒，只问路", rewards={"reputation": 5}, flavor="她为你指了路，你道谢离开。声望 +5"),
            ]
        }),
        _c("点头致意后离开", rewards={}, flavor="你未多言，径自离去。"),
    ]
))

EVENTS.append(_e(
    "野火余烬",
    "一片山坡刚经历过野火，草木焦黑，余烬未冷。灰烬中隐约有灵光闪烁，不知是何物。",
    [
        _c("在余烬中翻找", next_event={
            "desc": "你拨开灰烬，发现几块被火烧过的石头和一根焦黑的灵木，灵光正是从灵木中透出。",
            "choices": [
                _c("取走灵木", condition=_cond("physique", 6), rewards={"spirit_stones": 90, "physique": 1}, flavor="灵木是雷击火炼后的残存，价值不菲。你售出后体魄在翻找中亦有锻炼。灵石 +90，体魄 +1"),
                _c("取走灵木", rewards={"spirit_stones": 50}, flavor="你取走灵木，到城中卖了个不错价钱。灵石 +50"),
                _c("只取几块石头", rewards={"spirit_stones": 30}, flavor="石头中蕴含一丝火灵，可作炼器辅料。灵石 +30"),
            ]
        }),
        _c("怕有余火，不靠近", rewards={}, flavor="你绕开余烬离开。"),
    ]
))

EVENTS.append(_e(
    "拦路书生",
    "一名书生模样的修士拦在路中，拱手道：「道友留步。在下与同门走散，盘缠用尽，可否借几块灵石，日后必还？」",
    [
        _c("借他一些灵石", next_event={
            "desc": "书生接过灵石，感激涕零，从怀中摸出一枚玉简道：「此乃师门心法残卷，权当抵押。」",
            "choices": [
                _c("收下玉简", condition=_cond("comprehension", 6), rewards={"cultivation": 100, "comprehension": 1}, flavor="玉简中确有修炼心得，你参悟后修为与悟性皆进。修为 +100，悟性 +1"),
                _c("收下玉简", rewards={"cultivation": 50}, flavor="玉简内容零散，你略有所得。修为 +50"),
                _c("婉拒玉简，只当相助", rewards={"reputation": 20, "fortune": 1}, flavor="书生感动，说日后若相遇必报。声望 +20，机缘 +1"),
            ]
        }),
        _c("不借，婉拒离开", rewards={}, flavor="书生叹气让路，你径自离开。"),
    ]
))

EVENTS.append(_e(
    "崖顶鹰巢",
    "峭壁顶端有一个巨大的鹰巢，巢中隐约有雏鹰鸣叫。若攀上去，或能取到灵禽之卵或羽毛，但成鹰随时可能归来。",
    [
        _c("攀崖探巢", next_event={
            "desc": "你攀至巢边，巢中有两枚蛋和几根泛着灵光的羽毛。远处传来一声鹰唳。",
            "choices": [
                _c("取一枚蛋和几根羽毛便走", condition=_cond("physique", 7), rewards={"spirit_stones": 120, "physique": 1}, flavor="你速取速退，成鹰未及赶回。灵蛋与灵羽售得高价。灵石 +120，体魄 +1"),
                _c("取一枚蛋和几根羽毛便走", rewards={"lifespan": -8, "spirit_stones": 60}, flavor="成鹰赶回，你被啄伤后逃下山崖。寿元 -8，灵石 +60"),
                _c("只取羽毛，不碰蛋", condition=_cond("fortune", 6), rewards={"fortune": 1, "spirit_stones": 70}, flavor="你只取羽毛，成鹰归巢后未追击。机缘 +1，灵石 +70"),
                _c("只取羽毛，不碰蛋", rewards={"spirit_stones": 40}, flavor="你取了几根羽毛便退下。灵石 +40"),
            ]
        }),
        _c("不冒险，离开", rewards={}, flavor="你不想招惹灵禽，转身离开。"),
    ]
))

EVENTS.append(_e(
    "古钟残响",
    "荒寺中有一口锈迹斑斑的古钟，风吹过时发出低沉的嗡鸣。据说曾有人在此闻钟悟道。",
    [
        _c("在钟旁静坐聆听", next_event={
            "desc": "钟声时有时无，你闭目聆听，心神随之起伏。若能抓住那一瞬的共鸣，或有所得。",
            "choices": [
                _c("全心感应钟韵", condition=_cond("soul", 7), rewards={"soul": 1, "cultivation": 80}, flavor="你与钟韵共鸣，神识与修为皆进。神识 +1，修为 +80"),
                _c("全心感应钟韵", rewards={"cultivation": 45}, flavor="你略有所感，修为小有进境。修为 +45"),
                _c("以悟性参悟钟中意", condition=_cond("comprehension", 6), rewards={"comprehension": 1, "cultivation": 60}, flavor="你从钟声中悟出一丝禅意。悟性 +1，修为 +60"),
                _c("以悟性参悟钟中意", rewards={"cultivation": 30}, flavor="钟意玄奥，你只抓住一点。修为 +30"),
            ]
        }),
        _c("轻敲古钟试音", rewards={"lifespan": 5}, flavor="钟声清越，你心神一静。寿元 +5"),
        _c("不打扰，离去", rewards={}, flavor="你未动古钟，悄然离开。"),
    ]
))

EVENTS.append(_e(
    "瘴气边缘",
    "前方山谷弥漫着淡绿色瘴气，草木枯黄。据说瘴气深处有珍稀灵菇，但吸入过多会损及修为与寿元。",
    [
        _c("服下避瘴丹后深入", next_event={
            "desc": "你在瘴气中搜寻，避瘴丹效力有限，需尽快找到灵菇并退出。",
            "choices": [
                _c("快速搜寻灵菇", condition=_cond("fortune", 7), rewards={"spirit_stones": 100, "lifespan": -5}, flavor="你找到几株灵菇后迅速退出，售出得利，但瘴气略伤元气。灵石 +100，寿元 -5"),
                _c("快速搜寻灵菇", rewards={"lifespan": -12, "spirit_stones": 40}, flavor="你搜寻过久，瘴气侵体，只带回少量灵菇。寿元 -12，灵石 +40"),
                _c("见好就收，浅入即出", condition=_cond("soul", 6), rewards={"soul": 1, "spirit_stones": 60}, flavor="你以神识辨路，浅入即出，收获尚可。神识 +1，灵石 +60"),
                _c("见好就收，浅入即出", rewards={"spirit_stones": 35}, flavor="你未敢深入，只在外围采到少许。灵石 +35"),
            ]
        }),
        _c("不进入，绕道", rewards={"lifespan": -1}, flavor="你绕道而行，多费了些时辰。寿元 -1"),
        _c("只在瘴气边缘采集", rewards={"spirit_stones": 40}, flavor="你在边缘采到几株普通灵草。灵石 +40"),
    ]
))

EVENTS.append(_e(
    "茶摊论道",
    "路边茶摊坐着几位修士，正在争论「道在何方」。见你路过，有人招呼：「这位道友，可有高见？」",
    [
        _c("坐下参与论道", next_event={
            "desc": "众人各抒己见，有人重修行，有人重机缘，有人重心境。轮到你时，你需言之有物。",
            "choices": [
                _c("以自身感悟作答", condition=_cond("comprehension", 7), rewards={"comprehension": 1, "reputation": 15}, flavor="你的见解得到众人认可，悟性与声望皆进。悟性 +1，声望 +15"),
                _c("以自身感悟作答", rewards={"cultivation": 50}, flavor="你畅所欲言，心境舒畅，修为略增。修为 +50"),
                _c("虚心请教，少说多听", condition=_cond("soul", 6), rewards={"soul": 1, "cultivation": 60}, flavor="你从众人言语中听出不少门道。神识 +1，修为 +60"),
                _c("虚心请教，少说多听", rewards={"reputation": 10}, flavor="众人觉得你谦逊，对你印象不错。声望 +10"),
            ]
        }),
        _c("婉拒，称赶路匆忙", rewards={}, flavor="你拱手告辞，继续赶路。"),
    ]
))

EVENTS.append(_e(
    "地动裂缝",
    "方才一阵地动，地面裂开一道尺余宽的裂缝，深不见底。裂缝中隐约有灵气上涌，不知底下有何物。",
    [
        _c("以绳索下探", next_event={
            "desc": "你缓缓下降，裂缝内壁有结晶状灵矿，深处似乎有微光。绳索长度有限，你需决定下探多深。",
            "choices": [
                _c("下探至微光处", condition=_cond("fortune", 7), rewards={"spirit_stones": 130, "bone": 1}, flavor="微光来自一块灵晶，你取回后售出高价，灵晶之气淬体，根骨略增。灵石 +130，根骨 +1"),
                _c("下探至微光处", rewards={"lifespan": -6, "spirit_stones": 50}, flavor="底下有瘴气，你取到小块灵矿后攀上，略损元气。寿元 -6，灵石 +50"),
                _c("只取壁上的灵矿便上", condition=_cond("physique", 6), rewards={"physique": 1, "spirit_stones": 70}, flavor="你取了几块灵矿后攀上，体魄在攀爬中有所锻炼。体魄 +1，灵石 +70"),
                _c("只取壁上的灵矿便上", rewards={"spirit_stones": 45}, flavor="你取了些灵矿后返回。灵石 +45"),
            ]
        }),
        _c("不冒险，绕开裂缝", rewards={}, flavor="你绕开裂缝继续前行。"),
    ]
))

EVENTS.append(_e(
    "灵蝶引路",
    "一只泛着灵光的蝴蝶在你面前盘旋数圈，似乎想引你去某处。它飞一段便停一停，像是在等你跟上。",
    [
        _c("跟随灵蝶", next_event={
            "desc": "灵蝶将你引至一株古树下，树根处有一小洞，洞中隐约有灵光。灵蝶在洞口盘旋不去。",
            "choices": [
                _c("伸手入洞探查", condition=_cond("fortune", 6), rewards={"spirit_stones": 90, "fortune": 1}, flavor="洞中是一小窝灵蝶卵与几块灵蜜，你取走灵蜜售出。灵石 +90，机缘 +1"),
                _c("伸手入洞探查", rewards={"lifespan": -2, "spirit_stones": 30}, flavor="洞中有小虫咬了你一口，你只取到少许灵蜜。寿元 -2，灵石 +30"),
                _c("不取洞中物，只观灵蝶", rewards={"fortune": 1, "cultivation": 40}, flavor="你未贪心，灵蝶绕你飞了几圈后散去，你心有所感。机缘 +1，修为 +40"),
            ]
        }),
        _c("不跟，继续原路", rewards={}, flavor="你未随灵蝶，径自离开。"),
    ]
))

EVENTS.append(_e(
    "石碑试力",
    "路旁立着一块试力碑，碑上刻着「留痕者可得赏」。已有不少深浅不一的掌印拳印留在碑上。",
    [
        _c("运功在碑上留痕", next_event={
            "desc": "你凝气于掌，向石碑拍去。碑身微震，留下一个浅印。一旁有人道：「留痕逾寸可领赏。」",
            "choices": [
                _c("再试一次，全力出手", condition=_cond("physique", 7), rewards={"physique": 1, "spirit_stones": 80}, flavor="你第二掌留下深痕，领到赏银，体魄亦在发力中有所精进。体魄 +1，灵石 +80"),
                _c("再试一次，全力出手", rewards={"spirit_stones": 30}, flavor="你留痕仍不足一寸，只领到少许赏银。灵石 +30"),
                _c("以巧劲击碑", condition=_cond("comprehension", 6), rewards={"comprehension": 1, "spirit_stones": 60}, flavor="你以巧劲在碑上留下深痕，领赏后悟性略增。悟性 +1，灵石 +60"),
                _c("以巧劲击碑", rewards={"spirit_stones": 25}, flavor="巧劲不足，留痕仍浅。灵石 +25"),
            ]
        }),
        _c("不试，离开", rewards={}, flavor="你对试力无兴趣，径自离开。"),
    ]
))

EVENTS.append(_e(
    "荒坟磷火",
    "荒野中有几座荒坟，夜间磷火飘荡。有传言说此地曾有修士坐化，坟中或留遗物，但阴气极重。",
    [
        _c("在坟周查探", next_event={
            "desc": "你绕坟一周，发现一座坟前有松动的石板，似被人动过。磷火在你靠近时微微摇曳。",
            "choices": [
                _c("移开石板查看", condition=_cond("soul", 6), rewards={"soul": 1, "spirit_stones": 70}, flavor="你以神识护体，取出一只储物袋，内有些灵石。神识 +1，灵石 +70"),
                _c("移开石板查看", rewards={"lifespan": -5, "spirit_stones": 30}, flavor="阴气侵体，你取到少量灵石后速退，略损元气。寿元 -5，灵石 +30"),
                _c("不启坟，只在外行礼", rewards={"reputation": 10, "fortune": 1}, flavor="你恭敬行礼后离开，未动坟茔。冥冥中似得福缘。声望 +10，机缘 +1"),
            ]
        }),
        _c("不靠近，绕行", rewards={}, flavor="你不想招惹阴气，绕道离开。"),
    ]
))

EVENTS.append(_e(
    "驯兽师邀约",
    "一名驯兽师牵着一头灵犬拦住你，道：「道友可愿与我这灵犬比试一番脚力？若你赢，我赠你一颗驯兽丹。」",
    [
        _c("答应比试", next_event={
            "desc": "灵犬撒腿便跑，你在后追赶。山路崎岖，需以体魄与耐力坚持。",
            "choices": [
                _c("全力追赶", condition=_cond("physique", 7), rewards={"physique": 1, "cultivation": 60}, flavor="你追上灵犬，驯兽师兑现承诺，你服下驯兽丹后体魄与修为皆进。体魄 +1，修为 +60"),
                _c("全力追赶", rewards={"cultivation": 35}, flavor="你未能追上，但驯兽师仍赠你半颗丹药。修为 +35"),
                _c("以神识感应灵犬路线，抄近道", condition=_cond("soul", 6), rewards={"soul": 1, "spirit_stones": 50}, flavor="你抄近道截住灵犬，驯兽师改赠你灵石。神识 +1，灵石 +50"),
                _c("以神识感应灵犬路线，抄近道", rewards={"spirit_stones": 25}, flavor="你抄了近道但仍慢一步，得少许灵石安慰。灵石 +25"),
            ]
        }),
        _c("婉拒比试", rewards={}, flavor="你拱手告辞。"),
    ]
))

EVENTS.append(_e(
    "旧书摊",
    "坊市角落有个旧书摊，摊主在打盹。架上多是杂书，但有一本封面残破、无字的旧册混在其中。",
    [
        _c("翻看无字旧册", next_event={
            "desc": "你翻开旧册，内页空白，但以灵力或神识触碰时，隐约有字迹浮现。",
            "choices": [
                _c("以灵力注入试探", condition=_cond("soul", 6), rewards={"soul": 1, "cultivation": 70}, flavor="字迹显现，是一段修炼心得，你参悟后神识与修为皆进。神识 +1，修为 +70"),
                _c("以灵力注入试探", rewards={"cultivation": 35}, flavor="字迹模糊，你只悟得零碎。修为 +35"),
                _c("问摊主价钱后买下", condition=_cond("fortune", 6), rewards={"spirit_stones": -15, "comprehension": 1}, flavor="摊主贱卖，你带回后慢慢参悟，悟性略增。灵石 -15，悟性 +1"),
                _c("问摊主价钱后买下", rewards={"spirit_stones": -15}, flavor="你买下旧册，日后或有用处。灵石 -15"),
            ]
        }),
        _c("不买，离开", rewards={}, flavor="你放下旧册离开。"),
    ]
))

EVENTS.append(_e(
    "山泉分流",
    "山腰处一道泉水分为两股，一股清澈，一股略浑。当地人说清泉可饮，浊泉曾有人饮后腹痛。",
    [
        _c("取清泉饮用", rewards={"lifespan": 8}, flavor="清泉甘冽，你饮后神清气爽。寿元 +8"),
        _c("两股各取一些对比", next_event={
            "desc": "你各取一壶，以神识感应，发现浊泉中蕴含的灵气反而更浓，但夹杂一丝暴烈之意。",
            "choices": [
                _c("只饮清泉，弃浊泉", rewards={"lifespan": 8}, flavor="你为求稳妥只饮清泉。寿元 +8"),
                _c("尝试炼化浊泉中的灵气", condition=_cond("physique", 6), rewards={"physique": 1, "cultivation": 60}, flavor="你以体魄化解暴烈之意，炼化浊泉灵气，体魄与修为皆进。体魄 +1，修为 +60"),
                _c("尝试炼化浊泉中的灵气", rewards={"lifespan": -4, "cultivation": 30}, flavor="暴烈之意伤身，你勉强炼化部分。寿元 -4，修为 +30"),
            ]
        }),
        _c("不饮，只取水囊装水", rewards={}, flavor="你装了一囊清泉备用，未饮。"),
    ]
))

EVENTS.append(_e(
    "告示悬赏",
    "城门口贴着一张悬赏：某家灵兽走失，提供线索者赏五十灵石，寻回者赏两百。不少人围观议论。",
    [
        _c("揭榜寻兽", next_event={
            "desc": "你按告示描述在城外搜寻，数日后在一处山谷听到类似灵兽的叫声。",
            "choices": [
                _c("入谷寻声", condition=_cond("fortune", 6), rewards={"spirit_stones": 200, "reputation": 25}, flavor="你找到走失灵兽并送回，领到全额赏银，名声大振。灵石 +200，声望 +25"),
                _c("入谷寻声", rewards={"lifespan": -3, "spirit_stones": 80}, flavor="谷中有妖兽，你受伤后仍将灵兽带出，领到部分赏银。寿元 -3，灵石 +80"),
                _c("先布陷阱再引兽", condition=_cond("comprehension", 6), rewards={"comprehension": 1, "spirit_stones": 180}, flavor="你以智取，设陷阱引灵兽入套，顺利送回。悟性 +1，灵石 +180"),
                _c("先布陷阱再引兽", rewards={"spirit_stones": 100}, flavor="灵兽未中陷阱，你费了一番功夫才寻回。灵石 +100"),
            ]
        }),
        _c("不揭榜，离开", rewards={}, flavor="你对悬赏无兴趣，径自离开。"),
    ]
))

EVENTS.append(_e(
    "藤蔓高墙",
    "前路被一道密实的藤蔓墙挡住，藤蔓粗壮，隐约有灵光流动。若要通过，需斩断或攀越。",
    [
        _c("挥剑斩藤开路", next_event={
            "desc": "藤蔓坚韧，你斩断数根后，断口处渗出乳白色汁液，散发着淡淡灵气。",
            "choices": [
                _c("收集汁液", condition=_cond("fortune", 6), rewards={"spirit_stones": 65, "lifespan": 10}, flavor="汁液可入药，你收集后售出并自留少许服用。灵石 +65，寿元 +10"),
                _c("收集汁液", rewards={"spirit_stones": 40}, flavor="你收集了些汁液，到城中卖了个价。灵石 +40"),
                _c("不理会，继续斩藤通过", condition=_cond("physique", 6), rewards={"physique": 1}, flavor="你硬生生开出一条路，体魄在挥剑中有所锻炼。体魄 +1"),
                _c("不理会，继续斩藤通过", rewards={"lifespan": -2}, flavor="你费力通过，略感疲惫。寿元 -2"),
            ]
        }),
        _c("攀藤越墙", condition=_cond("physique", 6), rewards={"cultivation": 45}, flavor="你攀过藤墙，修为在运功中略增。修为 +45"),
        _c("攀藤越墙", rewards={"lifespan": -3}, flavor="藤蔓湿滑，你跌了一跤。寿元 -3"),
        _c("绕道而行", rewards={"lifespan": -1}, flavor="你绕了远路。寿元 -1"),
    ]
))

EVENTS.append(_e(
    "琴音招魂",
    "夜色中传来若有若无的琴音，循声而去，见一白衣人坐在石上抚琴。他头也不抬道：「听琴者，可留步；扰琴者，请自便。」",
    [
        _c("静立听琴", next_event={
            "desc": "琴曲凄清，你听得出神。曲终时白衣人淡淡道：「此曲名为《招魂》，听罢不魂不守舍者，可赠一物。」",
            "choices": [
                _c("以神识守心，不为曲动", condition=_cond("soul", 7), rewards={"soul": 1, "cultivation": 80}, flavor="你神识稳固，白衣人赠你一枚养神丹。神识 +1，修为 +80"),
                _c("以神识守心，不为曲动", rewards={"cultivation": 50}, flavor="你勉强稳住心神，白衣人赠你几块灵石。修为 +50"),
                _c("坦言曾有一瞬失神", condition=_cond("comprehension", 6), rewards={"comprehension": 1, "reputation": 15}, flavor="白衣人欣赏你的坦诚，与你论道片刻，悟性与声望皆进。悟性 +1，声望 +15"),
                _c("坦言曾有一瞬失神", rewards={"reputation": 10}, flavor="白衣人点头，赠你一句修炼心得。声望 +10"),
            ]
        }),
        _c("不打扰，悄然离开", rewards={}, flavor="你未近前，悄然退走。"),
    ]
))

EVENTS.append(_e(
    "石像睁眼",
    "荒废的祠堂中，一尊石像忽然睁开了眼，目光扫过你。石像口不能言，但一股意念传入你脑海：「试炼……通过……有赏……」",
    [
        _c("接受试炼", next_event={
            "desc": "石像眼中射出一道灵光，将你罩住。你感到周身压力倍增，需以体魄或神识抵御。",
            "choices": [
                _c("以体魄硬抗", condition=_cond("physique", 7), rewards={"physique": 1, "cultivation": 90}, flavor="你撑过灵压，石像颔首，赐你一缕灵气。体魄 +1，修为 +90"),
                _c("以体魄硬抗", rewards={"lifespan": -5, "cultivation": 50}, flavor="你勉强撑住，略损元气。寿元 -5，修为 +50"),
                _c("以神识化解压力", condition=_cond("soul", 7), rewards={"soul": 1, "cultivation": 85}, flavor="你以神识引导灵压，石像赐你感悟。神识 +1，修为 +85"),
                _c("以神识化解压力", rewards={"cultivation": 45}, flavor="你化解部分压力，有所收获。修为 +45"),
            ]
        }),
        _c("拒绝试炼，退出祠堂", rewards={}, flavor="你退出祠堂，石像双眼缓缓闭合。"),
    ]
))
