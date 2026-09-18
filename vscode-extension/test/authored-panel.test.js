'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const crypto = require('node:crypto');
const { api, vscode } = require('./harness');

const fixtures = [];
test.afterEach(() => {
  for (const fixture of fixtures.splice(0)) {
    try { fixture.controller?.dispose(); }
    finally { fs.rmSync(fixture.root, {recursive:true, force:true}); }
  }
});

const tick = () => new Promise((resolve) => setImmediate(resolve));
function manualTimers() {
  let next=0;
  const callbacks=new Map();
  return {
    api:{set(callback){const id=++next;callbacks.set(id,callback);return id;},clear(id){callbacks.delete(id);}},
    fire(){const pending=[...callbacks.values()];callbacks.clear();for(const callback of pending)callback();},
    get size(){return callbacks.size;}
  };
}
function context() {
  const extensionPath=path.join(__dirname,'..');
  return {extensionPath,extensionUri:vscode.Uri.file(extensionPath),subscriptions:[]};
}
function log() { return {info(){},warn(){},error(){},dispose(){}}; }
function workflow(file='source.py') {
  return {workflowVersion:'1.0',title:'Authored',producer:{kind:'host-llm',host:'codex'},revision:{id:'r1'},request:{question:'Explain training',scope:'training',entrypoints:['train.py'],configuration:'config=fast'},phases:[{id:'p',label:'Train'}],nodes:[{id:'n',label:'Fit',phase:'p',basis:'observed',evidence:['e']},{id:'out',label:'Weights',phase:'p',basis:'inferred',evidence:[]}],edges:[{id:'flow',source:'n',target:'out',label:'produces',basis:'inferred',evidence:['e']}],findings:[{id:'risk',title:'Unverified output',message:'Output needs checking',severity:'medium',nodeIds:['out'],edgeIds:['flow'],basis:'inferred',evidence:['e'],counterEvidence:[]}],evidence:[{id:'e',file,line:1,endLine:1,quote:'fit()'}],coverage:{status:'scoped',summary:'source',inspectedFiles:[file],limitations:[]}};
}
function publishedWorkflow() {
  const value=workflow();
  value.verification={files:{'source.py':crypto.createHash('sha256').update('fit()\n').digest('hex')},publishedAt:'2026-09-16T12:00:00Z'};
  return value;
}
function setup(raw, validator) {
  vscode.__reset();
  const root=fs.mkdtempSync(path.join(os.tmpdir(),'mlview-panel-'));
  const fixture={root};
  fixtures.push(fixture);
  fs.writeFileSync(path.join(root,'source.py'),'fit()\n');
  vscode.__setDocument(path.join(root,'source.py'),'fit()\n');
  const artifact=path.join(root,'run.mlview.json');
  fs.writeFileSync(artifact,typeof raw==='string'?raw:JSON.stringify(raw));
  vscode.__setWorkspaceFolders([root]);
  const controller=new api.AuthoredDiagramController(context(),log(),validator);
  fixture.controller=controller;
  controller.register();
  return {root,artifact,controller};
}

test('authored panel opens, handshakes, and posts a validated workflow without legacy analysis', async () => {
  const {artifact,controller}=setup(workflow());
  await controller.open(vscode.Uri.file(artifact));
  const panel=vscode.__recorded.panels.at(-1);
  panel.fire({v:1,type:'ready'}); await tick();
  assert.deepEqual(panel.postedTypes(),['init','workflow']);
  assert.deepEqual(panel.posted[0].capabilities,{
    canOpenSource:true,
    canReanalyze:false,
    canExport:false,
    canAskAssistant:false,
    canRefine:true
  });
  assert.equal(panel.posted[1].document.revision.id,'r1');
  panel.fire({v:1,type:'openLocation',evidenceId:'e'});await new Promise((resolve)=>setTimeout(resolve,20));
  assert.equal(vscode.__recorded.shownDocuments.at(-1).document.uri.fsPath,path.join(path.dirname(artifact),'source.py'));
  controller.dispose();
});

test('initial malformed artifact reports an error after ready instead of leaving a blank panel', async () => {
  const {artifact,controller}=setup('{bad json');
  await controller.open(vscode.Uri.file(artifact));
  const panel=vscode.__recorded.panels.at(-1);
  panel.fire({v:1,type:'ready'}); await tick();
  assert.deepEqual(panel.postedTypes(),['init','workflowError']);
  assert.match(panel.posted[1].message,/nothing valid can be displayed/);
  controller.dispose();
});

test('same revision content replacement is rejected and the prior workflow stays displayed', async () => {
  const {artifact,controller}=setup(workflow());
  await controller.open(vscode.Uri.file(artifact));
  const panel=vscode.__recorded.panels.at(-1);panel.fire({v:1,type:'ready'});await tick();
  const changed=workflow();changed.title='Silently changed';fs.writeFileSync(artifact,JSON.stringify(changed));
  await controller.open(vscode.Uri.file(artifact));
  assert.equal(panel.posted.filter(x=>x.type==='workflow').length,1);
  assert.match(panel.posted.at(-1).message,/without a new revision id/);
  controller.dispose();
});

test('panel restore reloads the saved artifact without invoking analysis', async () => {
  const {artifact,controller}=setup(workflow());
  const panel=vscode.window.createWebviewPanel('mlview.authoredDiagram','restored',{},{});
  const serializer=vscode.__recorded.serializers.get('mlview.authoredDiagram');
  await serializer.deserializeWebviewPanel(panel,{artifact});
  assert.equal(panel.webview.options.enableScripts,true);
  assert.equal(panel.webview.options.localResourceRoots.length,1);
  panel.fire({v:1,type:'ready'});await tick();
  assert.equal(panel.posted.find(x=>x.type==='workflow').document.title,'Authored');
  controller.dispose();
});

test('initial and restored historical artifacts stay visible when cited source changed', async () => {
  const {root,artifact,controller}=setup(publishedWorkflow());
  fs.writeFileSync(path.join(root,'source.py'),'changed()\n');
  vscode.__setDocument(path.join(root,'source.py'),'changed()\n');
  await controller.open(vscode.Uri.file(artifact));
  const opened=vscode.__recorded.panels.at(-1);opened.fire({v:1,type:'ready'});await tick();
  assert.ok(opened.posted.find(x=>x.type==='workflow'));
  assert.match(opened.posted.find(x=>x.type==='workflowError').message,/historical diagram is visible/);
  opened.fire({v:1,type:'openLocation',evidenceId:'e'});await new Promise((resolve)=>setTimeout(resolve,20));
  assert.equal(vscode.__recorded.shownDocuments.length,0);

  const restored=vscode.window.createWebviewPanel('mlview.authoredDiagram','restored',{},{});
  const serializer=vscode.__recorded.serializers.get('mlview.authoredDiagram');
  await serializer.deserializeWebviewPanel(restored,{artifact});
  restored.fire({v:1,type:'ready'});await tick();
  assert.ok(restored.posted.find(x=>x.type==='workflow'));
  assert.match(restored.posted.find(x=>x.type==='workflowError').message,/historical diagram is visible/);
  controller.dispose();
});

test('out-of-order reload completion can only adopt the newest generation', async () => {
  const gate=new api.ReloadGeneration();
  const adopted=[];
  let releaseOld;
  const old=new Promise((resolve)=>{releaseOld=resolve;}).then(()=>{if(gate.isCurrent(first))adopted.push('old');});
  const first=gate.begin();
  const second=gate.begin();
  if(gate.isCurrent(second))adopted.push('new');
  releaseOld();await old;
  assert.deepEqual(adopted,['new']);
});

test('validation scheduler debounces typing bursts into one run', async () => {
  const timers=manualTimers();
  let runs=0;
  const scheduler=new api.ValidationScheduler(async()=>{runs++;},120,timers.api);
  scheduler.debounce();scheduler.debounce();scheduler.debounce();
  assert.equal(timers.size,1);
  timers.fire();await tick();
  assert.equal(runs,1);
  scheduler.dispose();
});

test('validation scheduler permits one active run and coalesces overlapping events', async () => {
  const timers=manualTimers();
  let runs=0,active=0,maxActive=0,release;
  const firstGate=new Promise(resolve=>{release=resolve;});
  const scheduler=new api.ValidationScheduler(async()=>{
    runs++;active++;maxActive=Math.max(maxActive,active);
    if(runs===1)await firstGate;
    active--;
  },120,timers.api);
  const completed=scheduler.immediate();await tick();
  scheduler.debounce();scheduler.debounce();timers.fire();await tick();
  assert.equal(runs,1);
  release();await completed;
  assert.equal(runs,2);
  assert.equal(maxActive,1);
  scheduler.dispose();
});

test('validation scheduler cancels pending and queued work on disposal', async () => {
  const timers=manualTimers();
  let runs=0,release;
  const gate=new Promise(resolve=>{release=resolve;});
  const scheduler=new api.ValidationScheduler(async()=>{runs++;await gate;},120,timers.api);
  const completed=scheduler.immediate();await tick();
  scheduler.debounce();timers.fire();
  scheduler.dispose();release();await completed;await tick();
  assert.equal(runs,1);
  scheduler.debounce();timers.fire();await tick();
  assert.equal(runs,1);
});

test('immediate completion waits for a newer debounce timer and its work', async () => {
  const timers=manualTimers();
  let runs=0,release;
  const gate=new Promise(resolve=>{release=resolve;});
  const scheduler=new api.ValidationScheduler(async()=>{runs++;if(runs===1)await gate;},120,timers.api);
  let completed=false;
  const completion=scheduler.immediate().then(()=>{completed=true;});
  await tick();
  scheduler.debounce();
  release();await tick();
  assert.equal(completed,false,'a pending debounce is part of reload completion');
  assert.equal(runs,1);
  timers.fire();await completion;
  assert.equal(runs,2);
  scheduler.dispose();
});

test('validation scheduler reports work rejection without stranding waiters', async () => {
  const errors=[];
  const scheduler=new api.ValidationScheduler(async()=>{throw new Error('validator exploded');},0,undefined,error=>errors.push(error));
  await scheduler.immediate();
  assert.equal(errors.length,1);
  assert.match(String(errors[0]),/validator exploded/);
  scheduler.dispose();
});

test('source save rejects stale evidence, then a child revision clears the error', async () => {
  const {artifact,controller}=setup(workflow());
  await controller.open(vscode.Uri.file(artifact));
  const panel=vscode.__recorded.panels.at(-1);panel.fire({v:1,type:'ready'});await tick();
  fs.writeFileSync(path.join(path.dirname(artifact),'source.py'),'changed()\n');
  vscode.__setDocument(path.join(path.dirname(artifact),'source.py'),'changed()\n');
  for(const listener of vscode.__recorded.saveListeners)listener(await vscode.workspace.openTextDocument(vscode.Uri.file(path.join(path.dirname(artifact),'source.py'))));
  await new Promise((resolve)=>setTimeout(resolve,180));
  assert.match(panel.posted.at(-1).message,/retaining the last valid revision/);
  fs.writeFileSync(path.join(path.dirname(artifact),'source.py'),'fit()\n');
  vscode.__setDocument(path.join(path.dirname(artifact),'source.py'),'fit()\n');
  const next=workflow();next.revision={id:'r2',parent:'r1'};fs.writeFileSync(artifact,JSON.stringify(next));
  await controller.open(vscode.Uri.file(artifact));
  assert.equal(panel.posted.filter(x=>x.type==='workflow').at(-1).document.revision.id,'r2');
  assert.equal(panel.posted.at(-2).type,'workflowError');
  assert.equal(panel.posted.at(-2).message,'');
  controller.dispose();
});

test('notebook save events invalidate dependent artifacts', async () => {
  const {root,artifact,controller}=setup(workflow());
  await controller.open(vscode.Uri.file(artifact));
  const panel=vscode.__recorded.panels.at(-1);panel.fire({v:1,type:'ready'});await tick();
  const dependent={uri:vscode.Uri.file(path.join(root,'source.py'))};
  for(const listener of vscode.__recorded.notebookSaveListeners)listener(dependent);
  assert.match(panel.posted.at(-1).message,/checking diagram freshness/);
  await new Promise(resolve=>setTimeout(resolve,180));
  controller.dispose();
});

test('artifact and source event bursts show pending freshness once and recover after a failed revision', async () => {
  const {root,artifact,controller}=setup(workflow());
  await controller.open(vscode.Uri.file(artifact));
  const panel=vscode.__recorded.panels.at(-1);panel.fire({v:1,type:'ready'});await tick();
  const source=await vscode.workspace.openTextDocument(vscode.Uri.file(path.join(root,'source.py')));
  for(const listener of vscode.__recorded.changeListeners)listener({document:source});
  for(const listener of vscode.__recorded.saveListeners)listener(source);
  for(const listener of vscode.__recorded.changeListeners)listener({document:source});
  assert.equal(panel.posted.filter(x=>x.type==='workflowError'&&/checking diagram freshness/.test(x.message)).length,1);
  fs.writeFileSync(artifact,'{"workflowVersion":');
  for(const listener of vscode.__recorded.saveListeners)listener(await vscode.workspace.openTextDocument(vscode.Uri.file(artifact)));
  await new Promise(resolve=>setTimeout(resolve,180));
  assert.match(panel.posted.at(-1).message,/JSON parse error/);
  const next=workflow();next.revision={id:'r2',parent:'r1'};
  fs.writeFileSync(artifact,JSON.stringify(next));
  vscode.__setDocument(artifact,JSON.stringify(next));
  for(const listener of vscode.__recorded.saveListeners)listener(await vscode.workspace.openTextDocument(vscode.Uri.file(artifact)));
  await new Promise(resolve=>setTimeout(resolve,180));
  assert.equal(panel.posted.filter(x=>x.type==='workflow').at(-1).document.revision.id,'r2');
  assert.equal(panel.posted.at(-2).message,'');
  controller.dispose();
});

test('a source event invalidates an active result until the coalesced newest rerun completes', async () => {
  const gates=[];
  const starts=[];
  let calls=0;
  const validator=async(...args)=>{
    calls++;
    if(calls>1) {
      let release,started;
      const waiting=new Promise(resolve=>{release=resolve;});
      const announced=new Promise(resolve=>{started=resolve;});
      gates.push(release);starts.push(announced);started();await waiting;
    }
    return api.validateWorkflow(...args);
  };
  const {root,artifact,controller}=setup(workflow(),validator);
  await controller.open(vscode.Uri.file(artifact));
  const panel=vscode.__recorded.panels.at(-1);panel.fire({v:1,type:'ready'});await tick();
  const source=await vscode.workspace.openTextDocument(vscode.Uri.file(path.join(root,'source.py')));
  for(const listener of vscode.__recorded.changeListeners)listener({document:source});
  await new Promise(resolve=>setTimeout(resolve,140));await starts[0];
  for(const listener of vscode.__recorded.saveListeners)listener(source);
  await new Promise(resolve=>setTimeout(resolve,140));
  gates[0]();
  while(starts.length<2)await tick();
  await starts[1];
  assert.equal(panel.posted.filter(x=>x.type==='workflow').length,1);
  assert.match(panel.posted.at(-1).message,/checking diagram freshness/);
  gates[1]();await new Promise(resolve=>setTimeout(resolve,20));
  assert.equal(panel.posted.filter(x=>x.type==='workflow').length,2);
  controller.dispose();
});

test('navigation validation cannot open a source after panel disposal', async () => {
  let release,started;
  const gate=new Promise(resolve=>{release=resolve;});
  const began=new Promise(resolve=>{started=resolve;});
  let calls=0;
  const validator=async(...args)=>{calls++;if(calls===2){started();await gate;}return api.validateWorkflow(...args);};
  const {artifact,controller}=setup(workflow(),validator);
  await controller.open(vscode.Uri.file(artifact));
  const panel=vscode.__recorded.panels.at(-1);panel.fire({v:1,type:'ready'});await tick();
  panel.fire({v:1,type:'openLocation',evidenceId:'e'});await began;
  panel.dispose();release();await new Promise(resolve=>setTimeout(resolve,20));
  assert.equal(vscode.__recorded.shownDocuments.length,0);
  controller.dispose();
});

test('awaited document open cannot navigate after panel disposal', async () => {
  const {artifact,controller}=setup(workflow());
  await controller.open(vscode.Uri.file(artifact));
  const panel=vscode.__recorded.panels.at(-1);panel.fire({v:1,type:'ready'});await tick();
  const original=vscode.workspace.openTextDocument;
  let release,started;
  const gate=new Promise(resolve=>{release=resolve;});
  const began=new Promise(resolve=>{started=resolve;});
  vscode.workspace.openTextDocument=async uri=>{started();await gate;return original(uri);};
  try {
    panel.fire({v:1,type:'openLocation',evidenceId:'e'});await began;
    panel.dispose();release();await new Promise(resolve=>setTimeout(resolve,20));
    assert.equal(vscode.__recorded.shownDocuments.length,0);
  } finally {
    vscode.workspace.openTextDocument=original;
    controller.dispose();
  }
});

test('refine action copies a bounded prompt for the displayed revision', async () => {
  const {artifact,controller}=setup(workflow());
  await controller.open(vscode.Uri.file(artifact));
  const panel=vscode.__recorded.panels.at(-1);panel.fire({v:1,type:'ready'});await tick();
  panel.fire({v:1,type:'refineWorkflow',revisionId:'r1',intent:'explain',question:'ignored',scope:'ignored'});await tick();
  assert.equal(vscode.__recorded.clipboardWrites.length,1);
  assert.match(vscode.__recorded.clipboardWrites[0],/parent is r1/);
  assert.match(vscode.__recorded.clipboardWrites[0],/Selected entrypoints: train.py/);
  assert.match(vscode.__recorded.clipboardWrites[0],/Selected configuration: config=fast/);
  assert.doesNotMatch(vscode.__recorded.clipboardWrites[0],/ignored/);
  controller.dispose();
});

test('selection refinement resolves trusted node, edge, and finding context from the document', async () => {
  const {artifact,controller}=setup(workflow());
  await controller.open(vscode.Uri.file(artifact));
  const panel=vscode.__recorded.panels.at(-1);panel.fire({v:1,type:'ready'});await tick();
  for (const [selection, expected] of [
    [{kind:'node',id:'n',label:'injected'},/node n \(Fit\); basis observed; evidence e/],
    [{kind:'edge',id:'flow',label:'injected'},/edge flow \(Fit -> Weights, produces\); basis inferred/],
    [{kind:'issue',id:'risk',title:'injected'},/finding risk \(Unverified output\); basis inferred/]
  ]) {
    panel.fire({v:1,type:'refineWorkflow',revisionId:'r1',selection,intent:'challenge'});await tick();
    assert.match(vscode.__recorded.clipboardWrites.at(-1),expected);
    assert.doesNotMatch(vscode.__recorded.clipboardWrites.at(-1),/injected/);
    assert.match(vscode.__recorded.clipboardWrites.at(-1),/Preserve every unaffected stable phase, node, edge, finding, and evidence ID/);
  }
  controller.dispose();
});

test('selection refinement bounds document-owned ID lists in the copied prompt', async () => {
  const document=workflow();
  const extra=Array.from({length:30},(_,i)=>i);
  document.nodes.push(...extra.map(i=>({id:`out-${i}`,label:`Output ${i}`,phase:'p',basis:'inferred',evidence:[]})));
  document.edges.push(...extra.map(i=>({id:`flow-${i}`,source:'n',target:`out-${i}`,label:'produces',basis:'inferred',evidence:[]})));
  document.evidence.push(...extra.map(i=>({id:`e-${i}`,file:'source.py',line:1,endLine:1,quote:'fit()'})));
  document.findings[0].nodeIds=extra.map(i=>`out-${i}`);
  document.findings[0].edgeIds=extra.map(i=>`flow-${i}`);
  document.findings[0].evidence=extra.map(i=>`e-${i}`);
  document.findings[0].counterEvidence=extra.map(i=>`e-${i}`);
  const {artifact,controller}=setup(document);
  await controller.open(vscode.Uri.file(artifact));
  const panel=vscode.__recorded.panels.at(-1);panel.fire({v:1,type:'ready'});await tick();
  panel.fire({v:1,type:'refineWorkflow',revisionId:'r1',selection:{kind:'issue',id:'risk'},intent:'challenge'});await tick();
  const prompt=vscode.__recorded.clipboardWrites.at(-1);
  assert.match(prompt,/out-0, out-1, out-2, out-3, out-4, out-5, out-6, out-7, and 22 more/);
  assert.match(prompt,/stable finding ID risk/);
  controller.dispose();
});

test('refinement rejects stale revisions and missing selected IDs clearly', async () => {
  const {artifact,controller}=setup(workflow());
  await controller.open(vscode.Uri.file(artifact));
  const panel=vscode.__recorded.panels.at(-1);panel.fire({v:1,type:'ready'});await tick();
  panel.fire({v:1,type:'refineWorkflow',revisionId:'old',intent:'trace'});await tick();
  for (const kind of ['node','edge','issue']) {
    panel.fire({v:1,type:'refineWorkflow',revisionId:'r1',selection:{kind,id:'missing'},intent:'trace'});await tick();
    assert.match(vscode.__recorded.messages.at(-1)[1],new RegExp(`selected ${kind === 'issue' ? 'finding' : kind} missing is no longer`));
  }
  assert.equal(vscode.__recorded.clipboardWrites.length,0);
  assert.match(vscode.__recorded.messages.at(-4)[1],/stale/);
  controller.dispose();
});

test('authored exportFile uses the guarded SVG save path', async () => {
  const {artifact,controller}=setup(workflow());
  await controller.open(vscode.Uri.file(artifact));
  const panel=vscode.__recorded.panels.at(-1);panel.fire({v:1,type:'ready'});await tick();
  const target=vscode.Uri.file(path.join(path.dirname(artifact),'diagram.svg'));
  vscode.__answerSaveDialog(target);
  const svg=Buffer.from('<svg xmlns="http://www.w3.org/2000/svg"></svg>').toString('base64');
  panel.fire({v:1,type:'exportFile',kind:'svg',data:svg,base64:svg,name:'diagram.svg',suggestedName:'diagram.svg',scope:'all'});await tick();
  assert.equal(vscode.__recorded.writtenFiles.at(-1).fsPath,target.fsPath);
  controller.dispose();
});

test('remote authored artifact is refused before a panel is created', async () => {
  vscode.__reset();
  const controller=new api.AuthoredDiagramController(context(),log());controller.register();
  const remote=new vscode.Uri('/workspace/run.mlview.json','vscode-remote');
  await controller.open(remote);
  assert.equal(vscode.__recorded.panels.length,0);
  assert.match(vscode.__recorded.messages.at(-1)[1],/local file workspace/);
  controller.dispose();
});
