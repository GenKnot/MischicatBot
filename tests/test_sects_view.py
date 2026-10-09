"""宗门一览面板（utils/views/sects.py）。加入 / 退出 / 修炼功法命令见 test_sect_cog.py。"""

import discord

from tests.discord_fakes import FakeInteraction
from utils.sects import SECTS
from utils.views.sects import SectAlignmentView, _sects_embed

U = "1001"


def view(cog=None):
    return SectAlignmentView(FakeInteraction(U).user, cog)


def test_宗门列表_正道邪道各列出对应宗门():
    for alignment in ("正道", "邪道"):
        e = _sects_embed(alignment)
        expected = [n for n, d in SECTS.items() if d["alignment"] == alignment]
        assert [f.name.split(" · ")[0] for f in e.fields] == expected and alignment in e.title
        assert expected, alignment


def test_宗门列表_要求文案():
    e = _sects_embed("正道")
    fields = {f.name.split(" · ")[0]: f.value for f in e.fields}
    assert "炼气期5层" in fields["青云宗"] and "单灵根或双灵根灵根" in fields["青云宗"] and "悟性7+" in fields["青云宗"]
    assert "筑基期1层" in fields["天玄门"] and "木或火灵根" in fields["灵药宗"] and "神识6+" in fields["灵药宗"]
    evil = {f.name.split(" · ")[0]: f.value for f in _sects_embed("邪道").fields}
    assert "机缘7+" in evil["合欢宗"] and "体魄8+" in evil["血煞门"]


def test_宗门列表_每个宗门带所在地与简介():
    for f in _sects_embed("正道").fields + _sects_embed("邪道").fields:
        name = f.name.split(" · ")[0]
        assert SECTS[name]["location"] in f.name and SECTS[name]["desc"] in f.value and "入门要求：" in f.value


def test_宗门列表_无要求时显示无特殊要求(monkeypatch):
    from utils import sects as sects_mod
    from utils.views import sects as sv
    fake = {"野路子": {"alignment": "正道", "location": "某地", "desc": "x",
                       "req": {"min_realm": None, "spirit_roots": None, "single_root": False, "min_stat": None, "min_fortune": None}}}
    monkeypatch.setattr(sv, "SECTS", fake)
    assert "无特殊要求" in _sects_embed("正道").fields[0].value
    assert sects_mod.SECTS is not fake


def test_隐世宗门数量与说明一致():
    hidden = [n for n, d in SECTS.items() if d["alignment"] == "隐世"]
    assert len(hidden) == 5                                          # 面板文案写的是『共有五个隐世宗门』


async def test_只有本人能操作():
    other = FakeInteraction("2002")
    assert await view().interaction_check(other) is False


async def test_三个分类按钮():
    v = view()
    for btn, title in ((v.righteous, "正道"), (v.evil, "邪道"), (v.hidden, "隐世")):
        i = FakeInteraction(U)
        await btn.callback(i)
        assert title in i.last.embed.title and i.last.view is v


async def test_返回世界():
    v = view()
    i = FakeInteraction(U)
    await v.back_world.callback(i)
    assert i.last.embed is not None and i.last.view is not None and not isinstance(i.last.view, SectAlignmentView)


async def test_返回主菜单(monkeypatch):
    sent = {}

    async def fake(interaction, cog):
        sent["cog"] = cog
    monkeypatch.setattr("utils.views.world._send_main_menu", fake)
    i = FakeInteraction(U)
    await view().back_menu.callback(i)
    assert "无法返回" in i.last
    marker = object()
    i = FakeInteraction(U)
    await view(marker).back_menu.callback(i)
    assert i.response.deferred and sent["cog"] is marker


def test_嵌入大小在限制内():
    for a in ("正道", "邪道"):
        e = _sects_embed(a)
        assert len(e.fields) <= 25 and all(len(f.value) <= 1024 for f in e.fields) and isinstance(e, discord.Embed)
