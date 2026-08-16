# Source Healthcheck — 2026-08-15

**Total**: 30  |  **Healthy (2xx)**: 22  |  **Broken**: 7  |  **Error**: 1

## By result

- `2xx_pass`: 22
- `4xx_blocked`: 4
- `4xx_not_found`: 3
- `fetch_error:EndOfStream`: 1

## By category × result

- **lookbook_images**: 4xx_not_found=2, 2xx_pass=9, 4xx_blocked=2
- **videos**: 2xx_pass=5, 4xx_not_found=1
- **articles**: 2xx_pass=8, 4xx_blocked=2, fetch_error:EndOfStream=1

## Per-URL

| Status | Bytes | Result | Cat | Name |
|---|---|---|---|---|
| 404 | 792381 | `4xx_not_found` | lookbook_images | Vogue Runway - Menswear |
| 404 | 745583 | `4xx_not_found` | lookbook_images | Vogue Runway - Lemaire |
| 200 | 777708 | `2xx_pass` | lookbook_images | Vogue Runway - 032c |
| 200 | 373945 | `2xx_pass` | lookbook_images | 032c Magazine |
| 202 | 2239 | `4xx_blocked` | lookbook_images | Hypebeast Fashion |
| 200 | 511490 | `2xx_pass` | lookbook_images | Highsnobiety Style |
| 200 | 27906 | `2xx_pass` | lookbook_images | BranD Magazine |
| 200 | 114 | `2xx_pass` | lookbook_images | Das Programm — Dieter Rams Archive |
| 403 | 6180 | `4xx_blocked` | lookbook_images | Toshio Saeki — WikiArt Archive |
| 200 | 446672 | `2xx_pass` | lookbook_images | Toshio Saeki Estate |
| 200 | 198198 | `2xx_pass` | lookbook_images | Savee — Curated Design |
| 200 | 15987 | `2xx_pass` | lookbook_images | Same Energy — Visual Search |
| 200 | 256411 | `2xx_pass` | lookbook_images | Visuelle — Branding & Editorial |
| 200 | 532670 | `2xx_pass` | videos | SHOWstudio Fashion Film |
| 404 | 26438 | `4xx_not_found` | videos | SHOWstudio Video |
| 200 | 12310 | `2xx_pass` | videos | NOWNESS Fashion |
| 200 | 151839 | `2xx_pass` | videos | Dazed Video |
| 200 | 97917 | `2xx_pass` | videos | Vimeo Staff Picks |
| 200 | 101372 | `2xx_pass` | videos | Rams — Gary Hustwit |
| 200 | 936393 | `2xx_pass` | articles | SSENSE Editorial |
| 200 | 373945 | `2xx_pass` | articles | 032c Magazine |
| 200 | 178365 | `2xx_pass` | articles | Dazed Fashion |
| 200 | 74363 | `2xx_pass` | articles | i-D Fashion |
| 200 | 672999 | `2xx_pass` | articles | The Guardian Art & Design |
| 403 | 520 | `4xx_blocked` | articles | Vogue Business |
| 200 | 27906 | `2xx_pass` | articles | BranD Magazine |
| 200 | 59940 | `2xx_pass` | articles | Vitsoe — Dieter Rams Philosophy |
| 200 | 119666 | `2xx_pass` | articles | Toshio Saeki — Selected Works & Essays |
| -1 | ? | `fetch_error:EndOfStream` | articles | STEEP — Cultural Intelligence |
| 429 | 33794 | `4xx_blocked` | articles | SiteInspire — Editorial Web Design |

## Anti-crawl / blocked URLs (need playwright or replacement)

- **Hypebeast Fashion** (202): https://hypebeast.com/fashion
- **Toshio Saeki — WikiArt Archive** (403): https://www.wikiart.org/en/toshio-saeki
- **Vogue Business** (403): https://www.voguebusiness.com/
- **SiteInspire — Editorial Web Design** (429): https://www.siteinspire.com

## Dead links (replace)

- **Vogue Runway - Menswear** (404): https://www.vogue.com/fashion-shows/menswear
- **Vogue Runway - Lemaire** (404): https://www.vogue.com/fashion-shows/designer/lemaire
- **SHOWstudio Video** (404): https://www.showstudio.com/videos