#!/usr/bin/env bash
# Tests for neuroloom-sdlc-plugin hook scripts
# Runs standalone — no external dependencies required
set -euo pipefail

PASS=0
FAIL=0

# ---------------------------------------------------------------------------
# Test framework
# ---------------------------------------------------------------------------

assert_eq() {
  local description="$1"
  local expected="$2"
  local actual="$3"
  if [[ "$expected" == "$actual" ]]; then
    echo "  PASS: $description"
    ((PASS++)) || true
  else
    echo "  FAIL: $description"
    echo "        expected: '$expected'"
    echo "        actual:   '$actual'"
    ((FAIL++)) || true
  fi
}

assert_contains() {
  local description="$1"
  local substring="$2"
  local actual="$3"
  if [[ "$actual" == *"$substring"* ]]; then
    echo "  PASS: $description"
    ((PASS++)) || true
  else
    echo "  FAIL: $description"
    echo "        expected to contain: '$substring'"
    echo "        actual: '$actual'"
    ((FAIL++)) || true
  fi
}

assert_empty() {
  local description="$1"
  local actual="$2"
  if [[ -z "$actual" ]]; then
    echo "  PASS: $description"
    ((PASS++)) || true
  else
    echo "  FAIL: $description"
    echo "        expected empty, got: '$actual'"
    ((FAIL++)) || true
  fi
}

# ---------------------------------------------------------------------------
# Helper: extract deliverable ID from filename (mirrors post-tool-use.sh logic)
# ---------------------------------------------------------------------------

extract_deliverable_id() {
  local filename="$1"
  local id=""
  if [[ "$filename" =~ ^d([0-9]+[a-z]?)_ ]]; then
    id="${BASH_REMATCH[1]}"
  fi
  echo "$id"
}

# ---------------------------------------------------------------------------
# Helper: extract doc type from filename (mirrors post-tool-use.sh logic)
# ---------------------------------------------------------------------------

extract_doc_type() {
  local filename="$1"
  local doc_type=""
  if [[ "$filename" =~ _spec\.md$ ]]; then
    doc_type="spec"
  elif [[ "$filename" =~ _plan\.md$ ]]; then
    doc_type="plan"
  elif [[ "$filename" =~ _result\.md$ ]]; then
    doc_type="result"
  elif [[ "$filename" =~ _COMPLETE\.md$ ]]; then
    doc_type="chronicle"
  fi
  echo "$doc_type"
}

# ---------------------------------------------------------------------------
# Helper: path matching logic (mirrors post-tool-use.sh logic)
# ---------------------------------------------------------------------------

path_matches_sdlc() {
  local path="$1"
  if [[ "$path" =~ docs/current_work/.*\.md$ ]]; then
    echo "match"
  else
    echo "no-match"
  fi
}

# ---------------------------------------------------------------------------
# Test suite: PostToolUse path matching
# ---------------------------------------------------------------------------

echo ""
echo "PostToolUse: Path matching"
echo "---"

assert_eq "matching path — spec file" \
  "match" \
  "$(path_matches_sdlc "docs/current_work/specs/d17_test_spec.md")"

assert_eq "matching path — plan file in subdir" \
  "match" \
  "$(path_matches_sdlc "docs/current_work/planning/d17_test_plan.md")"

assert_eq "matching path — result file" \
  "match" \
  "$(path_matches_sdlc "docs/current_work/results/d17_test_result.md")"

assert_eq "non-matching path — chronicle" \
  "no-match" \
  "$(path_matches_sdlc "docs/chronicle/d5_graph_api_COMPLETE.md")"

assert_eq "non-matching path — source file" \
  "no-match" \
  "$(path_matches_sdlc "api/neuroloom_api/routers/sessions.py")"

assert_eq "non-matching path — non-md file" \
  "no-match" \
  "$(path_matches_sdlc "docs/current_work/specs/d17_test_spec.yaml")"

assert_eq "non-matching path — _index.md" \
  "no-match" \
  "$(path_matches_sdlc "docs/_index.md")"

assert_eq "absolute path — spec file" \
  "match" \
  "$(path_matches_sdlc "/Users/dev/projects/myapp/docs/current_work/specs/d17_test_spec.md")"

assert_eq "absolute path — plan file" \
  "match" \
  "$(path_matches_sdlc "/home/user/myapp/docs/current_work/planning/d17_test_plan.md")"

assert_eq "absolute path — non-matching directory" \
  "no-match" \
  "$(path_matches_sdlc "/Users/dev/projects/myapp/docs/chronicle/d5_graph_api_COMPLETE.md")"

# ---------------------------------------------------------------------------
# Test suite: Deliverable ID extraction
# ---------------------------------------------------------------------------

echo ""
echo "PostToolUse: Deliverable ID extraction"
echo "---"

assert_eq "single digit ID" \
  "5" \
  "$(extract_deliverable_id "d5_graph_api_spec.md")"

assert_eq "two digit ID" \
  "17" \
  "$(extract_deliverable_id "d17_neuroloom_sdlc_plugin_spec.md")"

assert_eq "ID with letter suffix" \
  "1a" \
  "$(extract_deliverable_id "d1a_subdeliverable_plan.md")"

assert_eq "no ID in filename" \
  "" \
  "$(extract_deliverable_id "README.md")"

assert_eq "no ID — underscore-only name" \
  "" \
  "$(extract_deliverable_id "_index.md")"

# ---------------------------------------------------------------------------
# Test suite: Doc type extraction
# ---------------------------------------------------------------------------

echo ""
echo "PostToolUse: Doc type extraction"
echo "---"

assert_eq "spec suffix" \
  "spec" \
  "$(extract_doc_type "d17_neuroloom_sdlc_plugin_spec.md")"

assert_eq "plan suffix" \
  "plan" \
  "$(extract_doc_type "d17_neuroloom_sdlc_plugin_plan.md")"

assert_eq "result suffix" \
  "result" \
  "$(extract_doc_type "d17_neuroloom_sdlc_plugin_result.md")"

assert_eq "COMPLETE suffix maps to chronicle" \
  "chronicle" \
  "$(extract_doc_type "d5_graph_api_COMPLETE.md")"

assert_eq "no known suffix" \
  "" \
  "$(extract_doc_type "d17_something_notes.md")"

assert_eq "BLOCKED suffix not a doc type" \
  "" \
  "$(extract_doc_type "d17_test_BLOCKED.md")"

# ---------------------------------------------------------------------------
# Test suite: SessionStart — absent sentinel behavior
# ---------------------------------------------------------------------------

echo ""
echo "SessionStart: Absent sentinel behavior"
echo "---"

# Simulate the sentinel-absent code path by extracting the logic inline
simulate_sentinel_absent_output() {
  local sentinel_count="$1"
  if [[ "$sentinel_count" == "0" || "$sentinel_count" == "null" ]]; then
    echo "Neuroloom SDLC: workspace not initialized. Run /sdlc-initialize to seed SDLC knowledge."
  else
    echo ""
  fi
}

assert_contains "sentinel count 0 triggers init prompt" \
  "Run /sdlc-initialize" \
  "$(simulate_sentinel_absent_output "0")"

assert_contains "sentinel count null triggers init prompt" \
  "Run /sdlc-initialize" \
  "$(simulate_sentinel_absent_output "null")"

assert_empty "sentinel count 1 produces no output" \
  "$(simulate_sentinel_absent_output "1")"

# ---------------------------------------------------------------------------
# Test suite: SessionStart — version comparison
# ---------------------------------------------------------------------------

echo ""
echo "SessionStart: Version comparison"
echo "---"

simulate_version_comparison_output() {
  local workspace_version="$1"
  local latest_version="$2"
  if [[ -n "$workspace_version" && "$workspace_version" != "$latest_version" ]]; then
    echo "Neuroloom SDLC: update available (${workspace_version} -> ${latest_version}). Run /sdlc-migrate to update."
  else
    echo ""
  fi
}

assert_contains "different versions triggers update notice" \
  "Run /sdlc-migrate" \
  "$(simulate_version_comparison_output "v1.0.0" "v1.1.0")"

assert_contains "update notice includes both versions" \
  "v1.0.0 -> v1.1.0" \
  "$(simulate_version_comparison_output "v1.0.0" "v1.1.0")"

assert_empty "same versions produces no output" \
  "$(simulate_version_comparison_output "v1.1.0" "v1.1.0")"

assert_empty "empty workspace version produces no output" \
  "$(simulate_version_comparison_output "" "v1.1.0")"

# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------

echo ""
echo "---"
TOTAL=$((PASS + FAIL))
echo "Results: ${PASS}/${TOTAL} passed"

if [[ "$FAIL" -gt 0 ]]; then
  echo "FAIL: ${FAIL} test(s) failed"
  exit 1
else
  echo "All tests passed."
  exit 0
fi
