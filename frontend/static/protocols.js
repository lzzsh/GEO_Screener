const protocolFieldLabels = {GSE_id:(tr("GSE 编号")),GSM_id:(tr("GSM 编号")),Article_title:(tr("论文标题")),Start_cell_type:(tr("起始细胞类型")),Final_cell_type:(tr("目标细胞类型")),Stage_name:(tr("阶段名称")),Stage_order:(tr("阶段顺序")),Pert_name:(tr("扰动名称")),Addition_context:(tr("添加背景")),Pert_type:(tr("扰动类型")),pubchem_cid:'PubChem CID',chembl_id:'ChEMBL ID',dose_value:(tr("剂量数值")),dose_unit:(tr("剂量单位")),time_pert_start:(tr("开始时间")),time_pert_end:(tr("结束时间")),duration_pert:(tr("持续时间")),time_unit:(tr("时间单位")),time_collection:(tr("采样时间")),Culture_medium:(tr("培养基")),Culture_system:(tr("培养体系")),Batch_id:(tr("批次编号")),Collection_methods:(tr("收集方法")),Reference:(tr("参考来源"))};
function statusClass(status) { return ['reviewed'].includes(status)?'ui-badge--green':['failed'].includes(status)?'ui-badge--red':['needs_sources','waiting_material','needs_review'].includes(status)?'ui-badge--amber':protocolActive(status)?'ui-badge--blue':''; }
const protocolLabels = {waiting_material:(tr("待补材料")), ready:(tr("材料就绪")), queued:(tr("排队中")), fetching:(tr("获取材料")), extracting:(tr("提取中")), needs_review:(tr("待复核")), needs_sources:(tr("待补引用")), no_protocol:(tr("未找到 Protocol")), reviewed:(tr("已复核")), failed:(tr("失败"))};
const protocolActive = status => ['queued','fetching','extracting'].includes(status);
async function protocolApi(path, options = {}) {
  const response = await fetch('/api/protocols' + path, options);
  if (response.status === 401) { location.href = '/login'; throw new Error((tr("请先登录"))); }
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    const detail = payload.detail;
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail || (tr("请求失败"))));
  }
  return response;
}
function protocolList() {
  return {
    jobs: [], error: '', loading: true, timer: null,
    label: status => protocolLabels[status] || status,
    async init() { await this.load(); this.timer = setInterval(() => this.load(), 5000); },
    destroy() { clearInterval(this.timer); },
    async load() {
      try { this.jobs = await (await protocolApi('/jobs')).json(); this.error=''; }
      catch (e) { this.error = e.message; }
      finally { this.loading = false; }
    },
    reviewed(job) { return job.counts.reviewed || 0; }
  };
}
function protocolDetail(jobId) {
  return {
    jobId, job: {items:[], columns:[]}, item: null, currentId: null,
    revisionId: null, draft: null, dirty: false, busy: false, error: '', notice: '',
    selectedRow: null, docId: null, evidenceMode: 'text', page: 1, sourceText: '', timer: null, pollError: '',
    uploadKind:'main', uploadReference:'', protocolFilter:'',
    label: status => protocolLabels[status] || status,
    fieldGroups() { return [
      {title:tr('样本与细胞'),keys:['GSE_id','GSM_id','Article_title','Start_cell_type','Final_cell_type','Batch_id']},
      {title:tr('阶段与时间'),keys:['Stage_name','Stage_order','time_pert_start','time_pert_end','duration_pert','time_unit','time_collection']},
      {title:tr('扰动与剂量'),keys:['Pert_name','Addition_context','Pert_type','dose_value','dose_unit','pubchem_cid','chembl_id']},
      {title:tr('培养与来源'),keys:['Culture_medium','Culture_system','Collection_methods','Reference']}
    ]; },
    fieldLabel(key) { return protocolFieldLabels[key] || key; },
    active() { return this.item && protocolActive(this.item.status); },
    async init() {
      try {
        await this.loadJob();
        if (this.job.items.length) await this.openItem(this.job.items[0].id);
        this.timer = setInterval(() => this.poll(), 4000);
      } catch(e) { this.error=e.message; }
    },
    destroy() { clearInterval(this.timer); },
    async loadJob() { this.job = await (await protocolApi('/jobs/' + this.jobId)).json(); },
    async poll() {
      if (this.busy) return;
      try {
        await this.loadJob();
        if (this.currentId && !this.dirty) await this.refreshItem();
        if (this.error === this.pollError) this.error='';
        this.pollError='';
      } catch(e) { this.pollError=e.message; this.error=e.message; }
    },
    async openItem(id) {
      if (this.dirty && !confirm((tr("当前有未保存修改。放弃修改并切换文献？")))) return;
      this.currentId=id; this.revisionId=null; this.draft=null; this.dirty=false;
      this.selectedRow=null; this.docId=null; this.sourceText=''; this.protocolFilter='';
      this.error=''; this.notice='';
      try { await this.refreshItem(); } catch(e) { this.error=e.message; }
    },
    async refreshItem() {
      const id=this.currentId;
      const value=await (await protocolApi('/items/' + id)).json();
      if (id !== this.currentId || this.dirty) return;
      this.item=value;
      const revision=value.revisions.find(r => r.id === this.revisionId) || value.revisions.find(r=>r.id===value.active_revision_id);
      if (revision) {
        const changed = this.revisionId !== revision.id;
        this.revisionId=revision.id;
        this.draft=JSON.parse(JSON.stringify(revision.payload));
        if (changed) this.selectedRow=null;
      }
      if (!this.docId && value.documents.length) await this.showDocument(value.documents[0].id, 1);
    },
    changeRevision() {
      const revision=this.item.revisions.find(r=>r.id===Number(this.revisionId));
      if (!revision) return;
      this.revisionId=revision.id; this.draft=JSON.parse(JSON.stringify(revision.payload));
      this.dirty=false; this.selectedRow=null;
    },
    groups() { return [...new Set((this.draft?.events || []).map(e=>e.protocol_name))]; },
    visibleRows() { return (this.draft?.events || []).map((event,index)=>({event,index})).filter(row=>!this.protocolFilter || row.event.protocol_name===this.protocolFilter); },
    selected() { return this.draft?.events?.[this.selectedRow] || null; },
    async chooseRow(index) {
      this.selectedRow=index;
      const evidence=this.selected()?.evidence?.[0];
      if (evidence) await this.showDocument(evidence.document_id, evidence.page);
    },
    async showDocument(id, page=1) {
      this.docId=Number(id); this.page=Number(page) || 1;
      try {
        const content=await (await protocolApi('/documents/' + this.docId + '?page=' + this.page)).json();
        this.sourceText=content.text;
      } catch(e) { this.error=e.message; }
    },
    document() { return this.item?.documents.find(d=>d.id===this.docId); },
    fileUrl() { return this.docId ? '/api/protocols/documents/' + this.docId + '#page=' + this.page : ''; },
    async upload() {
      const file=this.$refs.material.files[0];
      if (!file) { this.error=(tr("请选择材料文件")); return; }
      this.busy=true; this.error=''; this.notice='';
      const form=new FormData(); form.append('file',file); form.append('kind',this.uploadKind); form.append('reference',this.uploadReference);
      try {
        const response=await (await protocolApi('/items/' + this.currentId + '/documents', {method:'POST',body:form})).json();
        this.notice=response.duplicate ? (tr("材料已存在，已复用。")) : (tr("材料已保存。"));
        this.$refs.material.value=''; this.uploadReference='';
        if (!this.dirty) await this.refreshItem();
        else { const data=await (await protocolApi('/items/'+this.currentId)).json(); this.item.documents=data.documents; }
        await this.showDocument(response.id,1); await this.loadJob();
      } catch(e) { this.error=e.message; } finally { this.busy=false; }
    },
    async runItem(extract=true) {
      if (this.dirty) { this.error=(tr("请先保存当前修改再运行")); return; }
      this.busy=true; this.error=''; this.notice='';
      try {
        await protocolApi('/items/' + this.currentId + '/run?extract=' + extract, {method:'POST'});
        this.notice=extract ? (tr("任务已提交。已有人工版本会保留，新提取结果可在版本菜单中查看。")) : (tr("正在获取已有或关联的正文 PDF。"));
        await this.refreshItem(); await this.loadJob();
      } catch(e) { this.error=e.message; } finally { this.busy=false; }
    },
    async runJob(retryOnly=false) {
      this.busy=true; this.error='';
      try {
        const result=await (await protocolApi('/jobs/'+this.jobId+'/run?retry_only='+retryOnly,{method:'POST'})).json();
        this.notice=(tr("已提交")+" ")+result.queued+(" "+tr("条记录；已有提取结果保留。"));
        await this.loadJob();
        if (this.currentId && !this.dirty) await this.refreshItem();
      } catch(e) { this.error=e.message; } finally { this.busy=false; }
    },
    addRow() {
      if (!this.draft) this.draft={outcome:'extracted',summary:'',events:[],reference_requests:[],warnings:[],blockers:[]};
      const values=Object.fromEntries(this.job.columns.map(k=>[k,'NA'])); values.GSE_id=this.item.dataset_id;
      this.draft.events.push({protocol_name:this.protocolFilter || 'Protocol 1',values,evidence:[]});
      this.draft.outcome='extracted'; this.selectedRow=this.draft.events.length-1; this.dirty=true;
    },
    removeRow(index) { this.draft.events.splice(index,1); this.selectedRow=null; this.dirty=true; },
    addEvidence() {
      this.selected().evidence.push({document_id:this.docId || this.item.documents[0]?.id || null,page:this.page,quote:''});
      this.dirty=true;
    },
    async save(reviewed=false) {
      this.busy=true; this.error=''; this.notice='';
      try {
        const result=await (await protocolApi('/items/'+this.currentId+'/revisions',{
          method:'POST',headers:{'Content-Type':'application/json'},
          body:JSON.stringify({payload:this.draft,base_revision_id:this.revisionId,
            expected_active_revision_id:this.item.active_revision_id,reviewed})
        })).json();
        this.revisionId=result.id; this.dirty=false;
        this.notice=reviewed?(tr("已保存并标记为已复核。")):(tr("修订已保存；校验结果已更新。"));
        await this.refreshItem(); await this.loadJob();
      } catch(e) { this.error=e.message; } finally { this.busy=false; }
    },
    async download(draft=false, format='tsv') {
      this.error='';
      try {
        const response=await protocolApi('/jobs/'+this.jobId+'/export?draft='+draft+'&format='+format);
        const blob=await response.blob(), url=URL.createObjectURL(blob), link=document.createElement('a');
        link.href=url; link.download='protocol_'+this.jobId+'_'+(draft?'draft':'reviewed')+'_'+format+(format==='tsv'?'.tsv':'.json');
        document.body.appendChild(link); link.click(); link.remove(); setTimeout(()=>URL.revokeObjectURL(url),1000);
      } catch(e) { this.error=e.message; }
    }
  };
}
