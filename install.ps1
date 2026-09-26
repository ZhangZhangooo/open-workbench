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
# 切到脚本所在目录：否则 config.json 会被写到「你执行命令时所在的目录」而不是项目里
if ($PSScriptRoot) { Set-Location -LiteralPath $PSScriptRoot }

$ChatModel   = if ($env:CHAT_MODEL)   { $env:CHAT_MODEL }   else { 'gpt-oss:120b-cloud' }
$VisionModel = if ($env:VISION_MODEL) { $env:VISION_MODEL } else { 'gemma4:31b-cloud' }
$env:OWB_CHAT   = $ChatModel
$env:OWB_VISION = $VisionModel
$OllamaApi = 'http://127.0.0.1:11434'

function Say($m)  { Write-Host "`n$m" -ForegroundColor White }
function Ok($m)   { Write-Host "  [ok] $m" -ForegroundColor Green }
function Warn($m) { Write-Host "  [!] $m" -ForegroundColor Yellow }
function Die($m)  { Write-Host "  [x] $m" -ForegroundColor Red; exit 1 }

function Confirm-Exec([string]$label) {
    if ($Yes) { return $true }
    Write-Host "`n  准备执行："
    Write-Host "    $label" -ForegroundColor Cyan
    $a = Read-Host "  回车=执行 / n=跳过 / q=退出"
    if ($a -eq 'n' -or $a -eq 'N') { return $false }
    if ($a -eq 'q' -or $a -eq 'Q') { exit 0 }
    return $true
}
# 用「脚本块」而不是拼接字符串执行：display 只用于给人看，action 是真正要跑的
function Invoke-Ask([string]$display, [scriptblock]$action) {
    if (Confirm-Exec $display) {
        Write-Host "  -> $display" -ForegroundColor DarkGray
        & $action
        if ($LASTEXITCODE -ne 0) { Warn "命令退出码 $LASTEXITCODE，继续（可手动重试）" }
    } else { Warn "已跳过" }
}
function Refresh-Path {
    $machine = [System.Environment]::GetEnvironmentVariable('Path', 'Machine')
    $user    = [System.Environment]::GetEnvironmentVariable('Path', 'User')
    $env:Path = "$machine;$user"
}
function Get-PyVersion([string]$exe, [string[]]$pre) {
    try { $v = (& $exe @pre -c "import sys;print('%d.%d'%sys.version_info[:2])" 2>$null | Select-Object -First 1) }
    catch { return $null }
    if ("$v" -match '^\d+\.\d+$') { return "$v" }
    return $null
}
function Test-PyExe([string]$exe) {
    # 应用商店的 python.exe 只是占位符，不算数
    $g = Get-Command $exe -ErrorAction SilentlyContinue
    if ($g -and $g.Source -and $g.Source -like '*\WindowsApps\*') { return $false }
    return $true
}

Write-Host "OpenWorkbench 环境配置" -ForegroundColor White
Write-Host "  (Windows / PowerShell)" -ForegroundColor DarkGray

# ---------- 1 Python ----------
Say "1/5  Python（工作台本体只需要标准库，但至少 3.8）"
$PyExe = $null; $PyArgs = @()
$PySrc = ""

# 0) 本机覆盖文件 .python-path（可选、不提交）：第一行写 python.exe 完整路径
$ppFile = Join-Path (Get-Location) '.python-path'
if (Test-Path $ppFile) {
    $cand = (Get-Content $ppFile -TotalCount 1).Trim()
    if ($cand) {
        $v = Get-PyVersion $cand @()
        if ($v) { $PyExe = $cand; $PyArgs = @(); $PySrc = ".python-path" }
        else { Warn ".python-path 里的 Python 跑不起来，忽略" }
    }
}
# 1) py 启动器  2) python  3) python3
if (-not $PyExe) {
    foreach ($cand in @(@('py', @('-3')), @('python', @()), @('python3', @()))) {
        $exe = $cand[0]; $pre = $cand[1]
        if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) { continue }
        if (-not (Test-PyExe $exe)) { continue }
        $v = Get-PyVersion $exe $pre
        if ($v) { $PyExe = $exe; $PyArgs = $pre; break }
    }
}

if ($PyExe) {
    $v = Get-PyVersion $PyExe $PyArgs
    $p = $v.Split('.'); $maj = [int]$p[0]; $min = [int]$p[1]
    if ($maj -gt 3 -or ($maj -eq 3 -and $min -ge 8)) { Ok "Python $v$($(if ($PySrc) { " (来自 $PySrc)" } else { '' }))" }
    else { Die "Python $v 太低，需要 3.8+，请升级后再跑" }
} else {
    Warn "没找到可用的 Python 3.8+（机器上的 python 若是「应用商店」占位符则不算数）。"
    Invoke-Ask "winget install Python.Python.3.11" { winget install --id Python.Python.3.11 --accept-package-agreements --accept-source-agreements }
    Refresh-Path
    foreach ($cand in @(@('py', @('-3')), @('python', @()))) {
        if ((Get-Command $cand[0] -ErrorAction SilentlyContinue) -and (Test-PyExe $cand[0])) {
            $PyExe = $cand[0]; $PyArgs = $cand[1]; break
        }
    }
    if ($PyExe) { Ok "Python 已装（$PyExe）" }
    else { Die "Python 仍不可用：装好 https://www.python.org/downloads/ 后重跑，或在项目根目录建 .python-path 写上 python.exe 完整路径" }
}

# ---------- 2 Ollama ----------
Say "2/5  Ollama（本机模型运行时，工作台的 AI 全靠它）"
if (Get-Command ollama -ErrorAction SilentlyContinue) {
    Ok "已装 Ollama"
} else {
    Warn "未装 Ollama"
    Invoke-Ask "winget install Ollama.Ollama" { winget install --id Ollama.Ollama --accept-package-agreements --accept-source-agreements }
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
        $list = (ollama list 2>$null | Out-String)
        if ($list -match [regex]::Escape($m)) { Ok "已有 $m" }
        else { Invoke-Ask "ollama pull $m" { ollama pull $m } }
    } else { Warn "Ollama 不可用，跳过 $m" }
}

# ---------- 4 OpenClaw ----------
Say "4/5  OpenClaw（可选：技能库 / 神经桥要用；不用可以跳过）"
if (Get-Command openclaw -ErrorAction SilentlyContinue) {
    Ok "已装 OpenClaw"
} else {
    if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
        Warn "没找到 npm（OpenClaw 是 npm 全局包）"
        Invoke-Ask "winget install OpenJS.NodeJS.LTS" { winget install --id OpenJS.NodeJS.LTS --accept-package-agreements --accept-source-agreements }
        Refresh-Path
    }
    Invoke-Ask "npm install -g openclaw" { npm install -g openclaw }
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
    Copy-Item config.json "config.json.bak.$(Get-Date -Format yyyyMMddHHmmss)" -Force
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
# 故意用 ASCII 输出：Windows 控制台是 cp936，Python 打中文会乱码
print("  [ok] config.json ready  ai=%s  ocr=%s" % (ai.get("model"), cfg["ocr"].get("model")))
'@
$tmpPy = Join-Path $env:TEMP "owb_init_config.py"
Set-Content -Path $tmpPy -Value $cfgPy -Encoding UTF8
& $PyExe @PyArgs $tmpPy
Remove-Item $tmpPy -Force -ErrorAction SilentlyContinue

Say "完成"
Write-Host "  启动：  双击 start_workbench.bat   或   $PyExe $($PyArgs -join ' ') server.py 8777"
Write-Host "  打开：  http://127.0.0.1:8777"
Write-Host ""
