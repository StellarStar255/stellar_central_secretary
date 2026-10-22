#!/bin/zsh
cd "${0:A:h}"
./.venv/bin/python -m secretary.diagnose_capture
read -r '?按回车关闭诊断窗口…'
