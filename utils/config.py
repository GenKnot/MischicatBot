"""应用配置，在模块加载时从环境变量读取（含 .env）。"""
import os

# 命令前缀，与 .env 中 COMMAND_PREFIX 一致，用于所有面向用户的提示文案
COMMAND_PREFIX = os.getenv("COMMAND_PREFIX", "cat!")
