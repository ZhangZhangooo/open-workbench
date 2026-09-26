# OpenWorkbench

本地优先的个人工作台。前端 + 后端一体、**零第三方依赖**（只用 Python 标准库），
自带 Ollama / OpenClaw / 文件检索 / 终端 / 系统状态等本机能力。
每个人跑自己的实例，连自己本机的 openclaw/ollama，各自自托管。

## 特性

- **零依赖**：`python server.py` 直接跑，不需要 `pip install` 任何东西。
- **前端后端一体**：`server.py` 既托管 `static/` 前端，又处理 `/api/*` 后端。
- **本机能力**：问一问（Ollama 兼容接口）、OpenClaw 神经桥、文件索引与语义搜索、终端、系统状态。
- **数据在自己机器**：所有数据落在 `data/app.db`，可一键导出备份。
- **自托管 / 远程访问**：配合内网穿透（cloudflared / frp）+ `remote.access_key`，手机 / 外网也能访问你自己的本机。

## 快速开始

方式一（推荐，双击即开）：双击 `start_workbench.bat`，会自动起服务并打开浏览器 `http://127.0.0.1:8777`。

方式二（命令行）：

```bash
python server.py 8777
# 浏览器打开 http://127.0.0.1:8777
```

首次运行会生成 `config.json`，按需填 AI 接口、邮箱等（详见 `config.example.json`）。

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

## 开源回环

这是一个开放的产品：每个使用者跑自己的实例、连自己本机的 openclaw/ollama、
各自做内网穿透。欢迎把你的技能、配置、部署经验回流到本仓库，形成开源生态的循环。

## 安全说明

`config.json` 含真实凭据（邮箱密码、AI key），已被 `.gitignore` 排除，**不会**进仓库。
请基于 `config.example.json` 自行创建。

## License

[MIT](LICENSE)
