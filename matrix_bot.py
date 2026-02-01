"""
Matrix Bot：通过 matrix-nio 连接 Matrix，支持 E2EE；将用户消息转发给 OpenCode，仅回复最终结果。
登录：首次使用 id + 密码 + 家服务器，成功后保存 token 到本地并从 config 删除密码，后续仅用 token 登录。
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time

import bot_core

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

ROOT = os.path.dirname(os.path.abspath(__file__))
CREDENTIALS_PATH = os.path.join(ROOT, "matrix_credentials.json")
STORE_PATH = os.path.join(ROOT, "matrix_store")
CONFIG_PATH = os.path.join(ROOT, "config.json")


def _load_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def _save_config(config: dict) -> None:
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


def _load_credentials() -> dict | None:
    if not os.path.isfile(CREDENTIALS_PATH):
        return None
    with open(CREDENTIALS_PATH, encoding="utf-8") as f:
        return json.load(f)


def _save_credentials(access_token: str, device_id: str, user_id: str, homeserver: str) -> None:
    os.makedirs(ROOT, exist_ok=True)
    with open(CREDENTIALS_PATH, "w", encoding="utf-8") as f:
        json.dump(
            {"access_token": access_token, "device_id": device_id, "user_id": user_id, "homeserver": homeserver},
            f,
            indent=2,
        )


def _remove_password_from_config() -> None:
    config = _load_config()
    if "matrix_password" in config:
        del config["matrix_password"]
        _save_config(config)
        logger.info("已从 config.json 移除 matrix_password")


async def _run_matrix(
    homeserver: str,
    user_id: str,
    access_token: str,
    device_id: str,
    allowed_room_ids: list[str],
    allowed_user_ids: list[str],
    matrix_password: str = "",
) -> None:
    from nio import AsyncClient, AsyncClientConfig, MegolmEvent, RoomMessageText, SyncResponse
    from nio.exceptions import LocalProtocolError
    from nio.responses import DeleteDevicesAuthResponse, DeleteDevicesResponse, DevicesResponse
    from nio.store import SqliteStore

    os.makedirs(STORE_PATH, exist_ok=True)
    config = AsyncClientConfig(store=SqliteStore, store_sync_tokens=True)
    client = AsyncClient(homeserver, user_id, device_id=device_id, store_path=STORE_PATH, config=config)
    client.restore_login(user_id, device_id, access_token)
    start_ts_ms = int(time.time() * 1000)

    def is_old_event(event) -> bool:
        """仅处理启动后的消息，避免对历史记录全部回复。"""
        ts = getattr(event, "server_timestamp", 0) or 0
        return ts < start_ts_ms - 60_000

    async def send_text(room_id: str, text: str) -> None:
        for chunk in bot_core.chunk_text(text):
            await client.room_send(
                room_id,
                message_type="m.room.message",
                content={"msgtype": "m.notice", "body": chunk},
                ignore_unverified_devices=True,
            )

    async def on_message(room, event):
        try:
            if event.sender == client.user_id:
                return
            if is_old_event(event):
                return
            if allowed_user_ids and event.sender not in allowed_user_ids:
                logger.info("忽略未允许用户的消息，将 user_id 加入 config allowed_user_ids 可回复: %s", event.sender)
                return
            if allowed_room_ids and room.room_id not in allowed_room_ids:
                logger.info("忽略未允许房间的消息，将 room_id 加入 config allowed_room_ids 可回复: %s", room.room_id)
                return
            body = getattr(event, "body", None) or getattr(event, "decrypted_body", None) or ""
            body = (body or "").strip()
            if not body:
                return

            if body == "/start":
                await send_text(room.room_id, bot_core.handle_start())
                return
            if body in ("/session", "/sessions"):
                text = await bot_core.handle_session_list()
                await send_text(room.room_id, text)
                return
            if body == "/new":
                text = await bot_core.handle_new_session()
                await send_text(room.room_id, text)
                return
            if body == "/opencode":
                text = bot_core.handle_opencode_status()
                if not bot_core.is_opencode_healthy():
                    log_path = os.path.join(ROOT, "opencode.log")
                    ok, msg = bot_core.handle_start_opencode(log_path)
                    text = f"OpenCode: {msg}"
                await send_text(room.room_id, text)
                return
            if body.startswith("/use "):
                sid = body[5:].strip()
                text = await bot_core.handle_switch_session(sid)
                await send_text(room.room_id, text)
                return

            await send_text(room.room_id, "已收到，正在执行…")
            result = await bot_core.handle_message(body)
            await send_text(room.room_id, result)
        except Exception as e:
            logger.exception("处理 Matrix 消息失败: %s", e)
            try:
                await send_text(room.room_id, f"错误: {e}")
            except Exception:
                pass

    async def on_encrypted_undecryptable(room, event):
        """加密消息无法解密时回复提示（否则用户收不到任何反馈）。"""
        try:
            if event.sender == client.user_id:
                return
            if is_old_event(event):
                return
            if allowed_user_ids and event.sender not in allowed_user_ids:
                return
            if allowed_room_ids and room.room_id not in allowed_room_ids:
                return
            await send_text(
                room.room_id,
                "收到加密消息但无法解密。开启房间加密时会生成新会话密钥，本 bot 尚未收到该密钥。"
                "请使用未加密房间与 bot 对话，或在 Element 中从本账号已解密设备「请求密钥」并转发给本 bot 设备。",
            )
        except Exception as e:
            logger.exception("回复加密未解密提示失败: %s", e)

    client.add_event_callback(on_message, RoomMessageText)
    client.add_event_callback(on_encrypted_undecryptable, MegolmEvent)

    try:
        device_count_checked = False
        while True:
            try:
                sync_response = await client.sync(timeout=30000)
                if isinstance(sync_response, SyncResponse) and getattr(sync_response.rooms, "invite", None):
                    for room_id in sync_response.rooms.invite:
                        try:
                            await client.join(room_id)
                            logger.info("已加入房间 %s", room_id)
                        except Exception as join_err:
                            logger.warning("加入房间 %s 失败: %s", room_id, join_err)
                if not device_count_checked:
                    device_count_checked = True
                    try:
                        dev_resp = await client.devices()
                        if isinstance(dev_resp, DevicesResponse) and getattr(dev_resp, "devices", None):
                            devices = dev_resp.devices
                            n = len(devices)
                            if n <= 1:
                                logger.info("当前账号仅一台设备；消除 Element「bot 账户没有作自我验证」需在 Element 中以该账号完成安全设置中的验证/cross-signing（matrix-nio 暂不支持在 bot 内完成）")
                            else:
                                other_ids = [d.id for d in devices if d.id != client.device_id]
                                if not other_ids:
                                    logger.info("当前账号仅一台设备")
                                else:
                                    del_resp = await client.delete_devices(other_ids)
                                    if isinstance(del_resp, DeleteDevicesResponse):
                                        logger.info("已强制登出其他 %d 台设备", len(other_ids))
                                    elif isinstance(del_resp, DeleteDevicesAuthResponse) and matrix_password:
                                        del_resp2 = await client.delete_devices(
                                            other_ids,
                                            auth={"type": "m.login.password", "user": user_id, "password": matrix_password},
                                        )
                                        if isinstance(del_resp2, DeleteDevicesResponse):
                                            logger.info("已强制登出其他 %d 台设备", len(other_ids))
                                        else:
                                            logger.warning("登出其他设备认证失败")
                                    elif isinstance(del_resp, DeleteDevicesAuthResponse):
                                        logger.warning("登出其他设备需要密码认证，请在 config 中设置 matrix_password 或 matrix_password_for_uia 后重启，或手动在 Element 中登出其他设备")
                                    else:
                                        logger.warning("登出其他设备失败: %s", del_resp)
                    except Exception as e:
                        logger.debug("获取设备列表或登出其他设备失败: %s", e)
                await client.send_to_device_messages()
                if getattr(client, "should_upload_keys", False):
                    try:
                        await client.keys_upload()
                    except LocalProtocolError:
                        pass
                if getattr(client, "should_query_keys", False):
                    try:
                        await client.keys_query()
                    except LocalProtocolError:
                        pass
                if getattr(client, "should_claim_keys", False):
                    try:
                        await client.keys_claim(client.get_users_for_key_claiming())
                    except LocalProtocolError:
                        pass
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception("matrix sync: %s", e)
                await asyncio.sleep(5)
    finally:
        await client.close()


async def main_async() -> None:
    config = _load_config()
    homeserver = (config.get("matrix_homeserver") or "").strip()
    user_id = (config.get("matrix_user_id") or "").strip()
    password = (config.get("matrix_password") or "").strip()
    allowed_room_ids = list(config.get("allowed_room_ids") or [])
    allowed_user_ids = list(config.get("allowed_user_ids") or [])

    if not homeserver or not user_id:
        logger.warning("未配置 matrix_homeserver / matrix_user_id，跳过 Matrix")
        return

    password_for_uia = (config.get("matrix_password") or config.get("matrix_password_for_uia") or "").strip()
    creds = _load_credentials()
    if creds:
        access_token = creds.get("access_token", "").strip()
        device_id = (creds.get("device_id") or "").strip()
        if access_token and device_id:
            logger.info("使用已保存的 token 登录 Matrix")
            user_id = (creds.get("user_id") or user_id).strip()
            homeserver = (creds.get("homeserver") or homeserver).strip()
            await _run_matrix(homeserver, user_id, access_token, device_id, allowed_room_ids, allowed_user_ids, password_for_uia)
            return

    if not password:
        logger.warning("未配置 matrix_password 且无有效 matrix_credentials.json，跳过 Matrix")
        return

    from nio import AsyncClient, LoginResponse

    logger.info("使用密码首次登录 Matrix")
    client = AsyncClient(homeserver, user_id)
    login_resp = await client.login(password)
    if not isinstance(login_resp, LoginResponse):
        logger.error("Matrix 登录失败: %s", login_resp)
        return
    access_token = login_resp.access_token
    device_id = login_resp.device_id or "opencode-bot"
    await client.close()
    _save_credentials(access_token, device_id, user_id, homeserver)
    _remove_password_from_config()
    logger.info("已保存 token，后续将使用 token 登录")
    await _run_matrix(homeserver, user_id, access_token, device_id, allowed_room_ids, allowed_user_ids, password)


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
