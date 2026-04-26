# Transformation Warning Log

Install-time content transformation (Stage 5b) may encounter patterns that look standard-phrase-adjacent but don't match any rule in the Pattern Mapping table. These surface as `TRANSFORMATION_WARNING` entries.

## Log location

- **Path:** `.sdlc-transformation-warnings.log` (project root, gitignored)
- **Format:** JSONL, append-only (same shape as transaction log but purpose-scoped)
- **Also emitted:** As `warning` events in `.sdlc-transaction-log` with `category: "transformation"` — duplication is intentional so users can find these in both places.

## Entry schema

```json
{"ts": "2026-04-21T18:33:12Z", "run_id": "init-abc123", "file": ".claude/skills/sdlc-plan/SKILL.md", "line": 178, "phrase": "consult [sdlc-root]/playbooks/", "reason": "pattern resembles agent-context-map lookup but path doesn't match any transformation rule", "action": "applied upstream content verbatim — no transformation"}
```

## Review workflow

After each init/migrate run, if `.sdlc-transformation-warnings.log` has new entries:
1. Report count in final summary (`Transformation warnings: {N} — review at .sdlc-transformation-warnings.log`)
2. User reviews and decides: the phrase is a false positive (ignore), or a genuine new phrase that needs a Pattern Mapping rule
3. If rule is needed: update the plugin's Pattern Mapping table in `skills/sdlc-migrate/SKILL.md` and file an issue for upstream to tag the `[contract-change]` for future consumers
