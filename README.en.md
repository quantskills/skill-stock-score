# skill-stock-score

`skill-stock-score` is a fundamental-analysis skill for Chinese A-shares. It scores stocks on five dimensions: financial condition, news, industry outlook, debt and solvency, and shareholder transactions/capital actions. It also supports TOP10 ranking within an industry or sector.

## Use cases

- Enter a six-digit A-share code, or a code with an exchange suffix, for an individual score report.
- Enter an industry or sector name for a ranked shortlist.
- Reports should include the data date, sources, missing fields, assumptions, and risk warnings.

## Requirements

- A working `skill-pandadata-api` data capability is required.
- Runtime entry points for Codex, Claude Code, Cursor, Hermes, and OpenClaw are documented in `SKILL.md` and `agents/`.

## Scope and disclaimer

This skill covers Shanghai, Shenzhen, and Beijing A-shares only. Scores are research aids based on available public data. They are not investment advice, trading instructions, a promise of returns, or a securities service. Users must independently verify data and remain responsible for decisions.

`QuantSkills` is only the maintainer label for this repository and does not imply official endorsement by an exchange, data provider, broker, or platform.

## License

This project is licensed under GPL-3.0-only. See [LICENSE](LICENSE).
