#!/bin/zsh
cd -- "$(dirname -- "$0")"
python3 local_service.py stop
if [ $? -ne 0 ]; then
  echo '停止未成功。请查看上方提示，按回车退出。'
  read
fi
