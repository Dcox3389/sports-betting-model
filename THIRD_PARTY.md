# Third-party notices

This project borrows from the MIT-licensed work below. MIT permits use,
modification, and commercial distribution provided the copyright notice and
permission notice travel with it — which is what this file is for.

---

## Agent-Reach

- Source: https://github.com/Panniantong/Agent-Reach
- License: MIT
- `Copyright (c) 2025 Agent Eyes`

**Used in `news.py`.** Two techniques are adapted from its channel design:

1. **Jina Reader as a universal page reader** (`https://r.jina.ai/<URL>`) —
   returns any public page as markdown with no API key and no per-service
   quota. This matters twice over here: it supplies ESPN's injury tables, and
   it reads ESPN's *public pages* rather than its API, which sidesteps the API
   throttling that blocked the MLB/NHL portion of `edge_test.py`.
2. **RSS/Atom as a zero-setup news channel**, following the pattern in
   `agent_reach/channels/rss.py` — declare the source, verify the backend is
   importable, then read.

Agent-Reach itself is not vendored or imported; `news.py` is an independent
implementation of these two approaches against sports sources. Its
`doctor` command was also used to determine which channels work without
credentials (4 of 15: RSS, arbitrary web via Jina, V2EX, Bilibili search —
Twitter and Reddit both require tokens).

---

## ruflo

- Source: https://github.com/ruvnet/ruflo
- License: MIT
- `Copyright (c) 2024-2026 ruvnet`

**Not currently used.** Forked and evaluated. It is a TypeScript/Rust
multi-agent orchestration harness — a well-built tool for coordinating agent
swarms, but architecturally unrelated to a Python statistical pipeline. There
is no component of it that this project needs today. Listed here so the
evaluation is on the record rather than repeated later.

If this project ever grows into multi-source concurrent collection where
orchestration is the bottleneck, it is worth revisiting. Right now the
bottleneck is data access and market efficiency, neither of which an agent
harness addresses.
