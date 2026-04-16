# Frontend Redesign + GEO Data Enrichment Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** Enrich GEO data with missing fields via on-demand eFetch, and redesign frontend with left sidebar navigation and improved detail modals.

**Architecture:** Backend adds `/geo/gse/{gse_id}/detail` endpoint that fetches MINiML XML from NCBI and parses contact info, abstract, overall design, and supplementary files. Frontend replaces top nav with left sidebar, updates search table columns, and redesigns detail modals to show 4 sections.

**Tech Stack:** Python (xml.etree.ElementTree), FastAPI, Tailwind CSS, Alpine.js

---

## File Structure

**Backend:**
- `backend/worker/geo_fetcher.py` — add `fetch_gse_detail()` and `_parse_miniml()`
- `backend/routers/geo.py` — add `GET /geo/gse/{gse_id}/detail` route
- `backend/tests/test_geo_fetcher.py` — add tests for new function
- `backend/tests/test_geo_router.py` — add tests for new route

**Frontend:**
- `frontend/templates/base.html` — replace top nav with left sidebar
- `frontend/templates/search.html` — update table columns, redesign detail modal
- `frontend/templates/tasks_detail.html` — add cellCount column to GSM table
- `frontend/templates/library_detail.html` — update modal to 4-section layout

---

## Task 1: Add `fetch_gse_detail()` to geo_fetcher.py

**Files:**
- Modify: `backend/worker/geo_fetcher.py`
- Test: `backend/tests/test_geo_fetcher.py`

- [ ] **Step 1: Add imports and helper function**

Add to top of `geo_fetcher.py`:
```python
import xml.etree.ElementTree as ET
```

Add after the existing functions:
```python
def _parse_miniml(xml_text: str, gse_id: str) -> dict:
    """Parse MINiML XML and extract GSE detail fields."""
    NS = "http://www.ncbi.nlm.nih.gov/geo/info/MINiML"
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return {"gse_id": gse_id}
    
    series = root.find(f"{{{NS}}}Series")
    if series is None:
        return {"gse_id": gse_id}
    
    # BioProject ID
    bioproject_id = ""
    bioproject_link = ""
    for rel in series.findall(f"{{{NS}}}Relation"):
        if rel.get("type") == "BioProject":
            target = rel.get("target", "")
            if "/bioproject/" in target:
                bioproject_id = target.split("/bioproject/")[-1]
            bioproject_link = target
    
    # Abstract and Overall Design
    abstract_el = series.find(f"{{{NS}}}Summary")
    abstract = abstract_el.text.strip() if abstract_el is not None and abstract_el.text else ""
    
    od_el = series.find(f"{{{NS}}}Overall-Design")
    overall_design = od_el.text.strip() if od_el is not None and od_el.text else ""
    
    # Supplementary files
    suppl_files = []
    for suppl in series.findall(f"{{{NS}}}Supplementary-Data"):
        url = suppl.text.strip() if suppl.text else ""
        if url:
            name = url.split("/")[-1]
            suppl_files.append({"name": name, "url": url})
    
    # Contact info
    contact_ref = series.find(f"{{{NS}}}Contact-Ref")
    contact = {}
    if contact_ref is not None:
        ref_id = contact_ref.get("ref", "")
        for contrib in root.findall(f"{{{NS}}}Contributor"):
            if contrib.get("iid") == ref_id:
                person = contrib.find(f"{{{NS}}}Person")
                first = last = ""
                if person is not None:
                    first_el = person.find(f"{{{NS}}}First")
                    last_el = person.find(f"{{{NS}}}Last")
                    first = first_el.text.strip() if first_el is not None and first_el.text else ""
                    last = last_el.text.strip() if last_el is not None and last_el.text else ""
                
                email_el = contrib.find(f"{{{NS}}}Email")
                email = email_el.text.strip() if email_el is not None and email_el.text else ""
                
                dept_el = contrib.find(f"{{{NS}}}Department")
                department = dept_el.text.strip() if dept_el is not None and dept_el.text else ""
                
                org = contrib.find(f"{{{NS}}}Organization")
                address = city = state = zip_code = country = ""
                if org is not None:
                    addr_el = org.find(f"{{{NS}}}Address")
                    city_el = org.find(f"{{{NS}}}City")
                    state_el = org.find(f"{{{NS}}}State")
                    zip_el = org.find(f"{{{NS}}}Zip-Code")
                    country_el = org.find(f"{{{NS}}}Country")
                    address = addr_el.text.strip() if addr_el is not None and addr_el.text else ""
                    city = city_el.text.strip() if city_el is not None and city_el.text else ""
                    state = state_el.text.strip() if state_el is not None and state_el.text else ""
                    zip_code = zip_el.text.strip() if zip_el is not None and zip_el.text else ""
                    country = country_el.text.strip() if country_el is not None and country_el.text else ""
                
                contact = {
                    "name": f"{first} {last}".strip(),
                    "email": email,
                    "address": address,
                    "city": city,
                    "state": state,
                    "zip": zip_code,
                    "country": country,
                    "department": department,
                }
                break
    
    return {
        "gse_id": gse_id,
        "bioproject_id": bioproject_id,
        "bioproject_link": bioproject_link,
        "abstract": abstract,
        "overall_design": overall_design,
        "contact": contact,
        "supplementary_files": suppl_files,
    }


async def fetch_gse_detail(gse_id: str) -> dict:
    """Fetch full GSE detail via eFetch MINiML format."""
    ids = await _esearch("gds", f'"{gse_id}"[Accession] AND gse[EntryType]', retmax=1)
    if not ids:
        return {"gse_id": gse_id}
    
    url = f"{NCBI_BASE}/efetch.fcgi"
    params = {"db": "gds", "id": ids[0], "rettype": "miniml", "retmode": "xml"}
    
    async with httpx.AsyncClient(timeout=30) as client:
        for attempt in range(MAX_RETRIES):
            try:
                r = await client.get(url, params=params)
                r.raise_for_status()
                return _parse_miniml(r.text, gse_id)
            except (httpx.HTTPStatusError, httpx.TimeoutException):
                if attempt == MAX_RETRIES - 1:
                    raise
                await asyncio.sleep(2 ** attempt)
    return {"gse_id": gse_id}
```

- [ ] **Step 2: Run existing tests to ensure no regression**

```bash
pytest backend/tests/test_geo_fetcher.py -v
```

Expected: All existing tests PASS

- [ ] **Step 3: Write test for `_parse_miniml()`**

Add to `backend/tests/test_geo_fetcher.py`:
```python
@pytest.mark.asyncio
async def test_parse_miniml_extracts_all_fields():
    from backend.worker.geo_fetcher import _parse_miniml
    
    xml = '''<?xml version="1.0"?>
<MINiML xmlns="http://www.ncbi.nlm.nih.gov/geo/info/MINiML">
  <Contributor iid="contrib1">
    <Person><First>Jens</First><Last>Magnusson</Last></Person>
    <Email>jens@test.com</Email>
    <Department>Biosciences</Department>
    <Organization>
      <Address>Alfred Nobels Allé 8</Address>
      <City>Stockholm</City>
      <Zip-Code>14152</Zip-Code>
      <Country>Sweden</Country>
    </Organization>
  </Contributor>
  <Series iid="GSE305128">
    <Summary>Test abstract</Summary>
    <Overall-Design>Test design</Overall-Design>
    <Contact-Ref ref="contrib1"/>
    <Supplementary-Data type="TAR">ftp://test.com/file.tar</Supplementary-Data>
    <Relation type="BioProject" target="https://www.ncbi.nlm.nih.gov/bioproject/PRJNA1304480"/>
  </Series>
</MINiML>'''
    
    result = _parse_miniml(xml, "GSE305128")
    assert result["gse_id"] == "GSE305128"
    assert result["bioproject_id"] == "PRJNA1304480"
    assert result["abstract"] == "Test abstract"
    assert result["overall_design"] == "Test design"
    assert result["contact"]["name"] == "Jens Magnusson"
    assert result["contact"]["email"] == "jens@test.com"
    assert result["contact"]["city"] == "Stockholm"
    assert len(result["supplementary_files"]) == 1
    assert result["supplementary_files"][0]["name"] == "file.tar"
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest backend/tests/test_geo_fetcher.py::test_parse_miniml_extracts_all_fields -v
```

Expected: PASS

- [ ] **Step 5: Write test for `fetch_gse_detail()`**

Add to `backend/tests/test_geo_fetcher.py`:
```python
@pytest.mark.asyncio
async def test_fetch_gse_detail_calls_efetch():
    from backend.worker.geo_fetcher import fetch_gse_detail
    
    mock_xml = '''<?xml version="1.0"?>
<MINiML xmlns="http://www.ncbi.nlm.nih.gov/geo/info/MINiML">
  <Contributor iid="c1"><Person><First>Test</First></Person></Contributor>
  <Series iid="GSE123"><Summary>Test</Summary><Contact-Ref ref="c1"/></Series>
</MINiML>'''
    
    async def mock_get(url, params=None, **kwargs):
        m = MagicMock()
        m.raise_for_status = MagicMock()
        m.text = mock_xml
        return m
    
    with patch("backend.worker.geo_fetcher._esearch", new=AsyncMock(return_value=["123"])), \
         patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=mock_get)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client
        
        result = await fetch_gse_detail("GSE123")
    
    assert result["gse_id"] == "GSE123"
    assert "contact" in result
```

- [ ] **Step 6: Run test to verify it passes**

```bash
pytest backend/tests/test_geo_fetcher.py::test_fetch_gse_detail_calls_efetch -v
```

Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add backend/worker/geo_fetcher.py backend/tests/test_geo_fetcher.py
git commit -m "feat: add fetch_gse_detail with MINiML parsing"
```

---

## Task 2: Add `/geo/gse/{gse_id}/detail` route

**Files:**
- Modify: `backend/routers/geo.py`
- Test: `backend/tests/test_geo_router.py`

- [ ] **Step 1: Add import**

Add to imports in `backend/routers/geo.py`:
```python
from backend.worker.geo_fetcher import fetch_gse_detail
```

- [ ] **Step 2: Add route**

Add after existing routes in `backend/routers/geo.py`:
```python
@router.get("/gse/{gse_id}/detail")
async def get_gse_detail(
    gse_id: str,
    user: User = Depends(get_current_user),
):
    try:
        detail = await fetch_gse_detail(gse_id)
        return detail
    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code if exc.response is not None else None
        if status_code == 429:
            raise HTTPException(status_code=503, detail="NCBI rate limit reached. Please retry in a moment.")
        raise HTTPException(status_code=502, detail="GEO upstream request failed.")
    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail="Unable to reach GEO right now.")
```

- [ ] **Step 3: Write test**

Add to `backend/tests/test_geo_router.py`:
```python
@pytest.mark.asyncio
async def test_gse_detail_endpoint_returns_enriched_data(auth_client):
    detail_data = {
        "gse_id": "GSE305128",
        "bioproject_id": "PRJNA1304480",
        "abstract": "Test abstract",
        "overall_design": "Test design",
        "contact": {"name": "Test User", "email": "test@test.com"},
        "supplementary_files": [{"name": "file.tar", "url": "ftp://test.com/file.tar"}],
    }
    
    with patch("backend.routers.geo.fetch_gse_detail", new=AsyncMock(return_value=detail_data)):
        response = await auth_client.get("/geo/gse/GSE305128/detail")
    
    assert response.status_code == 200
    payload = response.json()
    assert payload["gse_id"] == "GSE305128"
    assert payload["bioproject_id"] == "PRJNA1304480"
    assert payload["contact"]["name"] == "Test User"
```

- [ ] **Step 4: Run test**

```bash
pytest backend/tests/test_geo_router.py::test_gse_detail_endpoint_returns_enriched_data -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/routers/geo.py backend/tests/test_geo_router.py
git commit -m "feat: add GET /geo/gse/{gse_id}/detail endpoint"
```

---

## Task 3: Replace top nav with left sidebar in base.html

**Files:**
- Modify: `frontend/templates/base.html`

- [ ] **Step 1: Replace entire base.html**

Replace content of `frontend/templates/base.html` with:
```html
<!DOCTYPE html>
<html lang="en" x-data="appState()" x-init="init()">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{% block title %}GEO Screener{% endblock %}</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <script defer src="https://cdn.jsdelivr.net/npm/alpinejs@3.x.x/dist/cdn.min.js"></script>
  <script src="/static/app.js"></script>
</head>
<body class="bg-gray-50 text-gray-900 min-h-screen flex">
  <!-- Left Sidebar -->
  <aside class="w-40 bg-white border-r border-gray-200 fixed h-full flex flex-col z-10">
    <div class="px-4 py-4 border-b border-gray-100">
      <a href="/search" class="font-semibold text-blue-600 text-sm">GEO Screener</a>
    </div>
    <nav class="flex-1 py-2 overflow-y-auto">
      <a href="/search" class="block px-4 py-2.5 text-sm text-gray-600 hover:bg-gray-50 hover:text-gray-900">论文列表</a>
      <a href="/tasks-list" class="block px-4 py-2.5 text-sm text-gray-600 hover:bg-gray-50 hover:text-gray-900">任务管理</a>
      <a href="/library" class="block px-4 py-2.5 text-sm text-gray-600 hover:bg-gray-50 hover:text-gray-900">文献库</a>
      <a href="/criteria-page" class="block px-4 py-2.5 text-sm text-gray-600 hover:bg-gray-50 hover:text-gray-900">配置管理</a>
      <a href="/settings" class="block px-4 py-2.5 text-sm text-gray-600 hover:bg-gray-50 hover:text-gray-900">Settings</a>
    </nav>
    <div class="px-4 py-3 border-t border-gray-100">
      <button @click="logout()" class="text-xs text-red-500 hover:text-red-700">退出登录</button>
    </div>
  </aside>
  <!-- Main Content -->
  <main class="ml-40 flex-1 px-6 py-6 min-w-0">
    {% block content %}{% endblock %}
  </main>
</body>
</html>
```

- [ ] **Step 2: Commit**

```bash
git add frontend/templates/base.html
git commit -m "feat: replace top nav with left sidebar"
```

---

## Task 4: Update search.html table columns and detail modal

**Files:**
- Modify: `frontend/templates/search.html`

- [ ] **Step 1: Update table colgroup and thead**

Replace the `<colgroup>` and `<thead>` in the results table:
```html
<colgroup>
  <col class="w-32">
  <col>
  <col class="w-24">
  <col class="w-32">
  <col class="w-28">
  <col class="w-28">
  <col class="w-16">
  <col class="w-16">
</colgroup>
<thead class="bg-gray-50 border-b">
  <tr>
    <th class="text-left px-4 py-3 font-medium text-gray-600">Accession</th>
    <th class="text-left px-4 py-3 font-medium text-gray-600">标题</th>
    <th class="text-left px-4 py-3 font-medium text-gray-600">Sample count</th>
    <th class="text-left px-4 py-3 font-medium text-gray-600">实验类型</th>
    <th class="text-left px-4 py-3 font-medium text-gray-600">论文更新日期</th>
    <th class="text-left px-4 py-3 font-medium text-gray-600">最后更新日期</th>
    <th class="text-left px-4 py-3 font-medium text-gray-600">原始数据</th>
    <th class="text-left px-4 py-3 font-medium text-gray-600">操作</th>
  </tr>
</thead>
```

- [ ] **Step 2: Update table body**

Replace the `<tbody>` section with:
```html
<tbody class="divide-y">
  <template x-for="item in visibleItems" :key="item.id">
    <tr class="hover:bg-gray-50">
      <td class="px-4 py-3 font-mono text-xs text-blue-700 align-top">
        <p x-text="item.id"></p>
        <p class="text-gray-400 text-[10px]" x-show="item.bioproject_id" x-text="'PRJNA' + item.bioproject_id"></p>
      </td>
      <td class="px-4 py-3 align-top">
        <p class="text-sm font-medium text-gray-900 line-clamp-2" x-text="item.title"></p>
      </td>
      <td class="px-4 py-3 text-xs text-gray-500 align-top text-center" x-text="item.n_samples || '—'"></td>
      <td class="px-4 py-3 text-xs text-gray-500 align-top line-clamp-2" x-text="item.gse_type || '—'"></td>
      <td class="px-4 py-3 text-xs text-gray-500 align-top" x-text="item.pubdate || '—'"></td>
      <td class="px-4 py-3 text-xs text-gray-500 align-top" x-text="item.update_date || '—'"></td>
      <td class="px-4 py-3 text-center align-top">
        <span x-show="item.has_raw_data" class="text-green-500">✓</span>
        <span x-show="!item.has_raw_data" class="text-gray-300">—</span>
      </td>
      <td class="px-4 py-3 text-xs align-top">
        <button @click.stop="openModal(item)" class="text-blue-500 hover:text-blue-700">标注 →</button>
      </td>
    </tr>
  </template>
</tbody>
```

- [ ] **Step 3: Replace detail modal**

Replace the entire `<!-- Summary Modal -->` section with the new 4-section modal. See continuation in next step.

- [ ] **Step 4: Update modal state in script**

In the `searchPage()` function, update modal initialization:
```javascript
modal: {open: false, id: '', title: '', summary: '', organism: '', n_samples: 0,
        has_raw_data: false, gse_type: '', samples: [], loadingDetail: false, detail: null},
```

- [ ] **Step 5: Update openModal function**

Replace the `openModal` function:
```javascript
async openModal(item) {
  this.modal = {
    open: true, id: item.id, title: item.title, summary: item.summary || '',
    organism: item.organism, n_samples: item.n_samples,
    has_raw_data: item.has_raw_data, gse_type: item.gse_type,
    samples: [], loadingDetail: true, detail: null,
  };
  // Fetch GSM samples
  try {
    const r = await fetch(`/geo/gse/${item.id}/samples`);
    if (r.ok) {
      const d = await r.json();
      this.modal.samples = d.samples || [];
    }
  } catch(e) {}
  
  // Fetch detail info
  try {
    const r = await fetch(`/geo/gse/${item.id}/detail`);
    if (r.ok) {
      this.modal.detail = await r.json();
    }
  } catch(e) {}
  
  this.modal.loadingDetail = false;
},
```

- [ ] **Step 6: Commit**

```bash
git add frontend/templates/search.html
git commit -m "feat: redesign search table columns and detail modal with 4 sections"
```

---

## Task 5: Add cellCount column to GSM table in tasks_detail.html

**Files:**
- Modify: `frontend/templates/tasks_detail.html`

- [ ] **Step 1: Update GSM table header**

In the GSM samples table (around line 150), update the `<thead>`:
```html
<thead class="bg-gray-100">
  <tr>
    <th class="text-left px-3 py-2 font-medium text-gray-600">样本名称</th>
    <th class="text-left px-3 py-2 font-medium text-gray-600">标题</th>
    <th class="text-left px-3 py-2 font-medium text-gray-600">生物体</th>
    <th class="text-left px-3 py-2 font-medium text-gray-600">生物样本关系ID</th>
    <th class="text-left px-3 py-2 font-medium text-gray-600">cellCount</th>
  </tr>
</thead>
```

- [ ] **Step 2: Update GSM table body**

Update the `<tbody>` rows:
```html
<tbody class="divide-y bg-white">
  <template x-for="s in r.samples" :key="s.gsm_id">
    <tr>
      <td class="px-3 py-2 font-mono text-blue-700" x-text="s.gsm_id"></td>
      <td class="px-3 py-2 text-gray-700" x-text="s.title || '—'"></td>
      <td class="px-3 py-2 text-gray-500" x-text="s.organism || '—'"></td>
      <td class="px-3 py-2 text-blue-600" x-text="s.biosample_id || '—'"></td>
      <td class="px-3 py-2 text-gray-700" x-text="s.cell_count || '—'"></td>
    </tr>
  </template>
</tbody>
```

- [ ] **Step 3: Commit**

```bash
git add frontend/templates/tasks_detail.html
git commit -m "feat: add cellCount column to GSM samples table"
```

---

## Task 6: Update library_detail.html modal to 4-section layout

**Files:**
- Modify: `frontend/templates/library_detail.html`

- [ ] **Step 1: Update modal structure**

Replace the modal content (after the header) with 4 sections similar to search.html. The modal should include:
- Section 1: 数据信息 (bioproject_id, bioproject_link)
- Section 2: 其他信息 (abstract, overall_design)
- Section 3: 联系人信息 (contact fields)
- Section 4: Supplementary data files

- [ ] **Step 2: Update modal state**

Update the modal object to include `detail` field:
```javascript
modal: {open: false, gse_id: '', title: '', organism: '', n_samples: 0,
        has_raw_data: false, gse_type: '', samples: [], entry_id: null, detail: null, loadingDetail: false},
```

- [ ] **Step 3: Update openModal function**

Update to fetch detail:
```javascript
async openModal(entry) {
  this.modal = {
    open: true, gse_id: entry.gse_id, title: entry.title, organism: entry.organism,
    n_samples: entry.n_samples, has_raw_data: entry.has_raw_data, gse_type: entry.gse_type,
    samples: entry.samples || [], entry_id: entry.id, detail: null, loadingDetail: true,
  };
  
  // Fetch detail
  try {
    const r = await fetch(`/geo/gse/${entry.gse_id}/detail`);
    if (r.ok) {
      this.modal.detail = await r.json();
    }
  } catch(e) {}
  
  this.modal.loadingDetail = false;
},
```

- [ ] **Step 4: Commit**

```bash
git add frontend/templates/library_detail.html
git commit -m "feat: update library detail modal to 4-section layout"
```

---

## Verification

After all tasks complete:

- [ ] Run all backend tests: `pytest backend/tests/ -v`
- [ ] Verify frontend pages load without errors
- [ ] Test detail modal opens and loads data
- [ ] Test GSM table displays cellCount

