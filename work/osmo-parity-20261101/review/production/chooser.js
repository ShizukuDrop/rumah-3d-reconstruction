import {MODEL_LABELS,createChoiceGate} from './choice-core.js';
const $=id=>document.getElementById(id),params=new URLSearchParams(location.search);
const choices=[...document.querySelectorAll('input[name="model-choice"]')];
let timer,selected=null;
const returnToChoices=()=>{const url=new URL(location.pathname,location.origin);if(selected)url.searchParams.set('quality',selected);url.searchParams.set('v','20261031-native-provisional');location.assign(url.href);};
const fail=()=>{
  if(document.body.dataset.phase)return;
  clearTimeout(timer);document.body.dataset.phase='failed';$('load-title').textContent='The viewer could not start';
  $('load-status').textContent='Please check the connection, then choose a model again.';
  $('load-detail').textContent='No model download has started.';$('load-progress').hidden=true;
  $('retry').hidden=false;$('retry').textContent='Choose a model';$('loading-photos').hidden=true;
};
const gate=createChoiceGate({preselected:params.get('quality'),available:choices.map(input=>input.value),onLaunch:key=>{
  selected=key;document.body.dataset.selectedModel=key;
  $('open-model').disabled=true;$('model-chooser').hidden=true;$('viewer-app').hidden=false;
  $('load-title').textContent='Opening '+MODEL_LABELS[key];
  $('load-status').textContent='Starting the viewer…';$('load-detail').textContent='';
  $('retry').onclick=returnToChoices;$('cancel-load').onclick=returnToChoices;$('change-model').onclick=returnToChoices;
  $('loading-photos').disabled=true;$('photos').disabled=true;
  timer=setTimeout(fail,20000);
  const script=document.createElement('script');script.src='__BUNDLE__';script.defer=true;script.type='module';
  script.onerror=fail;document.body.appendChild(script);
}});
const initial=gate.state().selected;
for(const input of choices){
  input.checked=input.value===initial;
  input.addEventListener('change',()=>{gate.select(input.value);$('open-model').disabled=!gate.state().selected;$('choice-status').textContent='Press Open model to start the selected download.';});
}
$('open-model').disabled=!initial;$('open-model').addEventListener('click',()=>gate.open());
if(initial)$('choice-status').textContent='Your linked model is selected. Press Open model to start its download.';
window.addEventListener('pagehide',()=>clearTimeout(timer));
