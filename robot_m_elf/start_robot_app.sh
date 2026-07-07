#!/usr/bin/env bash

set -u

PROJECT_DIR="/home/elf/Desktop/robot_m"
APP_URL="http://127.0.0.1:8080"

# Always use the board's system Python and system package paths.
unset VIRTUAL_ENV
unset PYTHONHOME
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

cd "$PROJECT_DIR" || exit 1

if /usr/bin/python3 -c '
import socket
s = socket.socket()
s.settimeout(0.2)
try:
    s.connect(("127.0.0.1", 8080))
except OSError:
    raise SystemExit(1)
finally:
    s.close()
'; then
    echo "机器人控制台已经运行，正在打开网页..."
    /usr/bin/xdg-open "$APP_URL" >/dev/null 2>&1 &
    sleep 1
    exit 0
fi

echo "正在使用系统 Python 启动机器人控制台..."
echo "访问地址：$APP_URL"

(
    for _ in $(seq 1 30); do
        if /usr/bin/python3 -c '
import socket
s = socket.socket()
s.settimeout(0.2)
try:
    s.connect(("127.0.0.1", 8080))
except OSError:
    raise SystemExit(1)
finally:
    s.close()
'; then
            /usr/bin/xdg-open "$APP_URL" >/dev/null 2>&1
            exit 0
        fi
        sleep 0.2
    done
) &

exec /usr/bin/python3 -u robot_app.py --host 0.0.0.0 --port 8080
