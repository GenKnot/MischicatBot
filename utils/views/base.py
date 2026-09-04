"""面板基类。

解决两件事：

1. **超时后按钮"幽灵失效"**。原先 79 个 View 里只有 1 个实现了 `on_timeout`，
   其余超时后按钮看着还在、点了没反应也没提示。
2. **71 处 `interaction_check` 里 64 处一字不差**，各写各的。

`View.message` 在 discord.py 2.7 里不会自动设置，所以这里在 `interaction_check`
里顺手记下来 —— 用户点过一次之后，超时就能编辑那条消息。一次都没点过的面板
拿不到消息，只能让它静默过期（那种情况也没人在看）。
"""

import logging

import discord

log = logging.getLogger(__name__)

# 统一的面板存活时间。原先 60/120/180/300 四种值混用，没有理由。
# 5 分钟：够玩家读完一屏内容再决定，也不至于让 view 在内存里堆太久。
VIEW_TIMEOUT = 300.0

TIMEOUT_NOTICE = "此面板已过期，请重新打开。"


class TimedView(discord.ui.View):
    """带超时提示和归属校验的面板。

    子类传 `author` 就能拿到「这不是你的面板」的校验；想改文案就覆盖
    `not_owner_message`；确实要人人可点的面板（公共事件）传 `author=None`。
    """

    not_owner_message = "这不是你的面板。"

    # 面板是否人人可点。不设 author 又不标 public，会在日志里告警 ——
    # 免得有人漏写 author 就悄悄做出一个谁都能操作的面板。
    # 有些面板的归属校验写在按钮回调里（自己比对 uid），那种也标 public。
    public = False

    def __init__(self, author=None, *, timeout: float | None = VIEW_TIMEOUT):
        super().__init__(timeout=timeout)
        self.author = author
        self.message: discord.Message | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # 顺手记下消息，供 on_timeout 编辑
        if interaction.message is not None:
            self.message = interaction.message
        if self.author is None:
            if not self.public:
                log.warning("%s 没有设置 author 也没有标记 public，任何人都能操作",
                            type(self).__name__)
            return True
        if interaction.user != self.author:
            await interaction.response.send_message(self.not_owner_message, ephemeral=True)
            return False
        return True

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True
        if self.message is None:
            return                      # 没人点过，拿不到消息
        try:
            await self.message.edit(content=TIMEOUT_NOTICE, view=self)
        except discord.HTTPException:
            # 消息被删了或没权限，没别的办法
            log.debug("面板超时提示发送失败", exc_info=True)
