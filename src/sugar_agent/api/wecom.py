"""企业微信回调接口。

处理企业微信应用的消息回调：
- GET  /api/v1/wecom/callback — URL验证（企业微信后台配置时触发）
- POST /api/v1/wecom/callback — 接收用户消息，异步处理后主动回复
"""

import asyncio
from fastapi import APIRouter, Query, Request, Response
from loguru import logger

router = APIRouter()


@router.get("/wecom/callback")
async def wecom_verify(
    msg_signature: str = Query(..., alias="msg_signature"),
    timestamp: str = Query(...),
    nonce: str = Query(...),
    echostr: str = Query(...),
    request: Request = None,
):
    """企业微信回调 URL 验证。

    企业微信后台在配置回调 URL 时会发送 GET 请求来验证服务器。
    我们需要解密 echostr 并返回明文（不能加引号，不能有 BOM）。
    """
    bridge = request.app.state.bridge

    # 检查是否是 WeCom 桥接
    if not hasattr(bridge, "verify_callback_url"):
        logger.warning("WeCom verify: bridge doesn't support WeCom callbacks")
        return Response(content="bridge not configured", status_code=400)

    errcode, plaintext = bridge.verify_callback_url(
        msg_signature, timestamp, nonce, echostr
    )

    if errcode != 0:
        logger.error(f"WeCom URL verification failed: errcode={errcode}")
        return Response(content=f"verify failed: {errcode}", status_code=403)

    logger.info("WeCom callback URL verified successfully!")
    # 返回解密后的 echostr 明文（FastAPI 的 Response 直接返回字符串，不会加引号）
    return Response(content=plaintext, media_type="text/plain")


@router.post("/wecom/callback")
async def wecom_receive(
    request: Request,
    msg_signature: str = Query(..., alias="msg_signature"),
    timestamp: str = Query(...),
    nonce: str = Query(...),
):
    """接收企业微信推送的用户消息。

    流程：
    1. 读取加密的 XML body
    2. 解密得到明文 XML
    3. 解析用户消息
    4. 异步调用 Agent 处理
    5. 如果采用被动回复模式，构造加密回复返回
    """
    bridge = request.app.state.bridge

    if not hasattr(bridge, "decrypt_callback_msg"):
        return Response(content="not configured", status_code=400)

    # 1. 读取加密 body
    post_data = await request.body()
    post_str = post_data.decode("utf-8")

    # 2. 解密
    errcode, xml_content = bridge.decrypt_callback_msg(
        msg_signature, timestamp, nonce, post_str
    )

    if errcode != 0:
        logger.error(f"WeCom decrypt failed: errcode={errcode}")
        return Response(content="decrypt failed", status_code=403)

    # 3. 检查是否是"添加联系人"事件 → 发送欢迎语
    new_user_id = bridge.parse_event(xml_content)
    if new_user_id:
        welcome = (
            f"嗨！我是一帆派来的小分身～☀️\n"
            f"他让我随时陪着你，关心你、逗你开心。\n"
            f"以后每天会跟你说早安、提醒你天气，\n"
            f"你有什么想说的、想聊的，随时发给我就好。\n"
            f"我一直都在 💛"
        )
        asyncio.create_task(bridge.send_text(new_user_id, welcome))
        logger.info(f"👋 Welcome message sent to new contact: {new_user_id[:20]}...")
        return Response(content="")

    # 4. 解析消息
    msg = bridge.parse_message(xml_content)
    if msg is None:
        logger.debug("WeCom received non-text message, ack only")
        return Response(content="")

    logger.info(f"📩 WeCom: {msg.content[:100]}")

    # 4. 异步处理：先返回 200 给企业微信，再通过 API 主动回复
    agent = request.app.state.agent
    if agent:
        # 尝试被动回复（5秒内有效）
        try:
            response_text = await asyncio.wait_for(
                agent.process_incoming_message(msg), timeout=4.0
            )
        except asyncio.TimeoutError:
            # 超时则先回复"稍等"，后续异步推送
            response_text = "收到你的消息啦～让我想想...☁️"

        if response_text:
            # 构造并加密回复
            # from_user = msg.to_user_name (即原 XML 的 ToUserName)
            # to_user   = msg.from_user
            # 从解密后的 XML 中提取 ToUserName
            import re
            to_user_match = re.search(
                r"<ToUserName><!\[CDATA\[(.*?)\]\]></ToUserName>", xml_content
            )
            corp_id = to_user_match.group(1) if to_user_match else bridge.corp_id

            reply_xml = bridge.build_reply_xml(msg.from_user, corp_id, response_text)
            _, encrypted = bridge.encrypt_reply(reply_xml, nonce)

            if encrypted:
                logger.info(f"📤 WeCom reply: {response_text[:50]}...")
                return Response(content=encrypted, media_type="application/xml")

    # 如果 Agent 不可用或加密失败
    return Response(content="")
