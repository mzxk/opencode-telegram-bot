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

import opencode_runner as runner
import bot_core

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

allowed_chat_ids: set[int] = set()

CALLBACK_PREFIX_USE = "use_"
CALLBACK_START_OPENCODE = "start_opencode"


class AllowChatFilter(filters.BaseFilter):
    def filter(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
        if not allowed_chat_ids:
            return True
        chat = update.effective_chat
        return chat is not None and chat.id in allowed_chat_ids


def _session_keyboard(sessions: list) -> InlineKeyboardMarkup:
    buttons = []
    for s in sessions:
        sid = s.get("id", "")
        title = (s.get("title") or "(无标题)")[:40]
        buttons.append([InlineKeyboardButton(title, callback_data=CALLBACK_PREFIX_USE + sid)])
    return InlineKeyboardMarkup(buttons)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(bot_core.handle_start())


async def cmd_session(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = await bot_core.handle_session_list()
    sessions = await bot_core.get_sessions()
    if not sessions:
        await update.message.reply_text(text)
        return
    await update.message.reply_text(text, reply_markup=_session_keyboard(sessions))


async def on_switch_session(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    if not q or not q.data or not q.data.startswith(CALLBACK_PREFIX_USE):
        return
    if allowed_chat_ids and update.effective_chat and update.effective_chat.id not in allowed_chat_ids:
        await q.answer()
        return
    await q.answer()
    session_id = q.data[len(CALLBACK_PREFIX_USE) :]
    text = await bot_core.handle_switch_session(session_id)
    await q.edit_message_text(text)


async def cmd_new(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = await bot_core.handle_new_session()
    await update.message.reply_text(text)


async def cmd_opencode(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = bot_core.handle_opencode_status()
    keyboard = None
    if not bot_core.is_opencode_healthy():
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("启动 OpenCode", callback_data=CALLBACK_START_OPENCODE)]
        ])
    await update.message.reply_text(text, reply_markup=keyboard)


async def on_start_opencode(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    if not q or q.data != CALLBACK_START_OPENCODE:
        return
    if allowed_chat_ids and update.effective_chat and update.effective_chat.id not in allowed_chat_ids:
        await q.answer()
        return
    await q.answer()
    log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "opencode.log")
    ok, msg = bot_core.handle_start_opencode(log_path)
    await q.edit_message_text(f"OpenCode: {msg}")


async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return
    text = update.message.text.strip()
    if not text:
        return
    await update.message.reply_text("已收到，正在执行…")
    result = await bot_core.handle_message(text)
    for chunk in bot_core.chunk_text(result):
        await update.message.reply_text(chunk)


def run_telegram(config: dict) -> None:
    global allowed_chat_ids
    token = (config.get("telegram_token") or "").strip()
    if not token:
        return
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


def load_config() -> dict:
    root = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(root, "config.json")
    if not os.path.isfile(path):
        raise SystemExit("请创建 config.json（参考 config.json.example）")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main() -> None:
    config = load_config()
    if not config.get("telegram_token"):
        raise SystemExit("config.json 中 telegram_token 不能为空")
    run_telegram(config)


if __name__ == "__main__":
    main()
