# Decision Editing Design

Date: 2026-04-20

## Overview

Allow users to manually override the LLM screening decision for any `ScreeningResult` directly from the task detail table. Clicking the decision badge turns it into an inline `<select>`, selecting a new value saves immediately and updates the task-level counts.

---

## Backend

### New endpoint

```
PATCH /tasks/{task_id}/results/{result_id}
Body: {"decision": "include" | "exclude" | "uncertain"}
```

- Validates task ownership (404 if not found or wrong owner)
- Loads `ScreeningResult` by `result_id`, verifies it belongs to `task_id`
- Updates `sr.decision`
- Recomputes `ScreeningTask.included_count`, `excluded_count`, `uncertain_count` from DB (single COUNT query per value)
- Returns `{"decision": "<new>", "included_count": N, "excluded_count": N, "uncertain_count": N}`

**File:** `backend/routers/tasks.py` — append new route.

---

## Frontend

### "决策" column — inline select

Current: `<span :class="decisionClass(r.decision)" x-text="...">` (read-only badge)

New behavior:
- Each result row tracks `editingDecision` state (boolean, per-row via Alpine)
- Click on badge → `editingDecision = true`, badge replaced by `<select>` with three options
- On `@change`: call `PATCH /tasks/{taskId}/results/{r.id}`, update `r.decision` and task counts, set `editingDecision = false`
- On error: restore original value, set `editingDecision = false`
- Click outside (`@click.outside` or `@blur`) without changing: cancel, set `editingDecision = false`

**Implementation:** Add `editingDecision` flag to each result object in `loadResults()`. Add `updateDecision(r, newVal)` method to `taskDetailPage()`.

**File:** `frontend/templates/tasks_detail.html`

---

## Data flow

```
User clicks badge
  → editingDecision = true (show <select>)
User selects new value
  → PATCH /tasks/{taskId}/results/{r.id} {decision: newVal}
  → on success: r.decision = newVal, task.included_count = ..., editingDecision = false
  → on error: r.decision = oldVal, editingDecision = false
```

---

## Files changed

| File | Change |
|---|---|
| `backend/routers/tasks.py` | Add `PATCH /{task_id}/results/{result_id}` |
| `frontend/templates/tasks_detail.html` | Inline select on decision badge, `updateDecision()` method |
