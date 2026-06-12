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
else
  echo "[错误] 还没安装运行环境。"
  echo "请先双击同目录下的 setup.command 完成一键安装，再运行本文件。"
  echo "按回车键关闭…"; read -r _; exit 1
fi

echo "开始抓取（约需 30-60 秒）…"
echo

"$PY" scraper.py "$@"
STATUS=$?

echo
if [ $STATUS -eq 0 ]; then
  echo "[完成] 结果已生成，正在打开 output 文件夹…"
  open output 2>/dev/null
elif [ $STATUS -eq 2 ]; then
  echo "[失败] 登录态失效。请按上方提示在浏览器重新登录后台后重试。"
else
  echo "[失败] 退出码 $STATUS。详见上方日志。"
fi

echo
echo "按回车键关闭此窗口…"
read -r _
