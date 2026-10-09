"""钱庄面板（utils/views/bank.py）：按钮、表单、下拉选择与提示文案。账务本身见 test_bank.py。"""

import time

import pytest

from tests.conftest import make_player
from tests.discord_fakes import FakeInteraction
from utils import bank
from utils.bank import MIN_DEPOSIT, TERM_OPTIONS
from utils.views import bank as bv
from utils.views.bank import (BackToBankButton, BankMainView, DemandDepositModal, DemandWithdrawModal,
                              TermDepositModal, TermDepositSelectView, TermSelect, TermWithdrawSelect,
                              TermWithdrawSelectView, TransferModal, _bank_main_embed, _format_due,
                              _term_select_embed, _term_withdraw_embed)

U = "1001"
YEAR = 7200


async def _add(db, uid=U, stones=100_000, city="灵虚城"):
    D = db["db_async"]
    p = make_player(D, uid, stones=stones)
    p.name = f"道友{uid}"
    p.current_city = city
    async with D.AsyncSessionLocal() as s:
        s.add(p)
        await s.commit()


async def stones(db, uid=U):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        return (await s.get(D.Player, uid)).spirit_stones


def inter(uid=U):
    return FakeInteraction(uid)


def author(uid=U):
    return inter(uid).user


async def main_view(db=None):
    player = await bv._get_player(U)
    account = await bank.get_bank_account(U)
    deposits = await bank.get_term_deposits(U)
    return BankMainView(author(), player, account, deposits, cog=None)


def modal_with(modal, **values):
    for k, v in values.items():
        getattr(modal, k)._value = v
    return modal


def footer(i):
    return (i.edited[-1].embed.footer.text if i.edited else i.last.embed.footer.text)


# --- 主界面文案 ---------------------------------------------------------------

def deposit_row(**kw):
    now = time.time()
    base = dict(deposit_id="ab12cd34", principal=20_000, term_years=10, interest=2000, due_at=now + 5 * YEAR)
    base.update(kw)
    return base


def test_主界面_没有存款():
    e = _bank_main_embed({"spirit_stones": 1234}, {"demand_balance": 0, "demand_deposited_at": 0}, [])
    assert "1,234" in e.description
    f = {x.name: x.value for x in e.fields}
    assert "0** 灵石" in f["活期余额"] and f["定期存款"] == "暂无" and "10年" in f["定期利率表（单利）"]


def test_主界面_活期显示利息():
    acc = {"demand_balance": 10_000, "demand_deposited_at": time.time() - 100 * YEAR}
    f = {x.name: x.value for x in _bank_main_embed({"spirit_stones": 0}, acc, []).fields}
    assert "10,000" in f["活期余额"] and "利息 +1,000" in f["活期余额"] and "0.1%" in f["活期余额"]


def test_主界面_定期存款区分到期与未到期():
    now = time.time()
    deps = [deposit_row(deposit_id="aaaa1111", due_at=now - 10), deposit_row(deposit_id="bbbb2222", due_at=now + 5 * YEAR)]
    text = {x.name: x.value for x in _bank_main_embed({"spirit_stones": 0}, {}, deps).fields}["定期存款"]
    lines = text.splitlines()
    assert "aaaa1111" in lines[0] and "已到期" in lines[0] and "20,000" in lines[0] and "利息+2,000" in lines[0]
    assert "bbbb2222" in lines[1] and "还剩 5.0 年" in lines[1]


def test_主界面_账户字段缺失也不崩():
    _bank_main_embed({}, {}, [])


def test_期限选择文案列出全部期限():
    e = _term_select_embed()
    assert len(e.fields) == len(TERM_OPTIONS) and f"{MIN_DEPOSIT:,}" in e.description


def test_取出定期文案_到期可取本息_未到期只取本金():
    now = time.time()
    e = _term_withdraw_embed([deposit_row(deposit_id="aaaa1111", due_at=now - 1),
                              deposit_row(deposit_id="bbbb2222", due_at=now + YEAR)])
    assert "可取：**22,000**" in e.fields[0].value and "已到期" in e.fields[0].value
    assert "可取：**20,000**" in e.fields[1].value


def test_到期时间文案():
    assert _format_due(time.time() - 5) == "已到期"
    assert _format_due(time.time() + 3 * YEAR) == "3.0 游戏年后"


# --- 主界面按钮 ---------------------------------------------------------------

async def test_只有本人能操作面板(db):
    await _add(db)
    v = await main_view()
    other = inter("2002")
    assert await v.interaction_check(other) is False and other.last.ephemeral


@pytest.mark.parametrize("btn,modal", [("demand_deposit_btn", DemandDepositModal),
                                       ("demand_withdraw_btn", DemandWithdrawModal),
                                       ("transfer_btn", TransferModal)])
async def test_按钮弹出对应表单(db, btn, modal):
    await _add(db)
    v = await main_view()
    i = inter()
    await getattr(v, btn).callback(i)
    assert isinstance(i.modal, modal)


async def test_定期存款按钮_进入期限选择(db):
    await _add(db)
    v = await main_view()
    i = inter()
    await v.term_deposit_btn.callback(i)
    assert isinstance(i.last.view, TermDepositSelectView) and "选择期限" in i.last.embed.title


async def test_取出定期按钮_没有存款时提示(db):
    await _add(db)
    v = await main_view()
    i = inter()
    await v.term_withdraw_btn.callback(i)
    assert "没有活跃的定期存款" in i.last and i.last.ephemeral


async def test_取出定期按钮_有存款进入选择(db):
    await _add(db)
    await bank.deposit_term(U, MIN_DEPOSIT, 10)
    v = await main_view()
    i = inter()
    await v.term_withdraw_btn.callback(i)
    assert isinstance(i.last.view, TermWithdrawSelectView)


async def test_返回城市按钮(db):
    await _add(db)
    v = await main_view()
    i = inter()
    await v.back_btn.callback(i)
    assert i.last.embed is not None and i.last.view is not None and not isinstance(i.last.view, BankMainView)


# --- 活期表单 -----------------------------------------------------------------

@pytest.mark.parametrize("raw", ["abc", "", "1.5", "一千"])
@pytest.mark.parametrize("cls", [DemandDepositModal, DemandWithdrawModal, TermDepositModal, TransferModal])
async def test_表单_非数字被拒(db, cls, raw):
    await _add(db)
    m = cls(author(), None) if cls is not TermDepositModal else cls(author(), 10, None)
    modal_with(m, amount_input=raw)
    if cls is TransferModal:
        modal_with(m, target_input="1002")
    i = inter()
    await m.on_submit(i)
    assert "请输入有效数字" in i.last and i.last.ephemeral and await stones(db) == 100_000


async def test_活期存入表单_成功后刷新面板(db):
    await _add(db)
    m = modal_with(DemandDepositModal(author(), None), amount_input=" 1,500 ")
    i = inter()
    await m.on_submit(i)
    assert await stones(db) == 98_500 and i.response.deferred
    assert "已存入活期 **1,500**" in footer(i) and isinstance(i.edited[-1].view, BankMainView)


async def test_活期存入表单_失败时原样转述原因(db):
    await _add(db, stones=10)
    m = modal_with(DemandDepositModal(author(), None), amount_input="500")
    i = inter()
    await m.on_submit(i)
    assert "灵石不足" in i.last and i.last.ephemeral and not i.edited


async def test_活期取出表单(db):
    await _add(db)
    await bank.deposit_demand(U, 10_000)
    m = modal_with(DemandWithdrawModal(author(), None), amount_input="4000")
    i = inter()
    await m.on_submit(i)
    assert "取出 **4,000**" in footer(i) and await stones(db) == 94_000

    m = modal_with(DemandWithdrawModal(author(), None), amount_input="999999")
    i = inter()
    await m.on_submit(i)
    assert "可取金额为" in i.last and i.last.ephemeral


async def test_转账表单(db):
    await _add(db)
    await _add(db, "1002", stones=0)
    m = modal_with(TransferModal(author(), None), amount_input="1000", target_input=" 1002 ")
    i = inter()
    await m.on_submit(i)
    assert "道友1002" in footer(i) and "手续费 20" in footer(i)
    assert await stones(db, "1002") == 1000 and await stones(db) == 100_000 - 1020


async def test_转账表单_对方不存在(db):
    await _add(db)
    m = modal_with(TransferModal(author(), None), amount_input="1000", target_input="999")
    i = inter()
    await m.on_submit(i)
    assert "对方角色不存在" in i.last and await stones(db) == 100_000


async def test_表单用点击者身份而不是面板作者(db):
    """表单只会发给点按钮的人，但提交身份取自 interaction.user —— 钱只会动提交者自己的账。"""
    await _add(db)
    await _add(db, "2002")
    m = modal_with(DemandDepositModal(author(U), None), amount_input="100")
    await m.on_submit(inter("2002"))
    assert await stones(db, "2002") == 99_900 and await stones(db) == 100_000


# --- 定期 ---------------------------------------------------------------------

async def test_期限下拉_选项与返回按钮(db):
    v = TermDepositSelectView(author(), None)
    sel = next(c for c in v.children if isinstance(c, TermSelect))
    assert [o.value for o in sel.options] == [str(t["years"]) for t in TERM_OPTIONS]
    assert any(isinstance(c, BackToBankButton) for c in v.children)


async def test_期限下拉_选择后弹出带期限的表单(db):
    v = TermDepositSelectView(author(), None)
    sel = next(c for c in v.children if isinstance(c, TermSelect))
    sel._values = ["50"]
    i = inter()
    await sel.callback(i)
    assert isinstance(i.modal, TermDepositModal) and i.modal.term_years == 50


async def test_定期存入表单(db):
    await _add(db)
    m = modal_with(TermDepositModal(author(), 20, None), amount_input="20000")
    i = inter()
    await m.on_submit(i)
    assert "20年期" in footer(i) and "到期可得利息 **6,000**" in footer(i) and "游戏年后" in footer(i)
    assert await stones(db) == 80_000


async def test_定期存入表单_低于最低额(db):
    await _add(db)
    m = modal_with(TermDepositModal(author(), 10, None), amount_input="19999")
    i = inter()
    await m.on_submit(i)
    assert "最低" in i.last and i.last.ephemeral


async def test_取出下拉_最多25项(db):
    deps = [deposit_row(deposit_id=f"id{i:06d}") for i in range(30)]
    v = TermWithdrawSelectView(author(), deps, None)
    sel = next(c for c in v.children if isinstance(c, TermWithdrawSelect))
    assert len(sel.options) == 25


async def _withdraw(db, due_in):
    await _add(db)
    dep = (await bank.deposit_term(U, MIN_DEPOSIT, 10))["deposit_id"]
    from sqlalchemy import update
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        await s.execute(update(D.BankDeposit).where(D.BankDeposit.deposit_id == dep).values(due_at=time.time() + due_in))
        await s.commit()
    deposits = await bank.get_term_deposits(U)
    v = TermWithdrawSelectView(author(), deposits, None)
    sel = next(c for c in v.children if isinstance(c, TermWithdrawSelect))
    sel._values = [dep]
    i = inter()
    await sel.callback(i)
    return i


async def test_取出下拉_到期(db):
    i = await _withdraw(db, -1)
    assert "到期取出 **22,000**" in footer(i) and "本金 20,000 + 利息 2,000" in footer(i)
    assert isinstance(i.last.view, BankMainView) and await stones(db) == 102_000


async def test_取出下拉_提前(db):
    i = await _withdraw(db, 5 * YEAR)
    assert "提前取出本金 **20,000**" in footer(i) and "利息全损" in footer(i)


async def test_取出下拉_已被取走(db):
    await _add(db)
    dep = (await bank.deposit_term(U, MIN_DEPOSIT, 10))["deposit_id"]
    await bank.withdraw_term(U, dep)
    v = TermWithdrawSelectView(author(), [deposit_row(deposit_id=dep)], None)
    sel = next(c for c in v.children if isinstance(c, TermWithdrawSelect))
    sel._values = [dep]
    i = inter()
    await sel.callback(i)
    assert "已结算" in i.last and i.last.ephemeral and await stones(db) == 100_000


async def test_返回钱庄按钮(db):
    await _add(db)
    v = TermDepositSelectView(author(), None)
    btn = next(c for c in v.children if isinstance(c, BackToBankButton))
    i = inter()
    await btn.callback(i)
    assert isinstance(i.last.view, BankMainView) and "钱庄" in i.last.embed.title


async def test_成功后表单都先defer再编辑原消息(db):
    """真实的 Discord 里不先响应就 edit_original_response 会报『未知交互』。"""
    await _add(db)
    await _add(db, "1002", stones=0)
    await bank.deposit_demand(U, 5_000)
    cases = [
        modal_with(DemandDepositModal(author(), None), amount_input="100"),
        modal_with(DemandWithdrawModal(author(), None), amount_input="100"),
        modal_with(TermDepositModal(author(), 10, None), amount_input="20000"),
        modal_with(TransferModal(author(), None), amount_input="100", target_input="1002"),
    ]
    for m in cases:
        i = inter()
        await m.on_submit(i)
        assert i.response.deferred and i.edited, type(m).__name__
