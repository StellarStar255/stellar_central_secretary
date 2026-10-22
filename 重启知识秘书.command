#!/bin/zsh
set -e
cd "${0:A:h}"
project_dir="$PWD"
listener_pids=(${(f)"$(/usr/sbin/lsof -t -iTCP:8768 -sTCP:LISTEN 2>/dev/null || true)"})
for listener_pid in $listener_pids; do
  [[ -z "$listener_pid" ]] && continue
  process_command=$(/bin/ps -p "$listener_pid" -o command=)
  process_cwd=$(/usr/sbin/lsof -a -p "$listener_pid" -d cwd -Fn 2>/dev/null | /usr/bin/sed -n 's/^n//p')
  if [[ "$process_command" != *"-m secretary.server"* || "$process_cwd" != "$project_dir" ]]; then
    echo "8768 端口由其他程序占用，未停止该程序。请使用 ./start.sh --port 8770 启动。"
    read -r '?按回车关闭窗口…'
    exit 1
  fi
  echo '正在停止旧版知识秘书…'
  /bin/kill -TERM "$listener_pid"
done
for attempt in {1..40}; do
  if ! /usr/sbin/lsof -t -iTCP:8768 -sTCP:LISTEN >/dev/null 2>&1; then
    exec ./start.sh
  fi
  /bin/sleep 0.2
done
echo '旧服务仍在退出，请稍后再双击本文件。'
read -r '?按回车关闭窗口…'
