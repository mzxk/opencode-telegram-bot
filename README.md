# opencode-telegram-bot

用 Telegram 或 Matrix Bot 控制本地 [OpenCode](https://opencode.ai)（发消息、切会话、查状态、可选启动 opencode serve）。

- 仓库：<https://github.com/mzxk/opencode-telegram-bot>
- 依赖：Python 3，`opencode serve` 已安装且在 PATH

## 配置

1. 复制 `config.json.example` 为 `config.json`
2. **Telegram**：填写 `telegram_token`（Bot Token）和 `allowed_chat_ids`（留空则所有人可用）
3. **Matrix**（可选）：填写 `matrix_homeserver`、`matrix_user_id`（@bot:domain）、`matrix_password`（**仅首次登录**；成功后程序会删除该字段并仅用 token 文件登录）。`allowed_room_ids` 留空即不限制房间。E2EE 与 token 存于 `matrix_store/`、`matrix_credentials.json`，不提交。

## 运行

```bash
pip install -r requirements.txt
python main.py
```

仅 Telegram 时也可 `python telegram_bot.py`；仅 Matrix 时 `python matrix_bot.py`。

需先启动 `opencode serve`（默认 `http://127.0.0.1:4096`），或发送 `/opencode` 点「启动 OpenCode」。

## 命令

- `/start` 说明
- `/session` 会话列表（Telegram 可点按钮切换；Matrix 用 `/use <session_id>` 切换）
- `/new` 新建会话
- `/opencode` 查看/启动 OpenCode
- `/use <session_id>`（Matrix）切换当前会话

