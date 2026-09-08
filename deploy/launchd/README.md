# launchd 服务项（TasteGraph mini 常驻）

> 这些 plist **只入库，不自动安装**。加载/卸载是老板的人工动作，
> 仓库内任何脚本都不会执行 launchctl。

## 文件

| plist | Label | 作用 | 重启策略 |
|---|---|---|---|
| `com.user.tastegraph.ingestion.plist` | `com.user.tastegraph.ingestion` | 每天 03:00 跑 `daily_ingestion.py --resume`（唯一安全采集入口）；RunAtLoad 开机/登录补跑，当天已成功则幂等跳过 | 不 KeepAlive；失败靠 `--resume` + 下一轮补跑 |
| `com.user.tastegraph.backup.plist` | `com.user.tastegraph.backup` | 每天 04:00 跑 `backup_db.py`（SQLite 在线备份 → `data/backups/`，校验 + 14 天保留） | 一次性班任务；睡眠错过醒来补跑 |
| `com.user.tastegraph.queue.plist` | `com.user.tastegraph.queue` | 工作台 HTTP 服务（编辑台/发布登记/源面板），绑定 `127.0.0.1:8766` | KeepAlive，崩溃/开机自动恢复 |

旧服务 `com.user.tastegraph.daemon`（daemon_scheduler 内存态调度）被
ingestion plist 取代；切换时先卸载它（见下）。`daemon_scheduler.py` 仍保留，
需要多任务 tape 循环时可继续用（现已 job_runs 持久化 + detached worker）。

## 前置

```bash
mkdir -p ~/Library/Logs/TasteGraph
# plist 内路径写死为部署目录（auto_deploy 的落点）:
# /Volumes/SanDisk2TB/自媒体作品/小红书起号/moodboard-hidden-ny-jjjjound
```

## 切换步骤（人工执行，一次性）

```bash
REPO="/Volumes/SanDisk2TB/自媒体作品/小红书起号/moodboard-hidden-ny-jjjjound"

# 1) 卸载旧 daemon（内存态调度，确认任务已并入新入口后再做）
launchctl bootout gui/$(id -u)/com.user.tastegraph.daemon 2>/dev/null \
  || launchctl unload ~/Library/LaunchAgents/com.user.tastegraph.daemon.plist 2>/dev/null

# 2) 安装新 plist
cp "$REPO/deploy/launchd/com.user.tastegraph.ingestion.plist" ~/Library/LaunchAgents/
cp "$REPO/deploy/launchd/com.user.tastegraph.backup.plist"    ~/Library/LaunchAgents/
cp "$REPO/deploy/launchd/com.user.tastegraph.queue.plist"     ~/Library/LaunchAgents/

# 3) 加载
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.user.tastegraph.ingestion.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.user.tastegraph.backup.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.user.tastegraph.queue.plist

# 4) 验证
launchctl print gui/$(id -u)/com.user.tastegraph.ingestion | head -20
launchctl print gui/$(id -u)/com.user.tastegraph.backup | head -20
launchctl print gui/$(id -u)/com.user.tastegraph.queue | head -20
tail -f ~/Library/Logs/TasteGraph/ingestion.log
```

卸载：

```bash
launchctl bootout gui/$(id -u)/com.user.tastegraph.ingestion
launchctl bootout gui/$(id -u)/com.user.tastegraph.backup
launchctl bootout gui/$(id -u)/com.user.tastegraph.queue
```

## Tailscale / 局域网访问工作台

默认只绑环回。要从手机/iPad（tailnet）访问编辑台，把 queue plist 的
`EnvironmentVariables` 改为：

```xml
<key>QUEUE_HOST</key><string>0.0.0.0</string>
<key>TASTEGRAPH_ALLOWED_ORIGINS</key>
<string>http://mini-的-tailscale-名:8766,http://100.x.x.x:8766</string>
```

然后 `bootout` + `bootstrap` 重新加载。CORS 白名单默认空（同源 only），
永不返回 `*`；没有内建认证，网络暴露面 = tailnet/局域网，**不要**绑公网 IP。

## 备份

每日备份不在 launchd 里：采集 03:00 班之后由调度配置
（`config/schedule.json` 的 `backup` 任务，04:00）或人工执行：

```bash
python3 scripts/backup_db.py     # SQLite 在线备份 → data/backups/，保留 14 天
```
