# OpenWorkbench 环境一键脚本（Windows / PowerShell 5.1+）
#
#   powershell -ExecutionPolicy Bypass -File install.ps1          # 每步先问你
#   powershell -ExecutionPolicy Bypass -File install.ps1 -Yes     # 全自动
#
# 它做的事：
#   1 检查 Python 3.8+   2 装/起 Ollama    3 拉两个云端模型
#   4 装 OpenClaw        5 生成 config.json（指向本机 Ollama）
#
# 它明确不做的事：
#   - 不静默安装软件（默认每步都问，-Yes 才自动）
#   - 绝不覆盖已有 config.json：先备份成 config.json.bak.<时间戳>，
#     且只在你「没配过」或「还是出厂默认值」时才改，不会动你自定义的接口
param([switch]$Yes)

$ErrorActionPreference = 'Stop'
$ChatModel   = if ($env:CHAT_MODEL)   { $env:CHAT_MODEL }   else { 'gpt-oss:120b-cloud' }
$VisionModel = if ($env:VISION_MODEL) { $env:VISION_MODEL } else { 'gemma4:31b-cloud' }
$env:OWB_CHAT   = $ChatModel
$env:OWB_VISION = $VisionModel
$OllamaApi = 'http://127.0.0.1:11434'

function Say($m)  { Write-Host "`n$m" -ForegroundColor White }
function Ok($m)   { Write-Host "  [ok] $m" -ForegroundColor Green }
function Warn($m) { Write-Host "  [!] $m" -ForegroundColor Yellow }
function Die($m)  { Write-Host "  [x] $m" -ForegroundColor Red; exit 1 }

function Confirm-Exec([string]$cmd) {
    if ($Yes) { return $true }
    Write-Host "`n  准备执行："
    Write-Host "    $cmd" -ForegroundColor Cyan
    $a = Read-Host "  回车=执行 / n=跳过 / q=退出"
    if ($a -eq 'n' -or $a -eq 'N') { return $false }
    if ($a -eq 'q' -or $a -eq 'Q') { exit 0 }
    return $true
}
function Invoke-Ask([string]$cmd) {
    if (Confirm-Exec $cmd) {
        Write-Host "  -> $cmd" -ForegroundColor DarkGray
        Invoke-Expression $cmd | Out-Host
        if ($LASTEXITCODE -ne 0) { Warn "命令退出码 $LASTEXITCODE，继续（可手动重试）" }
    } else { Warn "已跳过" }
}
function Refresh-Path {
    $env:Path = [System.Environment]::GetEnvironmentVariable('Path','Machine') + ';' +
                [System.Environment]::GetEnvironmentVariable('Path','User')
}

Write-Host "OpenWorkbench 环境配置" -ForegroundColor White
Write-Host "  (Windows / PowerShell)" -ForegroundColor DarkGray

# ---------- 1 Python ----------
Say "1/5  Python（工作台本体只需要标准库，但至少 3.8）"
$PyPrefix = $null
if (Get-Command python -ErrorAction SilentlyContinue) { $PyPrefix = 'python' }
elseif (Get-Command py -ErrorAction SilentlyContinue) { $PyPrefix = 'py -3' }

if ($PyPrefix) {
    $v = (Invoke-Expression "$PyPrefix -c `"import sys;print('%d.%d'%sys.version_info[:2])`"").Trim()
    if ($v -match '^(\d+)\.(\d+)$') {
        $maj = [int]$Matches[1]; $min = [int]$Matches[2]
        if ($maj -gt 3 -or ($maj -eq 3 -and $min -ge 8)) { Ok "Python $v ($PyPrefix)" }
        else { Die "Python $v 太低，需要 3.8+，请升级后再跑" }
    } else { Warn "读不到 Python 版本，继续但请自查" }
} else {
    Warn "没找到 Python。"
    Invoke-Ask 'winget install --id Python.Python.3.11 --accept-package-agreements --accept-source-agreements'
    Refresh-Path
    if (Get-Command python -ErrorAction SilentlyContinue) { $PyPrefix = 'python'; Ok "Python 已装" }
    else { Die "Python 仍不可用，请手动安装 https://www.python.org/downloads/ 后重跑" }
}

# ---------- 2 Ollama ----------
Say "2/5  Ollama（本机模型运行时，工作台的 AI 全靠它）"
if (Get-Command ollama -ErrorAction SilentlyContinue) {
    Ok "已装 Ollama"
} else {
    Warn "未装 Ollama"
    Invoke-Ask 'winget install --id Ollama.Ollama --accept-package-agreements --accept-source-agreements'
    Refresh-Path
}
$ollamaUp = $false
try { Invoke-WebRequest -Uri "$OllamaApi/api/tags" -UseBasicParsing -TimeoutSec 3 | Out-Null; $ollamaUp = $true } catch {}
if ($ollamaUp) {
    Ok "Ollama 服务已在 11434 运行"
} else {
    Warn "Ollama 没在跑，后台起一下"
    if (Get-Command ollama -ErrorAction SilentlyContinue) {
        Start-Process -FilePath 'ollama' -ArgumentList 'serve' -WindowStyle Hidden
        Start-Sleep -Seconds 5
        try { Invoke-WebRequest -Uri "$OllamaApi/api/tags" -UseBasicParsing -TimeoutSec 3 | Out-Null; Ok "Ollama 起来了" }
        catch { Warn "还是没起来，请手动跑 ollama serve" }
    } else { Warn "Ollama 不可用，跳过" }
}

# ---------- 3 模型 ----------
Say "3/5  拉模型（这两个是云端模型，只有几百字节的代理壳，不下权重）"
foreach ($m in @($ChatModel, $VisionModel)) {
    if (Get-Command ollama -ErrorAction SilentlyContinue) {
        $have = (ollama list 2>$null) -match "^$([regex]::Escape($m))\b"
        if ($have) { Ok "已有 $m" } else { Invoke-Ask "ollama pull $m" }
    } else { Warn "Ollama 不可用，跳过 $m" }
}

# ---------- 4 OpenClaw ----------
Say "4/5  OpenClaw（可选：技能库 / 神经桥要用；不用可以跳过）"
if (Get-Command openclaw -ErrorAction SilentlyContinue) {
    Ok "已装 OpenClaw"
} else {
    if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
        Warn "没找到 npm（OpenClaw 是 npm 全局包）"
        Invoke-Ask 'winget install --id OpenJS.NodeJS.LTS --accept-package-agreements --accept-source-agreements'
        Refresh-Path
    }
    Invoke-Ask 'npm install -g openclaw'
    Refresh-Path
}
if (Get-Command openclaw -ErrorAction SilentlyContinue) {
    $healthy = $false
    try { openclaw health 2>$null | Out-Null; $healthy = ($LASTEXITCODE -eq 0) } catch {}
    if ($healthy) { Ok "Gateway 已在运行" }
    else { Warn "Gateway 没起。要用 OpenClaw 就另开一个终端跑：openclaw gateway run --port 18789" }
}

# ---------- 5 config.json ----------
Say "5/5  生成 config.json"
if (Test-Path config.json) {
    Copy-Item config.json "config.json.bak.$([int][double]::Parse((Get-Date -UFormat %s)))" -Force
    Ok "已备份旧配置 -> config.json.bak.*"
}
$cfgPy = @'
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
    ai["model"] = os.environ["OWB_CHAT"]
cfg.setdefault("ocr", {})
if not cfg["ocr"].get("model"):
    cfg["ocr"]["model"] = os.environ["OWB_VISION"]   # 看图 / OCR
json.dump(cfg, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print("  [ok] config.json 就绪：ai=%s  ocr=%s" % (ai.get("model"), cfg["ocr"].get("model")))
'@
$tmpPy = Join-Path $env:TEMP "owb_init_config.py"
Set-Content -Path $tmpPy -Value $cfgPy -Encoding UTF8
Invoke-Expression "$PyPrefix `"$tmpPy`""
Remove-Item $tmpPy -Force -ErrorAction SilentlyContinue

Say "完成"
Write-Host "  启动：  双击 start_workbench.bat   或   $PyPrefix server.py 8777" -ForegroundColor White
Write-Host "  打开：  http://127.0.0.1:8777" -ForegroundColor White
Write-Host ""
