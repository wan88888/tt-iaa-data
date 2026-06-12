#!/bin/bash
# 双击运行：把「每天定时自动抓取」安装为 macOS 定时任务(launchd)。
# 默认每天 10:00 和 18:00 各执行一次，可在下方修改 TIMES。

cd "$(dirname "$0")" || exit 1
ROOT="$(pwd)"

# ===== 执行时间（24 小时制，HH:MM，可加多个）=====
TIMES=("10:00" "18:00")
# =================================================

LABEL="com.tt.iaa.daily"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
WRAPPER="$ROOT/scheduler/run_scheduled.sh"

chmod +x "$WRAPPER" 2>/dev/null

mkdir -p "$HOME/Library/LaunchAgents"

# 由 TIMES 生成多个 <dict> 时间点
INTERVALS=""
for t in "${TIMES[@]}"; do
  H="${t%%:*}"
  M="${t##*:}"
  H=$((10#$H)); M=$((10#$M))
  INTERVALS="$INTERVALS
        <dict>
            <key>Hour</key>
            <integer>$H</integer>
            <key>Minute</key>
            <integer>$M</integer>
        </dict>"
done

cat >"$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>$WRAPPER</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$ROOT</string>
    <key>StartCalendarInterval</key>
    <array>$INTERVALS
    </array>
    <key>StandardOutPath</key>
    <string>$ROOT/logs/launchd.out.log</string>
    <key>StandardErrorPath</key>
    <string>$ROOT/logs/launchd.err.log</string>
</dict>
</plist>
EOF

# 重新加载
launchctl unload "$PLIST" 2>/dev/null
if launchctl load "$PLIST"; then
  echo "已安装定时任务：每天 ${TIMES[*]} 各自动抓取一次。"
  echo "任务文件：$PLIST"
  echo "日志目录：$ROOT/logs/"
  echo
  echo "提示：定时运行时若用浏览器读取 Cookie，请保持已在浏览器登录后台；"
  echo "      也可改用手动 Cookie（config.yaml: cookie_source: config）。"
else
  echo "[错误] 加载定时任务失败，请重试或检查权限。"
fi

echo
echo "按回车键关闭此窗口…"
read -r _
