.PHONY: update restart logs status dev install

# 自动检测虚拟环境
VENV := $(shell find . -maxdepth 3 -name activate -path "*/.env*/bin/activate" 2>/dev/null | head -1)
VENV_CMD := $(if $(VENV),. $(VENV) &&,)

# 一键更新+重启（服务器上用）
update:
	bash deploy/update.sh

# 杀进程+重启（自动用虚拟环境）
restart:
	kill -9 $$(lsof -t -i:8080) 2>/dev/null || true
	sleep 1
	$(VENV_CMD) nohup python -m sugar_agent > sugar.log 2>&1 &
	@sleep 2
	@echo "✅ 已重启"
	@tail -5 sugar.log

# 看日志
logs:
	tail -f sugar.log

# 看进程状态
status:
	@curl -s http://localhost:8080/api/v1/health | python3 -m json.tool 2>/dev/null || echo "❌ 服务未运行"

# 安装依赖（自动用虚拟环境）
install:
	$(VENV_CMD) pip install -e . -i https://pypi.tuna.tsinghua.edu.cn/simple
