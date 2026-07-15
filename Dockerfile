FROM python:3.11-slim

WORKDIR /app

# 安装依赖
COPY pyproject.toml .
RUN pip install --no-cache-dir -e ".[dev]" && pip install --no-cache-dir pycryptodome

# 复制源码
COPY . .

# 创建数据目录
RUN mkdir -p data/memories data/logs

EXPOSE 8080

CMD ["python", "-m", "sugar_agent"]
