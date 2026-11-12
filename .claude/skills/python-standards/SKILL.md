---
name: python-standards
description: "Apply Python conventions for typed, testable service code: pydantic-settings config, typed boundaries, no import-time side effects, test seams, UTF-8 on Windows. Use when writing, reviewing or scaffolding Python here."
---

# Python standards

Target Python 3.11+ (the repo venv). Snippets: [config and test seams](references/config-and-seams.md).

## Rules

Tooling
1. `pyproject.toml` holds dependencies and tool config. Code in `src/<package>/`, tests in `tests/`. No `sys.path` edits.
2. `ruff check` and `ruff format` are the only lint and format tools.
3. CLIs have a `main()` returning an int exit code, declared in `[project.scripts]`.

Types and data
4. Full annotations, including `-> None`. Builtin generics and `X | None`.
5. Config is a `pydantic-settings` `BaseSettings` class with validated ranges and enums. Secrets are `SecretStr`. No `os.environ[...]` outside it.
6. Untrusted input (API payloads, LLM structured output, files) is parsed once at the boundary into Pydantic models. Past that, code handles typed objects.
7. `get_settings()` returns a fresh object, not a cached singleton, so tests can vary it.
8. Closed value sets are `StrEnum` or `Literal`, not scattered strings.

Structure
9. No import-time side effects: importing a module must not read `.env`, create clients, touch the network, or create directories. Build things in factories or `main()`.
10. No module-level mutable state. Pass dependencies in; swap providers through a factory function (the test seam).
11. One base exception per package, subclasses per failure kind. Re-raise with `from`. Never swallow: handle, wrap, or log and re-raise.
12. `pathlib.Path` for paths. Open text files with `encoding="utf-8"` explicitly (Windows defaults differ). Do not pass `shell=True`.
13. Resources use `with`. HTTP calls always set a timeout.

Secrets
14. The key lives in the root `.env` only. Never print, log, echo or commit it; never put it in tests, fixtures or result files.

Testing
15. `pytest`; assert behavior, not internals. Tests run offline with the key unset: fakes at the client boundary, no network, no sleeps (inject the clock or patch backoff).
16. Use `tmp_path` for files, `monkeypatch` for env. Test fault paths as well as happy paths.

## Checklist

- [ ] `ruff check`, `ruff format --check`, `pytest` pass with `NVIDIA_API_KEY` unset.
- [ ] No import-time side effects; settings and clients built on demand.
- [ ] Boundaries validated; no secrets in code, logs or tests.
- [ ] Every file read or write names its encoding.
- [ ] No caches, logs, venvs or result files left in the tree.
