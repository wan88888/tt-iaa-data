#!/bin/bash
# 双击运行：卸载「每天定时自动抓取」定时任务。

cd "$(dirname "$0")" || exit 1

LABEL="com.tt.iaa.daily"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null
launchctl unload "$PLIST" 2>/dev/null

if [ -f "$PLIST" ]; then
  rm -f "$PLIST"
  echo "已卸载定时任务。"
else
  echo "未找到定时任务（可能尚未安装）。"
fi

echo
echo "按回车键关闭此窗口…"
read -r _
