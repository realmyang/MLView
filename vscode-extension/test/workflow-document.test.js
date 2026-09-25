'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const crypto = require('node:crypto');
const { validateWorkflow, validateWorkflowStructure } = require('./harness').api;

const fixtures = [];
test.afterEach(() => {
  for (const root of fixtures.splice(0)) {
    fs.rmSync(root, {recursive:true, force:true});
  }
});

function fixture(prefix) {
  const root=fs.mkdtempSync(path.join(os.tmpdir(),prefix));
  fixtures.push(root);
  return root;
}

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

test('workflow parent validation handles a maximum-depth chain and cycle iteratively', () => {
  const valid=document();
  valid.nodes=Array.from({length:2000},(_,i)=>({id:`n${i}`,label:`Node ${i}`,phase:'train',...(i?{parent:`n${i-1}`}:{}),basis:'inferred',evidence:[]}));
  valid.nodes.at(-1).basis='unresolved';
  assert.doesNotThrow(()=>validateWorkflowStructure(valid));
  assert.ok(validateWorkflowStructure(valid).document);
  valid.nodes[0].parent='n1999';
  const cyclic=validateWorkflowStructure(valid);
  assert.equal(cyclic.document,undefined);
  assert.match(cyclic.issues.map(x=>x.message).join('\n'),/forest/);
});

test('claims without evidence require unresolved basis except conceptual parent nodes', () => {
  const value=document();
  value.nodes=[
    {id:'parent',label:'Conceptual group',phase:'train',basis:'inferred',evidence:[]},
    {id:'child',label:'Leaf',phase:'train',parent:'parent',basis:'observed',evidence:[]},
    {id:'unknown',label:'Unknown leaf',phase:'train',basis:'unresolved',evidence:[]}
  ];
  value.edges=[
    {id:'unsupported-edge',source:'child',target:'unknown',label:'flows',basis:'inferred',evidence:[]},
    {id:'unknown-edge',source:'unknown',target:'child',label:'may flow',basis:'unresolved',evidence:[]}
  ];
  value.findings=[
    {id:'unsupported-finding',title:'Claim',message:'Unsupported',severity:'low',nodeIds:['child'],basis:'observed',evidence:[]},
    {id:'unknown-finding',title:'Unknown',message:'Unresolved',severity:'low',nodeIds:['unknown'],basis:'unresolved',evidence:[]}
  ];
  value.evidence=[];
  const result=validateWorkflowStructure(value);
  assert.equal(result.document,undefined);
  assert.deepEqual(result.issues.filter(issue=>issue.message.startsWith('empty evidence')).map(issue=>issue.path),[
    '$.nodes[1].evidence',
    '$.edges[0].evidence',
    '$.findings[0].evidence'
  ]);
});

test('workflow validator checks exact source quotes and workspace containment', async () => {
  const root=fixture('mlview-workflow-');
  fs.writeFileSync(path.join(root,'pipeline.py'),'fit()\n');
  const valid=await validateWorkflow(document(),root);
  assert.equal(valid.issues.length,0);
  assert.deepEqual(valid.value.files,[await fs.promises.realpath(path.join(root,'pipeline.py'))]);
  const bad=document('../outside.py');
  bad.evidence[0].quote='wrong';
  const invalid=await validateWorkflow(bad,root);
  assert.equal(invalid.value,undefined);
  assert.match(invalid.issues.map(x=>x.message).join('\n'), /does not exist|escapes|workspace-relative/);
});

test('workflow validator resolves zero-based notebook cells', async () => {
  const root=fixture('mlview-notebook-');
  fs.writeFileSync(path.join(root,'flow.ipynb'),JSON.stringify({cells:[{source:['x = 1\n','fit(x)\n']}]}));
  const value=document('flow.ipynb'); value.evidence[0]={id:'e1',file:'flow.ipynb',cell:0,line:2,endLine:2,quote:'fit(x)'};
  const result=await validateWorkflow(value,root);
  assert.equal(result.issues.length,0);
});

test('workflow validator decides notebook evidence from the cell on disk, never an open buffer', async () => {
  const root=fixture('mlview-notebook-open-');
  fs.writeFileSync(path.join(root,'flow.ipynb'),JSON.stringify({cells:[{source:['old()\n']}]}));
  const value=document('flow.ipynb'); value.evidence[0]={id:'e1',file:'flow.ipynb',cell:0,line:1,endLine:1,quote:'old()'};
  // A fourth argument (the retired open-cell reader) is ignored.
  const result=await validateWorkflow(value,root,undefined,async()=> 'new()\n');
  assert.equal(result.issues.length,0);
  assert.ok(result.value);
  value.evidence[0].cell=3;
  const missing=await validateWorkflow(value,root);
  assert.deepEqual(missing.issues.map(x=>x.path),['$.evidence[0].cell']);
});

test('published historical source changes are stale, while a forged current quote is invalid', async () => {
  const root=fixture('mlview-historical-');
  const source=path.join(root,'pipeline.py');
  fs.writeFileSync(source,'fit()\n');
  const value=document();
  value.verification={files:{'pipeline.py':crypto.createHash('sha256').update('fit()\n').digest('hex')},publishedAt:'2026-09-16T12:00:00Z'};
  fs.writeFileSync(source,'changed()\n');
  const historical=await validateWorkflow(value,root);
  assert.equal(historical.issues.length,0);
  assert.deepEqual(historical.value.staleFiles,[await fs.promises.realpath(source)]);

  value.verification.files['pipeline.py']=crypto.createHash('sha256').update('changed()\n').digest('hex');
  const forged=await validateWorkflow(value,root);
  assert.equal(forged.value,undefined);
  assert.match(forged.issues.map(x=>x.message).join('\n'),/does not exactly match/);
});

test('a deleted file from a published snapshot remains stale and contained', async () => {
  const root=fixture('mlview-deleted-');
  const value=document();
  value.verification={files:{'pipeline.py':crypto.createHash('sha256').update('fit()\n').digest('hex')},publishedAt:'2026-09-16T12:00:00Z'};
  const result=await validateWorkflow(value,root);
  assert.equal(result.issues.length,0);
  assert.deepEqual(result.value.staleFiles,[path.join(await fs.promises.realpath(root),'pipeline.py')]);
});

test('workflow validator watches inspected files beyond direct evidence', async () => {
  const root=fixture('mlview-inspected-');
  fs.writeFileSync(path.join(root,'pipeline.py'),'fit()\n');
  fs.writeFileSync(path.join(root,'config.yaml'),'epochs: 3\n');
  const value=document(); value.coverage.inspectedFiles.push('config.yaml');
  const result=await validateWorkflow(value,root);
  assert.equal(result.issues.length,0);
  assert.ok(result.value.files.includes(await fs.promises.realpath(path.join(root,'config.yaml'))));
});

test('workflow validator reads a multiply-cited source once', async () => {
  const root=fixture('mlview-workflow-cache-');
  const source=path.join(root,'pipeline.py');
  fs.writeFileSync(source,'fit()\n');
  const value=document();
  value.evidence.push({id:'e2',file:'pipeline.py',line:1,endLine:1,quote:'fit()'});
  value.nodes[0].evidence.push('e2');
  value.verification={files:{'pipeline.py':crypto.createHash('sha256').update('fit()\n').digest('hex')},publishedAt:'2026-09-16T12:00:00Z'};
  let reads=0;
  const result=await validateWorkflow(value,root,{readBytes:async (file,limit)=>{reads++;assert.equal(limit,8*1024*1024);return fs.promises.readFile(file);}});
  assert.equal(result.issues.length,0);
  assert.equal(reads,1);
});

const sha=(bytes)=>crypto.createHash('sha256').update(bytes).digest('hex');
const published=(value,files)=>{value.verification={files:Object.fromEntries(Object.entries(files).map(([rel,bytes])=>[rel,sha(bytes)])),publishedAt:'2026-09-25T00:00:00Z'};return value;};

test('sources are hashed as raw bytes: CRLF, BOM and Latin-1 files match the helper digest', async () => {
  const root=fixture('mlview-raw-hash-');
  const crlf=Buffer.from('fit()\r\nstep()\r\n');
  const bom=Buffer.concat([Buffer.from([0xef,0xbb,0xbf]),Buffer.from('import torch\n')]);
  const latin1=Buffer.from([0x6e,0x61,0x6d,0x65,0x3d,0x63,0x61,0x66,0xe9,0x0a]);
  fs.writeFileSync(path.join(root,'pipeline.py'),crlf);
  fs.writeFileSync(path.join(root,'bom.py'),bom);
  fs.writeFileSync(path.join(root,'config.cfg'),latin1);
  const value=document();
  value.evidence.push({id:'e2',file:'bom.py',line:1,endLine:1,quote:'import torch'});
  value.nodes[0].evidence.push('e2');
  value.coverage.inspectedFiles.push('bom.py','config.cfg');
  published(value,{'pipeline.py':crlf,'bom.py':bom,'config.cfg':latin1});
  const result=await validateWorkflow(value,root);
  assert.deepEqual(result.issues,[]);
  assert.deepEqual(result.value.stale,[]);
  assert.deepEqual(result.value.fingerprints,{'bom.py':sha(bom),'config.cfg':sha(latin1),'pipeline.py':sha(crlf)});
  // Unverified, the Latin-1 inspected file is fingerprinted without being decoded.
  delete value.verification;
  const draft=await validateWorkflow(value,root);
  assert.deepEqual(draft.issues,[]);
  assert.equal(draft.value.fingerprints['config.cfg'],sha(latin1));
});

test('a line-1 quote may include or omit the byte-order mark', async () => {
  const root=fixture('mlview-bom-');
  fs.writeFileSync(path.join(root,'bom.py'),Buffer.concat([Buffer.from([0xef,0xbb,0xbf]),Buffer.from('import torch\nfit()\n')]));
  for (const quote of ['import torch',String.fromCharCode(0xfeff)+'import torch']) {
    const value=document('bom.py');value.evidence[0].quote=quote;
    assert.deepEqual((await validateWorkflow(value,root)).issues,[],JSON.stringify(quote));
  }
  const second=document('bom.py');second.evidence[0]={id:'e1',file:'bom.py',line:2,endLine:2,quote:'fit()'};
  assert.deepEqual((await validateWorkflow(second,root)).issues,[]);
  const bad=document('bom.py');bad.evidence[0].quote='import  torch';
  assert.deepEqual((await validateWorkflow(bad,root)).issues.map(x=>x.path),['$.evidence[0].quote']);
});

test('a cited file that is not UTF-8 is an issue without a fingerprint and stale with one', async () => {
  const root=fixture('mlview-not-utf8-');
  const bytes=Buffer.from([0x66,0x69,0x74,0x28,0x29,0xff,0x0a]);
  fs.writeFileSync(path.join(root,'pipeline.py'),bytes);
  const draft=await validateWorkflow(document(),root);
  assert.deepEqual(draft.issues,[{path:'$.evidence[0].file',message:'cannot be decoded as UTF-8'}]);
  const verified=await validateWorkflow(published(document(),{'pipeline.py':bytes}),root);
  assert.deepEqual(verified.issues,[]);
  assert.deepEqual(verified.value.stale.map(x=>[x.rel,x.reason]),[['pipeline.py','unreadable']]);
});

test('isOwnedPath matches MLView artifacts, drafts and installed skills, ASCII case-insensitively', () => {
  const { isOwnedPath }=require('./harness').api;
  for (const rel of ['workflow.mlview.json','sub/Run.MLVIEW.JSON','.mlview/llm/run/draft.json','.MLView/notes.txt','a/b.draft.json','.agents/skills/mlview/SKILL.md','.Claude/Skills/MLView/references/x.md','.github/skills/mlview/scripts/artifact.py'])
    assert.equal(isOwnedPath(rel),true,rel);
  for (const rel of ['skills/mlview/SKILL.md','train.py','x.mlview.json.bak','.agents/skills/mlviewer/SKILL.md','a/.mlview/x','.mlv'+String.fromCharCode(0x130)+'ew/x','draft.json'])
    assert.equal(isOwnedPath(rel),false,rel);
});

test('trackedFiles lists cited files and non-owned inspected files once', () => {
  const { trackedFiles }=require('./harness').api;
  const value=document();
  value.coverage.inspectedFiles.push('config.yaml','workflow.mlview.json','.agents/skills/mlview/SKILL.md','config.yaml');
  assert.deepEqual(trackedFiles(value),['pipeline.py','config.yaml']);
});

test('evidence on MLView-owned files is a structural issue', () => {
  for (const file of ['workflow.mlview.json','.mlview/llm/run/draft.json','.agents/skills/mlview/SKILL.md']) {
    const value=document(file);
    const result=validateWorkflowStructure(value);
    assert.equal(result.document,undefined);
    assert.deepEqual(result.issues,[{path:'$.evidence[0].file',message:'evidence must cite project files, not an MLView artifact, draft or installed MLView skill file'}]);
  }
});

test('drive-qualified paths are rejected everywhere a workspace path is accepted', () => {
  const cases=[
    [(d)=>{d.evidence[0].file='C:/repo/pipeline.py';d.coverage.inspectedFiles=['pipeline.py'];},'$.evidence[0].file'],
    [(d)=>{d.request.entrypoints=['c:train.py'];},'$.request.entrypoints[0]'],
    [(d)=>{d.coverage.inspectedFiles.push('D:/data.csv');},'$.coverage.inspectedFiles[1]'],
    [(d)=>{d.verification={files:{'Z:/x.py':'0'.repeat(64)},publishedAt:'2026-09-25T00:00:00Z'};},'$.verification.files.Z:/x.py']
  ];
  for (const [mutate,at] of cases) {
    const value=document();mutate(value);
    const result=validateWorkflowStructure(value);
    assert.equal(result.document,undefined,at);
    assert.ok(result.issues.some(x=>x.path===at),`${at}: ${JSON.stringify(result.issues)}`);
  }
});

test('owned inspected entries are never touched and fingerprints outside tracked files are ignored', async () => {
  const root=fixture('mlview-owned-');
  fs.writeFileSync(path.join(root,'pipeline.py'),'fit()\n');
  fs.writeFileSync(path.join(root,'notes.md'),'changed\n');
  const value=document();
  value.coverage.inspectedFiles.push('workflow.mlview.json','.agents/skills/mlview/SKILL.md');
  published(value,{'pipeline.py':Buffer.from('fit()\n'),'workflow.mlview.json':Buffer.from('older artifact'),'.agents/skills/mlview/SKILL.md':Buffer.from('original\n'),'notes.md':Buffer.from('original\n')});
  const result=await validateWorkflow(value,root);
  assert.deepEqual(result.issues,[]);
  assert.deepEqual(result.value.stale,[]);
  assert.deepEqual(result.value.staleFiles,[]);
  assert.deepEqual(result.value.files,[path.join(await fs.promises.realpath(root),'pipeline.py')]);
  assert.deepEqual(Object.keys(result.value.fingerprints),['pipeline.py']);
});

test('inspected-only files: verified documents check keyed files, drafts require regular files', async () => {
  const root=fixture('mlview-inspected-rules-');
  fs.writeFileSync(path.join(root,'pipeline.py'),'fit()\n');
  fs.mkdirSync(path.join(root,'data'));
  fs.writeFileSync(path.join(root,'data','sample.csv'),'a,b\n');
  const directory=document();directory.coverage.inspectedFiles.push('data');
  assert.deepEqual((await validateWorkflow(directory,root)).issues,[{path:'$.coverage.inspectedFiles[1]',message:'data must identify a regular file'}]);
  const missing=document();missing.coverage.inspectedFiles.push('gone.yaml');
  assert.deepEqual((await validateWorkflow(missing,root)).issues,[{path:'$.coverage.inspectedFiles[1]',message:'gone.yaml does not exist'}]);
  // A published revision checks only the files it fingerprinted.
  published(missing,{'pipeline.py':Buffer.from('fit()\n')});
  const verified=await validateWorkflow(missing,root);
  assert.deepEqual(verified.issues,[]);
  assert.deepEqual(verified.value.stale,[]);
  published(missing,{'pipeline.py':Buffer.from('fit()\n'),'gone.yaml':Buffer.from('epochs: 3\n')});
  const keyed=await validateWorkflow(missing,root);
  assert.deepEqual(keyed.issues,[]);
  assert.deepEqual(keyed.value.stale,[{rel:'gone.yaml',reason:'missing'}]);
  assert.deepEqual(keyed.value.staleFiles,[path.join(await fs.promises.realpath(root),'gone.yaml')]);
});

test('inspected files over 8 MiB are listed without a fingerprint, and stale if they had one', async () => {
  const root=fixture('mlview-oversize-');
  fs.writeFileSync(path.join(root,'pipeline.py'),'fit()\n');
  fs.writeFileSync(path.join(root,'weights.bin'),Buffer.alloc(8*1024*1024+1,0x61));
  const value=document();value.coverage.inspectedFiles.push('weights.bin');
  const draft=await validateWorkflow(value,root);
  assert.deepEqual(draft.issues,[]);
  assert.deepEqual(Object.keys(draft.value.fingerprints),['pipeline.py']);
  published(value,{'pipeline.py':Buffer.from('fit()\n'),'weights.bin':Buffer.from('small at publish\n')});
  const verified=await validateWorkflow(value,root);
  assert.deepEqual(verified.value.stale.map(x=>[x.rel,x.reason]),[['weights.bin','too-large']]);
});

test('an unverified revision revalidated with its baseline turns a source edit into staleness', async () => {
  const root=fixture('mlview-baseline-');
  fs.writeFileSync(path.join(root,'pipeline.py'),'fit()\n');
  const first=await validateWorkflow(document(),root);
  assert.deepEqual(first.value.fingerprints,{'pipeline.py':sha(Buffer.from('fit()\n'))});
  fs.writeFileSync(path.join(root,'pipeline.py'),'changed()\n');
  const withoutBaseline=await validateWorkflow(document(),root);
  assert.deepEqual(withoutBaseline.issues.map(x=>x.path),['$.evidence[0].quote']);
  const withBaseline=await validateWorkflow(document(),root,{baseline:first.value.fingerprints});
  assert.deepEqual(withBaseline.issues,[]);
  assert.deepEqual(withBaseline.value.stale.map(x=>[x.rel,x.reason]),[['pipeline.py','changed']]);
  // A baseline never applies to a published revision: its own fingerprints decide.
  const verified=published(document(),{'pipeline.py':Buffer.from('fit()\n')});
  const checked=await validateWorkflow(verified,root,{baseline:{'pipeline.py':sha(Buffer.from('changed()\n'))}});
  assert.deepEqual(checked.issues,[]);
  assert.deepEqual(checked.value.stale.map(x=>[x.rel,x.reason]),[['pipeline.py','changed']]);
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
    (d)=>{d.request.entrypoints=['./pipeline.py'];},
    (d)=>{d.coverage.inspectedFiles=['src//pipeline.py'];},
    (d)=>{d.verification={files:{'pipeline.py':'0'.repeat(64)},publishedAt:'2024-02-31T12:00:00Z'};},
    (d)=>{d.nodes[0].mystery='x';}
  ];
  for(const mutate of mutations){
    const value=document();mutate(value);
    assert.doesNotThrow(()=>validateWorkflowStructure(value));
    assert.equal(validateWorkflowStructure(value).document,undefined);
  }
});
