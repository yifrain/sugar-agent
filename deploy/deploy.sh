#!/bin/bash
# Sugar Agent Deployment Script
# Deploys the agent to a remote server via rsync + ssh

set -e

REMOTE_HOST="${SUGAR_REMOTE_HOST:-}"
REMOTE_USER="${SUGAR_REMOTE_USER:-root}"
REMOTE_PATH="${SUGAR_REMOTE_PATH:-/opt/sugar-agent}"

if [ -z "$REMOTE_HOST" ]; then
    echo "Error: Set SUGAR_REMOTE_HOST environment variable"
    echo "Usage: SUGAR_REMOTE_HOST=123.456.789.0 SUGAR_REMOTE_USER=root ./deploy.sh"
    exit 1
fi

echo "🚀 Deploying Sugar Agent to $REMOTE_USER@$REMOTE_HOST:$REMOTE_PATH"

# 1. Sync source code (excluding data, venv, git)
echo "📦 Syncing source files..."
rsync -avz --delete \
    --exclude '.git' \
    --exclude '.venv' \
    --exclude 'data/' \
    --exclude '.env' \
    --exclude '__pycache__' \
    --exclude '*.pyc' \
    --exclude '.mypy_cache' \
    --exclude '.ruff_cache' \
    --exclude '.pytest_cache' \
    ./ "$REMOTE_USER@$REMOTE_HOST:$REMOTE_PATH/"

# 2. Install/update dependencies
echo "📥 Installing dependencies..."
ssh "$REMOTE_USER@$REMOTE_HOST" "cd $REMOTE_PATH && python -m venv .venv && .venv/bin/pip install -e ."

# 3. Copy .env file if it exists locally
if [ -f ".env" ]; then
    echo "🔑 Copying .env file..."
    scp .env "$REMOTE_USER@$REMOTE_HOST:$REMOTE_PATH/.env"
fi

# 4. Create data directories
echo "📁 Setting up data directories..."
ssh "$REMOTE_USER@$REMOTE_HOST" "mkdir -p $REMOTE_PATH/data/{memories,logs}"

# 5. Install and enable systemd service
echo "⚙️ Setting up systemd service..."
ssh "$REMOTE_USER@$REMOTE_HOST" "cp $REMOTE_PATH/deploy/sugar-agent.service /etc/systemd/system/ && systemctl daemon-reload && systemctl enable sugar-agent"

# 6. Restart the service
echo "🔄 Restarting service..."
ssh "$REMOTE_USER@$REMOTE_HOST" "systemctl restart sugar-agent"

# 7. Check status
echo "✅ Checking service status..."
sleep 3
ssh "$REMOTE_USER@$REMOTE_HOST" "systemctl status sugar-agent --no-pager"

echo ""
echo "🎉 Deployment complete!"
echo "   Health check: http://$REMOTE_HOST:8080/api/v1/health"
echo "   Admin panel:  http://$REMOTE_HOST:8080/admin/"
