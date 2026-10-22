#!/bin/zsh
cd "${0:A:h}"
./.venv/bin/python -m secretary.retry_summary
read -r '?按回车关闭窗口…'
