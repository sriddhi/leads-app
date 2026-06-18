# Diagram sources

The `.mmd` files here are the [Mermaid](https://mermaid.js.org/) **sources** for the diagrams in
[`../../DESIGN.md`](../../DESIGN.md) and [`../../ARCHITECTURE.md`](../../ARCHITECTURE.md). The docs
embed the same Mermaid inline (GitHub renders it natively), so these sources are the single source
of truth — edit them, and re-sync the doc blocks if needed.

PNG renders are **generated artifacts** (gitignored). Regenerate them locally with:

```bash
# from docs/diagrams/
npx -y puppeteer browsers install chrome-headless-shell   # first time only
for f in *.mmd; do npx -y @mermaid-js/mermaid-cli -i "$f" -o "${f%.mmd}.png" -b white -s 2; done
```

| File | Diagram |
|---|---|
| `01-deploy-docker.mmd` | Local Docker Compose topology |
| `02-deploy-aws.mmd` | AWS target deployment |
| `03-service-interactions.mmd` | Backend layering & service interactions |
| `04-database-er.mmd` | Database ER model |
| `05-state-machine.mmd` | Lead status state machine |
| `06-flow-intake.mmd` | Public intake sequence |
| `07-flow-assignment-concurrency.mmd` | Concurrent assignment (optimistic lock) |
| `08-assignment-logic.mmd` | Assignment decision flow |
| `09-notifications.mmd` | Notification dispatch |
| `10-audit-sse.mmd` | Append-only audit + live SSE |
