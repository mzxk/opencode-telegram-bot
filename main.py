"""
统一入口：根据 config.json 同时或单独启动 Telegram 与 Matrix。
"""
from __future__ import annotations

import asyncio
import logging
import os
import threading

import opencode_runner as runner

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def main() -> None:
    from telegram_bot import load_config, run_telegram
    import matrix_bot

    config = load_config()
    root = os.path.dirname(os.path.abspath(__file__))
    ok, msg = runner.ensure_opencode_running(log_path=os.path.join(root, "opencode.log"))
    logger.info("OpenCode: %s", msg)

    has_telegram = bool(config.get("telegram_token"))
    has_matrix = bool(config.get("matrix_homeserver") and config.get("matrix_user_id"))
    if not has_telegram and not has_matrix:
        raise SystemExit("config.json 中需配置 telegram_token 或 matrix_homeserver+matrix_user_id")

    if has_telegram and has_matrix:
        t = threading.Thread(target=run_telegram, args=(config,), daemon=True)
        t.start()
        logger.info("Telegram 已启动")
        asyncio.run(matrix_bot.main_async())
    elif has_telegram:
        run_telegram(config)
    else:
        asyncio.run(matrix_bot.main_async())


if __name__ == "__main__":
    main()
