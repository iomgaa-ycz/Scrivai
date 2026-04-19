# Contributing to Scrivai

Thank you for your interest in contributing to Scrivai. This guide covers everything you need to get started.

## Development Setup

```bash
git clone https://github.com/iomgaa-ycz/Scrivai
cd Scrivai
conda create -n scrivai python=3.11 -y
conda activate scrivai
pip install -e ".[dev,docs]"
cp .env.example .env
# Edit .env with your API credentials
```

## Code Standards

See [CLAUDE.md](CLAUDE.md) for the full specification. Key points:

- **Python 3.11+** — all function signatures must have complete type annotations
- **Class names** — PascalCase (e.g., `BasePES`, `WorkspaceManager`)
- **Variable names** — descriptive; prefix private members with `_`
- **Import order** — stdlib → third-party → project internals, with a blank line between each group
- **Logging** — use the project logger; never use `print()` for debugging

## Documentation Standards

### Docstrings

Docstrings are written in **English**, following **Google style**. Coverage is tiered:

| Tier | Symbols | Required sections |
|------|---------|-------------------|
| **Tier 1** (core public API) | `BasePES`, `ExtractorPES`, `AuditorPES`, `GeneratorPES`, `ModelConfig`, `WorkspaceSpec`, `load_pes_config`, `build_workspace_manager` | Summary, `Args`, `Returns`, `Raises`, `Example` |
| **Tier 2** (common API) | `PESRun`, `PESConfig`, `PhaseResult`, `HookManager`, `TrajectoryStore`, `run_evolution`, `promote`, Knowledge libraries | Summary, `Args`, `Returns` |
| **Tier 3** (everything else) | All other public symbols | One-line summary |

**Rules:**

- Do not reference internal file paths (e.g., `dev-docs/design.md`) in any docstring or `Field(description=...)` string.
- Tier 1 `Example` blocks must be runnable without access to private infrastructure.
- All `Field(description=...)` strings must be written in English.

### File Organization

| Content | Location |
|---------|----------|
| User documentation (English) | `docs/` |
| User documentation (Chinese) | `docs/zh/` |
| Internal dev docs | `dev-docs/` |
| API reference pages | `docs/api/` (auto-generated from docstrings) |

> **Note:** Do not edit `docs/api/*.md` directly — edit the docstrings in source code instead.

## Translation Sync

- When English docs under `docs/` change, open an issue tagged `docs:zh-sync`.
- `docs/zh/` must mirror the structure of `docs/`.
- `docs/zh/api/` does not exist — Chinese users read the English API reference.

## Previewing Docs

```bash
mkdocs serve    # http://127.0.0.1:8000
```

## Testing

Always run tests inside the project's conda environment to avoid picking up the base environment's pytest:

```bash
# Unit tests
conda run -n scrivai pytest tests/unit/ -v

# Contract tests
conda run -n scrivai pytest tests/ -k "contract" -v

# Integration tests
conda run -n scrivai pytest tests/integration/ -v
```

## Pull Requests

- Follow **Conventional Commits**: `feat:`, `fix:`, `docs:`, `refactor:`, `test:`
- One logical change per commit — do not bundle unrelated changes
- Run `ruff` before committing:

```bash
ruff check . --fix
ruff format .
```

## License

By contributing, you agree that your contributions will be licensed under the **Apache 2.0 License**.
