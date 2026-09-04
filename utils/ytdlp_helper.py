import logging
import os
import shutil
import sys

import yt_dlp

log = logging.getLogger("mischicat.music")

PREFERRED_BROWSERS = os.getenv("YTDLP_BROWSER_ORDER", "edge,chrome,brave,chromium,firefox,safari").split(",")

# PO token provider 地址，留空则不启用。容器里设成 http://pot-provider:4416。
# 之前起了容器装了插件却没配这个，等于白起。
POT_PROVIDER_URL = os.getenv("POT_PROVIDER_URL", "").strip()


# 缺这两个时报错很隐晦（FFmpegPCMAudio 要到播放时才抛），所以加载时先查一遍
REQUIRED_BINARIES = {
    "ffmpeg": "播放音频（discord.py 的 FFmpegPCMAudio 直接调用它）",
    "node": "yt-dlp 解 YouTube nsig 挑战所需的 JS 运行时",
}


def check_media_dependencies() -> list[str]:
    """返回缺失的可执行文件名列表；同时把结果写进日志。"""
    missing = [name for name in REQUIRED_BINARIES if shutil.which(name) is None]
    if missing:
        for name in missing:
            log.error("缺少可执行文件 %s —— %s", name, REQUIRED_BINARIES[name])
        log.error(
            "音乐功能将无法正常工作。容器部署请确认镜像里装了：%s",
            " ".join(missing),
        )
    else:
        log.info("音乐依赖检查通过：%s", "、".join(REQUIRED_BINARIES))
    return missing


FFMPEG_OPTIONS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn",
}

BASE_OPTIONS = {
    "format": "bestaudio[acodec^=opus]/bestaudio[abr>=192]/bestaudio[abr>=160]/bestaudio/best",
    "outtmpl": "downloads/%(extractor)s-%(id)s-%(title)s.%(ext)s",
    "restrictfilenames": True,
    "noplaylist": False,
    "playlistend": 50,
    "nocheckcertificate": True,
    "ignoreerrors": True,
    "logtostderr": False,
    "quiet": True,
    "no_warnings": True,
    "default_search": "auto",
    "source_address": "0.0.0.0",
    "extractor_args": {
        "youtube": {
            # 是 player_client 不是 player-client，写错了这行就不生效，
            # yt-dlp 会退回默认的 ANDROID_VR，那个取流拿 403。
            # 实测只有 android 能取到 206，后两个留着兜底。
            "player_client": ["android", "tv", "web"],
        },
    },
    "js_runtimes": {"node": {}},
}

if POT_PROVIDER_URL:
    # 键名来自插件 bgutil-ytdlp-pot-provider：'youtubepot-bgutilhttp:base_url'
    BASE_OPTIONS["extractor_args"]["youtubepot-bgutilhttp"] = {
        "base_url": [POT_PROVIDER_URL],
    }


def check_pot_provider(timeout: float = 3.0) -> bool:
    """检查 PO token provider 是否可达（provider 自带 /ping）。

    未配置地址时直接返回 False 并给出提示。这个检查存在的理由和
    `check_media_dependencies` 一样：provider 连不上时 yt-dlp 只会安静地
    退化，最终表现为"YouTube 放不了"，很难定位到是这里。
    """
    if not POT_PROVIDER_URL:
        log.warning(
            "未设置 POT_PROVIDER_URL，未启用 PO token。"
            "数据中心 IP 上 YouTube 大概率会拦截，容器部署建议配置。"
        )
        return False
    import json as _json
    import urllib.request
    try:
        with urllib.request.urlopen(f"{POT_PROVIDER_URL}/ping", timeout=timeout) as r:
            info = _json.loads(r.read().decode("utf-8"))
        log.info("PO token provider 可达：%s（版本 %s）",
                 POT_PROVIDER_URL, info.get("version", "unknown"))
        return True
    except Exception as e:
        log.error("PO token provider 不可达：%s —— %s: %s",
                  POT_PROVIDER_URL, type(e).__name__, e)
        return False


_BROWSER_PATHS = {
    "darwin": {
        "chrome":   "~/Library/Application Support/Google/Chrome",
        "edge":     "~/Library/Application Support/Microsoft Edge",
        "brave":    "~/Library/Application Support/BraveSoftware/Brave-Browser",
        "chromium": "~/Library/Application Support/Chromium",
        "firefox":  "~/Library/Application Support/Firefox",
        "safari":   "~/Library/Safari",
    },
    "linux": {
        "chrome":   "~/.config/google-chrome",
        "chromium": "~/.config/chromium",
        "edge":     "~/.config/microsoft-edge",
        "brave":    "~/.config/BraveSoftware/Brave-Browser",
        "firefox":  "~/.mozilla/firefox",
    },
    "win32": {
        "chrome":   os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\User Data"),
        "edge":     os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\User Data"),
        "brave":    os.path.expandvars(r"%LOCALAPPDATA%\BraveSoftware\Brave-Browser\User Data"),
        "firefox":  os.path.expandvars(r"%APPDATA%\Mozilla\Firefox"),
    },
}


def _has_cookie_store(root: str) -> bool:
    """浏览器目录里是否真的有 cookie 库。

    只判断目录存在是不够的：卸载或从未登录过的浏览器会留下空目录，
    yt-dlp 随后会报 `could not find edge cookies database` 并丢掉 cookie ——
    日志里看到的正是这个。
    """
    root = os.path.expanduser(root)
    if not os.path.isdir(root):
        return False
    # Chromium 系：<root>/<Profile>/Cookies；Firefox：<profile>/cookies.sqlite
    for dirpath, _dirnames, filenames in os.walk(root):
        if "Cookies" in filenames or "cookies.sqlite" in filenames:
            return True
        # 只往下找两层，避免遍历整个浏览器目录
        if dirpath[len(root):].count(os.sep) >= 2:
            _dirnames.clear()
    return False


def _detect_browser():
    platform = "linux" if sys.platform.startswith("linux") else sys.platform
    paths = _BROWSER_PATHS.get(platform, {})
    for browser in PREFERRED_BROWSERS:
        browser = browser.strip()
        if browser in paths and _has_cookie_store(paths[browser]):
            return browser
    for browser, path in paths.items():
        if _has_cookie_store(path):
            return browser
    return None


_browser = _detect_browser()
_cookie_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), "cookies.txt")
_has_cookie_file = os.path.isfile(_cookie_file)

if _has_cookie_file:
    log.info("使用 cookie 文件：%s", _cookie_file)
else:
    log.info("cookie 来源浏览器：%s", _browser or "未找到")


def get_ytdl(with_cookies: bool = True):
    opts = dict(BASE_OPTIONS)
    if with_cookies:
        if _has_cookie_file:
            opts["cookiefile"] = _cookie_file
        elif _browser:
            opts["cookiesfrombrowser"] = (_browser,)
    return yt_dlp.YoutubeDL(opts)


def build_ffmpeg_options(http_headers: dict | None = None):
    """
    Build per-track ffmpeg options.

    Some sites (e.g. bilibili) require specific HTTP headers (User-Agent, Referer)
    on the media request. yt_dlp exposes these via the `http_headers` field in
    the extraction result. We inject them into ffmpeg via the -headers option.
    """
    opts = dict(FFMPEG_OPTIONS)
    if http_headers:
        # Build header block as required by ffmpeg: one header per line, CRLF-terminated.
        header_lines = "".join(f"{k}: {v}\r\n" for k, v in http_headers.items())
        extra = f'-headers "{header_lines}"'
        before = opts.get("before_options", "")
        opts["before_options"] = (before + " " + extra).strip()
    return opts


# 音乐命令收的是任意用户给的任意字符串，直接丢给 yt-dlp 抓，等于开了个
# SSRF 口子 —— 在 k8s 里 pod 能摸到集群内部服务和 169.254.169.254。
# 所以链接必须先过域名白名单，非链接当搜索词走。
ALLOWED_MEDIA_HOSTS = (
    "youtube.com", "youtu.be", "music.youtube.com",
    "bilibili.com", "b23.tv",
    "soundcloud.com",
)


def parse_media_url(query: str):
    """把用户输入解析成 URL。不是 http(s) 链接就返回 None（当搜索词处理）。"""
    from urllib.parse import urlparse
    try:
        parsed = urlparse(query.strip())
    except ValueError:
        return None
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return None
    return parsed


def is_allowed_host(hostname: str) -> bool:
    """域名是否在白名单里。按后缀比对，`evil.com/youtube.com` 这种命不中。"""
    host = (hostname or "").lower().rstrip(".")
    return any(host == d or host.endswith("." + d) for d in ALLOWED_MEDIA_HOSTS)


def is_youtube_playlist_link(query: str) -> bool:
    parsed = parse_media_url(query)
    if parsed is None:
        return False
    host = parsed.hostname.lower().rstrip(".")
    on_youtube = host == "youtu.be" or host.endswith("youtube.com") or host == "youtube.com"
    return on_youtube and "list=" in (parsed.query or "")
