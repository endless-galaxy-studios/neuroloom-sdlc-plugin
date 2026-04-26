# Change Manifest Preview Templates

Output format specifications for Stage 3.3 category preview drill-down.

#### 3.3.3 Category preview behavior

When CD selects a preview category, output the full content for that category:

**New knowledge entries:**
```
New entries to be created ({N}):

1. {title}
   knowledge_id: {id}
   tags: [{tags}]
   ---
   {full content}

2. {title}
   ...
```

**Updated knowledge entries:**
```
Updated entries ({N}):

1. {title}
   knowledge_id: {id}
   
   --- Current (in workspace)
   {current content}
   
   +++ New (from cc-sdlc {LATEST_VERSION})
   {new content}

2. {title}
   ...
```

For large diffs, show a unified diff format highlighting only changed lines.

**Deprecated knowledge entries:**
```
Entries to be deprecated ({N}):

These entries exist in your workspace but are no longer in cc-sdlc {LATEST_VERSION}.
They will be tagged sdlc:deprecated but NOT deleted.

1. {title} (knowledge_id: {id})
2. {title} (knowledge_id: {id})
...
```

**Updated operational files:**
```
Operational files to be overwritten ({N}):

1. {file_path}
   @@ unified diff @@
   ...

2. {file_path}
   ...
```

**Modified operational files:**
```
Modified files requiring review ({N}):

These files have project customizations that differ from the upstream version.
Each will get a per-file confirmation in Stage 4.

1. {file_path}
   Project customization detected:
   {summary of what's different}
   
   @@ unified diff (project vs upstream) @@
   ...

2. {file_path}
   ...
```

#### 3.3.4 Return to options

After displaying any category preview, return to the options prompt (3.3.2). CD can preview multiple categories before deciding to apply or cancel.

**Loop until CD selects `Apply migration` or `Cancel`.**

If there are modified operational files, note that Stage 4 will present a per-file confirmation for each one (the preview here shows what to expect; the gate in Stage 4 is where the decision is made).

---

---

## Stage 3.3 Summary and Preview Options


Output the change manifest summary (not via `AskUserQuestion` — this is informational):

```
Change manifest: {KNOWLEDGE_VERSION} → {LATEST_VERSION}

Knowledge layer:
  New:        {N} entries
  Updated:    {N} entries
  Unchanged:  {N} entries
  Deprecated: {N} entries (will be tagged deprecated, not deleted)

Operational layer:
  Unchanged:  {N} files
  Updated:    {N} files (framework-only changes — will overwrite)
  Modified:   {N} files (project customizations detected — will require review)
```

#### 3.3.2 Preview options

Use `AskUserQuestion` with category-based drill-down options:

```
What would you like to review before applying?
```

Options (show only categories with count > 0):
- `Preview new knowledge entries ({N})` — shows titles + full content of entries to be created
- `Preview updated knowledge entries ({N})` — shows titles + content diff (old vs new)
- `Preview deprecated knowledge entries ({N})` — shows titles of entries that will be tagged deprecated
- `Preview updated operational files ({N})` — shows file paths + unified diff
- `Preview modified operational files ({N})` — shows file paths + diff highlighting project customizations
- `Apply migration` — proceed to Stage 4
- `Cancel` — abort without changes


---

## Stage 5.4 — Final Migration Report Template

### 5.4 Report to CD

Output the full migration summary:

```
SDLC Migration Complete — {N} files updated, {N} entries re-seeded, 0 regressions

Upgraded from {KNOWLEDGE_VERSION} to {LATEST_VERSION} across both layers. {1-2 sentences: what the migration brought — e.g., "Added 3 new knowledge entries, merged 2 expanded skills, preserved 4 MCP-bearing sections." State any items needing manual review.}

Knowledge layer:
  Created:     {N} new entries
  Updated:     {N} changed entries
  Unchanged:   {N} entries
  Deprecated:  {N} entries (preserved, tagged sdlc:deprecated)
  Errors:      {N} (see below if > 0)

Operational layer:
  Overwritten:    {N} files
  Skipped:        {N} files (kept project version)
  Modified:       {N} files (required manual review — see decisions below)
  Consolidated:   {N} skills removed (absorbed into other skills)
  Never-touched:  agent-selection.yaml, provenance_log.md (project-specific)

PROJECT-SECTION markers:
  Blocks found:      {N}
  Re-injected as-is: {N}
  Reviewed:          {N}
  Orphaned:          {N} (heading no longer exists — appended at end of file)

Neuroloom content transformation:
  Files with MCP patterns preserved: {N} [list files]
  Sections preserved: [list file § section]

CLAUDE.md:
  Stale references updated: {N}
  Guarded renames skipped:  {N} (targets don't exist)
  New sections merged:      {N}
  Standalone CLAUDE-SDLC.md removed: {yes/no/not present}

Manifest:
  sdlc_version: {LATEST_VERSION}
  New fields added: {list or "none"}

Compliance audit: {pass / N findings — see below}

Migration decisions:
  [table of modified files and CD's chosen action for each]

Errors (if any):
  [list of knowledge entries that failed to ingest, with error messages]

Next step: Run /sdlc-status to verify both layers, or begin work with /sdlc-plan.
```

---
