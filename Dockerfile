# 钉住次版本。原先是 python:3-slim，会跟着上游滚到最新，Jinja2 + 3.14
# 那几次兼容事故就是这么来的。代码验证过兼容 3.10 语法。
FROM python:3.12-slim

WORKDIR /app

# ffmpeg 是 FFmpegPCMAudio 要的，nodejs 是 yt-dlp 解 nsig 要的
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg nodejs \
 && rm -rf /var/lib/apt/lists/*

# requirements.txt 是 pip-compile 生成的锁文件，含全部传递依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 唯一不锁死的依赖。YouTube 变得快，锁住等于几个月后音乐失效。
# 放在依赖层之后，让每周的定时重建能带上最新版。
RUN pip install --no-cache-dir --upgrade yt-dlp

# 拷贝范围看 .dockerignore
COPY . .

# 把镜像 tag 写进 version.py，ARG 放这里免得版本变动让上面的层失效
ARG APP_VERSION=dev
RUN echo "VERSION = '${APP_VERSION}'" > /app/version.py

EXPOSE 8080

CMD ["python", "main.py"]
