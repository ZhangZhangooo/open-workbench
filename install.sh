#!/usr/bin/env bash
# OpenWorkbench 环境一键脚本（macOS / Linux）
#
#   bash install.sh          # 每一步都先告诉你命令、等你按回车才执行
#   bash install.sh --yes    # 全自动，不再询问（CI / 熟练用户）
#
# 它做的事：
#   1 检查 Python 3.8+      2 装/起 Ollama      3 拉两个云端模型
#   4 装 OpenClaw           5 生成 config.json（指向本机 Ollama）
#
# 它明确不做的事：
#   - 不静默跑远程安装脚本（默认每步都问，--yes 才自动）
#   - 绝不覆盖已有 config.json：先备份成 config.json.bak.<时间戳>，
#     且只在你「没配过」或「还是出厂默认值」时才改，不会动你自定义的接口
set -euo pipefail
cd "$(dirname "$0")"

CHAT_MODEL="${CHAT_MODEL:-gpt-oss:120b-cloud}"    # 对话
VISION_MODEL="${VISION_MODEL:-gemma4:31b-cloud}"  # 看图 / OCR
export CHAT_MODEL VISION_MODEL
OLLAMA_API="http://127.0.0.1:11434"

AUTO=0
for a in "$@"; do case "$a" in -y|--yes) AUTO=1 ;; esac; done

B=$'\033[1m'; G=$'\033[32m'; Y=$'\033[33m'; R=$'\033[31m'; N=$'\033[0m'
say()  { printf "\n${B}%s${N}\n" "$1"; }
ok()   { printf "  ${G}[ok]${N} %s\n" "$1"; }
warn() { printf "  ${Y}[!]${N} %s\n" "$1"; }
die()  { printf "  ${R}[x]${N} %s\n" "$1"; exit 1; }
has()  { command -v "$1" >/dev/null 2>&1; }

confirm() {
  [[ "$AUTO" == 1 ]] && return 0
  printf "\n  准备执行：\n    ${B}%s${N}\n" "$1"
  read -r -p "  回车=执行 / n=跳过 / q=退出  " ans || ans=""
  case "$ans" in n|N) return 1 ;; q|Q) exit 0 ;; *) return 0 ;; esac
}
run() {
  if confirm "$1"; then eval "$1" || warn "上条命令失败了，继续（可手动重试）"
  else warn "已跳过"; fi
}

printf "${B}OpenWorkbench 环境配置${N}  (macOS / Linux)\n"

# ---------- 1 Python ----------
say "1/5  Python（工作台本体只需要标准库，但至少 3.8）"
PY=""
if has python3; then PY=python3; elif has python; then PY=python; fi
if [[ -n "$PY" ]]; then
  read -r maj min < <("$PY" -c 'import sys;print(sys.version_info[0],sys.version_info[1])')
  if (( maj > 3 || (maj == 3 && min >= 8) )); then ok "Python $maj.$min ($PY)"
  else die "Python $maj.$min 太低，需要 3.8+，请升级后再跑"; fi
else
  warn "没找到 Python。"
  if has brew; then run "brew install python@3.11"
  elif has apt-get; then run "sudo apt-get update && sudo apt-get install -y python3 python3-venv"
  else die "请先装 Python 3.8+：https://www.python.org/downloads/"; fi
  PY=python3
fi

# ---------- 2 Ollama ----------
say "2/5  Ollama（本机模型运行时，工作台的 AI 全靠它）"
if has ollama; then
  ok "已装 Ollama"
else
  warn "未装 Ollama（官方脚本会装到 /usr/local 并注册服务）"
  run "curl -fsSL https://ollama.com/install.sh | sh"
fi
if curl -fsS "$OLLAMA_API/api/tags" >/dev/null 2>&1; then
  ok "Ollama 服务已在 11434 运行"
else
  warn "Ollama 没在跑，后台起一下"
  run "(ollama serve >/tmp/ollama-serve.log 2>&1 &)"
  sleep 3
  curl -fsS "$OLLAMA_API/api/tags" >/dev/null 2>&1 && ok "Ollama 起来了" || warn "还是没起来，看 /tmp/ollama-serve.log"
fi

# ---------- 3 模型 ----------
say "3/5  拉模型（这两个是云端模型，只有几百字节的代理壳，不下权重）"
for m in "$CHAT_MODEL" "$VISION_MODEL"; do
  if ollama list 2>/dev/null | grep -q "^${m}"; then ok "已有 $m"
  else run "ollama pull $m"; fi
done

# ---------- 4 OpenClaw ----------
say "4/5  OpenClaw（可选：技能库 / 神经桥要用；不用可以跳过）"
if has openclaw; then
  ok "已装 OpenClaw"
else
  if ! has npm; then
    warn "没找到 npm（OpenClaw 是 npm 全局包）"
    if has brew; then run "brew install node"
    elif has apt-get; then run "sudo apt-get install -y nodejs npm"
    else warn "请先装 Node.js：https://nodejs.org"; fi
  fi
  run "npm install -g openclaw"
fi
if has openclaw; then
  if openclaw health >/dev/null 2>&1; then ok "Gateway 已在运行"
  else warn "Gateway 没起。要用 OpenClaw 就另开一个终端跑：openclaw gateway run --port 18789"; fi
fi

# ---------- 5 config.json ----------
say "5/5  生成 config.json"
if [[ -f config.json ]]; then
  cp config.json "config.json.bak.$(date +%s)"
  ok "已备份旧配置 -> config.json.bak.*"
fi
"$PY" - <<'PYEOF'
import json, os
p = "config.json"
cfg = {}
if os.path.exists(p):
    try:    cfg = json.load(open(p, encoding="utf-8"))
    except Exception: cfg = {}
elif os.path.exists("config.example.json"):
    cfg = json.load(open("config.example.json", encoding="utf-8"))

cfg.setdefault("ai", {})
ai = cfg["ai"]
# 只在「没配过」或「还是出厂的云端直连地址」时改为走本机 Ollama，
# 你自己填过的接口一律不动（那条直连地址在免费档会 402）。
if not ai.get("base_url") or ai.get("base_url") == "https://ollama.com/v1":
    ai["base_url"] = "http://127.0.0.1:11434/v1"
    ai["label"] = "本机 Ollama"
if not ai.get("model") or ai.get("model") in ("gpt-oss:120b", ""):
    ai["model"] = os.environ["CHAT_MODEL"]

cfg.setdefault("ocr", {})
if not cfg["ocr"].get("model"):
    cfg["ocr"]["model"] = os.environ["VISION_MODEL"]   # 看图 / OCR

json.dump(cfg, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print("  [ok] config.json 就绪：ai=%s  ocr=%s" % (ai.get("model"), cfg["ocr"].get("model")))
PYEOF

say "完成"
printf "  启动：  ${B}%s server.py 8777${N}\n" "$PY"
printf "  打开：  ${B}http://127.0.0.1:8777${N}\n\n"
printf "  ${Y}说明${N}：macOS/Linux 上没有 Windows ConPTY，所以「内置终端」不可用；\n"
printf "         WPS 文档集成同样仅限 Windows。其余功能（问一问、OpenClaw、\n"
printf "         文件检索、项目/资料/日历/邮件等）都正常。\n\n"
