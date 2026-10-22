#!/bin/zsh
cd "${0:A:h}"
if (( $# )); then
  exec ./start.sh "$@"
fi
exec ./重启知识秘书.command
