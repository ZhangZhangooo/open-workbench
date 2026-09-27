#!/usr/bin/env bash
# OpenWorkbench 环境一键脚本（macOS / Linux）
#
#   sudo ./install.sh        # 免 chmod；每一步都先告诉你命令、等你按回车才执行
#   sudo ./install.sh --yes  # 全自动，不再询问（CI / 熟练用户）
#
#   想用 ./install.sh 这种写法，先赋一次执行权限即可：
#     chmod +x install.sh && sudo ./install.sh
#
#   ⚠️ 必须以 root 运行（脚本内部会把 brew / ollama 自动降回你本人，见下方说明）：
#      sudo ./install.sh
#      不是 root 时脚本会自己 sudo 重新跑；不想自动提权就请先 sudo 再执行。
#
#   ⚠️ 为什么不是「只在某几步 sudo」：mac 上装 Ollama / Node / OpenClaw 几乎每步都要权限，
#      整体 sudo 一次最省事。但 brew 与 ollama 必须降回你本人（见提权模型那段注释）。
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
# hasu：以「真实用户」身份探测命令是否存在（brew/ollama/openclaw/npm 都装在用户侧）
hasu() { $RU command -v "$1" >/dev/null 2>&1; }

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

# ===== 提权模型：整个脚本以 root 运行（sudo ./install.sh）=====
# 不是 root 就自动 sudo 重新跑本脚本（保留原参数）；没有 sudo 就报错退出。
# root 下「系统级」操作（apt、官方 Ollama 安装脚本写 /usr/local、收尾 chown）直接做；
# 但 brew 与 ollama 必须降回你本人来跑：
#   - brew 直接拒绝以 root 运行（"Running Homebrew as root is extremely dangerous"）；
#   - ollama 模型要落在你自己的家目录，否则你日常跑的 ollama 看不到、也写不进。
if [[ "$(id -u)" -ne 0 ]]; then
  if has sudo; then
    say "本脚本需要 root 权限，正在用 sudo 重新以 root 运行…"
    exec sudo bash "./$(basename "$0")" "$@"
  else
    die "本脚本需要 root 权限，请用：sudo ./install.sh"
  fi
fi
IS_ROOT=1

# 找到「真实用户」：sudo 运行时是 $SUDO_USER；root 直接跑则退回控制台用户
REAL_USER="${SUDO_USER:-}"
if [[ -z "$REAL_USER" || "$REAL_USER" == "root" ]]; then
  REAL_USER="$(logname 2>/dev/null || who am i 2>/dev/null | awk '{print $1}' || echo "$USER")"
fi
# RU：以真实用户身份执行一条命令（brew / ollama / openclaw / npm 都走它）
RU=""
if [[ -n "$REAL_USER" && "$REAL_USER" != "root" ]]; then
  RU="sudo -u $REAL_USER -- "
fi

IS_MAC=0; [[ "$(uname -s)" == "Darwin" ]] && IS_MAC=1

# sudo 下 root 的 PATH 常常不含 Homebrew / 自带 Node 的安装目录，
# 先把常见位置补进 PATH，后面 has brew / ollama / npm 的探测才准
# （Apple Silicon 的 brew 在 /opt/homebrew/bin，Intel 在 /usr/local/bin）
if [[ "$IS_ROOT" == 1 ]]; then
  for d in /opt/homebrew/bin /opt/homebrew/sbin /usr/local/bin /usr/local/sbin; do
    [[ -d "$d" ]] || continue
    case ":$PATH:" in *":$d:"*) ;; *) export PATH="$d:$PATH" ;; esac
  done
fi

# brew 拒绝在 root 下运行，但二进制在系统 PATH 里（上面已补），root 也能 detect 到
HAS_BREW=0; if has brew; then HAS_BREW=1; fi

printf "${B}OpenWorkbench 环境配置${N}  (macOS / Linux, 以 root 运行)\n"
if [[ -n "$RU" ]]; then
  printf "  ${B}brew / ollama / openclaw / npm 都以你的身份（$REAL_USER）执行${N}\n"
  printf "  （brew 拒绝 root；ollama 模型要进你的家目录，否则你自己的 ollama 看不到）\n"
else
  printf "  ${Y}没找到真实非 root 用户，全部以 root 执行（不推荐）${N}\n"
fi

# ---------- 1 Python ----------
say "1/5  Python（工作台本体只需要标准库，但至少 3.8）"
PY=""
# 本机覆盖文件（可选、不提交）：第一行写 python 解释器的完整路径
if [[ -f .python-path ]]; then IFS= read -r PY < .python-path; fi
if [[ -z "$PY" ]] || ! "$PY" -c 'import sys' >/dev/null 2>&1; then
  PY=""
  if has python3; then PY=python3; elif has python; then PY=python; fi
fi
if [[ -n "$PY" ]]; then
  # tr -d '\r'：Windows 上的 Python 会把 \n 输出成 \r\n，不去掉会让下面
  # 的算术判断报 "invalid arithmetic operator"（3.13 被误判成版本太低）
  read -r maj min < <("$PY" -c 'import sys;print(sys.version_info[0],sys.version_info[1])' | tr -d '\r')
  maj="${maj%$'\r'}"; min="${min%$'\r'}"
  if (( maj > 3 || (maj == 3 && min >= 8) )); then ok "Python $maj.$min ($PY)"
  else die "Python $maj.$min 太低，需要 3.8+，请升级后再跑"; fi
else
  warn "没找到 Python。"
  if has brew; then run "${RU}brew install python@3.11"
  elif has apt-get; then run "apt-get update && apt-get install -y python3 python3-venv"
  else die "请先装 Python 3.8+：https://www.python.org/downloads/"; fi
  PY=python3
fi

# ---------- 2 Ollama ----------
say "2/5  Ollama（本机模型运行时，工作台的 AI 全靠它）"
if has ollama; then
  ok "已装 Ollama"
else
  OI="curl -fsSL https://ollama.com/install.sh | sh"
  if [[ "$IS_MAC" == 1 && "$HAS_BREW" == 1 ]]; then
    # 首选：Homebrew。装进 /opt/homebrew（归你自己的用户），以你的身份跑（brew 拒绝 root）
    warn "未装 Ollama。macOS 上用 Homebrew 装最省事，以你的身份执行"
    run "${RU}brew install ollama"
  elif [[ "$IS_ROOT" == 1 ]]; then
    # Linux 上不用 brew 装 Ollama：homebrew-core 那份只有 CPU 后端，
    # 官方脚本才会按你的显卡装对应后端（这一步以 root 写 /usr/local）
    warn "未装 Ollama。官方脚本要写 /usr/local，所以这一步以 ${B}root${N} 执行"
    run "$OI"
  else
    warn "未装 Ollama，且当前环境没有 sudo，这一步得你手动来："
    printf "    ${B}%s${N}\n" "curl -fsSL https://ollama.com/install.sh | sh"
    printf "    装完（或改由管理员装好）后，重新跑本脚本即可继续。\n"
  fi
fi
if curl -fsS "$OLLAMA_API/api/tags" >/dev/null 2>&1; then
  ok "Ollama 服务已在 11434 运行"
else
  if [[ "$HAS_BREW" == 1 ]] && ${RU}brew list ollama >/dev/null 2>&1; then
    warn "Ollama 是 Homebrew 装的，用 brew services 起（之后开机自动运行）"
    run "${RU}brew services start ollama"
  elif [[ "$IS_MAC" == 1 ]]; then
    warn "macOS 上请先打开 Ollama.app（首次启动会弹确认），它会自动监听 11434"
    printf "    ${B}open -a Ollama${N}\n"
    run "${RU}open -a Ollama"
  else
    warn "Ollama 没在跑，后台起一下（以你的身份，模型才会进你的家目录）"
    run "${RU}bash -c 'ollama serve >/tmp/ollama-serve.log 2>&1 &'"
  fi
  # 服务启动要几秒，轮询而不是死等固定时长
  for _ in 1 2 3 4 5 6; do
    curl -fsS "$OLLAMA_API/api/tags" >/dev/null 2>&1 && break
    sleep 2
  done
  curl -fsS "$OLLAMA_API/api/tags" >/dev/null 2>&1 && ok "Ollama 起来了" \
    || warn "还是没起来。brew 装的看：brew services info ollama；其他看 /tmp/ollama-serve.log"
fi

# ---------- 3 模型 ----------
say "3/5  拉模型（这两个是云端模型，只有几百字节的代理壳，不下权重）"
for m in "$CHAT_MODEL" "$VISION_MODEL"; do
  if ${RU}ollama list 2>/dev/null | tr -d '\r' | grep -q "^${m}"; then ok "已有 $m"
  else run "${RU}ollama pull $m"; fi
done

# ---------- 4 OpenClaw ----------
say "4/5  OpenClaw（可选：技能库 / 神经桥要用；不用可以跳过）"
if hasu openclaw; then
  ok "已装 OpenClaw（命令行）"
else
  # 路线 1：macOS 用 Homebrew 装官方客户端（openclaw 在 homebrew/cask 里，不是 formula）
  if [[ "$IS_MAC" == 1 && "$HAS_BREW" == 1 ]]; then
    warn "先用 Homebrew 装 OpenClaw 官方客户端"
    printf "    它装的是 ${B}/Applications/OpenClaw.app${N}（GUI 客户端，要求 macOS 15+）\n"
    printf "    ${Y}注意：cask 不含命令行工具${N}，工作台连 gateway 还得有 CLI，所以下面会继续装。\n"
    run "${RU}brew install --cask openclaw"
    hash -r 2>/dev/null || true
  fi

  # 路线 2：官方安装脚本（自带 Node 运行时，彻底绕开 npm 目录权限问题）
  if ! hasu openclaw; then
    warn "装命令行版：官方脚本会${B}自己准备 Node 运行时${N}，不用你管 npm 权限"
    # 以你的身份跑：脚本把 CLI 装进你的 ~/.local/bin，而不是 root 的家目录
    if [[ -n "$RU" ]]; then run "${RU}bash -c 'curl -fsSL https://openclaw.ai/install.sh | bash'"
    else run "curl -fsSL https://openclaw.ai/install.sh | bash"; fi
    export PATH="$HOME/.local/bin:$HOME/.openclaw/bin:/usr/local/bin:$PATH"; hash -r 2>/dev/null || true
  fi

  # 路线 3：你已经装好 Node 的话，直接装 npm 包最省事
  if ! hasu openclaw; then
    if ! hasu npm; then
      warn "没找到 npm（OpenClaw 同时提供 npm 包）"
      if [[ "$HAS_BREW" == 1 ]]; then run "${RU}brew install node"
      elif has apt-get; then run "apt-get install -y nodejs npm"
      else warn "请先装 Node.js：https://nodejs.org"; fi
      # brew 的 bin 目录可能不在 PATH 里（Apple Silicon 是 /opt/homebrew）
      if [[ "$HAS_BREW" == 1 ]]; then export PATH="$(${RU}brew --prefix)/bin:$PATH"; hash -r 2>/dev/null || true; fi
    fi

    if hasu npm; then
      # npm 的全局目录要能写。官方 Node 安装包在 mac 上把 /usr/local 给了 root，
      # 于是 npm -g 就得 sudo —— 但 sudo 装完会留下一堆 root 属主的缓存文件，
      # 之后每次 -g 都得 sudo。两条出路：用 brew 的 node（全局目录归用户），
      # 或把目录换到用户级，都是一劳永逸。
      NPM_PREFIX="$(${RU}npm config get prefix 2>/dev/null | tr -d '\r')"
      if [[ -n "$NPM_PREFIX" && ! -w "$NPM_PREFIX" ]]; then
        # 出路一：改用 Homebrew 的 Node（它的全局目录在 brew 目录下，归你自己）
        if [[ "$HAS_BREW" == 1 ]] && ! ${RU}brew list node >/dev/null 2>&1; then
          warn "npm 全局目录 $NPM_PREFIX 不可写（官方 Node 包把 /usr/local 给了 root）"
          printf "    改用 Homebrew 装 Node —— 它的全局目录 ${B}归你自己${N}，之后 npm -g 都不用 sudo\n"
          run "${RU}brew install node"
          export PATH="$(${RU}brew --prefix)/bin:$PATH"; hash -r 2>/dev/null || true
          NPM_PREFIX="$(${RU}npm config get prefix 2>/dev/null | tr -d '\r')"
        fi
        # 出路二：还是不可写（没 brew / 就是要用系统 node）→ 换到用户级目录
        if [[ -n "$NPM_PREFIX" && ! -w "$NPM_PREFIX" ]]; then
          warn "npm 全局目录 $NPM_PREFIX 当前用户不可写（mac 上直接 npm -g 就得 sudo）"
          printf "    换成用户级目录，以后所有 ${B}npm -g${N} 都不再需要 sudo：\n"
          run "${RU}bash -c 'mkdir -p \"\$HOME/.npm-global\" && npm config set prefix \"\$HOME/.npm-global\"'"
          NPM_PREFIX="$(${RU}npm config get prefix 2>/dev/null | tr -d '\r')"
          export PATH="$NPM_PREFIX/bin:$PATH"
          hash -r 2>/dev/null || true
          # 让新开的终端也找得到（已配置过就跳过）
          RUNE="$(${RU}printenv HOME)"
          RC="$RUNE/.bashrc"; [[ -f "$RUNE/.zshrc" ]] && RC="$RUNE/.zshrc"
          if ! $RU grep -q "npm-global/bin" "$RC" 2>/dev/null; then
            warn "把 $RUNE/.npm-global/bin 写进 $RC，新终端才能找到 openclaw"
            run "${RU}bash -c 'echo \"export PATH=\$HOME/.npm-global/bin:\$PATH\" >> \"$RC\"'"
          fi
        fi
      fi

      # --foreground-scripts：npm 7+ 默认把 postinstall 的输出丢进后台日志，屏幕上长时间
      #   一片空白 —— 这就是"看着像卡住"的元凶之一，放到前台才看得到进度。
      # --no-fund --no-audit：省掉两次联网请求，装得更快。
      # 以你的身份装（全局目录归你，之后都不用 sudo）
      warn "这一步通常 1~3 分钟，npm 会显示进度条 —— 没崩就是在装，别急"
      run "${RU}npm install -g openclaw@latest --allow-scripts=openclaw --no-fund --no-audit --foreground-scripts --unsafe-perm"
      hash -r 2>/dev/null || true
    fi
  fi
fi

# 结论：装没装成都要说清楚（这段必须在 if/else 外面，否则已装时不会检查 gateway）
if hasu openclaw; then
  if ${RU}openclaw health >/dev/null 2>&1; then ok "Gateway 已在运行"
  else warn "Gateway 没起。要用 OpenClaw 就另开一个终端跑：openclaw gateway run --port 18789"; fi

  # 4.5 用 Ollama 把 OpenClaw 拉起来（官方推荐的接法）
  if has ollama; then
    say "4.5 用 Ollama 启动 OpenClaw（模型：$CHAT_MODEL）"
    printf "    命令：${B}ollama launch openclaw --model $CHAT_MODEL -y${N}\n"
    printf "    ${Y}不会接入任何渠道${N}（微信 / 钉钉等）；要接的话自己跑 ${B}openclaw onboard${N}。\n"
    if [[ "$AUTO" == 1 ]]; then
      warn "--yes 模式下不自动启动（它会打开 OpenClaw 等你操作），请手动跑上面那条命令"
    else
      run "${RU}ollama launch openclaw --model $CHAT_MODEL -y"
    fi
  fi
else
  warn "OpenClaw 没装上 —— 工作台的「技能库 / 神经桥」用不了。可自己挑一条再试："
  printf "    1) ${B}curl -fsSL https://openclaw.ai/install.sh | bash${N}\n"
  printf "    2) ${B}npm install -g openclaw@latest --allow-scripts=openclaw${N}\n"
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
# 用 ASCII 输出，避免不同终端编码导致的乱码
print("  [ok] config.json ready  ai=%s  ocr=%s" % (ai.get("model"), cfg["ocr"].get("model")))
PYEOF

# 脚本以 root 跑，生成的 config.json / data / 模型目录会归 root，
# 还给你自己 —— 不然之后工作台改不动 config.json、ollama 也写不进模型目录
# （这两个是最容易事后才发现的坑）
if [[ "$IS_ROOT" == 1 && -n "$RU" ]]; then
  say "收尾：把 root 生成的文件归属还给你自己（$REAL_USER）"
  REAL_HOME="$(eval echo "~$REAL_USER" 2>/dev/null || echo "$HOME")"
  if [[ -f config.json ]]; then
    chown "$REAL_USER" config.json 2>/dev/null && ok "config.json -> $REAL_USER" || true
  fi
  if [[ -d data ]]; then chown -R "$REAL_USER" data 2>/dev/null || true; fi
  if [[ -d "$REAL_HOME/.ollama" ]]; then chown -R "$REAL_USER" "$REAL_HOME/.ollama" 2>/dev/null || true; fi
  ok "已归还给 $REAL_USER"
fi

say "完成"
printf "  启动：  ${B}%s server.py 8777${N}\n" "$PY"
printf "  打开：  ${B}http://127.0.0.1:8777${N}\n\n"
printf "  ${Y}说明${N}：macOS/Linux 上没有 Windows ConPTY，所以「内置终端」不可用；\n"
printf "         WPS 文档集成同样仅限 Windows。其余功能（问一问、OpenClaw、\n"
printf "         文件检索、项目/资料/日历/邮件等）都正常。\n\n"
