import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';
import {canonicalChoice,createChoiceGate,createLoadLifecycle} from './choice-core.js';
import {readModel} from './loader-core.js';
const source=await readFile(new URL('chooser.js',import.meta.url),'utf8');
const html=await readFile(new URL('room-shell.html',import.meta.url),'utf8');
function landing(search=''){
  const nodes=new Map(),scripts=[],requests=[],navigations=[],timers=new Map();
  function node(id){if(!nodes.has(id))nodes.set(id,{hidden:false,disabled:false,textContent:'',events:{},addEventListener(name,fn){this.events[name]=fn;}});return nodes.get(id);}
  const radios=['phone','osmo'].map(value=>Object.assign(node(value),{value,checked:false}));
  const body={dataset:{},appendChild(script){scripts.push(script);}};
  let timerId=0;
  const sandbox={canonicalChoice,createChoiceGate,URLSearchParams,URL,
    document:{body,getElementById:node,querySelectorAll:()=>radios,createElement:tag=>({tagName:tag})},
    location:{search,pathname:'/',origin:'https://rumah.shizuku.rest',assign:url=>navigations.push(url)},
    fetch:url=>requests.push(url),window:{addEventListener(){}},
    setTimeout:fn=>{timers.set(++timerId,fn);return timerId;},clearTimeout:id=>timers.delete(id)};
  vm.runInNewContext(source.replace(/^import .*;\r?\n/,''),sandbox,{filename:'chooser.js'});
  return {node,radios,body,scripts,requests,navigations,timers,
    select(key){const radio=radios.find(r=>r.value===key);radio.checked=true;radio.events.change();},
    open(){node('open-model').events.click();}};
}
test('bare landing and choosing any card never inject the viewer or fetch a model',()=>{
  const page=landing();assert.equal(page.node('open-model').disabled,true);
  assert.ok(page.radios.every(r=>!r.checked));page.open();
  for(const key of ['phone','osmo'])page.select(key);
  assert.deepEqual(page.requests,[]);assert.deepEqual(page.scripts,[]);
  assert.equal(page.body.dataset.selectedModel,undefined);
});
test('deep links only preselect, while Open launches exactly the chosen model once',()=>{
  for(const [query,model] of [['phone','phone'],['native','phone'],['iphone-full','phone'],['iphone-lite','phone'],['osmo-lite','osmo']]){
    const page=landing('?quality='+query);assert.equal(page.node('open-model').disabled,false);
    assert.equal(page.radios.find(r=>r.checked).value,model);assert.equal(page.scripts.length,0);assert.equal(page.requests.length,0);
    page.open();page.open();page.select('phone');page.open();
    assert.equal(page.scripts.length,1);assert.equal(page.scripts[0].src,'__BUNDLE__');
    assert.equal(page.body.dataset.selectedModel,model);assert.equal(page.node('model-chooser').hidden,true);
  }
});
test('entry-script failure never retries a download; retry returns to a chooser',()=>{
  const page=landing('?quality=osmo');page.open();page.scripts[0].onerror();
  assert.equal(page.body.dataset.phase,'failed');assert.equal(page.scripts.length,1);assert.equal(page.timers.size,0);
  assert.match(page.node('load-detail').textContent,/No model download/);
  page.node('retry').onclick();assert.equal(page.scripts.length,1);assert.equal(page.requests.length,0);
  assert.equal(new URL(page.navigations[0]).searchParams.get('quality'),'osmo');
});
test('HTML has no external scripts, preview/photo src, preload or CSS resource requests before choice',()=>{
  assert.doesNotMatch(html,/<(?:img|script)\b[^>]*\bsrc\s*=/i);
  assert.doesNotMatch(html,/<link\b|\b(?:srcset|poster)\s*=|\burl\s*\(|\b(?:prefetch|preload|autoplay)\b/i);
  assert.match(html,/<div id="viewer-app" hidden>/);assert.match(html,/<script>__CHOOSER_INLINE__<\/script>/);
  assert.equal((html.match(/name="model-choice"/g)||[]).length,2);
  assert.doesNotMatch(html,/iPhone Full|value="native"|iphone-full|__NATIVE_COST__|__NATIVE_FILE__/);
  assert.match(html,/iPhone Lite/);
});
const glb=()=>{const a=new Uint8Array(20),v=new DataView(a.buffer);v.setUint32(0,0x46546c67,true);v.setUint32(4,2,true);v.setUint32(8,20,true);return a;};
test('switching generations cancels a pending stream and prevents stale readiness',async()=>{
  const life=createLoadLifecycle(),old=life.begin();let streamCancelled=false;
  const response=new Response(new ReadableStream({start(c){c.enqueue(glb().subarray(0,12));},cancel(){streamCancelled=true;}}));
  const oldRead=readModel(response,20,{signal:old.controller.signal});
  const latest=life.begin();assert.equal(old.controller.signal.aborted,true);assert.equal(life.current(old.id),false);
  await assert.rejects(oldRead,{name:'AbortError'});assert.equal(streamCancelled,true);
  const buffer=await readModel(new Response(glb()),20,{signal:latest.controller.signal});
  assert.equal(buffer.byteLength,20);assert.equal(life.current(latest.id),true);
  life.cancel();assert.equal(latest.controller.signal.aborted,true);assert.equal(life.current(latest.id),false);
});
test('a timeout remains the current generation so its error can be displayed',()=>{
  const life=createLoadLifecycle(),request=life.begin();request.controller.abort();
  assert.equal(life.current(request.id),true);life.cancel();assert.equal(life.current(request.id),false);
});
test('viewer requires explicit chooser state before constructing graphics or reading metadata',async()=>{
  const viewer=await readFile(new URL('room-viewer.js',import.meta.url),'utf8');
  assert.ok(viewer.indexOf('if(!selectedOnOpen)throw')<viewer.indexOf('new THREE.WebGLRenderer'));
  assert.match(viewer,/loadAsset\(selectedOnOpen\);\s*$/);
  assert.doesNotMatch(viewer,/loadAsset\(chooseQuality/);
  assert.match(viewer,/onchange=\(\)=>chooseAnotherModel/);
});
