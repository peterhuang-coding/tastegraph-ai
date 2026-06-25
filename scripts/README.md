# Moodboard Fetch Script

这个脚本是给你的 `moodboard` 工作流准备的：

- 输入一份当天的候选清单 `manifest`
- 自动创建按日期命名的文件夹
- 尝试下载最多 `15` 张图
- 同时生成一个同日期的 `TXT` 说明文件

## 用法

```bash
python3 "小红书起号/moodboard-hidden-ny-jjjjound/scripts/moodboard_fetch.py" \
  --manifest "小红书起号/moodboard-hidden-ny-jjjjound/manifests/2026-04-09.json" \
  --output-root "小红书起号/moodboard-hidden-ny-jjjjound" \
  --date 2026-04-09 \
  --limit 15
```

## 每天直接跑

如果你想要一个更短的入口，直接用这个：

```bash
zsh "小红书起号/moodboard-hidden-ny-jjjjound/scripts/run_daily_moodboard.sh"
```

它会：

- 优先找当天日期对应的 `manifest`
- 如果当天还没有，就默认回退到最新的一份 `manifest`
- 自动生成当天的日期文件夹
- 调用下载器去抓图并生成 `TXT`

如果你想强制要求“今天必须有自己的 manifest，不准回退”，可以这样跑：

```bash
zsh "小红书起号/moodboard-hidden-ny-jjjjound/scripts/run_daily_moodboard.sh" --strict-date
```

## 设计思路

- 优先使用 `direct_image`
- 如果没有直链，就去抓 `source_page` 页面的 `og:image`
- 文件名会按顺序保存成 `01_xxx.jpg`
- 即使部分图片下载失败，也会把成功的结果和失败原因写进 `TXT`

## 现实限制

如果当前网络环境访问不到图片站点，脚本也会失败。
但它至少把“落盘流程”标准化了：

- 你可以在别的网络环境运行
- 也可以把我整理好的链接喂进去批量下载
- 后面自动任务也可以改成调用这套脚本

## 更推荐的新方案：从别人 curated 的 moodboard 里抓

之前的泛图片源质量不稳定，容易抓到网页缩略图、placeholder，甚至在网络失败时错误地退回本地视频截图。
新的入口改成从公开 Are.na channel 里抓别人已经整理过的 moodboard / editorial reference：

```bash
zsh "小红书起号/moodboard-hidden-ny-jjjjound/scripts/run_arena_moodboard.sh" \
  --date 2026-04-12 \
  --limit 15 \
  --shuffle
```

默认源包括：

- `brian-curran/jjjjound-full-archive`
- `lily-clempson-tfz8voo8tzo/editorial-fashion`
- `jeremy-turner/photography-editorial-lifestyle-fashion`

质量门槛：

- 不允许本地视频截图
- 不生成 placeholder
- 小于 `180KB` 的图直接拒绝
- 小于 `900x900` 的图直接拒绝
- 长宽比过于极端的图直接拒绝

如果没有抓满 15 张，它会退出失败，而不是拿垃圾图凑数。

## 品味记忆

现在这个爬虫有一个初始品味记忆：

```bash
小红书起号/moodboard-hidden-ny-jjjjound/taste_memory.json
```

它会用里面的偏好词、禁忌词和频道偏好给候选图排序。

你可以用反馈脚本修正它：

```bash
python3 "小红书起号/moodboard-hidden-ny-jjjjound/scripts/taste_feedback.py" \
  --like "brutalist, shadow, menswear" \
  --avoid "cute, colorful, influencer" \
  --note "更冷一点，少一点网红咖啡馆感"
```

也可以针对某张图反馈：

```bash
python3 "小红书起号/moodboard-hidden-ny-jjjjound/scripts/taste_feedback.py" \
  --image "2026-04-17/03_example.jpg" \
  --like "archive, object, concrete" \
  --note "这张方向对，像私藏参考册"
```

后面我们可以继续把这个反馈做得更顺手，比如用 `liked/` 和 `rejected/` 文件夹自动学习。

## 新方向：只找链接，不下载图片

现在更推荐用 `link pack` 作为每日产出：

- `lookbook / image references`：时尚 lookbook、runway、品牌图集
- `videos / moving image`：fashion film、实验短片、有品味的视频
- `articles / deep reading`：有深度的文章、访谈、趋势和文化判断

种子源在这里：

```bash
小红书起号/moodboard-hidden-ny-jjjjound/link_sources.json
```

每日链接包放这里：

```bash
小红书起号/moodboard-hidden-ny-jjjjound/link_packs/
```

如果你要反馈某个链接，可以用：

```bash
python3 "小红书起号/moodboard-hidden-ny-jjjjound/scripts/link_feedback.py" \
  --link "https://example.com" \
  --type lookbook \
  --like "quiet uniform, archive, menswear" \
  --note "这个方向对"
```

或者：

```bash
python3 "小红书起号/moodboard-hidden-ny-jjjjound/scripts/link_feedback.py" \
  --link "https://example.com" \
  --type article \
  --avoid "generic, influencer, shopping guide" \
  --note "太普通，不要这种"
```

## Link Pack Studio（更直白：点好坏 + 粘贴截图）

你说的“我来点开链接、自己截图、然后粘贴进去”的流程，用这个本地网页就能完成：

- 读取：`link_packs/YYYY-MM-DD.txt`
- 你在网页里对每条链接点 `LIKE / REJECT / NEUTRAL`，写 `tags/note`
- 你把截图直接粘贴（`Ctrl+V`）或上传到对应卡片
- 自动落盘到当天日期文件夹：`YYYY-MM-DD/screenshots/` + `YYYY-MM-DD/link_pack_review.json`
- 可一键导出 ZIP（截图 + review + link_pack 文本）

启动：

```bash
python3 "小红书起号/moodboard-hidden-ny-jjjjound/scripts/link_pack_studio.py"
```

然后打开：

`http://127.0.0.1:8787`
