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

## 🔌 微信桥接

当前使用抽象接口设计，支持可插拔的微信后端：

### 开发模式 (Mock Bridge)
默认使用 Mock 桥接，可通过管理后台手动发送消息进行测试。

### 生产模式 (HTTP Bridge)
需要在一台 Windows 机器上运行 WeChat 桥接程序（如 WeChatFerry），
该程序需要登录微信并暴露 HTTP API。

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
