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

# 重新加载（用 bootstrap/bootout，比老的 load/unload 在新版 macOS 上更可靠）
UID_NUM="$(id -u)"
DOMAIN="gui/$UID_NUM"

# 先彻底卸载旧任务（两种方式都试一遍，确保清干净）
launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null
launchctl unload "$PLIST" 2>/dev/null

if launchctl bootstrap "$DOMAIN" "$PLIST" 2>/dev/null || launchctl load "$PLIST" 2>/dev/null; then
  echo "已安装定时任务：每天 ${TIMES[*]} 各自动抓取一次。"
  echo "任务文件：$PLIST"
  echo "日志目录：$ROOT/logs/"
else
  echo "[错误] 加载定时任务失败，请重试或检查权限。"
  echo
  echo "按回车键关闭此窗口…"
  read -r _
  exit 1
fi

# ===== 安装后自检 =====
echo
echo "===== 自检 ====="

# 1) 任务是否已注册
if launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1; then
  echo "[OK] 任务已注册到 launchd。"
else
  echo "[警告] 任务似乎未注册成功，建议注销并重新登录系统后再试。"
fi

# 2) 日历触发点是否都已登记
REG_COUNT="$(launchctl print "$DOMAIN/$LABEL" 2>/dev/null | grep -c 'calendarinterval')"
WANT_COUNT="${#TIMES[@]}"
if [ "$REG_COUNT" -ge "$WANT_COUNT" ]; then
  echo "[OK] 已登记 $REG_COUNT 个定时触发点（期望 $WANT_COUNT 个）。"
else
  echo "[警告] 仅登记 $REG_COUNT 个触发点，期望 $WANT_COUNT 个。"
  echo "      这是 macOS 日历调度偶发问题，请『注销并重新登录』一次系统后再双击本脚本。"
fi

# 3) 立即试跑一次，确认脚本本身能正常工作
echo
echo "正在立即试跑一次以验证（约 1 分钟）…"
BEFORE="$(ls -1t logs/run_*.log 2>/dev/null | head -1)"
launchctl kickstart -k "$DOMAIN/$LABEL" 2>/dev/null

# 等待新日志出现并写出结束行（最多等 180 秒）
NEWLOG=""
for i in $(seq 1 60); do
  sleep 3
  LATEST="$(ls -1t logs/run_*.log 2>/dev/null | head -1)"
  if [ -n "$LATEST" ] && [ "$LATEST" != "$BEFORE" ]; then
    NEWLOG="$LATEST"
    if grep -q "结束 status=" "$LATEST" 2>/dev/null; then
      break
    fi
  fi
done

if [ -n "$NEWLOG" ]; then
  STATUS_LINE="$(grep "结束 status=" "$NEWLOG" 2>/dev/null | tail -1)"
  if echo "$STATUS_LINE" | grep -q "status=0"; then
    echo "[OK] 试跑成功。"
    grep -E "总广告收入|数据行数|写入数仓" "$NEWLOG" 2>/dev/null | sed 's/^/      /'
  elif [ -n "$STATUS_LINE" ]; then
    echo "[警告] 试跑结束但非成功状态，请看日志：$NEWLOG"
    tail -5 "$NEWLOG" | sed 's/^/      /'
  else
    echo "[提示] 试跑仍在运行中，稍后可查看日志：$NEWLOG"
  fi
else
  echo "[警告] 未检测到试跑日志，请手动检查 logs/ 目录。"
fi

echo "================"
echo
echo "提示：定时运行时若用浏览器读取 Cookie，请保持已在浏览器登录后台；"
echo "      也可改用手动 Cookie（config.yaml: cookie_source: config，更适合无人值守）。"
echo "若两次定时（${TIMES[*]}）仍不触发，请『注销并重新登录』系统一次，让日历事件重新注册。"

echo
echo "按回车键关闭此窗口…"
read -r _
