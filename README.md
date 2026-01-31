# opencode-telegram-bot

用 Telegram Bot 控制本地 [OpenCode](https://opencode.ai)（发消息、切会话、查状态、可选启动 opencode serve）。

- 仓库：<https://github.com/mzxk/opencode-telegram-bot>
- 依赖：Python 3，`opencode serve` 已安装且在 PATH

## 配置

1. 复制 `config.json.example` 为 `config.json`
2. 填写 `telegram_token`（Bot Token）和 `allowed_chat_ids`（允许使用的 Telegram chat id 列表，留空则所有人可用）

## 运行

```bash
pip install -r requirements.txt
python bot.py
```

需先启动 `opencode serve`（默认 `http://127.0.0.1:4096`），或通过 Bot 发送 `/opencode` 点「启动 OpenCode」。

## 命令

- `/start` 说明
- `/session` 会话列表（可点按钮切换）
- `/new` 新建会话
- `/opencode` 查看/启动 OpenCode

