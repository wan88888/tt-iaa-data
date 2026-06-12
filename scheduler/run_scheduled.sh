#!/bin/bash
# 由 launchd 定时调用：抓取数据并把日志写入 logs/。
# 不依赖终端，失败也会留下日志便于排查。

# 项目根目录 = 本脚本上一级
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT" || exit 1

export PATH="$HOME/.local/bin:$PATH"

mkdir -p logs
LOG="logs/run_$(date +%Y%m%d_%H%M%S).log"

if [ -x ".venv/bin/python" ]; then
  PY=".venv/bin/python"
else
  echo "[错误] 未找到 .venv，请先运行 setup.command 安装环境。" >>"$LOG" 2>&1
  exit 1
fi

echo "===== 定时抓取开始 $(date) =====" >>"$LOG" 2>&1
"$PY" scraper.py >>"$LOG" 2>&1
STATUS=$?
echo "===== 结束 status=$STATUS $(date) =====" >>"$LOG" 2>&1

# 只保留最近 30 个日志文件
ls -1t logs/run_*.log 2>/dev/null | tail -n +31 | xargs rm -f 2>/dev/null

exit $STATUS
