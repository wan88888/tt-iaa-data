#!/bin/bash
# 双击运行：拉取 TikTok IAA 数据并打开结果文件夹。
# 运营同学无需懂命令行，双击本文件即可。

cd "$(dirname "$0")" || exit 1

echo "==================================================="
echo " TikTok 应用内广告(IAA) 数据抓取"
echo "==================================================="

# 选择 Python：优先项目虚拟环境
if [ -x ".venv/bin/python" ]; then
  PY=".venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PY="python3"
else
  echo "[错误] 没找到可用的 Python，请先安装环境（见 README.md）。"
  echo "按回车键关闭…"; read -r _; exit 1
fi

echo "使用 Python: $PY"
echo "开始抓取（约需 30-60 秒）…"
echo

"$PY" scraper.py "$@"
STATUS=$?

echo
if [ $STATUS -eq 0 ]; then
  echo "[完成] 结果已生成，正在打开 output 文件夹…"
  open output 2>/dev/null
else
  echo "[失败] 退出码 $STATUS。常见原因：Cookie 过期（重新复制到 config.yaml）。"
fi

echo
echo "按回车键关闭此窗口…"
read -r _
