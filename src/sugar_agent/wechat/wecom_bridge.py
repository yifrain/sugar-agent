"""企业微信桥接适配器。

通过企业微信官方 API 实现消息收发：
- 被动回复：收到消息后通过回调 URL 的 HTTP 响应回复（5秒内有效）
- 主动推送：通过 /cgi-bin/message/send API 主动发送消息
- Access Token 自动管理（带缓存和提前刷新）

API 文档: https://developer.work.weixin.qq.com/document/
"""

import time
from typing import Optional

import httpx
from loguru import logger

from sugar_agent.wechat.base import BridgeStatus, IncomingMessage, WeChatBridge


class WeComBridge(WeChatBridge):
    """企业微信适配器，实现 WeChatBridge 抽象接口。"""

    def __init__(
        self,
        corp_id: str = "",
        agent_id: str = "",
        secret: str = "",
        token: str = "",
        encoding_aes_key: str = "",
    ):
        self.corp_id = corp_id
        self.agent_id = agent_id
        self.secret = secret
        self.token = token
        self.encoding_aes_key = encoding_aes_key

        self._access_token: Optional[str] = None
        self._token_expires_at: float = 0
        self._client: Optional[httpx.AsyncClient] = None
        self._crypto = None

    def _get_crypto(self):
        """懒加载加解密实例。"""
        if self._crypto is None:
            from sugar_agent.wechat.wecom_crypto import WXBizMsgCrypt
            self._crypto = WXBizMsgCrypt(
                token=self.token,
                encoding_aes_key=self.encoding_aes_key,
                corp_id=self.corp_id,
            )
        return self._crypto

    @property
    def is_configured(self) -> bool:
        return all([self.corp_id, self.agent_id, self.secret])

    # ============ Access Token 管理 ============

    async def _get_access_token(self) -> Optional[str]:
        """获取或刷新 Access Token（提前5分钟刷新）。"""
        if self._access_token and time.time() < self._token_expires_at - 300:
            return self._access_token

        if not self.is_configured:
            logger.error("WeCom not configured (corp_id/agent_id/secret)")
            return None

        try:
            client = await self._get_http_client()
            response = await client.get(
                "https://qyapi.weixin.qq.com/cgi-bin/gettoken",
                params={"corpid": self.corp_id, "corpsecret": self.secret},
            )
            data = response.json()
            if data.get("errcode") == 0:
                self._access_token = data["access_token"]
                self._token_expires_at = time.time() + data["expires_in"]
                logger.debug(f"WeCom token OK, expires in {data['expires_in']}s")
                return self._access_token
            else:
                logger.error(f"WeCom gettoken: {data}")
                return None
        except Exception as e:
            logger.error(f"WeCom gettoken error: {e}")
            return None

    async def _get_http_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(15))
        return self._client

    # ============ WeChatBridge 接口实现 ============

    async def send_text(self, to_user: str, text: str) -> bool:
        """主动发送文本消息。"""
        token = await self._get_access_token()
        if not token:
            return False

        try:
            client = await self._get_http_client()
            body = {
                "touser": to_user,
                "msgtype": "text",
                "agentid": int(self.agent_id),
                "text": {"content": text},
            }
            response = await client.post(
                "https://qyapi.weixin.qq.com/cgi-bin/message/send",
                params={"access_token": token},
                json=body,
            )
            data = response.json()
            if data.get("errcode") == 0:
                logger.debug(f"WeCom sent to {to_user}: {text[:50]}...")
                return True
            else:
                logger.error(f"WeCom send failed: {data}")
                return False
        except Exception as e:
            logger.error(f"WeCom send error: {e}")
            return False

    async def send_image(self, to_user: str, image_bytes: bytes) -> bool:
        """主动发送图片（先上传获取 media_id，再发送）。"""
        token = await self._get_access_token()
        if not token:
            return False

        try:
            client = await self._get_http_client()

            # 1. 上传临时素材
            upload_resp = await client.post(
                "https://qyapi.weixin.qq.com/cgi-bin/media/upload",
                params={"access_token": token, "type": "image"},
                files={"media": ("image.png", image_bytes, "image/png")},
            )
            upload_data = upload_resp.json()
            if upload_data.get("errcode") != 0:
                logger.error(f"WeCom upload: {upload_data}")
                return False

            # 2. 发送图片消息
            body = {
                "touser": to_user,
                "msgtype": "image",
                "agentid": int(self.agent_id),
                "image": {"media_id": upload_data["media_id"]},
            }
            send_resp = await client.post(
                "https://qyapi.weixin.qq.com/cgi-bin/message/send",
                params={"access_token": token},
                json=body,
            )
            return send_resp.json().get("errcode") == 0
        except Exception as e:
            logger.error(f"WeCom send image: {e}")
            return False

    async def poll_messages(self, since_id: Optional[str] = None) -> list[IncomingMessage]:
        """企业微信通过回调推送消息，不需轮询。"""
        return []

    async def get_bridge_status(self) -> BridgeStatus:
        """检查 Access Token 是否可用。"""
        if not self.is_configured:
            return BridgeStatus(connected=False, last_error="WeCom not configured")
        token = await self._get_access_token()
        return BridgeStatus(
            connected=token is not None,
            wechat_logged_in=token is not None,
            last_error=None if token else "Failed to get access token",
        )

    async def start(self):
        """验证配置。"""
        if self.is_configured:
            token = await self._get_access_token()
            if token:
                logger.info("WeCom bridge ready ✓")
            else:
                logger.error("WeCom bridge: check corp_id/agent_id/secret")

    async def stop(self):
        if self._client:
            await self._client.aclose()
            self._client = None

    # ============ 回调消息处理（在 api/wecom.py 回调路由中调用）============

    def verify_callback_url(
        self, msg_signature: str, timestamp: str, nonce: str, echostr: str
    ) -> tuple:
        """验证回调 URL。返回 (errcode, plaintext_echostr)。"""
        crypto = self._get_crypto()
        errcode, decrypted = crypto.verify_url(msg_signature, timestamp, nonce, echostr)
        return errcode, decrypted or ""

    def decrypt_callback_msg(
        self, msg_signature: str, timestamp: str, nonce: str, post_data: str
    ) -> tuple:
        """解密回调消息。返回 (errcode, xml_string)。"""
        crypto = self._get_crypto()
        return crypto.decrypt_msg(msg_signature, timestamp, nonce, post_data)

    def encrypt_reply(self, reply_xml: str, nonce: Optional[str] = None) -> tuple:
        """加密回复消息。返回 (errcode, encrypted_xml)。"""
        crypto = self._get_crypto()
        return crypto.encrypt_msg(reply_xml, nonce)

    @staticmethod
    def parse_message(xml_string: str) -> Optional[IncomingMessage]:
        """从企业微信 XML 中解析出消息。

        回调 XML 示例:
        <xml>
            <ToUserName><![CDATA[corpid]]></ToUserName>
            <FromUserName><![CDATA[UserId]]></FromUserName>
            <CreateTime>1348831860</CreateTime>
            <MsgType><![CDATA[text]]></MsgType>
            <Content><![CDATA[血糖7.8]]></Content>
            <MsgId>1234567890</MsgId>
            <AgentID>1000002</AgentID>
        </xml>
        """
        import re

        def get_tag(name):
            m = re.search(f"<{name}><!\\[CDATA\\[(.*?)\\]\\]></{name}>", xml_string)
            if m:
                return m.group(1)
            m = re.search(f"<{name}>(.*?)</{name}>", xml_string)
            return m.group(1) if m else ""

        msg_type = get_tag("MsgType")
        if msg_type != "text":
            return None

        from_user = get_tag("FromUserName")
        content = get_tag("Content")
        msg_id = get_tag("MsgId")

        if not from_user or not content:
            return None

        return IncomingMessage(
            from_user=from_user,
            from_name="",
            content=content,
            message_type="text",
            message_id=msg_id,
        )

    def build_reply_xml(self, to_user: str, from_user: str, content: str) -> str:
        """构造被动回复的 XML 文本。"""
        create_time = int(time.time())
        return (
            f"<xml>"
            f"<ToUserName><![CDATA[{to_user}]]></ToUserName>"
            f"<FromUserName><![CDATA[{from_user}]]></FromUserName>"
            f"<CreateTime>{create_time}</CreateTime>"
            f"<MsgType><![CDATA[text]]></MsgType>"
            f"<Content><![CDATA[{content}]]></Content>"
            f"</xml>"
        )
