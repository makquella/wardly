# Design notes

Each note describes one subsystem: what it owns, the contract it keeps and how it is tested. Some notes are in Ukrainian, some in English. Code and tests are the source of truth; a note says which version introduced the behaviour.

Start with [Architecture](ARCHITECTURE.md), then the area you are changing. [Testing](TESTING.md) maps every area to its checks.

## Start here

| Note | What it covers |
|---|---|
| [Architecture](ARCHITECTURE.md) | Processes, data flow, the owning module of each part |
| [Quickstart](QUICKSTART.md) · [Reference commands](REFERENCE_COMMANDS.md) | Running the app, the backend and the tools |
| [Testing](TESTING.md) · [Dev runner](DEV_RUNNER.md) | Which checks a change needs, and the runner that picks them |
| [Roadmap](ROADMAP.md) | The long-term goal, stages and their exit criteria |

## Live advice

| Note | What it covers |
|---|---|
| [Advice scheduler](ADVICE_SCHEDULER.md) | Priorities, cooldowns, urgent versus coaching advice |
| [GSI snapshot](GSI_SNAPSHOT.md) | Consistent publication of each GSI update |
| [GSI role preparation](GSI_ROLE_PREPARATION.md) · [GSI timer preparation](GSI_TIMER_PREPARATION.md) | Role and map-timer metadata prepared outside the state lock |
| [Pure abilities](PURE_ABILITIES.md) | Ability normalization without side effects |
| [Match memory ownership](MATCH_MEMORY_OWNERSHIP.md) · [Live hint ownership](LIVE_HINT_OWNERSHIP.md) | Who may change per-match state and live hints |
| [Live tracker snapshot](LIVE_TRACKER_SNAPSHOT.md) · [Live message history](LIVE_MESSAGE_HISTORY.md) | Detached reads and incremental advice messages |
| [Live event loop](LIVE_EVENT_LOOP.md) | Keeping GSI and demo work off the ASGI loop |
| [Advice feedback](ADVICE_FEEDBACK.md) | «Useful / Not to the point / Repeated» marks and quieter advice |
| [Replay demo](REPLAY_DEMO.md) · [Demo overlay cache](DEMO_OVERLAY_CACHE.md) | Playing a recorded match through the real pipeline |

## History and reviews

| Note | What it covers |
|---|---|
| [Match recovery](MATCH_RECOVERY.md) | Finishing a match durably across crashes and restarts |
| [Job queue lifecycle](JOB_QUEUE_LIFECYCLE.md) | Background sync and analysis jobs, retries and shutdown |
| [Finding evidence](FINDING_EVIDENCE.md) · [Review basis](REVIEW_BASIS.md) | What each finding is measured from, and comparable progress |
| [AI counter evidence](AI_COUNTER_EVIDENCE.md) · [AI questions](AI_QUESTIONS.md) | Fact-checking the AI review; one run per question |
| [Knowledge base cache](KNOWLEDGE_BASE_CACHE.md) | Retrieval over the Markdown knowledge base |
| [Large history](LARGE_HISTORY.md) | Reading long histories quickly |
| [Player contracts](PLAYER_CONTRACTS.md) · [Domain contracts](DOMAIN_CONTRACTS.md) | Typed responses and their JS consumers |
| [History backup](HISTORY_BACKUP.md) · [Transfer atomicity](TRANSFER_ATOMICITY.md) | Backups, restore and moving history between computers |

## Desktop app

| Note | What it covers |
|---|---|
| [Desktop security](DESKTOP_SECURITY.md) | IPC sender checks, navigation guards, CSP |
| [Desktop boundaries](DESKTOP_BOUNDARIES.md) | How the renderer is split into owned modules |
| [Match navigation](MATCH_NAVIGATION.md) · [Match requests](MATCH_REQUESTS.md) | Back/forward history and request ownership in reviews |
| [Renderer texts](RENDERER_TEXTS.md) · [Update history](RENDERER_UPDATE_HISTORY.md) | UK/EN copy and «What's new» |
| [Secrets at rest](SECRETS_AT_REST.md) | Keys encrypted with the OS key store |
| [Operations health](OPERATIONS_HEALTH.md) · [Local I/O health](LOCAL_IO_HEALTH.md) | Visible failures instead of silent ones |

## Security, data and cloud

| Note | What it covers |
|---|---|
| [Local API security](LOCAL_API_SECURITY.md) | Tokens, Origin/Host checks and limits of the local API |
| [Data plan](DATA_PLAN.md) | What goes to the cloud, only with consent, and how it is deleted |

## Build and release

| Note | What it covers |
|---|---|
| [Windows packaging](PACKAGING_WINDOWS.md) | PyInstaller + NSIS, smoke test, signing status |
| [Windows CI scope](WINDOWS_CI_SCOPE.md) · [Release validation](RELEASE_VALIDATION.md) | When the Windows build runs; validating the release commit |
| [Type checking](TYPE_CHECKING.md) | The mypy gate that blocks new debt |
| [Python dependencies](PYTHON_DEPENDENCIES.md) · [Dependencies](DEPENDENCIES.md) · [Maintenance validation](MAINTENANCE_VALIDATION.md) | Locked dependencies and generated data |

Release notes for every version are in [release-notes/](release-notes/); diagrams in [diagrams/](diagrams/); subsystem notes for agents in [reference/implementation-notes.md](reference/implementation-notes.md).
