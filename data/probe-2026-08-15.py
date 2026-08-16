"""Quick stealth probe — fetch Vogue/Hypebeast with taste_graph_ai stealth primitives.

Outputs a per-URL status code + bytes + first 200 chars of body to
$CLAUDE_JOB_DIR/tmp/probe-results.json. No persistence beyond that.
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path("/Volumes/SanDisk2TB/自媒体作品/小红书起号/moodboard-tg-crawl-opt").resolve()))
from taste_graph_ai.infrastructure.crawlers.stealth import StealthSession, jittered_delay

PROBES = [
    ("vogue.com.menswear", "https://www.vogue.com/fashion-shows/menswear", "https://www.google.com/"),
    ("vogue.lemaire", "https://www.vogue.com/fashion-shows/designer/lemaire", "https://duckduckgo.com/"),
    ("vogue.032c", "https://www.vogue.com/fashion-shows/designer/032c", ""),
    ("hypebeast.fashion", "https://hypebeast.com/fashion", "https://www.bing.com/"),
    ("voguebusiness", "https://www.voguebusiness.com/", "https://www.google.com/"),
]

async def probe():
    sess = StealthSession()
    results = []
    for label, url, ref in PROBES:
        domain = url.split("//", 1)[1].split("/", 1)[0]
        client = sess.get_client(domain, referer_url=ref)
        try:
            r = await client.get(url)
            body_preview = r.text[:200] if r.status_code == 200 else ""
            results.append({
                "label": label,
                "url": url,
                "status": r.status_code,
                "bytes": len(r.content),
                "preview": body_preview.replace("\n", " ")[:200],
                "final_url": str(r.url),
            })
        except Exception as e:
            results.append({"label": label, "url": url, "status": -1, "error": f"{type(e).__name__}: {e}"})
        await asyncio.sleep(jittered_delay(1.0, 0.3))
    await sess.close()
    out_path = Path("/Users/peter_mini/.claude/jobs/c51be99b/tmp/probe-results.json")
    out_path.write_text(json.dumps(results, indent=2, ensure_ascii=False))
    print(json.dumps(results, indent=2, ensure_ascii=False))

asyncio.run(probe())
