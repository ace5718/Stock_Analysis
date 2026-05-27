"""Publish vertical-slice GitHub issues per development plan."""
import subprocess

SLICES = [
    (
        "setup-matt-pocock-skills + CONTEXT + ADR 0001-0004",
        "Scaffold agent skills, CONTEXT.md, ADRs 0001-0004.",
        ["docs/agents/ and AGENTS.md exist", "CONTEXT.md and four ADRs exist"],
    ),
    (
        "Phase0 FastAPI skeleton and SQLite migration",
        "Health endpoint, SQLite schema, requirements, .env.example.",
        ["GET /health ok", "uvicorn starts", "DB tables created"],
    ),
    (
        "Slice 1.1 Watchlist CRUD",
        "Watchlist API and UI, max 5 symbols, persisted.",
        ["CRUD API works", "Survives restart"],
    ),
    (
        "Slice 1.2 Fugle realtime quotes WebSocket",
        "Quote stream to /ws/quotes with mock fallback.",
        ["Live quote updates", "Five symbol cap"],
    ),
    (
        "Slice 1.3 K-line Lightweight Charts",
        "Candles API and chart on dashboard.",
        ["Symbol switch updates chart"],
    ),
    (
        "Slice 2.1 Technical indicators pipeline",
        "MA, RSI, MACD, volume ratio locally.",
        ["Indicator bar and MA overlays"],
    ),
    (
        "Slice 2.2 Condition engine and trigger settings",
        "Trigger evaluation and settings UI.",
        ["Signals shown when conditions fire"],
    ),
    (
        "Slice 3.1 AI abstraction + GPT-4o",
        "AIEngine + OpenAI on trigger or manual.",
        ["Analysis panel populated"],
    ),
    (
        "Slice 3.2 Analysis cache and multi-engine",
        "Cache, Claude, Gemini, engine selector.",
        ["Cache prevents duplicate calls"],
    ),
    (
        "Slice 4.1 Manual simulated trading",
        "Manual buy/sell with fees and portfolio.",
        ["Trades update cash and positions"],
    ),
    (
        "Slice 4.2 Order mode and position sizing",
        "notify_confirm, full_auto, percent 20% default.",
        ["Modes and sizing configurable"],
    ),
    (
        "Slice 4.3 Risk stop-loss and daily halt",
        "Stop-loss and daily loss protection.",
        ["pytest for risk rules"],
    ),
    (
        "Slice 5.1 Gmail SMTP notifications",
        "SMTP app password emails on signals.",
        ["Email sends when configured"],
    ),
    (
        "Slice 5.2 Performance page",
        "Stats and trade history page.",
        ["Performance metrics display"],
    ),
    (
        "Slice 5.3 Backtest engine rules A + AI opt-in",
        "Historical backtest with rule mapping and optional AI quota.",
        ["Backtest API returns metrics"],
    ),
]


def create(title: str, what: str, criteria: list[str], blocked: str) -> int:
    crit = "\n".join(f"- [ ] {c}" for c in criteria)
    body = f"""## What to build

{what}

## Acceptance criteria

{crit}

## Blocked by

{blocked}
"""
    r = subprocess.run(
        ["gh", "issue", "create", "--title", title, "--body", body, "--label", "ready-for-agent"],
        capture_output=True,
        text=True,
        check=True,
    )
    url = r.stdout.strip()
    num = int(url.rstrip("/").split("/")[-1])
    print(url)
    return num


def main():
    nums: list[int] = []
    for title, what, criteria in SLICES:
        blocked = "None - can start immediately" if not nums else f"#{nums[-1]}"
        n = create(title, what, criteria, blocked)
        nums.append(n)


if __name__ == "__main__":
    main()
