const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const root = path.join(__dirname, '..');
const catalog = JSON.parse(fs.readFileSync(path.join(root, 'locales/ui.json'), 'utf8'));
function environment() {
  const window = {uiLang:'en',uiMessages:Object.fromEntries(Object.entries(catalog).map(([k,v])=>[k,v.en])),
    dispatchEvent:()=>true,location:{reload(){window.reloaded=true;}}};
  const context = vm.createContext({window,document:{cookie:''},CustomEvent:class{},setTimeout:()=>{},
    fetch:async()=>{throw new Error('Network unavailable');}});
  for(const name of ['i18n.js','settings.js','protocols.js']) {
    vm.runInContext(fs.readFileSync(path.join(root,'static',name),'utf8'),context);
  }
  return context;
}
function settings(c) {
  const p=vm.runInContext('settingsPage()',c);
  p.$nextTick=callback=>callback();p.$refs={apiKey:{focus(){}}};
  p.savedActive={provider:'deepseek',model:'deepseek_pro',temperature:0};
  p.activeForm={...p.savedActive};
  p.providerConfigs={deepseek:{has_key:true,model:'deepseek_pro',effective_base_url:'https://hpc.example.org/v1',temperature:0}};
  return p;
}
test('language preference persists, respects cancellation and ignores invalid values',()=>{
  const c=environment();
  vm.runInContext("setUiLanguage('xx')",c);assert.equal(c.document.cookie,'');
  c.window.dispatchEvent=()=>false;
  vm.runInContext("setUiLanguage('zh')",c);assert.equal(c.document.cookie,'');
  c.window.dispatchEvent=()=>true;
  vm.runInContext("setUiLanguage('zh')",c);assert.match(c.document.cookie,/geo_ui_lang=zh; Path=\//);assert.equal(c.window.reloaded,true);
});
test('translation preserves research content, interpolates counts and explains validation',()=>{
  const c=environment();
  assert.equal(vm.runInContext("tr('用户方案 CHIR99021 3 uM')",c),'用户方案 CHIR99021 3 uM');
  assert.equal(vm.runInContext("tr('已识别 {count} 个 GSE ID：',{count:4})",c),'Recognized 4 GSE IDs: ');
  assert.equal(vm.runInContext("tr('第 2 行：dose_unit 缺失')",c),'Row 2: dose_unit is missing');
  assert.equal(vm.runInContext("tr('无法标记已复核：第 1 行：结束时间早于开始时间')",c),'Cannot mark reviewed: Row 1: End time is earlier than start time');
});
test('pending provider selection cannot test or change the active model',async()=>{
  const c=environment(),p=settings(c);let requested=false;c.fetch=async()=>{requested=true;};
  p.activeForm.provider='orcarouter';p.onActiveProviderChange();await p.testConn();
  assert.equal(p.savedActive.provider,'deepseek');assert.equal(p.activeForm.model,'orcarouter/auto');assert.equal(p.activeDirty(),true);assert.equal(requested,false);
});
test('saving another provider retains the active model and clears the entered key',async()=>{
  const c=environment(),p=settings(c);p.openModal('orcarouter');p.modal.api_key='test-only';
  c.fetch=async(url,options)=>{
    assert.equal(url,'/llm/credentials');const body=JSON.parse(options.body);
    assert.equal(body.base_url,'https://api.orcarouter.ai/v1');
    return {ok:true,json:async()=>({provider_configs:{...p.providerConfigs,orcarouter:{has_key:true,model:body.model}}})};
  };
  await p.saveModal();assert.equal(p.savedActive.provider,'deepseek');assert.equal(p.modal.api_key,'');assert.equal(p.modal.saving,false);
});
test('network failures release saving states and remain visible',async()=>{
  const c=environment(),p=settings(c);p.openModal('deepseek');
  assert.equal(p.modal.base_url,'https://hpc.example.org/v1');
  await p.saveModal();assert.equal(p.modal.saving,false);assert.equal(p.modal.error,'Network unavailable');
  await p.saveActive();assert.equal(p.activeSaving,false);assert.equal(p.error,'Network unavailable');
  await p.testConn();assert.equal(p.testing,false);assert.equal(p.testResult,false);
});
test('a response without content is not reported as connected',async()=>{
  const c=environment(),p=settings(c);c.fetch=async()=>({ok:true,json:async()=>({success:false})});
  await p.testConn();assert.equal(p.testResult,false);assert.ok(p.testError);
});
test('late protocol refresh cannot overwrite a newly edited draft',async()=>{
  const c=environment(),p=vm.runInContext('protocolDetail(1)',c);
  p.currentId=1;p.draft={summary:'unsaved'};
  c.fetch=async()=>({ok:true,json:async()=>{p.dirty=true;return {revisions:[],documents:[]};}});
  await p.refreshItem();assert.equal(p.draft.summary,'unsaved');
});
