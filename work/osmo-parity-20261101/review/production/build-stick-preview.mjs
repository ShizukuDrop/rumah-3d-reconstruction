import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {createRequire} from 'node:module';
import {createHash} from 'node:crypto';
import {selectModel} from './loader-core.js';

const here=path.dirname(fileURLToPath(import.meta.url));
const dependencies=path.resolve(here,'../../../mobile-20261029');
const {build}=createRequire(path.join(dependencies,'package.json'))('esbuild');
const [previewDir,cameraDir,output]=process.argv.slice(2).map(value=>path.resolve(value));
if(!previewDir||!cameraDir||!output)throw Error('Pass preview assets, camera export and a new output directory.');
const read=async file=>JSON.parse(await fs.readFile(file,'utf8'));
const meta=await read(path.join(previewDir,'metadata.json'));
const cameras=await read(path.join(cameraDir,'cameras.json'));
const model=await fs.readFile(path.join(previewDir,'model.spz'));
if(model.length!==meta.model.bytes||createHash('sha256').update(model).digest('hex')!==meta.model.sha256)
  throw Error('Preview model does not match the evaluated asset.');
if(!cameras.startCamera||!cameras.bounds||!(cameras.framingPoints?.length>=30)||!cameras.presets?.length)
  throw Error('Missing preview framing or camera data.');
await fs.mkdir(output);
await fs.mkdir(path.join(output,'sources'));
for(const [index,preset] of cameras.presets.entries()){
  if(!preset.sourceFile)continue;
  preset.source='sources/view-'+index+'.jpg';
  await fs.copyFile(path.join(cameraDir,preset.sourceFile),path.join(output,preset.source));
  delete preset.sourceFile;
}
cameras.photos=cameras.presets.filter(preset=>preset.source).map(({name,label,source})=>({name,label,source}));
const key='osmo-stick';
const manifest={
  build:'stick-preview-shared-controls',
  models:{[key]:{label:'Osmo Stick · Preview',cameraSet:key,representation:'gaussian',
    format:'spz',url:'model.spz',fileBytes:model.length,downloadBytes:model.length,
    splats:meta.model.splats,shDegree:meta.model.shDegree,previewCheckpoint:true}},
  cameraSets:{[key]:cameras},
};
selectModel(manifest,key);
await fs.writeFile(path.join(output,'room.json'),JSON.stringify(manifest));
await fs.writeFile(path.join(output,'model.spz'),model);

const source=await fs.readFile(path.join(here,'room-viewer.js'),'utf8');
const entry=source.replace('__MANIFEST__','room.json')
  .replace("$('change-model').onclick=()=>chooseAnotherModel(currentQuality||selectedOnOpen);",
    "$('change-model').onclick=()=>location.assign('/');");
await build({stdin:{contents:entry,sourcefile:'room-viewer.js',resolveDir:here},
  bundle:true,outdir:output,nodePaths:[path.join(dependencies,'node_modules')],format:'esm',
  splitting:true,minify:true,entryNames:'[name]-[hash]',chunkNames:'chunks/[name]-[hash]'});
// esbuild names stdin entry "stdin" unless an explicit output name is supplied.
const entries=(await fs.readdir(output)).filter(name=>name.endsWith('.js'));
if(entries.length!==1)throw Error('Expected one viewer entry point.');
const chooser=(await fs.readFile(path.join(here,'chooser.js'),'utf8'))
  .replace('__BUNDLE__',entries[0]).replace("preselected:params.get('quality')","preselected:'osmo-stick'");
const gate=await build({stdin:{contents:chooser,resolveDir:here},bundle:true,
  minify:true,write:false,format:'iife'});
const size=(model.length/1e6).toFixed(1);
const card='<label class="choice-card"><input type="radio" name="model-choice" value="osmo-stick" aria-label="Osmo Stick"><span class="choice-name">Osmo Stick</span><span class="choice-size">'+size+' MB model</span><span class="choice-description">Evaluated 6,000-step checkpoint. Uses the same Walk, Orbit, and touch controls as iPhone Lite.</span></label>';
let shell=await fs.readFile(path.join(here,'room-shell.html'),'utf8');
shell=shell.replace(/<label class="choice-card"><input[^\n]*<\/label>\n/g,'')
  .replace('<!-- stick-choice -->',card)
  .replace('<option value="phone">iPhone Lite</option><option value="osmo">Omso Held</option><!-- stick-option -->',
    '<option value="osmo-stick">Osmo Stick · Preview</option>')
  .replace('<h1 id="choose-heading">Choose a scan to explore</h1>',
    '<h1 id="choose-heading">Osmo Stick <span class="preview-badge">Preview</span></h1>')
  .replace('<header><h1>Apartment scans</h1>','<header><h1>Osmo Stick <span class="preview-badge">Preview</span></h1>')
  .replace('</style>','.preview-badge{font-size:11px;vertical-align:middle;padding:3px 8px;border-radius:99px;background:#503b20;color:#ffdda2}.choice-cards{grid-template-columns:minmax(0,470px)}</style>')
  .replace('You can return here to choose another version.','<a href="/">Back to all models</a>.')
  .replace('<title>Apartment scans · Ruang Kamare</title>','<title>Osmo Stick · Preview</title>')
  .replace('__CHOOSER_INLINE__',()=>gate.outputFiles[0].text.replaceAll('</script','<\\/script'));
if(/__[A-Z_]+__/.test(shell))throw Error('Unresolved preview HTML placeholder.');
await fs.writeFile(path.join(output,'index.html'),shell);
