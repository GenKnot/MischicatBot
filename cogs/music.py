import asyncio
from collections import deque

import discord
from discord.ext import commands

from utils.ytdlp_helper import FFMPEG_OPTIONS, get_ytdl


class MusicCog(commands.Cog, name="Music"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.queue = deque()
        self.current = None
        self._playlist_skip_counts: dict[str, int] = {}
        self._cancelled_playlists: set[str] = set()

    def _is_connected(self, ctx):
        return ctx.voice_client is not None and ctx.voice_client.is_connected()

    async def _ensure_voice(self, ctx):
        if self._is_connected(ctx):
            return True
        if ctx.author.voice and ctx.author.voice.channel:
            await ctx.author.voice.channel.connect()
            return True
        await ctx.send("you need to be in a voice channel first")
        return False

    def _play_next(self, ctx):
        if self.queue:
            source_info = self.queue.popleft()
            self.current = source_info

            playlist_query = source_info.get("playlist_query")
            is_first_from_playlist = source_info.get("is_first_from_playlist")
            if playlist_query and is_first_from_playlist:
                source_info["is_first_from_playlist"] = False
                self.bot.loop.create_task(self._enqueue_playlist_rest(ctx, playlist_query))

            artist = source_info.get("artist") or source_info.get("uploader")
            track = source_info.get("track") or source_info.get("title")
            if artist and track:
                display_name = f"{artist} - {track}"
            else:
                display_name = source_info.get("title", "unknown")

            link = (
                source_info.get("webpage_url")
                or source_info.get("original_url")
                or source_info.get("url")
            )

            embed = discord.Embed(description="正在播放")
            if link:
                value = f"[{display_name}]({link})"
            else:
                value = display_name
            embed.add_field(name="曲目", value=value, inline=False)

            asyncio.run_coroutine_threadsafe(ctx.send(embed=embed), self.bot.loop)

            audio = discord.FFmpegPCMAudio(source_info["url"], **FFMPEG_OPTIONS)
            ctx.voice_client.play(
                audio,
                after=lambda e: asyncio.run_coroutine_threadsafe(
                    self._after_play(ctx, e), self.bot.loop
                ),
            )

    async def _after_play(self, ctx, error):
        if error:
            print(f"playback error: {error}")
        self.current = None
        self._play_next(ctx)

    @commands.hybrid_command(name="join", description="让音乐机器人加入你所在的语音频道")
    async def join(self, ctx):
        if not ctx.author.voice:
            return await ctx.send("you're not in a voice channel")
        channel = ctx.author.voice.channel
        if ctx.voice_client:
            await ctx.voice_client.move_to(channel)
        else:
            await channel.connect()
        await ctx.send(f"joined **{channel.name}**")

    @commands.hybrid_command(name="leave", aliases=["l"], description="让音乐机器人离开当前语音频道并清空队列")
    async def leave(self, ctx):
        if not self._is_connected(ctx):
            return await ctx.send("i'm not in a voice channel")
        self.queue.clear()
        self.current = None
        await ctx.voice_client.disconnect()
        await ctx.send("disconnected")

    @commands.hybrid_command(name="play", aliases=["p"], description="播放或队列一首来自链接或关键词的歌曲")
    async def play(self, ctx, *, query: str):
        if not await self._ensure_voice(ctx):
            return

        is_yt_playlist_link = (
            "list=" in query
            and ("youtube.com" in query or "youtu.be" in query)
        )

        async with ctx.typing():
            loop = asyncio.get_event_loop()
            data = None
            last_error = None

            if is_yt_playlist_link:
                for with_cookies in (True, False):
                    try:
                        ytdl = get_ytdl(with_cookies=with_cookies)
                        ytdl.params["noplaylist"] = True
                        data = await loop.run_in_executor(
                            None, lambda: ytdl.extract_info(query, download=False)
                        )
                        break
                    except Exception as e:
                        last_error = e
                        if not with_cookies:
                            err_msg = str(e)
                            if "Sign in" in err_msg or "bot" in err_msg:
                                await ctx.send("YouTube is blocking requests — try switching browser cookies (set `YTDLP_BROWSER_ORDER` env var, e.g. `edge,chrome`)")
                            elif "Requested format" in err_msg:
                                await ctx.send("format not available for this video, might be age-restricted or region-locked")
                            else:
                                await ctx.send(f"couldn't fetch that: {err_msg[:200]}")
                            return
                if data is None:
                    return

                if "entries" in data and data["entries"]:
                    first = data["entries"][0]
                else:
                    first = data

                info = {
                    "title": first.get("title", "unknown"),
                    "url": first["url"],
                    "webpage_url": first.get("webpage_url") or query,
                    "artist": first.get("artist"),
                    "track": first.get("track"),
                    "uploader": first.get("uploader"),
                    "playlist_query": query,
                    "is_first_from_playlist": True,
                }
                self.queue.append(info)

            else:
                for with_cookies in (True, False):
                    try:
                        ytdl = get_ytdl(with_cookies=with_cookies)
                        data = await loop.run_in_executor(
                            None, lambda: ytdl.extract_info(query, download=False)
                        )
                        break
                    except Exception as e:
                        last_error = e
                        if not with_cookies:
                            err_msg = str(e)
                            if "Sign in" in err_msg or "bot" in err_msg:
                                await ctx.send("YouTube is blocking requests — try switching browser cookies (set `YTDLP_BROWSER_ORDER` env var, e.g. `edge,chrome`)")
                            elif "Requested format" in err_msg:
                                await ctx.send("format not available for this video, might be age-restricted or region-locked")
                            else:
                                await ctx.send(f"couldn't fetch that: {err_msg[:200]}")
                            return
                if data is None:
                    return

                if "entries" in data and data["entries"]:
                    original_url = str(data.get("original_url") or "")
                    entries = [e for e in data["entries"] if e]
                    if original_url.startswith("ytsearch"):
                        first = entries[0]
                        info = {
                            "title": first.get("title", "unknown"),
                            "url": first["url"],
                            "webpage_url": first.get("webpage_url") or query,
                            "artist": first.get("artist"),
                            "track": first.get("track"),
                            "uploader": first.get("uploader"),
                        }
                        self.queue.append(info)
                        await ctx.send(f"添加到队列: **{info['title']}**")
                    else:
                        for e in entries:
                            info = {
                                "title": e.get("title", "unknown"),
                                "url": e["url"],
                                "webpage_url": e.get("webpage_url") or query,
                                "artist": e.get("artist"),
                                "track": e.get("track"),
                                "uploader": e.get("uploader"),
                            }
                            self.queue.append(info)
                        await ctx.send(
                            f"已从 **{data.get('title', 'playlist')}** 添加 **{len(entries)}** 首歌到播放列表"
                        )
                else:
                    info = {
                        "title": data.get("title", "unknown"),
                        "url": data["url"],
                        "webpage_url": data.get("webpage_url") or query,
                        "artist": data.get("artist"),
                        "track": data.get("track"),
                        "uploader": data.get("uploader"),
                    }
                    self.queue.append(info)
                    await ctx.send(f"添加到队列: **{info['title']}**")

        if not ctx.voice_client.is_playing() and not ctx.voice_client.is_paused():
            self._play_next(ctx)

    async def _enqueue_playlist_rest(self, ctx, query: str):
        """后台加载播放列表剩余的歌曲并加入队列（第一个已在前面入队播放）。"""
        loop = asyncio.get_event_loop()
        data = None
        last_error = None

        if query in self._cancelled_playlists:
            return

        for with_cookies in (True, False):
            try:
                ytdl = get_ytdl(with_cookies=with_cookies)
                ytdl.params["noplaylist"] = False
                data = await loop.run_in_executor(
                    None, lambda: ytdl.extract_info(query, download=False)
                )
                break
            except Exception as e:
                last_error = e
                if not with_cookies:
                    err_msg = str(e)
                    await ctx.send(f"failed to load full playlist: {err_msg[:200]}")
                    return

        if not data or "entries" not in data or not data["entries"]:
            return

        entries = [e for e in data["entries"] if e]
        if not entries:
            return

        rest = entries[1:] if len(entries) > 1 else []
        if not rest:
            return

        for e in rest:
            info = {
                "title": e.get("title", "unknown"),
                "url": e["url"],
                "webpage_url": e.get("webpage_url") or query,
                "artist": e.get("artist"),
                "track": e.get("track"),
                "uploader": e.get("uploader"),
            }
            self.queue.append(info)

        await ctx.send(
            f"已从 **{data.get('title', 'playlist')}** 添加 **{len(rest)}** 首歌到播放列表"
        )
        if ctx.voice_client and not ctx.voice_client.is_playing() and not ctx.voice_client.is_paused() and self.queue:
            self._play_next(ctx)

    @commands.hybrid_command(name="pause", description="暂停当前播放的音乐")
    async def pause(self, ctx):
        if ctx.voice_client and ctx.voice_client.is_playing():
            ctx.voice_client.pause()
            await ctx.send("paused")
        else:
            await ctx.send("nothing is playing")

    @commands.hybrid_command(name="resume", description="继续播放已暂停的音乐")
    async def resume(self, ctx):
        if ctx.voice_client and ctx.voice_client.is_paused():
            ctx.voice_client.resume()
            await ctx.send("resumed")
        else:
            await ctx.send("nothing is paused")

    @commands.hybrid_command(name="stop", aliases=["st"], description="停止播放并清空当前播放队列")
    async def stop(self, ctx):
        self.queue.clear()
        self.current = None
        if ctx.voice_client:
            ctx.voice_client.stop()
        await ctx.send("stopped and cleared the queue")

    @commands.hybrid_command(name="skip", aliases=["s"], description="跳过当前正在播放的歌曲")
    async def skip(self, ctx):
        if ctx.voice_client and ctx.voice_client.is_playing():
            if self.current:
                playlist_query = self.current.get("playlist_query")
                if playlist_query:
                    count = self._playlist_skip_counts.get(playlist_query, 0) + 1
                    self._playlist_skip_counts[playlist_query] = count
                    if count >= 2:
                        self._cancelled_playlists.add(playlist_query)

            ctx.voice_client.stop()
            await ctx.send("skipped")
        else:
            await ctx.send("无正在播放的歌曲")

    @commands.hybrid_command(name="queue", aliases=["q"], description="查看当前歌曲与接下来队列")
    async def queue_cmd(self, ctx):
        if not self.current and not self.queue:
            return await ctx.send("播放队列为空")

        lines = []
        if self.current:
            lines.append(f"**now playing:** {self.current['title']}")
        if self.queue:
            lines.append("**up next:**")
            for i, item in enumerate(self.queue, start=1):
                lines.append(f"  {i}. {item['title']}")

        await ctx.send("\n".join(lines))


async def setup(bot):
    await bot.add_cog(MusicCog(bot))
