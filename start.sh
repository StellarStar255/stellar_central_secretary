#!/bin/zsh
set -e
cd "${0:A:h}"
if [[ ! -x .venv/bin/python ]]; then
  python3 -m venv .venv
fi
if ! .venv/bin/python -c 'import pypdf, playwright' >/dev/null 2>&1; then
  if ! .venv/bin/python -m pip install -r requirements.txt; then
    echo '部分依赖暂未安装，文件保存和搜索仍可使用。稍后重新运行此脚本重试。'
  fi
fi
exec .venv/bin/python -m secretary.server "$@"
