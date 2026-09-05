# Ripple resources integrated into Relay

Source: Singhacks-2026/ripple, checkout `e93bb8b14889c3e2325f28ada05071d5471d95b5`. Imported on 2026-09-05.

- README.md and resources.md are upstream challenge/reference snapshots, not claims that Relay implements every feature.
- ../../skills/xrpl-agentic-resources contains the upstream context pack, scripts and offline snapshots. No refresh or skill registration was executed during import. Snapshots are not live network facts. To refresh deliberately, run `bash skills/xrpl-agentic-resources/scripts/refresh.sh` from demo.
- ../../tools/xrpl-feedback contains the upstream feedback tooling, INACTIVE. No stop hook is registered and no feedback was submitted. Upstream setup directions are reference material, not an instruction to run their example feedback.

Before enabling feedback, obtain the developer's team name, real name and explicit authorization to send builder feedback to the hackathon server. Submit only actual observed experience. Keep identity configuration out of Git. Inspect the actual agent's supported hook configuration before registration.

The resource pack is self-contained: demo does not depend on a sibling ripple checkout. Upstream vendored SDK repos are downloaded only by an explicit refresh.
