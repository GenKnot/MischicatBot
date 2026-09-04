"""音乐链接解析测试。

原先是 `"youtube.com" in query` 这种子串判断，`evil.com/youtube.com` 也会命中。
更要紧的是命令收的是任意用户给的任意字符串、直接丢给 yt-dlp 抓 ——
在 k8s 里 pod 能摸到集群内部服务和 169.254.169.254。
"""

import pytest

from utils.ytdlp_helper import (is_allowed_host, is_youtube_playlist_link,
                                parse_media_url)


@pytest.mark.parametrize("url", [
    "https://www.youtube.com/watch?v=abc",
    "https://youtube.com/watch?v=abc",
    "https://youtu.be/abc",
    "https://music.youtube.com/watch?v=abc",
    "https://www.bilibili.com/video/BV1",
    "https://b23.tv/abc",
    "https://soundcloud.com/artist/track",
])
def test_白名单站点放行(url):
    assert is_allowed_host(parse_media_url(url).hostname)


@pytest.mark.parametrize("url", [
    "https://evil.com/youtube.com",              # 路径里带白名单域名
    "https://youtube.com.evil.com/",             # 白名单域名当子域前缀
    "https://notyoutube.com/watch?v=abc",        # 后缀相同但不是同一个域
    "http://169.254.169.254/latest/meta-data/",  # 云元数据端点
    "http://10.0.0.5:8080/admin",                # 内网地址
    "http://localhost:8080/",
])
def test_非白名单一律拒绝(url):
    assert not is_allowed_host(parse_media_url(url).hostname), url


@pytest.mark.parametrize("query", [
    "周杰伦 稻香", "some song name", "", "   ",
    "ftp://example.com/a.mp3",        # 非 http(s)
    "file:///etc/passwd",
])
def test_不是_http_链接的当搜索词(query):
    assert parse_media_url(query) is None, query


@pytest.mark.parametrize("url, expected", [
    ("https://www.youtube.com/watch?v=abc&list=PL1", True),
    ("https://youtu.be/abc?list=PL1", True),
    ("https://www.youtube.com/watch?v=abc", False),          # 没有 list=
    ("https://evil.com/youtube.com?list=PL1", False),        # 不是 YouTube
    ("https://www.bilibili.com/video/BV1?list=PL1", False),  # B 站不算
    ("随便一句话 list=", False),
])
def test_播放列表判断(url, expected):
    assert is_youtube_playlist_link(url) is expected, url


def test_域名大小写和结尾点都能处理():
    assert is_allowed_host("WWW.YouTube.COM")
    assert is_allowed_host("youtu.be.")
