"""企业微信"客户联系"桥接适配器（推荐，零限制主动推送）。

通过企业微信客户联系 API 实现消息收发：
- 主动推送：无48h限制，随时通过 externalcontact/message/send 发消息
- 被动回复：收到消息后通过回调 URL 的 HTTP 响应回复（5秒内有效，超时走主动推送）
- Access Token 自动管理（缓存 + 提前刷新）

API 文档:
- https://developer.work.weixin.qq.com/document/path/92135  (发送消息)
- https://developer.work.weixin.qq.com/document/path/90968  (加解密)
"""

import time
from typing import Optional

import httpx
from loguru import logger

from sugar_agent.wechat.base import BridgeStatus, IncomingMessage, WeChatBridge


class WeComBridge(WeChatBridge):
    """企业微信"客户联系"适配器。

    与普通应用消息的区别：
    - 发送API: /cgi-bin/externalcontact/message/send （无48h限制！）
    - 用户ID: 使用 external_userid（女朋友扫码后获得的永久ID）
    - 回调消息的 FromUserName 即为 external_userid
    """

    def __init__(
        self,
        corp_id: str = "",
        agent_id: str = "",
        secret: str = "",
        token: str = "",
        encoding_aes_key: str = "",
        # 客户联系需要的额外字段
        service_userid: str = "",  # 接待人员的 UserID（你自己的企业微信账号ID）
    ):
        self.corp_id = corp_id
        self.agent_id = agent_id
        self.secret = secret
        self.token = token
        self.encoding_aes_key = encoding_aes_key
        self.service_userid = service_userid

        self._access_token: Optional[str] = None
        self._token_expires_at: float = 0
        self._client: Optional[httpx.AsyncClient] = None
        self._crypto = None

    def _get_crypto(self):
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
        return all([self.corp_id, self.secret])

    # ============ Access Token ============

    async def _get_access_token(self) -> Optional[str]:
        """获取 Access Token，提前5分钟刷新。"""
        if self._access_token and time.time() < self._token_expires_at - 300:
            return self._access_token

        if not self.is_configured:
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
                return self._access_token
            else:
                logger.error(f"WeCom gettoken failed: {data}")
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
        """主动发送文本消息给客户（女朋友）。

        使用客户联系 API — 无 48 小时限制！
        API: POST /cgi-bin/externalcontact/message/send
        """
        token = await self._get_access_token()
        if not token:
            return False

        try:
            client = await self._get_http_client()
            body = {
                "touser": to_user,           # external_userid（回调消息中的 FromUserName）
                "msgtype": "text",
                "agentid": int(self.agent_id),
                "text": {"content": text},
            }
            # 如果配置了 service_userid，加上 sender
            if self.service_userid:
                body["sender"] = self.service_userid

            response = await client.post(
                "https://qyapi.weixin.qq.com/cgi-bin/externalcontact/message/send",
                params={"access_token": token},
                json=body,
            )
            data = response.json()
            if data.get("errcode") == 0:
                logger.debug(f"WeCom → {to_user[:20]}...: {text[:50]}...")
                return True
            else:
                logger.error(f"WeCom send failed: errcode={data.get('errcode')} errmsg={data.get('errmsg')}")
                return False
        except Exception as e:
            logger.error(f"WeCom send error: {e}")
            return False

    async def send_image(self, to_user: str, image_bytes: bytes) -> bool:
        """发送图片给客户。"""
        token = await self._get_access_token()
        if not token:
            return False

        try:
            client = await self._get_http_client()

            # 上传素材
            upload_resp = await client.post(
                "https://qyapi.weixin.qq.com/cgi-bin/media/upload",
                params={"access_token": token, "type": "image"},
                files={"media": ("image.png", image_bytes, "image/png")},
            )
            upload_data = upload_resp.json()
            if upload_data.get("errcode") != 0:
                logger.error(f"WeCom upload failed: {upload_data}")
                return False

            # 发送图片
            body = {
                "touser": to_user,
                "msgtype": "image",
                "agentid": int(self.agent_id),
                "image": {"media_id": upload_data["media_id"]},
            }
            if self.service_userid:
                body["sender"] = self.service_userid

            send_resp = await client.post(
                "https://qyapi.weixin.qq.com/cgi-bin/externalcontact/message/send",
                params={"access_token": token},
                json=body,
            )
            return send_resp.json().get("errcode") == 0
        except Exception as e:
            logger.error(f"WeCom send image error: {e}")
            return False

    async def poll_messages(self, since_id: Optional[str] = None) -> list[IncomingMessage]:
        """客户联系通过回调推送消息，不需轮询。"""
        return []

    async def get_bridge_status(self) -> BridgeStatus:
        if not self.is_configured:
            return BridgeStatus(connected=False, last_error="WeCom not configured")
        token = await self._get_access_token()
        return BridgeStatus(
            connected=token is not None,
            wechat_logged_in=token is not None,
            last_error=None if token else "Failed to get access token",
        )

    async def start(self):
        if self.is_configured:
            token = await self._get_access_token()
            if token:
                logger.info("WeCom (客户联系) bridge ready ✓ — 无48h限制的主动推送已就绪")
            else:
                logger.error("WeCom bridge: check corp_id/secret")

    async def stop(self):
        if self._client:
            await self._client.aclose()
            self._client = None

    # ============ 外部联系人查询 ============

    async def list_customers(self, userid: str = "") -> list[dict]:
        """获取外部联系人列表。

        用来找到女朋友的 external_userid。
        API: GET /cgi-bin/externalcontact/list
        """
        token = await self._get_access_token()
        if not token:
            return []

        uid = userid or self.service_userid
        if not uid:
            logger.error("Cannot list customers: no userid provided")
            return []

        try:
            client = await self._get_http_client()
            response = await client.get(
                "https://qyapi.weixin.qq.com/cgi-bin/externalcontact/list",
                params={"access_token": token, "userid": uid},
            )
            data = response.json()
            if data.get("errcode") == 0:
                external_ids = data.get("external_userid", [])
                return external_ids
            else:
                logger.error(f"List customers failed: {data}")
                return []
        except Exception as e:
            logger.error(f"List customers error: {e}")
            return []

    async def get_customer_info(self, external_userid: str) -> dict:
        """获取单个外部联系人的详细信息。

        API: GET /cgi-bin/externalcontact/get
        """
        token = await self._get_access_token()
        if not token:
            return {}

        try:
            client = await self._get_http_client()
            response = await client.get(
                "https://qyapi.weixin.qq.com/cgi-bin/externalcontact/get",
                params={"access_token": token, "external_userid": external_userid},
            )
            data = response.json()
            if data.get("errcode") == 0:
                ext = data.get("external_contact", {})
                return {
                    "external_userid": external_userid,
                    "name": ext.get("name", ""),
                    "type": "微信用户" if ext.get("type") == 1 else "企业微信用户",
                    "avatar": ext.get("avatar", ""),
                    "gender": ext.get("gender", ""),
                }
            return {}
        except Exception as e:
            logger.error(f"Get customer error: {e}")
            return {}

    async def get_follow_user_list(self) -> list[dict]:
        """获取配置了客户联系功能的成员列表。

        用于找到 service_userid。
        API: GET /cgi-bin/externalcontact/get_follow_user_list
        """
        token = await self._get_access_token()
        if not token:
            return []

        try:
            client = await self._get_http_client()
            response = await client.get(
                "https://qyapi.weixin.qq.com/cgi-bin/externalcontact/get_follow_user_list",
                params={"access_token": token},
            )
            data = response.json()
            if data.get("errcode") == 0:
                return data.get("follow_user", [])
            return []
        except Exception as e:
            logger.error(f"Get follow user list error: {e}")
            return []

    # ============ 回调消息处理 ============

    def verify_callback_url(
        self, msg_signature: str, timestamp: str, nonce: str, echostr: str
    ) -> tuple:
        crypto = self._get_crypto()
        errcode, decrypted = crypto.verify_url(msg_signature, timestamp, nonce, echostr)
        return errcode, decrypted or ""

    def decrypt_callback_msg(
        self, msg_signature: str, timestamp: str, nonce: str, post_data: str
    ) -> tuple:
        crypto = self._get_crypto()
        return crypto.decrypt_msg(msg_signature, timestamp, nonce, post_data)

    def encrypt_reply(self, reply_xml: str, nonce: Optional[str] = None) -> tuple:
        crypto = self._get_crypto()
        return crypto.encrypt_msg(reply_xml, nonce)

    @staticmethod
    def parse_message(xml_string: str) -> Optional[IncomingMessage]:
        """从回调 XML 中解析消息。

        客户联系的回调消息与普通应用消息格式一致，
        但 FromUserName 是 external_userid（格式如 wmXXXXXX 或 woXXXXXX）。
        """
        import re

        def get_tag(name):
            m = re.search(f"<{name}><!\\[CDATA\\[(.*?)\\]\\]></{name}>", xml_string)
            if m:
                return m.group(1)
            m = re.search(f"<{name}>(.*?)</{name}>", xml_string)
            return m.group(1) if m else ""

        msg_type = get_tag("MsgType")

        from_user = get_tag("FromUserName")
        msg_id = get_tag("MsgId")
        if not from_user:
            return None

        # 文本消息
        if msg_type == "text":
            content = get_tag("Content")
            if not content:
                return None
            return IncomingMessage(
                from_user=from_user,
                from_name="",
                content=content,
                message_type="text",
                message_id=msg_id,
            )

        # 图片消息
        if msg_type == "image":
            pic_url = get_tag("PicUrl")
            return IncomingMessage(
                from_user=from_user,
                from_name="",
                content="[图片]",
                message_type="image",
                image_url=pic_url,
                message_id=msg_id,
            )

        return None

    def build_reply_xml(self, to_user: str, from_user: str, content: str) -> str:
        """构造被动回复 XML。"""
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
