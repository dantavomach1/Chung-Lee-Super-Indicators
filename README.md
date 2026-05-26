# Chung-Lee-Super-Indicators

Private repository for TradingView Pine Script indicator development.

## Purpose

This repository is the source-of-truth for developing, organizing, reviewing, and tracking Pine Script indicators. GitHub is used for version control, notes, changelogs, and Codex-managed edits, while TradingView remains the runtime and publishing environment.

## Repository Layout

- `indicators/` holds active indicator development.
- `indicators/_template/` provides the standard folder structure for future imports.
- `libraries/` is reserved for reusable Pine helper or library-style code when multiple indicators clearly need the same shared logic.
- `published/` stores final paste-ready files intended for manual copy/paste into TradingView.
- `archive/` stores retired or older versions that should be kept for reference.
- `docs/` contains workflow rules, naming conventions, and operating instructions for this repo.

## Indicator File Rules

Each indicator should preserve:

- `original.pine` as the untouched imported reference copy.
- `source.pine` as the editable working copy.
- `changelog.md` for meaningful edit history.
- `notes.md` for plain-English behavior notes.

## Workflow Model

- Develop and review indicator source here in GitHub.
- Keep TradingView as the execution and publishing target.
- Create publish-ready copies only when needed.
- Place final paste-ready Pine files in `published/`.

## Rights

No open-source license is currently granted. All rights are reserved unless a license is explicitly added later.
