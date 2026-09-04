import time
import discord
from sqlalchemy import text
from utils.db_async import AsyncSessionLocal
from utils.bank import (
    BANK_CITIES, TERM_OPTIONS, MIN_DEPOSIT, TRANSFER_MAX, TRANSFER_FEE_RATE,
    DEMAND_RATE, calc_demand_interest, calc_term_interest,
    get_bank_account, get_term_deposits,
    deposit_demand, withdraw_demand, deposit_term, withdraw_term, transfer,
)
from utils.character import seconds_to_years
from utils.views.base import TimedView


async def _get_player(uid: str) -> dict | None:
    async with AsyncSessionLocal() as session:
        result = await session.execute(text("SELECT * FROM players WHERE discord_id = :uid"), {"uid": uid})
        row = result.fetchone()
        return dict(row._mapping) if row else None


def _bank_main_embed(player: dict, account: dict, deposits: list[dict]) -> discord.Embed:
    now = time.time()
    demand_bal = account.get("demand_balance", 0)
    demand_dep_at = account.get("demand_deposited_at") or now
    demand_interest = calc_demand_interest(demand_bal, demand_dep_at) if demand_bal > 0 else 0

    embed = discord.Embed(
        title="🏦 钱庄",
        description=f"灵石：**{player.get('spirit_stones', 0):,}**",
        color=discord.Color.gold(),
    )
    embed.add_field(
        name="活期余额",
        value=f"**{demand_bal:,}** 灵石（利息 +{demand_interest:,}，年利率 {DEMAND_RATE*100:.1f}%）",
        inline=False,
    )

    if deposits:
        lines = []
        for d in deposits:
            due_years = seconds_to_years(d["due_at"] - now)
            matured = now >= d["due_at"]
            status = "✅ 已到期" if matured else f"还剩 {due_years:.1f} 年"
            lines.append(
                f"`{d['deposit_id']}` **{d['principal']:,}** 灵石 · {d['term_years']}年期 · 利息+{d['interest']:,} · {status}"
            )
        embed.add_field(name="定期存款", value="\n".join(lines), inline=False)
    else:
        embed.add_field(name="定期存款", value="暂无", inline=False)

    term_lines = "\n".join(
        f"**{t['years']}年** — 年利率 {t['rate']*100:.2f}%，存{MIN_DEPOSIT:,}到期拿回 {MIN_DEPOSIT + calc_term_interest(MIN_DEPOSIT, t['years'], t['rate']):,}"
        for t in TERM_OPTIONS
    )
    embed.add_field(name="定期利率表（单利）", value=term_lines, inline=False)
    return embed


class BankMainView(TimedView):
    def __init__(self, author, player: dict, account: dict, deposits: list[dict], cog=None):
        super().__init__()
        self.author = author
        self.player = player
        self.account = account
        self.deposits = deposits
        self.cog = cog

    @discord.ui.button(label="💰 存入活期", style=discord.ButtonStyle.success, row=0)
    async def demand_deposit_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(DemandDepositModal(self.author, self.cog))

    @discord.ui.button(label="💸 取出活期", style=discord.ButtonStyle.primary, row=0)
    async def demand_withdraw_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(DemandWithdrawModal(self.author, self.cog))

    @discord.ui.button(label="📅 定期存款", style=discord.ButtonStyle.success, row=0)
    async def term_deposit_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=_term_select_embed(),
            view=TermDepositSelectView(self.author, cog=self.cog),
        )

    @discord.ui.button(label="📤 取出定期", style=discord.ButtonStyle.primary, row=1)
    async def term_withdraw_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.deposits:
            await interaction.response.send_message("没有活跃的定期存款。", ephemeral=True)
            return
        await interaction.response.edit_message(
            embed=_term_withdraw_embed(self.deposits),
            view=TermWithdrawSelectView(self.author, self.deposits, cog=self.cog),
        )

    @discord.ui.button(label="📨 转账", style=discord.ButtonStyle.danger, row=1)
    async def transfer_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(TransferModal(self.author, self.cog))

    @discord.ui.button(label="返回城市", style=discord.ButtonStyle.secondary, row=1)
    async def back_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _go_back(interaction, self.author, self.cog)


class DemandDepositModal(discord.ui.Modal, title="存入活期"):
    amount_input = discord.ui.TextInput(label="存入金额（灵石）", placeholder="输入数字", min_length=1, max_length=12)

    def __init__(self, author, cog):
        super().__init__()
        self.author = author
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        try:
            amount = int(self.amount_input.value.replace(",", "").strip())
        except ValueError:
            await interaction.response.send_message("请输入有效数字。", ephemeral=True)
            return
        uid = str(interaction.user.id)
        result = await deposit_demand(uid, amount)
        if not result["ok"]:
            await interaction.response.send_message(result["reason"], ephemeral=True)
            return
        await interaction.response.defer()
        await _refresh_bank_followup(interaction, uid, self.author, self.cog, f"✅ 已存入活期 **{amount:,}** 灵石。")


class DemandWithdrawModal(discord.ui.Modal, title="取出活期"):
    amount_input = discord.ui.TextInput(label="取出金额（灵石）", placeholder="输入数字", min_length=1, max_length=12)

    def __init__(self, author, cog):
        super().__init__()
        self.author = author
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        try:
            amount = int(self.amount_input.value.replace(",", "").strip())
        except ValueError:
            await interaction.response.send_message("请输入有效数字。", ephemeral=True)
            return
        uid = str(interaction.user.id)
        result = await withdraw_demand(uid, amount)
        if not result["ok"]:
            await interaction.response.send_message(result["reason"], ephemeral=True)
            return
        await interaction.response.defer()
        msg = f"✅ 取出 **{result['withdrawn']:,}** 灵石（含利息 **{result['interest']:,}**）。"
        await _refresh_bank_followup(interaction, uid, self.author, self.cog, msg)


class TransferModal(discord.ui.Modal, title="转账"):
    target_input = discord.ui.TextInput(label="对方 Discord ID", placeholder="输入数字ID", min_length=1, max_length=20)
    amount_input = discord.ui.TextInput(label="转账金额（灵石）", placeholder=f"最多 {TRANSFER_MAX:,}", min_length=1, max_length=12)

    def __init__(self, author, cog):
        super().__init__()
        self.author = author
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        try:
            amount = int(self.amount_input.value.replace(",", "").strip())
        except ValueError:
            await interaction.response.send_message("请输入有效数字。", ephemeral=True)
            return
        uid = str(interaction.user.id)
        target_id = self.target_input.value.strip()
        result = await transfer(uid, target_id, amount)
        if not result["ok"]:
            await interaction.response.send_message(result["reason"], ephemeral=True)
            return
        await interaction.response.defer()
        msg = f"✅ 已向 **{result['receiver_name']}** 转账 **{result['amount']:,}** 灵石（手续费 {result['fee']:,}）。"
        await _refresh_bank_followup(interaction, uid, self.author, self.cog, msg)


def _term_select_embed() -> discord.Embed:
    embed = discord.Embed(
        title="📅 定期存款 · 选择期限",
        description=f"每笔最低 **{MIN_DEPOSIT:,}** 灵石，单利计息，到期自动结算。\n提前取出只退本金，利息全损。",
        color=discord.Color.gold(),
    )
    for t in TERM_OPTIONS:
        interest = calc_term_interest(MIN_DEPOSIT, t["years"], t["rate"])
        embed.add_field(
            name=f"{t['years']} 年期　年利率 {t['rate']*100:.2f}%",
            value=f"存 {MIN_DEPOSIT:,} → 到期拿回 **{MIN_DEPOSIT + interest:,}**",
            inline=True,
        )
    return embed


class TermDepositSelectView(TimedView):
    def __init__(self, author, cog=None):
        super().__init__()
        self.author = author
        self.cog = cog
        options = [
            discord.SelectOption(
                label=f"{t['years']} 年期",
                description=f"年利率 {t['rate']*100:.2f}%，到期拿回 {MIN_DEPOSIT + calc_term_interest(MIN_DEPOSIT, t['years'], t['rate']):,}（以{MIN_DEPOSIT:,}为例）",
                value=str(t["years"]),
            )
            for t in TERM_OPTIONS
        ]
        self.add_item(TermSelect(options))
        self.add_item(BackToBankButton())


class TermSelect(discord.ui.Select):
    def __init__(self, options):
        super().__init__(placeholder="选择存款期限", options=options)

    async def callback(self, interaction: discord.Interaction):
        term_years = int(self.values[0])
        await interaction.response.send_modal(TermDepositModal(self.view.author, term_years, self.view.cog))


class TermDepositModal(discord.ui.Modal, title="定期存款"):
    amount_input = discord.ui.TextInput(label="存入金额（灵石）", placeholder=f"最低 {MIN_DEPOSIT:,}", min_length=1, max_length=12)

    def __init__(self, author, term_years: int, cog):
        super().__init__()
        self.author = author
        self.term_years = term_years
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        try:
            amount = int(self.amount_input.value.replace(",", "").strip())
        except ValueError:
            await interaction.response.send_message("请输入有效数字。", ephemeral=True)
            return
        uid = str(interaction.user.id)
        result = await deposit_term(uid, amount, self.term_years)
        if not result["ok"]:
            await interaction.response.send_message(result["reason"], ephemeral=True)
            return
        await interaction.response.defer()
        due_str = _format_due(result["due_at"])
        msg = f"✅ 已存入 **{amount:,}** 灵石，{self.term_years}年期，到期可得利息 **{result['interest']:,}**，到期时间：{due_str}。"
        await _refresh_bank_followup(interaction, uid, self.author, self.cog, msg)


def _term_withdraw_embed(deposits: list[dict]) -> discord.Embed:
    now = time.time()
    embed = discord.Embed(
        title="📤 取出定期 · 选择存款",
        description="到期可取本息，未到期只退本金。",
        color=discord.Color.gold(),
    )
    for d in deposits:
        matured = now >= d["due_at"]
        due_str = "✅ 已到期" if matured else f"还剩 {seconds_to_years(d['due_at'] - now):.1f} 年"
        payout = d["principal"] + d["interest"] if matured else d["principal"]
        embed.add_field(
            name=f"`{d['deposit_id']}` {d['term_years']}年期",
            value=f"本金 {d['principal']:,} · 利息 {d['interest']:,} · {due_str}\n可取：**{payout:,}**",
            inline=False,
        )
    return embed


class TermWithdrawSelectView(TimedView):
    def __init__(self, author, deposits: list[dict], cog=None):
        super().__init__()
        self.author = author
        self.cog = cog
        now = time.time()
        options = []
        for d in deposits[:25]:
            status_str = "✅到期" if now >= d["due_at"] else f"还剩{seconds_to_years(d['due_at']-now):.0f}年"
            options.append(discord.SelectOption(
                label=f"{d['deposit_id']} · {d['term_years']}年期",
                description=f"本金{d['principal']:,} {status_str}",
                value=d["deposit_id"],
            ))
        self.add_item(TermWithdrawSelect(options))
        self.add_item(BackToBankButton())


class TermWithdrawSelect(discord.ui.Select):
    def __init__(self, options):
        super().__init__(placeholder="选择要取出的存款", options=options)

    async def callback(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        deposit_id = self.values[0]
        result = await withdraw_term(uid, deposit_id)
        if not result["ok"]:
            await interaction.response.send_message(result["reason"], ephemeral=True)
            return
        if result["matured"]:
            msg = f"✅ 到期取出 **{result['payout']:,}** 灵石（本金 {result['principal']:,} + 利息 {result['interest_earned']:,}）。"
        else:
            msg = f"⚠️ 提前取出本金 **{result['payout']:,}** 灵石，利息全损。"
        await _refresh_bank(interaction, uid, self.view.author, self.view.cog, msg)


class BackToBankButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="返回钱庄", style=discord.ButtonStyle.secondary)

    async def callback(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        player = await _get_player(uid)
        account = await get_bank_account(uid)
        deposits = await get_term_deposits(uid)
        await interaction.response.edit_message(
            embed=_bank_main_embed(player, account, deposits),
            view=BankMainView(self.view.author, player, account, deposits, self.view.cog),
        )


def _format_due(due_at: float) -> str:
    now = time.time()
    years_left = seconds_to_years(due_at - now)
    if years_left <= 0:
        return "已到期"
    return f"{years_left:.1f} 游戏年后"


async def _refresh_bank(interaction: discord.Interaction, uid: str, author, cog, msg: str = None):
    player = await _get_player(uid)
    account = await get_bank_account(uid)
    deposits = await get_term_deposits(uid)
    embed = _bank_main_embed(player, account, deposits)
    if msg:
        embed.set_footer(text=msg)
    await interaction.response.edit_message(
        embed=embed,
        view=BankMainView(author, player, account, deposits, cog),
    )


async def _refresh_bank_followup(interaction: discord.Interaction, uid: str, author, cog, msg: str = None):
    player = await _get_player(uid)
    account = await get_bank_account(uid)
    deposits = await get_term_deposits(uid)
    embed = _bank_main_embed(player, account, deposits)
    if msg:
        embed.set_footer(text=msg)
    await interaction.edit_original_response(
        embed=embed,
        view=BankMainView(author, player, account, deposits, cog),
    )


async def _go_back(interaction: discord.Interaction, author, cog):
    from utils.views.city import CityMenuView, _city_menu_embed
    uid = str(interaction.user.id)
    async with AsyncSessionLocal() as session:
        result = await session.execute(text("SELECT * FROM players WHERE discord_id = :uid"), {"uid": uid})
        p = dict(result.fetchone()._mapping)
    await interaction.response.edit_message(
        embed=await _city_menu_embed(p),
        view=CityMenuView(interaction.user, p, cog),
    )
