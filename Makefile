.PHONY: update restart logs status dev install

# 一键更新+重启（服务器上用）
update:
	bash deploy/update.sh

# 杀进程+重启
restart:
	kill -9 $$(lsof -t -i:8080) 2>/dev/null || true
	sleep 1
	nohup python -m sugar_agent > sugar.log 2>&1 &
	@sleep 2
	@echo "✅ 已重启"
	@tail -5 sugar.log

# 看日志
logs:
	tail -f sugar.log

# 看进程状态
status:
	@curl -s http://localhost:8080/api/v1/health | python3 -m json.tool 2>/dev/null || echo "❌ 服务未运行"

# 开发模式（本地）
dev:
	python -m sugar_agent

# 安装依赖
install:
	pip install -e . -i https://pypi.tuna.tsinghua.edu.cn/simple
