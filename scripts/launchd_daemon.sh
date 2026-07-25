#!/bin/bash
# launchd wrapper for daemon_scheduler.py
PROJECT_DIR="/Volumes/SanDisk2TB/自媒体作品/小红书起号/moodboard-hidden-ny-jjjjound"
cd "$PROJECT_DIR" || exit 1
export PATH="/opt/anaconda3/bin:/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/bin"
export HOME="/Users/peter_mini"
echo "[launchd_daemon] Starting at $(date)"
exec /opt/anaconda3/bin/python3 -u "$PROJECT_DIR/scripts/daemon_scheduler.py"
