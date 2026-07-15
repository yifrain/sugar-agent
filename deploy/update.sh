#!/bin/bash
# Sugar Agent 一键更新脚本
# 放到服务器上：bash deploy/update.sh

set -e
cd "$(dirname "$0")/.."

echo "🔄 正在更新 sugar-agent..."

# 1. 停旧进程
kill -9 $(lsof -t -i:8080) 2>/dev/null || true
sleep 1

# 2. 拉最新代码
git pull

# 3. 安装依赖
if [ -d ".venv" ]; then
    .venv/bin/pip install -e . -q
else
    pip install -e . -q -i https://pypi.tuna.tsinghua.edu.cn/simple
fi

# 4. 启动
nohup python -m sugar_agent > sugar.log 2>&1 &
sleep 3

# 5. 检查
echo ""
echo "📋 启动日志:"
tail -20 sugar.log
echo ""
echo "🏥 健康检查:"
curl -s http://localhost:8080/api/v1/health | python3 -m json.tool 2>/dev/null || echo "(服务可能还在启动中...)"
echo ""
echo "✅ 更新完成！管理后台: http://$(hostname -I 2>/dev/null | awk '{print $1}' || echo '服务器IP'):8080/admin/"
