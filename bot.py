"""
Telegram Bot：将用户消息转发给 OpenCode，仅把最终结果回复给用户。
配置从 config.json 读取：telegram_token、allowed_chat_ids（允许使用的 chat id 列表）。
"""
from __future__ import annotations

import json
import os
import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

import opencode_client as opencode
import opencode_runner as runner

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

TELEGRAM_MAX_MESSAGE = 4096
current_session_id: str | None = None
allowed_chat_ids: set[int] = set()


class AllowChatFilter(filters.BaseFilter):
    def filter(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
        if not allowed_chat_ids:
            return True
        chat = update.effective_chat
        return chat is not None and chat.id in allowed_chat_ids


async def get_or_create_session() -> str:
    global current_session_id
    if current_session_id:
        return current_session_id
    sessions = await opencode.list_sessions()
    if not sessions:
        session = await opencode.create_session()
        current_session_id = session["id"]
    else:
        current_session_id = sessions[0]["id"]
    return current_session_id


def chunk_text(text: str, size: int = TELEGRAM_MAX_MESSAGE) -> list[str]:
    if len(text) <= size:
        return [text] if text else []
    out = []
    for i in range(0, len(text), size):
        out.append(text[i : i + size])
    return out


CALLBACK_PREFIX_USE = "use_"
CALLBACK_START_OPENCODE = "start_opencode"


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "直接发消息即会转发给 OpenCode 执行，仅回复最终结果。"
        " /session 查看会话并可点击按钮切换，/new 新建会话，/opencode 查看并启动 OpenCode。"
    )


def _session_keyboard(sessions: list) -> InlineKeyboardMarkup:
    buttons = []
    for s in sessions:
        sid = s.get("id", "")
        title = (s.get("title") or "(无标题)")[:40]
        buttons.append([InlineKeyboardButton(title, callback_data=CALLBACK_PREFIX_USE + sid)])
    return InlineKeyboardMarkup(buttons)


async def cmd_session(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        sessions = await opencode.list_sessions()
    except Exception as e:
        logger.exception("list_sessions")
        await update.message.reply_text(f"获取会话失败: {e}")
        return
    if not sessions:
        await update.message.reply_text("当前无会话，发送任意消息将自动创建。")
        return
    lines = []
    for s in sessions:
        sid = s.get("id", "")
        title = s.get("title") or "(无标题)"
        mark = " [当前]" if sid == current_session_id else ""
        lines.append(f"• {sid[:8]}… {title}{mark}")
    await update.message.reply_text(
        "会话列表（点击下方按钮切换当前会话）:\n" + "\n".join(lines),
        reply_markup=_session_keyboard(sessions),
    )


async def on_switch_session(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    global current_session_id
    q = update.callback_query
    if not q or not q.data or not q.data.startswith(CALLBACK_PREFIX_USE):
        return
    if allowed_chat_ids and update.effective_chat and update.effective_chat.id not in allowed_chat_ids:
        await q.answer()
        return
    await q.answer()
    session_id = q.data[len(CALLBACK_PREFIX_USE) :]
    try:
        sessions = await opencode.list_sessions()
        title = "(无标题)"
        for s in sessions:
            if s.get("id") == session_id:
                title = s.get("title") or title
                break
        current_session_id = session_id
        await q.edit_message_text(f"已切换到会话: {title}")
    except Exception as e:
        logger.exception("switch_session")
        await q.edit_message_text(f"切换失败: {e}")


async def cmd_new(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    global current_session_id
    try:
        session = await opencode.create_session()
        current_session_id = session["id"]
        await update.message.reply_text("已切换到新会话。")
    except Exception as e:
        logger.exception("create_session")
        await update.message.reply_text(f"创建会话失败: {e}")


def _opencode_status_text() -> tuple[str, InlineKeyboardMarkup | None]:
    """返回 (状态文本, 可选键盘：未运行时显示启动按钮)。"""
    base = runner.get_base_url()
    port = runner._parse_port_from_base_url(base)
    if port in (80, 443):
        port = runner.DEFAULT_PORT
    in_use, pid, cmd = runner.check_port(port)
    healthy = runner.is_opencode_healthy()
    lines = [
        f"端口: {port}",
        f"占用: {'是' if in_use else '否'}",
        f"健康: {'是' if healthy else '否'}",
    ]
    if pid:
        lines.append(f"进程: pid={pid}")
    if cmd:
        lines.append(f"命令: {cmd}")
    text = "OpenCode 状态:\n" + "\n".join(lines)
    keyboard = None
    if not healthy:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("启动 OpenCode", callback_data=CALLBACK_START_OPENCODE)]
        ])
    return text, keyboard


async def cmd_opencode(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text, keyboard = _opencode_status_text()
    await update.message.reply_text(text, reply_markup=keyboard)


async def on_start_opencode(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    if not q or q.data != CALLBACK_START_OPENCODE:
        return
    if allowed_chat_ids and update.effective_chat and update.effective_chat.id not in allowed_chat_ids:
        await q.answer()
        return
    await q.answer()
    try:
        log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "opencode.log")
        ok, msg = runner.ensure_opencode_running(log_path=log_path)
        await q.edit_message_text(f"OpenCode: {msg}")
    except Exception as e:
        logger.exception("start_opencode")
        await q.edit_message_text(f"启动失败: {e}")


async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return
    text = update.message.text.strip()
    if not text:
        return
    await update.message.reply_text("已收到，正在执行…")
    try:
        session_id = await get_or_create_session()
        result = await opencode.send_message(session_id, text)
    except Exception as e:
        logger.exception("send_message")
        await update.message.reply_text(f"调用 OpenCode 失败: {e}")
        return
    if not result:
        await update.message.reply_text("(无文本结果)")
        return
    for chunk in chunk_text(result):
        await update.message.reply_text(chunk)


def load_config() -> dict:
    root = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(root, "config.json")
    if not os.path.isfile(path):
        raise SystemExit("请创建 config.json（参考 config.json.example），包含 telegram_token 与 allowed_chat_ids")
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not data.get("telegram_token"):
        raise SystemExit("config.json 中 telegram_token 不能为空")
    return data


def main() -> None:
    global allowed_chat_ids
    config = load_config()
    token = config["telegram_token"].strip()
    allowed_chat_ids = set(int(x) for x in config.get("allowed_chat_ids") or [])
    root = os.path.dirname(os.path.abspath(__file__))
    ok, msg = runner.ensure_opencode_running(log_path=os.path.join(root, "opencode.log"))
    logger.info("OpenCode: %s", msg)
    commands = [
        BotCommand("start", "欢迎与说明"),
        BotCommand("session", "查看会话列表"),
        BotCommand("new", "新建会话"),
        BotCommand("opencode", "查看并启动 OpenCode"),
    ]

    async def post_init(application: Application) -> None:
        await application.bot.set_my_commands(commands)

    allow = AllowChatFilter()
    app = Application.builder().token(token).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start, filters=allow))
    app.add_handler(CommandHandler("session", cmd_session, filters=allow))
    app.add_handler(CommandHandler("sessions", cmd_session, filters=allow))
    app.add_handler(CommandHandler("new", cmd_new, filters=allow))
    app.add_handler(CommandHandler("opencode", cmd_opencode, filters=allow))
    app.add_handler(CallbackQueryHandler(on_switch_session, pattern=rf"^{CALLBACK_PREFIX_USE}"))
    app.add_handler(CallbackQueryHandler(on_start_opencode, pattern=rf"^{CALLBACK_START_OPENCODE}$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & allow, on_message))
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
