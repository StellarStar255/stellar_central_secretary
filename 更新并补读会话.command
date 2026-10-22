#!/bin/zsh
cd "${0:A:h}"
echo '正在补读最近归档的 ChatGPT 会话，请保持原登录窗口打开。'
./.venv/bin/python -m secretary.diagnose_capture
echo '正在加载新版搜索与采集逻辑…'
exec ./重启知识秘书.command
