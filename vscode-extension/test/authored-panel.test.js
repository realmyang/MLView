'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const crypto = require('node:crypto');
const { api, vscode } = require('./harness');

const tick = () => new Promise((resolve) => setImmediate(resolve));
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
function setup(raw) {
  vscode.__reset();
  const root=fs.mkdtempSync(path.join(os.tmpdir(),'mlview-panel-'));
  fs.writeFileSync(path.join(root,'source.py'),'fit()\n');
  vscode.__setDocument(path.join(root,'source.py'),'fit()\n');
  const artifact=path.join(root,'run.mlview.json');
  fs.writeFileSync(artifact,typeof raw==='string'?raw:JSON.stringify(raw));
  vscode.__setWorkspaceFolders([root]);
  const controller=new api.AuthoredDiagramController(context(),log());
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

test('source save rejects stale evidence, then a child revision clears the error', async () => {
  const {artifact,controller}=setup(workflow());
  await controller.open(vscode.Uri.file(artifact));
  const panel=vscode.__recorded.panels.at(-1);panel.fire({v:1,type:'ready'});await tick();
  fs.writeFileSync(path.join(path.dirname(artifact),'source.py'),'changed()\n');
  vscode.__setDocument(path.join(path.dirname(artifact),'source.py'),'changed()\n');
  for(const listener of vscode.__recorded.saveListeners)listener(await vscode.workspace.openTextDocument(vscode.Uri.file(path.join(path.dirname(artifact),'source.py'))));
  await new Promise((resolve)=>setTimeout(resolve,25));
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
