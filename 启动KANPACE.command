#!/bin/zsh
cd -- "$(dirname -- "$0")"
python3 launch.py
if [ $? -ne 0 ]; then
  echo '启动未成功。请查看上方提示，按回车退出。'
  read
fi
