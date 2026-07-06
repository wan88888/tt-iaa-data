#!/bin/bash
# 双击运行：一键安装运行环境（Python + 依赖）。
# 运营同学只需第一次双击本文件，装好后用 run.command 抓数据即可。

cd "$(dirname "$0")" || exit 1

echo "==================================================="
echo " TikTok IAA 工具 - 一键安装环境"
echo "==================================================="
echo

# 1) 准备 uv（自带独立 Python，无需预装，也不依赖 Xcode）
export PATH="$HOME/.local/bin:$PATH"
if ! command -v uv >/dev/null 2>&1; then
  echo "[1/3] 未检测到 uv，正在下载安装（需要联网）…"
  if ! curl -LsSf https://astral.sh/uv/install.sh | sh; then
    echo "[错误] uv 安装失败，请检查网络后重试。"
    echo "按回车键关闭…"; read -r _; exit 1
  fi
  export PATH="$HOME/.local/bin:$PATH"
else
  echo "[1/3] 已检测到 uv，跳过安装。"
fi

# 2) 创建虚拟环境
echo "[2/3] 创建虚拟环境 .venv（Python 3.12）…"
if ! uv venv --python 3.12 .venv; then
  echo "[错误] 创建虚拟环境失败。"
  echo "按回车键关闭…"; read -r _; exit 1
fi

# 3) 安装依赖
echo "[3/3] 安装依赖（requests / pyyaml / browser-cookie3 / bigquery）…"
if ! uv pip install --python .venv/bin/python -r requirements.txt; then
  echo "[错误] 依赖安装失败，请检查网络后重试。"
  echo "按回车键关闭…"; read -r _; exit 1
fi

if [ ! -f config.yaml ]; then
  if [ -f config.example.yaml ]; then
    cp config.example.yaml config.yaml
    echo
    echo "已根据 config.example.yaml 生成 config.yaml，请编辑后填入 org_id 等本机配置。"
  fi
fi

echo
echo "==================================================="
echo " 安装完成！✓"
echo " 以后每天双击 run.command 即可抓取数据。"
echo "==================================================="
echo
echo "按回车键关闭此窗口…"
read -r _
