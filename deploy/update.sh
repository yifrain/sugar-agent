#!/bin/bash
# Sugar Agent 一键更新脚本
set -e
cd "$(dirname "$0")/.."

# 1. 自动找虚拟环境
VENV=""
for d in .venv .env_sugar env venv; do
    if [ -f "$d/bin/activate" ]; then
        VENV="$d"
        break
    fi
done

echo "🔍 虚拟环境: ${VENV:-无（用系统python）}"
echo "🔄 更新 sugar-agent..."

# 2. 停旧进程
kill -9 $(lsof -t -i:8080) 2>/dev/null || true
sleep 1

# 3. 拉最新代码
git pull

# 4. 装依赖
if [ -n "$VENV" ]; then
    "$VENV/bin/pip" install -e . -q -i https://pypi.tuna.tsinghua.edu.cn/simple
else
    pip install -e . -q -i https://pypi.tuna.tsinghua.edu.cn/simple
fi

# 5. 启动（用虚拟环境的python）
if [ -n "$VENV" ]; then
    nohup "$VENV/bin/python" -m sugar_agent > sugar.log 2>&1 &
else
    nohup python -m sugar_agent > sugar.log 2>&1 &
fi
sleep 3

# 6. 检查
echo ""
echo "📋 启动日志:"
tail -15 sugar.log
echo ""
echo "🏥 健康检查:"
curl -s http://localhost:8080/api/v1/health | python3 -m json.tool 2>/dev/null || echo "(仍在启动中...)"
echo ""
echo "✅ 完成！"
