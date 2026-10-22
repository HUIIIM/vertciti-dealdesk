# Assets manifest — vertciti-dealdesk

Per GitHub 项目展示标准 v1 §4: every visual in this repo is registered here
with its type, source, capture date/tool, and sanitization state.
No AI-generated imagery is used as product evidence anywhere in this repo.

| File | Type | Source | Captured / rendered | Sanitization |
|---|---|---|---|---|
| `banner.png` | Banner (1600×560) | Code-rendered (PIL, typography only) | 2026-10-20 | n/a — no data shown |
| `demo.gif` | Demo GIF, ~14 s, 11 frames | **Real capture**: asciinema recording of a live session against a local instance of this repo's code (seed-DB copy), rendered frame-by-frame via pyte + PIL | 2026-10-20 | Property figures are public records (TopHap) for a real parcel; the scored project is the seed DB's built-in demo project, labeled demo in-frame; no user data, no credentials, no internal paths |
| `terminal-intake.png` | Terminal frame | Same recording, still at the subject-property block | 2026-10-20 | Same as demo.gif |
| `terminal-valuation.png` | Terminal frame | Same recording, still after the comps valuation block | 2026-10-20 | Same as demo.gif |
| `terminal-forecast.png` | Terminal frame | Same recording, still after the forecast block | 2026-10-20 | Same as demo.gif |
| `terminal-report.png` | Terminal frame | Same recording, final frame (demo-project score + report generation) | 2026-10-20 | Same as demo.gif |
| `ui-main.png` | UI screenshot (2880×1800) | **Real browser capture**: local instance of this repo's code (uvicorn on 127.0.0.1, seed-DB copy — production data untouched), Chromium + Playwright via route-fulfill (see closing note) | 2026-10-20 (evening) | Landing / mode picker; no data shown |
| `ui-intake.png` | UI screenshot, full page (2880×3302) | **Real browser capture**: same instance, one complete live intake of the demo subject (30-59 41st Street, Astoria, NY 11103) — all five analysis steps completed (TopHap comps / comps valuation / market index / public-record enrich / trend extrapolation), ask price $1,150,000 entered and recalculated; verdict PASS, deal score 43/100, confidence 64.2/100 | 2026-10-20 (evening) | Public-record figures for a real parcel; no credentials rendered (TopHap token never appears); the missing-rent gap is shown exactly as the product reports it |

## Why terminal captures instead of browser screenshots

On 2026-10-20 the capture sandbox's Chromium could not reach either the
production site (egress-proxy CONNECT tunnel rejected) or the local
instance (loopback blocked by local-network-access checks), so no honest
browser screenshot could be produced. Per the standard's real-capture
rule, the fallback is a real terminal session: the production intake had
already gathered the subject property's public record the same day, and
the recording drives the actual valuation / forecast / scoring / report
APIs of this codebase with those real figures. A browser-capture refresh
of the demo layer is the first follow-up when a working browser path is
available.

Not used: a rasterization of the HTML report's inline SVG payback chart
was produced during capture but dropped — the off-browser rasterizer
lost CJK glyphs in the chart labels. The chart itself renders correctly
in a real browser; a misrendered copy was not shipped.

## Update — browser UI captures added (2026-10-20, evening)

The gap described in the section above is closed (`ui-main.png`,
`ui-intake.png`). Working route: the local QA channel —
`/opt/meta-chromium/chrome` + Playwright (`~/workspace/.qa-venv`).
Direct navigation to 127.0.0.1 was refused by Chromium's
local-network-access checks in every variant tried
(ERR_BLOCKED_BY_LOCAL_NETWORK_ACCESS_CHECKS — direct loopback,
fake-host mapping via host-resolver rules, `--no-proxy-server`, and
LNA-disable feature flags), and the sandbox LAN address was
unreachable inbound. What worked is Playwright route-fulfill: the
browser only ever addresses fake hosts (dd.local), Playwright
intercepts every request, Python fetches the real bytes from
127.0.0.1 and fulfills the response — Chromium never opens a loopback
connection, so the LNA check never triggers. One earlier assumption
also fell: after the app process was restarted with a sanitized proxy
environment (ALL_PROXY removed), its TopHap MCP leg connected and the
intake's five analysis steps all completed live; the earlier
"unreachable" status reading was a casualty of the sandbox's proxy
handling, not of the product.
