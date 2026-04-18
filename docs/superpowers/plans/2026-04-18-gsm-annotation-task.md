# GSM Annotation Task Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement GSM annotation task type that creates detailed per-sample LLM annotations from completed GSE screening tasks.

**Architecture:** Add `task_type` and `parent_task_id` columns to ScreeningTask. Create new API endpoints to spawn GSM tasks and trigger async annotation. Implement worker function that fetches GSM samples and runs LLM annotation with rich label schema. Build new frontend page for GSM task detail with expandable GSM sub-tables.

**Tech Stack:** SQLAlchemy (models), FastAPI (routers), asyncio (worker), Jinja2 (templates), JavaScript (frontend interactions)

---

## File Structure

**Backend:**
- `backend/models.py` — Add `task_type`, `parent_task_id` to ScreeningTask
- `backend/routers/tasks.py` — Add POST `/tasks/{id}/create-gsm-task`, POST `/tasks/{id}/run-gsm-annotation`, fix GET `/tasks/{id}/results`
- `backend/worker/tasks.py` — Add `_run_gsm_task_async()` function
- `backend/alembic/versions/` — Migration to add new columns

**Frontend:**
- `frontend/templates/tasks.html` — Add task_type badge and parent task subtitle
- `frontend/templates/tasks_detail.html` — Add "创建 GSM 注释任务" button
- `frontend/templates/gsm_task_detail.html` — New page for GSM task detail with stats, table, expansions

---

## Task 1: Database Migration

**Files:**
- Create: `backend/alembic/versions/XXXX_add_gsm_task_columns.py`
- Modify: `backend/models.py:24-42` (ScreeningTask class)

- [ ] **Step 1: Add columns to ScreeningTask model**

```python
class ScreeningTask(Base):
    __tablename__ = "screening_tasks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    search_query: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    total: Mapped[int] = mapped_column(Integer, default=0)
    candidate_count: Mapped[int] = mapped_column(Integer, default=0)
    processed: Mapped[int] = mapped_column(Integer, default=0)
    included_count: Mapped[int] = mapped_column(Integer, default=0)
    excluded_count: Mapped[int] = mapped_column(Integer, default=0)
    uncertain_count: Mapped[int] = mapped_column(Integer, default=0)
    criteria_text: Mapped[str] = mapped_column(Text, nullable=False)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    label_schema: Mapped[str | None] = mapped_column(Text, nullable=True)
    task_type: Mapped[str] = mapped_column(String(32), default="screening")
    parent_task_id: Mapped[int | None] = mapped_column(ForeignKey("screening_tasks.id"), nullable=True)
    owner: Mapped["User"] = relationship(back_populates="tasks")
    results: Mapped[list["ScreeningResult"]] = relationship(back_populates="task")
```

- [ ] **Step 2: Create Alembic migration file**

```python
# backend/alembic/versions/XXXX_add_gsm_task_columns.py
from alembic import op
import sqlalchemy as sa

def upgrade():
    op.add_column('screening_tasks', sa.Column('task_type', sa.String(32), nullable=False, server_default='screening'))
    op.add_column('screening_tasks', sa.Column('parent_task_id', sa.Integer(), nullable=True))
    op.create_foreign_key('fk_screening_tasks_parent', 'screening_tasks', 'screening_tasks', ['parent_task_id'], ['id'])

def downgrade():
    op.drop_constraint('fk_screening_tasks_parent', 'screening_tasks', type_='foreignkey')
    op.drop_column('screening_tasks', 'parent_task_id')
    op.drop_column('screening_tasks', 'task_type')
```

- [ ] **Step 3: Run migration**

```bash
cd backend && alembic upgrade head
```

Expected: Migration applies without errors, new columns visible in database.

- [ ] **Step 4: Commit**

```bash
git add backend/models.py backend/alembic/versions/
git commit -m "feat: add task_type and parent_task_id columns to ScreeningTask"
```

---

## Task 2: Create GSM Task Endpoint

**Files:**
- Modify: `backend/routers/tasks.py` — Add POST `/tasks/{task_id}/create-gsm-task`

- [ ] **Step 1: Write test for create-gsm-task endpoint**

```python
# backend/tests/test_tasks_router.py
async def test_create_gsm_task_from_screening(db, user):
    # Create parent screening task with include/uncertain results
    parent_task = ScreeningTask(
        name="Parent GSE Task",
        source="geo",
        task_type="screening",
        criteria_text="test",
        owner_id=user.id,
    )
    db.add(parent_task)
    await db.flush()
    
    # Add results with different decisions
    for decision in ["include", "uncertain", "exclude"]:
        sr = ScreeningResult(
            task_id=parent_task.id,
            dataset_id=f"GSE{decision}",
            title=f"Dataset {decision}",
            decision=decision,
            n_samples=5,
        )
        db.add(sr)
    await db.commit()
    
    # Call create-gsm-task
    response = await client.post(f"/tasks/{parent_task.id}/create-gsm-task")
    assert response.status_code == 201
    data = response.json()
    assert data["id"]
    assert data["name"]
    
    # Verify new task created with correct type and parent
    new_task = await db.get(ScreeningTask, data["id"])
    assert new_task.task_type == "gsm_annotation"
    assert new_task.parent_task_id == parent_task.id
    
    # Verify only include/uncertain results copied
    results = await db.execute(select(ScreeningResult).where(ScreeningResult.task_id == new_task.id))
    result_list = results.scalars().all()
    assert len(result_list) == 2
    assert all(r.decision in ["include", "uncertain"] for r in result_list)
```

- [ ] **Step 2: Implement create-gsm-task endpoint**

Add to `backend/routers/tasks.py`:

```python
@router.post("/{task_id}/create-gsm-task", status_code=201)
async def create_gsm_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    parent_task = await db.get(ScreeningTask, task_id)
    if not parent_task:
        raise HTTPException(status_code=404, detail="Parent task not found")
    if parent_task.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    # Create new GSM task
    gsm_task = ScreeningTask(
        name=f"{parent_task.name} - GSM Annotation",
        source=parent_task.source,
        task_type="gsm_annotation",
        parent_task_id=parent_task.id,
        criteria_text=parent_task.criteria_text,
        owner_id=user.id,
        label_schema=parent_task.label_schema,
    )
    db.add(gsm_task)
    await db.flush()
    
    # Copy include/uncertain results from parent
    stmt = select(ScreeningResult).where(
        (ScreeningResult.task_id == parent_task.id) &
        (ScreeningResult.decision.in_(["include", "uncertain"]))
    )
    parent_results = (await db.execute(stmt)).scalars().all()
    
    for parent_result in parent_results:
        new_result = ScreeningResult(
            task_id=gsm_task.id,
            dataset_id=parent_result.dataset_id,
            title=parent_result.title,
            description=parent_result.description,
            decision=parent_result.decision,
            gse_type=parent_result.gse_type,
            pubdate=parent_result.pubdate,
            update_date=parent_result.update_date,
            has_raw_data=parent_result.has_raw_data,
            n_samples=parent_result.n_samples,
        )
        db.add(new_result)
    
    gsm_task.total = len(parent_results)
    gsm_task.candidate_count = len(parent_results)
    await db.commit()
    
    return {"id": gsm_task.id, "name": gsm_task.name}
```

- [ ] **Step 3: Run test**

```bash
cd backend && pytest tests/test_tasks_router.py::test_create_gsm_task_from_screening -v
```

Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add backend/routers/tasks.py backend/tests/test_tasks_router.py
git commit -m "feat: add POST /tasks/{id}/create-gsm-task endpoint"
```

---

## Task 3: Run GSM Annotation Endpoint

**Files:**
- Modify: `backend/routers/tasks.py` — Add POST `/tasks/{task_id}/run-gsm-annotation`

- [ ] **Step 1: Write test for run-gsm-annotation endpoint**

```python
# backend/tests/test_tasks_router.py
async def test_run_gsm_annotation(db, user):
    task = ScreeningTask(
        name="GSM Task",
        source="geo",
        task_type="gsm_annotation",
        criteria_text="test",
        owner_id=user.id,
    )
    db.add(task)
    await db.commit()
    
    response = await client.post(f"/tasks/{task.id}/run-gsm-annotation")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "running_inline"
```

- [ ] **Step 2: Implement run-gsm-annotation endpoint**

Add to `backend/routers/tasks.py`:

```python
@router.post("/{task_id}/run-gsm-annotation")
async def run_gsm_annotation(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    task = await db.get(ScreeningTask, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    if task.task_type != "gsm_annotation":
        raise HTTPException(status_code=400, detail="Task is not a GSM annotation task")
    
    from backend.worker.tasks import _run_gsm_task_async
    asyncio.create_task(_run_gsm_task_async(task_id))
    
    return {"status": "running_inline"}
```

- [ ] **Step 3: Run test**

```bash
cd backend && pytest tests/test_tasks_router.py::test_run_gsm_annotation -v
```

Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add backend/routers/tasks.py backend/tests/test_tasks_router.py
git commit -m "feat: add POST /tasks/{id}/run-gsm-annotation endpoint"
```

---

## Task 4: Fix GET /tasks/{id}/results Endpoint

**Files:**
- Modify: `backend/routers/tasks.py` — Add `"id"` field to sample dict

- [ ] **Step 1: Write test for sample id field**

```python
# backend/tests/test_tasks_router.py
async def test_get_results_includes_sample_id(db, user):
    task = ScreeningTask(
        name="Test Task",
        source="geo",
        criteria_text="test",
        owner_id=user.id,
    )
    db.add(task)
    await db.flush()
    
    result = ScreeningResult(
        task_id=task.id,
        dataset_id="GSE123",
        title="Test",
        decision="include",
    )
    db.add(result)
    await db.flush()
    
    sample = GeoSample(
        result_id=result.id,
        gsm_id="GSM456",
        title="Sample 1",
    )
    db.add(sample)
    await db.commit()
    
    response = await client.get(f"/tasks/{task.id}/results")
    assert response.status_code == 200
    data = response.json()
    assert len(data["results"]) == 1
    assert "samples" in data["results"][0]
    assert len(data["results"][0]["samples"]) == 1
    assert "id" in data["results"][0]["samples"][0]
    assert data["results"][0]["samples"][0]["id"] == sample.id
```

- [ ] **Step 2: Find and update GET /tasks/{id}/results endpoint**

In `backend/routers/tasks.py`, find the results endpoint and update sample dict construction to include `"id": s.id`.

- [ ] **Step 3: Run test**

```bash
cd backend && pytest tests/test_tasks_router.py::test_get_results_includes_sample_id -v
```

Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add backend/routers/tasks.py backend/tests/test_tasks_router.py
git commit -m "fix: add sample id field to GET /tasks/{id}/results endpoint"
```

---

## Task 5: Implement _run_gsm_task_async Worker Function

**Files:**
- Modify: `backend/worker/tasks.py` — Add `_run_gsm_task_async()` function

- [ ] **Step 1: Implement _run_gsm_task_async function**

Add to `backend/worker/tasks.py`:

```python
async def _run_gsm_task_async(task_id: int):
    """Run GSM annotation for all samples in a GSM task."""
    async with AsyncSessionLocal() as db:
        try:
            task = await db.get(ScreeningTask, task_id, options=[selectinload(ScreeningTask.results).selectinload(ScreeningResult.samples)])
            if not task:
                logger.error(f"Task {task_id} not found")
                return
            
            # Get LLM client
            llm_config = await db.execute(select(LLMConfig).where(LLMConfig.owner_id == task.owner_id))
            config = llm_config.scalar_one_or_none()
            if not config:
                logger.error(f"No LLM config for user {task.owner_id}")
                return
            
            llm = LLMClient(config)
            
            # Process each result
            for result in task.results:
                # Fetch samples if not already fetched
                if not result.samples:
                    try:
                        await fetch_gsm_samples(result.dataset_id, result.id, db)
                    except Exception as e:
                        logger.error(f"Failed to fetch samples for {result.dataset_id}: {e}")
                        continue
                
                # Fetch GSE detail for context
                gse_detail = await fetch_gse_detail(result.dataset_id)
                
                # Annotate each sample
                for sample in result.samples:
                    # Skip if already annotated
                    existing = await db.execute(
                        select(GsmLabel).where(
                            (GsmLabel.sample_id == sample.id) &
                            (GsmLabel.key == "gsm_available")
                        )
                    )
                    if existing.scalar_one_or_none():
                        continue
                    
                    # Build context
                    context = _build_geo_metadata_context(
                        result.description or "",
                        gse_detail,
                        [_stored_samples_to_dicts(result)[0]],
                        result.has_raw_data,
                    )
                    
                    # Call LLM
                    try:
                        annotation = await llm.annotate_gsm(
                            gsm_id=sample.gsm_id,
                            title=sample.title or "",
                            organism=sample.organism or "",
                            biosample_id=sample.biosample_id or "",
                            context=context,
                        )
                        
                        # Store labels
                        if annotation and "obj" in annotation:
                            for key, value in annotation["obj"].items():
                                label = GsmLabel(
                                    sample_id=sample.id,
                                    key=key,
                                    value=str(value),
                                    source="llm",
                                )
                                db.add(label)
                            
                            # Store response
                            response_label = GsmLabel(
                                sample_id=sample.id,
                                key="response",
                                value=annotation.get("response", ""),
                                source="llm",
                            )
                            db.add(response_label)
                        
                        task.processed += 1
                        await db.commit()
                    except Exception as e:
                        logger.error(f"Failed to annotate {sample.gsm_id}: {e}")
                        continue
            
            task.status = "done"
            await db.commit()
        except Exception as e:
            logger.error(f"Error in _run_gsm_task_async: {e}")
            task.status = "error"
            await db.commit()
```

- [ ] **Step 2: Commit**

```bash
git add backend/worker/tasks.py
git commit -m "feat: implement _run_gsm_task_async worker function"
```

---

## Task 6: Update Task List Frontend

**Files:**
- Modify: `frontend/templates/tasks.html` — Add task_type badge and parent task subtitle

- [ ] **Step 1: Update task list template to show badges**

In `frontend/templates/tasks.html`, add task_type badge and parent task subtitle in task row.

- [ ] **Step 2: Test in browser**

Navigate to tasks list, verify badges display correctly.

- [ ] **Step 3: Commit**

```bash
git add frontend/templates/tasks.html
git commit -m "feat: add task_type badge and parent task subtitle to task list"
```

---

## Task 7: Add Create GSM Task Button

**Files:**
- Modify: `frontend/templates/tasks_detail.html` — Add button

- [ ] **Step 1: Add button to task detail page**

Add "创建 GSM 注释任务" button that calls POST `/tasks/{id}/create-gsm-task`.

- [ ] **Step 2: Test in browser**

Click button, verify new GSM task created and redirected.

- [ ] **Step 3: Commit**

```bash
git add frontend/templates/tasks_detail.html
git commit -m "feat: add create GSM task button to task detail"
```

---

## Task 8: Create GSM Task Detail Page

**Files:**
- Create: `frontend/templates/gsm_task_detail.html`
- Modify: `backend/routers/tasks.py` — Update GET `/tasks/{id}` for GSM tasks

- [ ] **Step 1: Create GSM task detail template**

Create new template with stats row, run button, results table with expandable GSM sub-tables.

- [ ] **Step 2: Update backend to return GSM task data**

Modify GET `/tasks/{id}` to include sample labels and annotation counts for GSM tasks.

- [ ] **Step 3: Test in browser**

Navigate to GSM task, verify stats, table, and expansions work.

- [ ] **Step 4: Commit**

```bash
git add frontend/templates/gsm_task_detail.html backend/routers/tasks.py
git commit -m "feat: create GSM task detail page with stats and expandable tables"
```

