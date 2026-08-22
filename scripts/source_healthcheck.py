"""Weekly full-source healthcheck — 8/15 一次性探测的周期化版本.

对 link_sources.json 全部条目做一次 GET 探测，分类：
  - 2xx_pass        2xx 且 body > 5000 bytes
  - suspicious_small 2xx 但 body 太小（疑似 SPA 空壳）
  - 4xx_not_found   404/410（死链，应 patch 或移除）
  - 4xx_blocked     403/429/202+空 body（反爬，需 playwright 或换源）
  - fetch_error:*   网络/协议异常

产出 data/source-healthcheck-YYYY-MM-DD.{json,md}，退出码恒为 0（结果以报告为准）。
"""
import asyncio
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from taste_graph_ai.infrastructure.crawlers.stealth import StealthSession, jittered_delay  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SOURCES_PATH = ROOT / "link_sources.json"
DATA_DIR = ROOT / "data"
MIN_BODY = 5000


def flatten_sources(data: dict) -> list[tuple[str, str, str]]:
    """(category, name, url) 三元组列表。"""
    out = []
    for cat, entries in data.items():
        if isinstance(entries, list):
            for e in entries:
                if isinstance(e, dict) and e.get("url"):
                    out.append((cat, e.get("name", ""), e["url"]))
    return out


def classify(status: int, body_len: int, err: str | None = None) -> str:
    if err:
        return f"fetch_error:{err}"
    if status == 404 or status == 410:
        return "4xx_not_found"
    if status in (403, 429) or (status == 202 and body_len < MIN_BODY):
        return "4xx_blocked"
    if 200 <= status < 300:
        return "2xx_pass" if body_len >= MIN_BODY else "suspicious_small"
    return f"other_{status}"


async def main() -> None:
    data = json.loads(SOURCES_PATH.read_text(encoding="utf-8"))
    sources = flatten_sources(data)
    sess = StealthSession()
    results = []
    for cat, name, url in sources:
        domain = url.split("//", 1)[1].split("/", 1)[0]
        client = sess.get_client(domain, referer_url="https://www.google.com/")
        try:
            r = await client.get(url, timeout=20.0, follow_redirects=True)
            results.append({
                "cat": cat, "name": name, "url": url,
                "status": r.status_code, "bytes": len(r.content),
                "result": classify(r.status_code, len(r.content)),
            })
        except Exception as e:  # noqa: BLE001
            results.append({
                "cat": cat, "name": name, "url": url,
                "status": -1, "bytes": 0,
                "result": classify(0, 0, type(e).__name__),
            })
        await asyncio.sleep(jittered_delay(0.6, 0.4))
    await sess.close()

    today = date.today().isoformat()
    by_result: dict[str, int] = {}
    by_category: dict[str, dict[str, int]] = {}
    for r in results:
        by_result[r["result"]] = by_result.get(r["result"], 0) + 1
        cat_counts = by_category.setdefault(r["cat"], {})
        cat_counts[r["result"]] = cat_counts.get(r["result"], 0) + 1

    summary = {
        "run_at": today,
        "total": len(results),
        "by_result": by_result,
        "by_category": by_category,
    }
    (DATA_DIR / f"source-healthcheck-{today}.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    healthy = by_result.get("2xx_pass", 0)
    broken = len(results) - healthy
    lines = [
        f"# Source Healthcheck — {today}",
        "",
        f"**Total**: {len(results)}  |  **Healthy (2xx)**: {healthy}  |  **Broken/Error**: {broken}",
        "",
        "## By result",
        "",
        *(f"- `{k}`: {v}" for k, v in sorted(by_result.items())),
        "",
        "## Per-URL",
        "",
        "| Status | Bytes | Result | Cat | Name |",
        "|---|---|---|---|---|",
        *(f"| {r['status']} | {r['bytes']} | `{r['result']}` | {r['cat']} | {r['name']} |"
          for r in results),
    ]
    (DATA_DIR / f"source-healthcheck-{today}.md").write_text(
        "\n".join(lines), encoding="utf-8")
    print(f"healthcheck done: {len(results)} sources, healthy={healthy}, broken={broken}")
    print(f"report: {DATA_DIR / f'source-healthcheck-{today}.md'}")


if __name__ == "__main__":
    asyncio.run(main())
