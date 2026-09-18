# docs/assets/

Media referenced by the root [`README.md`](../../README.md). Nothing in this
folder is code — it exists so the three placeholders in the README have a
fixed, documented target to drop files into. None of these can be generated
from source; each needs a short manual capture against the live deployment
(or `docker-compose up` locally).

## Files this folder should eventually hold

| File | Used in | Captures |
| ---- | ------- | -------- |
| `airp-demo.gif` | README hero section | Full flow: landing page → type `"TCS vs Infosys"` → live agent progress board → debate viewer → Investment Memo + PDF download |
| `video-thumb.png` + a hosted video link | README "Live demo" section | Same flow as the GIF, narrated, ~3 minutes |
| `langsmith-trace.png` | README "Observability & evaluation" section | A LangSmith trace for one full analysis run — expand the trace tree so agent nodes, token counts, and per-node latency are visible |

## How to capture the GIF

1. Run the app against the live deployment (or `docker-compose up` for a
   clean local run so timings aren't affected by cold-start).
2. Record at **1280×800 or smaller** — GitHub renders large GIFs poorly and
   they bloat the repo. [ScreenToGif](https://www.screentogif.com/) (Windows)
   or [Kap](https://getkap.co/) (macOS) both export directly to GIF.
3. Capture the flow listed in the table above, start to finish. Trim dead
   time during the ~30–80s agent run — a few seconds of the live progress
   board updating is enough to prove it streams; the full wait isn't needed.
4. Keep the final file **under 10 MB** (GitHub renders larger files but they
   load slowly in the README). Reduce frame rate to 10–12 fps or trim length
   if needed.
5. Save as `docs/assets/airp-demo.gif`, then uncomment the corresponding
   `![AIRP demo](...)` line in `README.md`.

## How to capture the LangSmith screenshot

1. Open the [LangSmith](https://smith.langchain.com/) project dashboard for
   AIRP.
2. Run one analysis and open its trace.
3. Expand the trace tree so the Planner, all 4 parallel research agents, the
   debate round, Risk Officer, Valuation Agent, and Portfolio Manager nodes
   are all visible in one screenshot, with the latency/token columns showing.
4. Save as `docs/assets/langsmith-trace.png`, then uncomment the
   `![LangSmith trace](...)` line in `README.md`.

## How to record the walkthrough video

1. Same flow as the GIF, narrated — explain what each agent is doing as the
   live progress board updates, pause on the debate viewer to show the
   Contrarian agent's counter-arguments, then walk through the generated
   Investment Memo and PDF.
2. Upload to YouTube (unlisted is fine) or Loom.
3. Export a thumbnail frame as `docs/assets/video-thumb.png`.
4. Replace `YOUR_VIDEO_ID` in `README.md`'s video embed with the real link
   and uncomment the line.

## Why this is a separate, tracked step

`docs/week-28/T-076-readme.md` documents this as a deliberate scope
boundary: T-076 ships a README that is complete and renders correctly on
GitHub with every placeholder wired to a real, documented target — the
capture itself is a manual, human action (screen recording / dashboard
screenshot) that no code change can produce.