'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const crypto = require('node:crypto');
const { validateWorkflow, validateWorkflowStructure } = require('./harness').api;

function document(file='pipeline.py') {
  return {workflowVersion:'1.0',title:'Training',producer:{kind:'host-llm',host:'codex'},revision:{id:'r1'},request:{question:'How?',scope:'training'},phases:[{id:'train',label:'Train'}],nodes:[{id:'n1',label:'Fit',phase:'train',basis:'observed',evidence:['e1']}],edges:[],findings:[],evidence:[{id:'e1',file,line:1,endLine:1,quote:'fit()'}],coverage:{status:'scoped',summary:'entrypoint',inspectedFiles:[file],limitations:[]}};
}

test('workflow validator enforces references and a parent forest', () => {
  const value=document();
  value.nodes.push({id:'n2',label:'Loop',phase:'missing',parent:'n2',basis:'observed',evidence:['nope']});
  const result=validateWorkflowStructure(value);
  assert.equal(result.document, undefined);
  assert.match(result.issues.map(x=>x.message).join('\n'), /unknown phase|forest/);
  assert.match(result.issues.map(x=>x.path).join('\n'), /evidence/);
});

test('workflow validator checks exact source quotes and workspace containment', async () => {
  const root=fs.mkdtempSync(path.join(os.tmpdir(),'mlview-workflow-'));
  fs.writeFileSync(path.join(root,'pipeline.py'),'fit()\n');
  const valid=await validateWorkflow(document(),root);
  assert.equal(valid.issues.length,0);
  assert.deepEqual(valid.value.files,[fs.realpathSync(path.join(root,'pipeline.py'))]);
  const bad=document('../outside.py');
  bad.evidence[0].quote='wrong';
  const invalid=await validateWorkflow(bad,root);
  assert.equal(invalid.value,undefined);
  assert.match(invalid.issues.map(x=>x.message).join('\n'), /does not exist|escapes|workspace-relative/);
});

test('workflow validator resolves zero-based notebook cells', async () => {
  const root=fs.mkdtempSync(path.join(os.tmpdir(),'mlview-notebook-'));
  fs.writeFileSync(path.join(root,'flow.ipynb'),JSON.stringify({cells:[{source:['x = 1\n','fit(x)\n']}]}));
  const value=document('flow.ipynb'); value.evidence[0]={id:'e1',file:'flow.ipynb',cell:0,line:2,endLine:2,quote:'fit(x)'};
  const result=await validateWorkflow(value,root);
  assert.equal(result.issues.length,0);
});

test('workflow validator uses the open unsaved notebook cell for freshness', async () => {
  const root=fs.mkdtempSync(path.join(os.tmpdir(),'mlview-notebook-open-'));
  fs.writeFileSync(path.join(root,'flow.ipynb'),JSON.stringify({cells:[{source:['old()\n']}]}));
  const value=document('flow.ipynb'); value.evidence[0]={id:'e1',file:'flow.ipynb',cell:0,line:1,endLine:1,quote:'old()'};
  const result=await validateWorkflow(value,root,undefined,async()=> 'new()\n');
  assert.equal(result.value,undefined);
  assert.match(result.issues.map(x=>x.message).join('\n'),/does not exactly match/);
});

test('published historical source changes are stale, while a forged current quote is invalid', async () => {
  const root=fs.mkdtempSync(path.join(os.tmpdir(),'mlview-historical-'));
  const source=path.join(root,'pipeline.py');
  fs.writeFileSync(source,'fit()\n');
  const value=document();
  value.verification={files:{'pipeline.py':crypto.createHash('sha256').update('fit()\n').digest('hex')},publishedAt:'2026-09-16T12:00:00Z'};
  fs.writeFileSync(source,'changed()\n');
  const historical=await validateWorkflow(value,root);
  assert.equal(historical.issues.length,0);
  assert.deepEqual(historical.value.staleFiles,[fs.realpathSync(source)]);

  value.verification.files['pipeline.py']=crypto.createHash('sha256').update('changed()\n').digest('hex');
  const forged=await validateWorkflow(value,root);
  assert.equal(forged.value,undefined);
  assert.match(forged.issues.map(x=>x.message).join('\n'),/does not exactly match/);
});

test('a deleted file from a published snapshot remains stale and contained', async () => {
  const root=fs.mkdtempSync(path.join(os.tmpdir(),'mlview-deleted-'));
  const value=document();
  value.verification={files:{'pipeline.py':crypto.createHash('sha256').update('fit()\n').digest('hex')},publishedAt:'2026-09-16T12:00:00Z'};
  const result=await validateWorkflow(value,root);
  assert.equal(result.issues.length,0);
  assert.deepEqual(result.value.staleFiles,[path.join(fs.realpathSync(root),'pipeline.py')]);
});

test('workflow validator watches inspected files beyond direct evidence', async () => {
  const root=fs.mkdtempSync(path.join(os.tmpdir(),'mlview-inspected-'));
  fs.writeFileSync(path.join(root,'pipeline.py'),'fit()\n');
  fs.writeFileSync(path.join(root,'config.yaml'),'epochs: 3\n');
  const value=document(); value.coverage.inspectedFiles.push('config.yaml');
  const result=await validateWorkflow(value,root);
  assert.equal(result.issues.length,0);
  assert.ok(result.value.files.includes(fs.realpathSync(path.join(root,'config.yaml'))));
});

test('malformed optional and nested values are rejected without throwing', () => {
  const mutations=[
    (d)=>{d.verification=[];},
    (d)=>{d.producer=null;},
    (d)=>{d.request.extra=true;},
    (d)=>{d.nodes[0].parent=[];},
    (d)=>{d.nodes[0].basis={};},
    (d)=>{d.nodes[0].evidence={};},
    (d)=>{d.findings=[{id:'f',title:'F',message:'M',severity:'low',nodeIds:{},basis:'observed',evidence:[]}];},
    (d)=>{d.coverage.inspectedFiles=[{}];},
    (d)=>{d.coverage.limitations=[''];},
    (d)=>{d.evidence[0].file='../escape.py';},
    (d)=>{d.request.entrypoints=['bad\\path.py'];},
    (d)=>{d.nodes[0].mystery='x';}
  ];
  for(const mutate of mutations){
    const value=document();mutate(value);
    assert.doesNotThrow(()=>validateWorkflowStructure(value));
    assert.equal(validateWorkflowStructure(value).document,undefined);
  }
});
