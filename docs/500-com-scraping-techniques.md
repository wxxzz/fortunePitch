---
name: 500-com-scraping-techniques
description: "How to scrape 500.com odds/results pages reliably (UA header, GBK, results + HT scores endpoints)"
metadata: 
  node_type: memory
  type: reference
  originSessionId: 765bfc86-317e-4aa8-875e-cf577bd804fd
  modified: 2026-08-31T03:22:10.914Z
---

500.com scraping essentials (used for football lottery analysis):

- **All 500.com curl requests MUST pass UA header** `-A "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"` or return 403.
- Pages are **GBK/GB2312 encoded**: decode with `raw.decode('gbk', errors='ignore')`, write parsed output to UTF-8 files and Read them (GBK console garbles Chinese).
- **Never inline python heredocs containing Chinese** in Bash tool calls (exit 127 on this box) - always Write a separate .py file first.
- **Final scores**: `https://trade.500.com/jczq/?playid=312&g=2&date=YYYY-MM-DD` - each match row `<tr>` has `data-fixtureid`, `data-matchnum` (周三001 style), `data-homesxname/awaysxname`; the final score is in `<a class="score">H:A</a>`.
- **Half-time scores**: `https://live.500.com/wanchang.php?e=YYYY-MM-DD` - each finished-match row's `<td align="center" class="red">H - A</td>` is the HT score (comes after away team's yellow-card span). Yellow card counts and rank brackets sit between team name and HT score - don't confuse them.
- **Odds data pages**: `https://odds.500.com/fenxi/shuju-XXXXXXX.shtml` (as of 2026-08-31, `live.500.com/shuju-*.shtml` returns 404 - always use the odds.500.com/fenxi path). Parse `<table>` -> `<tr>` -> `<td>` with regex + html unescape. Match dates are **Beijing time** - Wednesday-night European games appear as Thursday 08-20 on the page, so searching rows by '08-19' misses them; current-match rows show 'VS' as HT placeholder until data is populated. These pages also contain 平均欧指, win/draw/loss, handicap (赢盘率), 大小球 (大球率), H2H, league standings, and predicted lineups - rich enough for full pre-match analysis without separate pages.
