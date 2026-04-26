### 2.2a Contract Change Gate (deterministic semver check)

This gate is **fully deterministic** — it does not involve LLM judgment. The plugin's `.claude-plugin/plugin.json` declares `supported_ccsdlc_version`, the highest cc-sdlc version whose `[contract-change]` entries have been reviewed and reflected in this plugin's Pattern Mapping + post-op audit. The gate compares that declaration against each contract-change entry in the migration range.

**Dual source of truth (cc-sdlc 1.3.0+):** The gate reads both `[contract-change]` changelog entries AND `skeleton/contract_changes.yaml` entries. For each, the version threshold comparison against `PSV` is the same. An entry in either source that exceeds PSV triggers the halt. Phrasing-contract entries typically appear in both; skill renames / field additions / bundle debuts typically appear only in contract_changes.yaml. The gate treats the union as one set of contract changes — it does not matter which source surfaced a given entry.

**Rationale for determinism:** prior versions of this gate halted-or-auto-resolved based on prose interpretation at runtime. Two runs of the same migration against the same source/target versions produced different outcomes — one halted, another silently resolved with a free-form "pattern_mapping_already_updated" note. A gate that sometimes fires is worse than no gate; maintainers can't reason about when to trust it. This version replaces LLM judgment with a version comparison so behavior is reproducible.

**Procedure:**

1. Read `supported_ccsdlc_version` (call it `PSV`) from this plugin's `.claude-plugin/plugin.json`. If the field is missing, **HALT** — the plugin is non-conformant; it must declare its support level before any migration can safely run.

2. For each `[contract-change]` entry collected in Stage 2.2, extract the cc-sdlc version the entry belongs to (e.g., `v1.2.1` → `1.2.1`). The version is the first changelog heading at or above the entry in `process/sdlc_changelog.md`.

3. Compare each contract-change version to `PSV` using semver:
   - If `contract_change_version <= PSV` → the plugin declares support. Emit `contract_change_covered` to the transaction log and continue.
   - If `contract_change_version > PSV` → the plugin has not been updated for this entry. **HALT deterministically**, with the message below.

4. If all entries are covered, the gate is silent — no AskUserQuestion, no maintainer prompt. Stage 2.3's general migration confirmation still runs normally.

**Deterministic halt message (when `contract_change_version > PSV`):**

```
⚠ Contract Change Gate — plugin behind upstream

Plugin `{plugin_name}` declares supported_ccsdlc_version: {PSV}
Migration target is cc-sdlc {LATEST_VERSION}

The following [contract-change] entries are in the migration range but ABOVE the plugin's declared support level:
  - cc-sdlc {version}: {title}
    {summary}
  - ...

This is a hard, deterministic halt. The plugin's Pattern Mapping and post-op
audit must be reviewed against each listed contract change. After review,
bump `supported_ccsdlc_version` in plugin.json to the new level, push, and
re-run /sdlc-migrate. The gate will then auto-resolve.

Do NOT clear this halt by "eyeballing" the changelog — that re-introduces the
LLM-judgment non-determinism this gate was designed to replace.
```

**Transaction-log events:**
```
contract_change_covered   — per entry: {version, title, psv}
contract_change_uncovered — per entry on halt: {version, title, psv}
```

**Edge cases:**
- Pre-release versions (e.g., `1.2.3-rc.1`) compare via semver rules. A pre-release is less than its corresponding stable release.
- If the target cc-sdlc version is below PSV, no contract-change entries are in range — the gate is trivially silent.
- If the changelog has a `[contract-change]` tag without a version heading above it (malformed), treat as `uncovered` and halt. This also flags upstream changelog defects.

**What changing PSV means for the plugin maintainer:**
- Before bumping PSV, review every contract-change entry between old PSV and new PSV in cc-sdlc's changelog.
- Verify the Pattern Mapping has rules for each newly standardized phrase.
- Verify the post-op audit's forbidden-phrasings list (`references/post-operation-audit.md` Check 2a) has detectors for each newly forbidden phrase.
- Only then bump PSV. Bumping without verification means the gate will silently pass a broken migration — defeating the entire purpose of the determinism fix.

