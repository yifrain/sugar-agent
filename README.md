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

## 📦 部署到服务器 + 连接企业微信

### 服务器要求

- 国内云服务器（阿里云/腾讯云/京东云，1核2G 足够，约 50元/月）
- Ubuntu 20.04+ 或 CentOS 7+
- 一个域名 + SSL 证书（企业微信回调要求 HTTPS）
- 开放 8080 端口（或通过 Nginx 反代到 443）

### 方式1：Docker 部署（推荐）

```bash
# 1. 在服务器上安装 Docker
curl -fsSL https://get.docker.com | bash

# 2. 克隆代码
git clone https://github.com/yifrain/sugar-agent.git
cd sugar-agent

# 3. 创建 .env 配置文件（填入真实值）
cat > .env << 'EOF'
DASHSCOPE_API_KEY=sk-你的千问key
SENIVERSE_API_KEY=SvhG1EICm4ihD8D9X
ADMIN_PASSWORD=你的管理密码
SUGAR_ENV=production
EOF

# 4. 创建生产配置
cat > config/production.yaml << 'EOF'
app:
  env: production
wechat_bridge:
  type: wecom
wecom:
  enabled: true
  corp_id: "ww你的企业ID"
  agent_id: "1000002"
  secret: "你的应用Secret"
  token: "你设的Token"
  encoding_aes_key: "43位随机Key"
  service_userid: "你的企业微信账号ID"
llm:
  model: dashscope/qwen-plus
  fallback:
    model: deepseek/deepseek-chat
EOF

# 5. 启动
docker compose up -d

# 6. 查看日志
docker compose logs -f
```

### 方式2：直接部署

```bash
# 1. 安装 Python 3.11+
sudo apt update && sudo apt install python3.11 python3.11-venv -y

# 2. 克隆 + 安装
git clone https://github.com/yifrain/sugar-agent.git
cd sugar-agent
python3.11 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/pip install pycryptodome

# 3. 创建 .env 和 config/production.yaml（同上）

# 4. 安装 systemd 服务
sudo cp deploy/sugar-agent.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable sugar-agent
sudo systemctl start sugar-agent

# 5. 查看状态
sudo systemctl status sugar-agent
sudo journalctl -u sugar-agent -f
```

### Nginx 反向代理（HTTPS）

企业微信回调必须 HTTPS。安装 Nginx + Let's Encrypt：

```bash
sudo apt install nginx certbot python3-certbot-nginx -y

# 配置 Nginx
sudo tee /etc/nginx/sites-available/sugar-agent > /dev/null << 'EOF'
server {
    listen 80;
    server_name 你的域名.com;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
EOF

sudo ln -s /etc/nginx/sites-available/sugar-agent /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx

# 申请免费 SSL 证书
sudo certbot --nginx -d 你的域名.com

# 证书会自动续期
```

### 验证部署

```bash
# 健康检查
curl https://你的域名.com/api/v1/health

# 管理后台
# 浏览器打开 https://你的域名.com/admin/

# 企业微信回调URL
# 在公司后台填: https://你的域名.com/api/v1/wecom/callback
```

### 配置检查清单

部署前确认这些值都已填写：

| 检查项 | 在哪配 | 说明 |
|--------|--------|------|
| ✅ DASHSCOPE_API_KEY | .env | 千问API Key |
| ✅ SENIVERSE_API_KEY | .env | 心知天气私钥 |
| ✅ ADMIN_PASSWORD | .env | 管理后台密码 |
| ✅ wecom.corp_id | production.yaml | 企业ID |
| ✅ wecom.secret | production.yaml | 应用Secret |
| ✅ wecom.token | production.yaml | 回调Token |
| ✅ wecom.encoding_aes_key | production.yaml | 回调加密Key |
| ✅ wecom.service_userid | production.yaml | 你的企微账号 |
| ✅ HTTPS | Nginx+Certbot | 企业微信要求 |

## 🔌 微信接入（企业微信"客户联系" — 零风险 + 无限制主动推送）

> **为什么选"客户联系"？** 普通企业微信应用有48h互动限制才能主动推送，但"客户联系"API 完全不受此限制。女朋友扫码加你为"客户"后，你可以随时主动给她发消息。

### 她的体验

```
女朋友的微信里：
  联系人列表 → 企业微信联系人 → 糖糖小助手
  ┌─────────────────────────────┐
  │ 糖糖小助手                    │
  │                             │
  │ 早上好宝贝☀️                  │
  │ 今天有雨，记得带伞哦 🌂       │
  │                             │
  │ 血糖7.8 刚吃完午饭           │
  │                             │
  │ 餐后7.8还不错！               │
  │ 午饭吃的什么好吃的？😋         │
  └─────────────────────────────┘

跟普通微信聊天一模一样，只是联系人名称旁有个小"企"字标记
```

---

### 手把手注册教程

#### 第1步：注册企业微信（5分钟）

1. 打开 https://work.weixin.qq.com/ → 点「企业注册」

| 字段 | 填什么 |
|------|--------|
| 企业名称 | **随便写**，如 `Yifan的日常`（只有你能看到） |
| 行业类型 | `IT服务` |
| 人员规模 | `5人以下`（免费，最多100人） |
| 管理员姓名 | 你的真名 |
| 管理员手机号 | 你的手机号（收验证码） |
| 管理员微信 | 扫码绑定 |

> 💡 不需要认证！未认证状态完全够用，100人以下永久免费。

#### 第2步：开启客户联系（1分钟）

1. 管理后台 → 左侧菜单「**客户联系**」
2. 如果未开启，点「开启」按钮
3. 开启后，找到「**联系我**」→ 点「新建」
4. 选择「**单人**」模式

| 字段 | 填什么 |
|------|--------|
| 接待人员 | 选你自己 |
| 备注名 | `糖糖小助手` |
| 场景 | `其他` |

5. 生成一个二维码 → **保存这张二维码**（女朋友之后扫这个码）

> 🔑 这只是加好友的入口。女朋友扫这个码后，你会收到她的加好友请求，通过就行。

#### 第3步：创建应用 + 获取参数

1. 管理后台 →「应用管理」→「自建」→「创建应用」

| 字段 | 填什么 |
|------|--------|
| 应用名称 | `糖糖小助手` |
| 应用logo | 随便上传个图片 |
| 可见范围 | 选你自己 |

2. 创建完后，进入应用详情页，**记下这些值**：

| 参数 | 在哪找 | 长什么样 |
|------|--------|---------|
| `corp_id` | 「我的企业」→「企业信息」→  企业ID | `ww1234567890abcd` |
| `agent_id` | 应用详情页顶部 | `1000002` |
| `secret` | 应用详情页 → 点「查看」Secret | 随机字符串（**只显示一次！**）|
| `service_userid` | 「通讯录」→ 点自己的名字 → 账号 | 如 `YifanLi` |

#### 第4步：配置接收消息回调

在应用详情页 →「接收消息」→「设置API接收」：

| 字段 | 填什么 |
|------|--------|
| **URL** | `https://你的域名/api/v1/wecom/callback` |
| **Token** | 自己随便写，如 `sugarAgent2024`（记下来） |
| **EncodingAESKey** | 点「随机生成」（记下43位）|

⚠️ 先**不要点保存**！等服务器启动后再回来保存。

> 如果还没有域名/HTTPS，可以用 [frp](https://github.com/fatedier/frp) 或 cloudflare tunnel 做内网穿透，先测试通再搞正式域名。

#### 第5步：写入配置

编辑 `.env` 文件（推荐，放在服务器上）：

```bash
# 企业微信"客户联系"配置
SUGAR__WECOM__ENABLED=true
SUGAR__WECOM__CORP_ID=ww1234567890abcd
SUGAR__WECOM__AGENT_ID=1000002
SUGAR__WECOM__SECRET=你复制的Secret
SUGAR__WECOM__TOKEN=sugarAgent2024
SUGAR__WECOM__ENCODING_AES_KEY=随机生成的43位
SUGAR__WECOM__SERVICE_USERID=YifanLi
```

同时也要改桥接类型，编辑 `config/production.yaml`：

```yaml
wechat_bridge:
  type: wecom  # 使用企业微信
```

#### 第6步：启动 → 保存回调 → 扫码测试

```bash
# 1. 在服务器上启动
python -m sugar_agent

# 日志应该显示:
# WeCom (客户联系) bridge ready ✓ — 无48h限制的主动推送已就绪

# 2. 回到企业微信后台，点「保存」
#    → 企业微信会 GET 回调URL验证
#    → 日志显示 "WeCom callback URL verified successfully!"

# 3. 如果保存失败，检查：
#    - URL 是否能从外网访问（curl https://你的域名/api/v1/wecom/callback）
#    - Token/EncodingAESKey 是否一致
#    - 服务日志 tail -f data/logs/sugar-agent_*.log
```

#### 第7步：女朋友扫码 ✨

1. 把第2步保存的「联系我」二维码发给女朋友
2. 她**用微信扫** → 点「添加」→ 变成她的微信联系人
3. 你登录企业微信 APP，通过她的好友请求
4. 然后她发一条消息 → agent 回复 → 🎉

> 以后她只需要在微信聊天列表里找到「糖糖小助手」就能随时聊天。
> 你也可以随时让 agent **主动**发消息给她 — 早上天气预报、低血糖提醒、定时问候。

### 开发测试（Mock 模式）

无需任何微信配置：
```bash
python -m sugar_agent
# 访问 http://localhost:8080/admin/ → 对话记录 → 手动发送消息
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
