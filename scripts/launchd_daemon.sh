#!/bin/bash
export PYTHONUNBUFFERED=1
export PATH="/opt/anaconda3/bin:/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/bin"
export HOME="/Users/peter_mini"
cd "/Volumes/SanDisk2TB/自媒体作品/小红书起号/moodboard-hidden-ny-jjjjound" || exit 1
/opt/anaconda3/bin/python3 -u scripts/daemon_scheduler.py
