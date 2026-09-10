
  const PROVIDER_MODELS = {
    deepseek: 'deepseek-chat', glm: 'glm-4', minimax: 'abab6.5s-chat',
    'campus-minimax': 'minimax', 'campus-glm': 'glm', orcarouter: 'orcarouter/auto', custom: ''
  };
  const PROVIDER_EFFECTIVE_URLS = {
    deepseek: 'https://api.deepseek.com/v1',
    glm: 'https://open.bigmodel.cn/api/paas/v4',
    minimax: 'https://api.minimax.chat/v1',
    'campus-minimax': 'http://10.28.0.22:30530/v1',
    'campus-glm': 'http://10.28.0.22:30530/v1',
    orcarouter: 'https://api.orcarouter.ai/v1',
    custom: ''
  };
  const ALL_PROVIDERS = [
    {value: 'deepseek', label: 'DeepSeek'},
    {value: 'glm', label: 'GLM (Zhipu)'},
    {value: 'minimax', label: 'MiniMax'},
    {value: 'campus-minimax', label: (tr("校内 MiniMax"))},
    {value: 'campus-glm', label: (tr("校内 GLM"))},
    {value: 'orcarouter', label: 'OrcaRouter'},
    {value: 'custom', label: (tr("Custom"))},
  ];

function settingsPage() {
  return {
    providerConfigs: {}, loading: true, error: '',
    savedActive: {provider:'deepseek',model:'',temperature:0.1},
    activeForm: {provider:'deepseek',model:'',temperature:0.1},
    activeSaving:false, activeSaveMsg:'', testing:false, testResult:null, testError:'',
    modal: {open:false,provider:'',base_url:'',model:'',api_key:'',saving:false,error:'',saveMsg:''},
    async init() { await this.load(); },
    providerName(id) { return ALL_PROVIDERS.find(p=>p.value===id)?.label || id; },
    hasKey(id) { return Boolean(this.providerConfigs[id]?.has_key); },
    configuredCount() { return ALL_PROVIDERS.filter(p=>this.hasKey(p.value)).length; },
    endpoint(id) { return this.providerConfigs[id]?.effective_base_url || PROVIDER_EFFECTIVE_URLS[id] || ''; },
    activeDirty() { return ['provider','model','temperature'].some(k=>this.activeForm[k]!==this.savedActive[k]); },
    async request(path, body) {
      const options=body===undefined?{}:{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)};
      const response=await fetch('/llm/'+path,options);
      if(response.status===401){window.location.href='/login';throw new Error((tr("请先登录")));}
      const data=await response.json();
      if(!response.ok)throw new Error(typeof data.detail==='string'?data.detail:(tr("保存失败，请重试")));
      return data;
    },
    async load() {
      try {
        const data=await this.request('config');this.providerConfigs=data.provider_configs || {};
        this.savedActive={provider:data.provider,model:data.model || '',temperature:data.temperature ?? 0.1};
        this.activeForm={...this.savedActive};
      }catch(e){this.error=e.message;}finally{this.loading=false;}
    },
    onActiveProviderChange() {
      const saved=this.providerConfigs[this.activeForm.provider];
      this.activeForm.model=saved?.model || PROVIDER_MODELS[this.activeForm.provider] || '';
      this.activeForm.temperature=saved?.temperature ?? 0.1;
      this.testResult=null;this.activeSaveMsg='';
    },
    openModal(provider) {
      this.modal={open:true,provider,api_key:'',base_url:this.endpoint(provider),
        model:this.providerConfigs[provider]?.model || PROVIDER_MODELS[provider] || '',saving:false,error:'',saveMsg:''};
      this.$nextTick(()=>this.$refs.apiKey.focus());
    },
    closeModal() { if(!this.modal.saving){this.modal.open=false;this.modal.api_key='';} },
    async saveModal() {
      this.modal.saving=true;this.modal.error='';this.modal.saveMsg='';
      const provider=this.modal.provider;
      const body={provider,base_url:this.modal.base_url.trim(),model:this.modal.model.trim() || PROVIDER_MODELS[provider] || '',
        temperature:this.providerConfigs[provider]?.temperature ?? 0.1};
      if(this.modal.api_key.trim())body.api_key=this.modal.api_key.trim();
      try {
        const pending=this.activeDirty(),data=await this.request('credentials',body);
        this.providerConfigs=data.provider_configs || {};this.modal.api_key='';this.modal.saveMsg=(tr("连接已保存"));
        if(this.savedActive.provider===provider){
          this.savedActive={...this.savedActive,model:body.model,temperature:body.temperature};
          if(!pending)this.activeForm={...this.savedActive};
          this.testResult=null;
        }
        if(this.activeForm.provider===provider && this.savedActive.provider!==provider)this.activeForm.model=body.model;
      }catch(e){this.modal.error=e.message;}finally{this.modal.saving=false;}
    },
    async saveActive() {
      this.activeSaving=true;this.error='';this.activeSaveMsg='';
      try{
        const data=await this.request('config',{...this.activeForm});
        this.providerConfigs=data.provider_configs || {};
        this.savedActive={provider:data.provider,model:data.model || '',temperature:data.temperature ?? 0.1};
        this.activeForm={...this.savedActive};this.activeSaveMsg=(tr("已保存，后续任务将使用此模型。"));this.testResult=null;
      }catch(e){this.error=e.message;}finally{this.activeSaving=false;}
    },
    async testConn() {
      if(this.activeDirty())return;
      this.testing=true;this.testResult=null;this.testError='';
      try{
        const response=await fetch('/llm/test',{method:'POST'}),data=await response.json();
        if(!response.ok)throw new Error(data.detail || (tr("连接失败")));
        this.testResult=data.success===true;
        if(!this.testResult)this.testError=(tr("模型返回了空响应"));
      }catch(e){this.testResult=false;this.testError=e.message;}finally{this.testing=false;}
    }
  };
}
