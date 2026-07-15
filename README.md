# sugar-agent 🍬🤖

> 一款基于 AI Agent 架构的个人微信恋爱健康守护助手。

`sugar-agent` 是一个专为女朋友定制的"暖男属性"智能体。它不仅像一个真正的微信好友一样 24 小时在线，还具备以下核心超能力：
- 📈 **Sugar Monitor (血糖监控)**：随时接收并结构化记录女朋友发送的血糖数据，根据数值给出幽默又暖心的反馈。
- 🌤️ **Weather & Umbrella Call (天气预测)**：实时调用天气工具，在雨天、极端天气时化身"贴心管家"提醒带伞、添衣。
- 💬 **Humorous Chatbot (幽默灵魂)**：拒绝冰冷说教，用最风趣、有梗、宠溺的语气和她聊天。
- 🧠 **Memory System (共同记忆)**：持续积累两人的共同记忆、她的喜好习惯，越来越有人味。
- 🖥️ **Web Admin Panel (管理后台)**：通过 Web 界面查看对话、管理记忆、编辑提示词、查看血糖趋势。

---
💡 *"This project runs 24/7, just like my love for her."*

(这个项目 24 小时永不停歇，就像我对她的爱一样。)

## 🏗️ 架构

```
用户微信 → 微信桥接 → FastAPI Server → Agent Core → LLM (DeepSeek/千问)
                                ↓
                    ┌───────────┼───────────┐
                    ↓           ↓           ↓
                记忆系统    健康分析    天气服务
                    ↓           ↓           ↓
                 SQLite + Markdown 文件存储
```

## 🚀 快速开始

### 1. 环境准备
```bash
# 克隆仓库
git clone <repo-url>
cd sugar-agent

# 安装依赖 (需要 Python 3.11+)
pip install -e .
# 或使用 uv
uv pip install -e .
```

### 2. 配置
```bash
# 复制环境变量模板
cp .env.example .env
# 编辑 .env 填入 API Keys
```

必需配置：
- `DEEPSEEK_API_KEY` - DeepSeek API (推荐，便宜)
- `ADMIN_PASSWORD` - 管理后台登录密码

可选配置：
- `DASHSCOPE_API_KEY` - 千问 API (备用)
- `SENIVERSE_API_KEY` - 心知天气 API
- `BRIDGE_BASE_URL` - 微信桥接进程地址
- `BRIDGE_API_KEY` - 桥接通信密钥

### 3. 启动
```bash
# 开发模式 (使用 Mock 桥接，可在终端看到对话)
python -m sugar_agent

# 或使用 uvicorn
uvicorn sugar_agent.main:app --reload --port 8080
```

### 4. 访问
- **管理后台**: http://localhost:8080/admin/
- **健康检查**: http://localhost:8080/api/v1/health
- **API 文档**: http://localhost:8080/docs

## 📋 管理后台

Web 管理界面提供以下功能：

| 页面 | 功能 |
|------|------|
| 📊 仪表盘 | 今日消息数、血糖记录数、LLM 用量、桥接状态 |
| 💬 对话记录 | 搜索/浏览历史对话，手动发送测试消息 |
| 🧠 记忆管理 | CRUD 记忆，分类筛选，设置重要性/钉选 |
| ✏️ 提示词编辑 | 在线编辑系统提示词，修改后即时生效，自动备份 |
| 📈 血糖数据 | 趋势图表、数据表格、手动添加/修正记录 |
| ⏰ 定时任务 | 查看/手动触发定时任务 |
| ⚙️ 系统设置 | 查看当前配置 |

## 🛠️ 技术栈

| 技术 | 用途 |
|------|------|
| **FastAPI** | Web 框架，Webhook + API + 静态文件 |
| **litellm** | 多模型 LLM 抽象 (DeepSeek/千问/Claude) |
| **SQLite + SQLAlchemy** | 数据存储 (零配置) |
| **APScheduler** | 定时任务 (天气提醒、问候、健康摘要) |
| **Alpine.js + Tailwind CSS** | 管理后台前端 (零构建) |
| **httpx** | 异步 HTTP 客户端 (桥接通信) |
| **loguru** | 日志 |
| **pytest** | 测试 |

## 🧪 测试

```bash
# 运行所有测试
pytest

# 运行特定测试
pytest tests/test_health_parser.py -v
```

## 📦 部署

### 国内云服务器

```bash
# 1. 设置环境变量
export SUGAR_REMOTE_HOST=your-server-ip
export SUGAR_REMOTE_USER=root

# 2. 执行部署
bash deploy/deploy.sh
```

部署脚本会自动：
- 同步源代码到服务器
- 安装依赖
- 配置 systemd 服务
- 启动并检查服务状态

### systemd 服务管理

```bash
# 查看状态
systemctl status sugar-agent

# 重启
systemctl restart sugar-agent

# 查看日志
journalctl -u sugar-agent -f
```

## 🔌 微信接入

### 方案选择

| 方案 | 封禁风险 | 主动推送 | 服务器 | 适合 |
|------|---------|---------|--------|------|
| **企业微信** ⭐ | 🟢 零风险 | ✅ | Linux | **推荐** |
| HTTP桥接(WeChatFerry等) | 🔴 高 | ✅ | Windows | 不推荐 |
| Mock | 🟢 无 | ✅ | 任意 | 开发调试 |

**企业微信是唯一零封禁风险的方案**，且你的女朋友在个人微信上就能收到消息。

---

### 企业微信接入教程（手把手）

#### 第1步：注册企业微信

1. 打开 https://work.weixin.qq.com/
2. 点右上角「企业注册」→ 选「全新注册」
3. **填写信息表格：**

| 字段 | 填什么 | 说明 |
|------|--------|------|
| 企业名称 | `Yifan的助手` 或随便起 | 只有你自己能看到 |
| 行业类型 | `IT服务` | 随便选 |
| 人员规模 | `5人以下` | 实际只需要1个账号 |
| 管理员姓名 | 你的真实姓名 | 不会对外显示 |
| 管理员手机号 | 你的手机号 | 需要收验证码 |
| 管理员微信 | 扫码绑定 | 用你的微信扫 |

4. 提交后收到验证码，填完就注册成功了

> 💡 **不需要认证**。注册完就是 "未认证" 状态，功能完全够用，100人以下免费。

#### 第2步：创建应用

1. 登录企业微信管理后台 https://work.weixin.qq.com/wework_admin/frame
2. 左侧菜单 →「应用管理」→ 点「自建」区域
3. 点「创建应用」按钮：

| 字段 | 填什么 |
|------|--------|
| 应用名称 | `糖糖小助手` |
| 应用logo | 上传一个可爱的图片（可以随便找张图）|
| 可见范围 | 选你自己（创建人）|

4. 点「创建应用」

#### 第3步：获取三个关键参数

创建完成后进入应用详情页，记下这三个值：

| 参数 | 在页面的位置 | 示例格式 |
|------|------------|---------|
| **Corp ID**（企业ID）| 页面最底部「我的企业」→「企业信息」| `ww1234567890abcdef` |
| **Agent ID**（应用ID）| 应用详情页顶部 | `1000002` |
| **Secret**（应用密钥）| 应用详情页 → 点「查看」Secret | `一串长随机字符串` |

> ⚠️ **Secret 只显示一次**，点「查看」后立即复制保存！

#### 第4步：配置回调 URL

在应用详情页往下滑，找到「接收消息」→ 点「设置API接收」：

1. **URL**：填入 `https://你的服务器域名:8080/api/v1/wecom/callback`
   > ⚠️ 必须是 `https://`，且域名要备案。如果你还没有 HTTPS，先跳过后面的步骤，等部署完服务器再回来配置
   
2. **Token**：随便填一个 3-32 位的字符串，比如 `sugarAgentToken2024`
   > 记下这个值，后面要写到配置文件里

3. **EncodingAESKey**：点「随机生成」按钮
   > 记下这 43 位字符，后面也要用

4. 先**不要点保存**！需要先启动你的服务器，企业微信才能验证 URL。

#### 第5步：配置 sugar-agent

编辑 `config/production.yaml`（或通过环境变量）：

```yaml
wechat_bridge:
  type: wecom  # 使用企业微信模式

wecom:
  enabled: true
  corp_id: "ww1234567890abcdef"    # 第3步记下的
  agent_id: "1000002"               # 第3步记下的
  secret: "你的Secret"               # 第3步记下的
  token: "sugarAgentToken2024"      # 第4步自己设的
  encoding_aes_key: "随机生成的43位"  # 第4步生成的
```

或通过环境变量（推荐放在 `.env` 里，更安全）：

```bash
SUGAR__WECOM__ENABLED=true
SUGAR__WECOM__CORP_ID=ww1234567890abcdef
SUGAR__WECOM__AGENT_ID=1000002
SUGAR__WECOM__SECRET=你的Secret
SUGAR__WECOM__TOKEN=sugarAgentToken2024
SUGAR__WECOM__ENCODING_AES_KEY=随机生成的43位
```

#### 第6步：启动并验证

```bash
# 1. 在服务器上启动 sugar-agent
python -m sugar_agent

# 2. 回到企业微信后台，点「保存」
#    企业微信会发送 GET 请求到你的回调 URL 验证
#    如果服务器在运行且配置正确，应该能保存成功

# 3. 如果失败，检查：
#    - 服务器日志 `tail -f data/logs/sugar-agent_*.log`
#    - 域名是否能从外网访问
#    - HTTPS 证书是否有效
```

#### 第7步：女朋友加你

1. 企业管理后台 →「通讯录」→「微信插件」
2. 看到一个二维码 → 让女朋友**用微信扫码**
3. 她扫码后，在微信里能看到「企业微信联系人」中有你的应用
4. 她发消息给你 → 你的 agent 就能收到并回复了！

> 💡 这一步是实现 "她微信→你bot" 的关键。她的微信会收到企业微信的提醒，看起来就像一个普通的微信对话。

#### 限制说明

| 项目 | 说明 |
|------|------|
| **主动推送** | 用户48小时内互动过才能推送。女朋友每天聊天 → 不存在问题 |
| **被动回复** | 收到消息5秒内回复有效（agent 在4秒内返回，超时则先回"让我想想"再主动推送） |
| **消息频率** | 企业微信API无频率限制 |
| **长期有效** | 不需要续费或认证，永久免费 |

### 开发模式 (Mock Bridge)

无需任何微信配置，直接在管理后台测试：
```bash
python -m sugar_agent
# 访问 http://localhost:8080/admin/ 
# → 对话记录 → 手动发送消息测试
```

桥接 API 契约：
- `POST /api/send` - 发送消息
- `GET /api/messages` - 拉取新消息 (轮询模式)
- `GET /api/health` - 健康检查

## 📖 系统提示词

提示词模板位于 `src/sugar_agent/prompts/system.md`，可通过管理后台在线编辑。

核心人格设定：
- 幽默但不刻意，温暖但不啰嗦
- 像男朋友一样关心血糖健康和生活细节
- **绝不给出具体用药建议**，提醒咨询医生
- 血糖知识：正常空腹 3.9-7.0 mmol/L，低血糖<3.9 立即提醒

## ⚠️ 重要提醒

- **隐私优先**：血糖数据和聊天记录属于敏感信息，请确保服务器安全
- **不是医疗设备**：本项目的血糖建议仅供参考，不替代专业医疗
- **微信使用合规**：个人微信桥接存在账号风险，请自行评估

## 📄 License

MIT License
