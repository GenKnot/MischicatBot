import os
import sys

import yt_dlp

PREFERRED_BROWSERS = os.getenv("YTDLP_BROWSER_ORDER", "edge,chrome,brave,chromium,firefox,safari").split(",")

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
            "player-client": ["default", "mweb"],
        },
    },
    "js_runtimes": {"node": {}},
}

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


def _detect_browser():
    platform = "linux" if sys.platform.startswith("linux") else sys.platform
    paths = _BROWSER_PATHS.get(platform, {})
    for browser in PREFERRED_BROWSERS:
        browser = browser.strip()
        if browser in paths and os.path.exists(os.path.expanduser(paths[browser])):
            return browser
    for browser, path in paths.items():
        if os.path.exists(os.path.expanduser(path)):
            return browser
    return None


_browser = _detect_browser()
_cookie_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), "cookies.txt")
_has_cookie_file = os.path.isfile(_cookie_file)

if _has_cookie_file:
    print(f"using cookie file: {_cookie_file}")
else:
    print(f"browser for cookies: {_browser or 'none found'}")


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
