# OpenWorkbench

**一句话**：把你本机的 Ollama、OpenClaw、文件、终端、系统状态，接进一个**零第三方依赖**的本地工作台 —— 数据全程不出你的机器。

它不是另一个云面板。前端后端一体（`server.py` 既托管页面又处理 API），
只用 Python 标准库，`pip install` 什么都不用装。每个人跑自己的实例、
连自己本机的模型、各自做内网穿透 —— 这是「开源回环」的起点。

---

## 一键装好环境（新用户先看这里）

开源项目最大的坎不是代码，是"clone 下来还要手填配置才能跑"。所以给了两个脚本：
**装 Ollama、装 OpenClaw、拉模型、并把 `config.json` 自动指向你本机的 Ollama**。

| 系统 | 命令（在项目目录下执行） |
| --- | --- |
| Windows | `powershell -ExecutionPolicy Bypass -File install.ps1` |
| macOS / Linux | `bash install.sh` |

想全自动、不再逐步确认：`install.ps1 -Yes` / `install.sh --yes`

**脚本会做的**：检查 Python 3.8+ → 装/起 Ollama → 拉 `gpt-oss:120b-cloud`（对话）和
`gemma4:31b-cloud`（看图 / OCR）→ 装 OpenClaw → 生成 `config.json` 指向本机 Ollama。

**脚本明确不会做的**：
- **不静默跑远程安装脚本**（默认每一步都把命令打出来、等你按回车；`-Yes` 才自动）
- **绝不覆盖你已有的 `config.json`** —— 先备份成 `config.json.bak.<时间戳>`，
  且只在「没配过」或「还是出厂默认值」时才改，你自己填过的接口一律不动

> 那两个模型是 Ollama **云端**模型，只有几百字节的代理壳、不下权重，所以拉起来是秒级的。
> 想跑纯离线本地模型，自己 `ollama pull qwen2.5:7b` 之类即可。

## 快速开始（环境已就绪）

```bash
python server.py 8777
# 浏览器打开 http://127.0.0.1:8777
```

Windows 也可以直接**双击 `start_workbench.bat`**（会自动起服务并开浏览器，
且带崩溃自动重启）。配置按需填，模板见 `config.example.json`。

## 特性

- **零依赖**：只用 Python 标准库，没有 requirements.txt。
- **前端后端一体**：`server.py` 既托管 `static/` 前端，又处理 `/api/*` 后端。
- **问一问**：接 Ollama 兼容接口的多模型对话，支持多模型对比、自动剥离推理模型的思考过程。
- **OpenClaw**：神经桥、技能库（可在线下载安装）、结果回写。
- **本机能力**：文件索引与语义搜索、内置 ConPTY 真终端、系统状态监控。
- **模块**：项目 / 资料 / 日历 / 邮件 / 笔记 / 习惯 / 番茄钟 / 剪贴板 / 房间布置 等 20+ 个。
- **连接器框架**：外接通道按统一契约拼入（已支持微信 PushPlus、Server酱），可把结果推到微信。
- **数据在自己机器**：落在 `data/app.db`，可导出备份。
- **自托管 / 远程访问**：配合内网穿透 + `remote.access_key`，手机 / 外网也能访问你自己的本机。

## 平台差异（先说清楚）

| | Windows | macOS / Linux |
| --- | --- | --- |
| 主体功能（问一问、OpenClaw、文件、项目、日历、邮件…） | ✅ | ✅ |
| 内置终端（基于 ConPTY，需 Win10 1809+） | ✅ | ❌ |
| WPS 文档读写集成 | ✅ | ❌ |

## 远程访问（自托管）

想用手机 / 外网访问你**自己本机**的能力：

1. 在 `config.json` 加：
   ```json
   "remote": { "access_key": "一段强随机串", "cors": "", "bind": "0.0.0.0" }
   ```
2. 启动：`python server.py 8777 --host 0.0.0.0`
3. 内网穿透（示例，免费免账号）：`cloudflared tunnel --url http://localhost:8777`
4. 手机开隧道地址即可。

> ⚠️ 安全：绝不裸绑 `0.0.0.0` 不设 `access_key`；`access_key` 用强随机串。
> 暴露本机 = 别人能跑你机器上的命令，必须口令到位才开远程。

> 另注：把它部署成**纯静态站点**（没有本机后端）时，问一问 / OpenClaw / 文件 / 终端 / 系统
> 这些依赖本机的能力不可用 —— 那只是个前端壳，界面会明确提示而不是白屏。

## 开源回环

这是一个开放的产品：每个使用者跑自己的实例、连自己本机的 openclaw/ollama、各自做内网穿透。
**欢迎把你的技能、配置、部署经验回流到本仓库**，形成生态循环 —— 怎么回流见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 安全说明

`config.json` 含真实凭据（邮箱密码、AI key），已被 `.gitignore` 排除，**不会**进仓库。
请基于 `config.example.json` 自行创建。源码本身不含任何个人身份信息。

## License

[MIT](LICENSE)
