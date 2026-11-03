export const MODEL_LABELS=Object.freeze({phone:'iPhone Lite',osmo:'Omso Held','osmo-stick':'Osmo Stick'});
export const isOsmoChoice=key=>key==='osmo'||key==='osmo-stick';

export function canonicalChoice(value){
  const aliases={'iphone-lite':'phone','iphone-fast':'phone','iphone-full':'phone',native:'phone','osmo-lite':'osmo'};
  const key=aliases[value]||value;
  return Object.prototype.hasOwnProperty.call(MODEL_LABELS,key)?key:null;
}

// Selecting a radio or arriving through a deep link is not download consent.
// Only open() may launch the viewer, once, after the explicit Open model press.
export function createChoiceGate({preselected=null,available=['phone','osmo'],onLaunch=()=>{}}={}){
  const selectable=value=>{
    const key=canonicalChoice(value);
    return available.includes(key)?key:null;
  };
  let selected=selectable(preselected),launched=false;
  return {
    select(value){if(launched)return false;selected=selectable(value);return Boolean(selected);},
    open(){if(launched||!selected)return null;launched=true;onLaunch(selected);return selected;},
    state(){return {selected,launched};}
  };
}

export function createLoadLifecycle(){
  let id=0,controller=null;
  return {
    begin(){controller?.abort();controller=new AbortController();return {id:++id,controller};},
  // A timeout aborts the current request but must still show its failure.
  // Supersession/cancel invalidate the token separately from AbortSignal.
  current(token){return token===id;},
    cancel(){controller?.abort();id++;}
  };
}
