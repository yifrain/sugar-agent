"""微信企业消息加解密工具。

实现企业微信回调消息的 AES-256-CBC 加解密和签名验证。
参考: https://developer.work.weixin.qq.com/document/path/90968
"""

import base64
import hashlib
import struct
import time
from typing import Optional, Tuple

from Crypto.Cipher import AES
from Crypto.Random import get_random_bytes


class WXBizMsgCrypt:
    """企业微信消息加解密类。"""

    def __init__(self, token: str, encoding_aes_key: str, corp_id: str):
        """
        Args:
            token: 回调配置中的 Token（自己设置的3-32位字符串）
            encoding_aes_key: 回调配置中的 EncodingAESKey（43位随机字符串）
            corp_id: 企业 ID，从"我的企业"页面获取
        """
        self.token = token
        self.encoding_aes_key = encoding_aes_key
        self.corp_id = corp_id

        # AES Key = Base64.decode(EncodingAESKey + "=")
        self.aes_key = base64.b64decode(encoding_aes_key + "=")

    def verify_url(
        self, msg_signature: str, timestamp: str, nonce: str, echostr: str
    ) -> Tuple[int, Optional[str]]:
        """验证回调 URL。

        企业微信后台配置回调URL时会发送GET请求验证：
        GET /callback?msg_signature=xxx&timestamp=xxx&nonce=xxx&echostr=xxx

        Returns:
            (errcode, decrypted_echostr) — errcode=0 表示成功
        """
        # 1. 验证签名
        if not self._verify_signature(msg_signature, timestamp, nonce, echostr):
            return (-1, None)

        # 2. 解密 echostr
        try:
            plaintext = self._decrypt(echostr)
            return (0, plaintext.decode("utf-8"))
        except Exception:
            return (-2, None)

    def decrypt_msg(
        self, msg_signature: str, timestamp: str, nonce: str, post_data: str
    ) -> Tuple[int, Optional[str]]:
        """解密企业微信推送的消息。

        POST 到回调 URL 的 XML 数据中包含加密的 Encrypt 字段。

        Returns:
            (errcode, decrypted_xml_string)
        """
        # 1. 从 XML 中提取 Encrypt 字段
        import re
        encrypt_match = re.search(r"<Encrypt><!\[CDATA\[(.*?)\]\]></Encrypt>", post_data)
        if not encrypt_match:
            return (-3, None)
        encrypt = encrypt_match.group(1)

        # 2. 验证签名
        if not self._verify_signature(msg_signature, timestamp, nonce, encrypt):
            return (-1, None)

        # 3. 解密
        try:
            plaintext = self._decrypt(encrypt)
            return (0, plaintext.decode("utf-8"))
        except Exception as e:
            return (-2, None)

    def encrypt_msg(self, reply_xml: str, nonce: Optional[str] = None) -> Tuple[int, Optional[str]]:
        """加密回复消息。

        Returns:
            (errcode, encrypted_xml_string)
        """
        try:
            if nonce is None:
                nonce = hashlib.md5(str(time.time()).encode()).hexdigest()[:16]

            # 1. 加密
            encrypted = self._encrypt(reply_xml.encode("utf-8"))

            # 2. 生成签名
            timestamp = str(int(time.time()))
            signature = self._generate_signature(self.token, timestamp, nonce, encrypted)

            # 3. 构造 XML
            result_xml = f"""<xml>
<Encrypt><![CDATA[{encrypted}]]></Encrypt>
<MsgSignature><![CDATA[{signature}]]></MsgSignature>
<TimeStamp>{timestamp}</TimeStamp>
<Nonce><![CDATA[{nonce}]]></Nonce>
</xml>"""
            return (0, result_xml)
        except Exception:
            return (-4, None)

    # ===== 内部加解密方法 =====

    def _decrypt(self, encrypted: str) -> bytes:
        """AES-256-CBC 解密。

        解密后数据格式: random(16) + msg_len(4) + raw_msg + corp_id
        """
        cipher = AES.new(self.aes_key, AES.MODE_CBC, iv=self.aes_key[:16])
        ciphertext = base64.b64decode(encrypted)
        plaintext = cipher.decrypt(ciphertext)

        # 去除 PKCS7 填充
        pad_len = plaintext[-1]
        plaintext = plaintext[:-pad_len]

        # 解析: random(16) + msg_len(4) + msg + corp_id
        msg_len = struct.unpack("!I", plaintext[16:20])[0]
        msg = plaintext[20:20 + msg_len]
        corp_id = plaintext[20 + msg_len:].decode("utf-8")

        # 验证 corp_id
        if corp_id != self.corp_id:
            raise ValueError(f"CorpId mismatch: expected {self.corp_id}, got {corp_id}")

        return msg

    def _encrypt(self, plaintext: bytes) -> str:
        """AES-256-CBC 加密。

        加密后数据格式: random(16) + msg_len(4) + raw_msg + corp_id
        然后 Base64 编码。
        """
        # 构造: random(16) + msg_len(4) + msg + corp_id
        random_bytes = get_random_bytes(16)
        msg_len = struct.pack("!I", len(plaintext))
        corp_id_bytes = self.corp_id.encode("utf-8")
        raw = random_bytes + msg_len + plaintext + corp_id_bytes

        # PKCS7 填充到 32 字节倍数
        block_size = 32
        pad_len = block_size - (len(raw) % block_size)
        raw += bytes([pad_len] * pad_len)

        # AES-256-CBC 加密
        cipher = AES.new(self.aes_key, AES.MODE_CBC, iv=self.aes_key[:16])
        ciphertext = cipher.encrypt(raw)

        return base64.b64encode(ciphertext).decode("utf-8")

    # ===== 签名方法 =====

    def _verify_signature(self, msg_signature: str, timestamp: str, nonce: str, encrypt: str) -> bool:
        """验证消息签名。

        签名算法: SHA1(sort([token, timestamp, nonce, encrypt]))
        """
        expected = self._generate_signature(self.token, timestamp, nonce, encrypt)
        return msg_signature == expected

    @staticmethod
    def _generate_signature(token: str, timestamp: str, nonce: str, encrypt: str) -> str:
        """生成消息签名。"""
        params = sorted([token, timestamp, nonce, encrypt])
        raw = "".join(params)
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()
