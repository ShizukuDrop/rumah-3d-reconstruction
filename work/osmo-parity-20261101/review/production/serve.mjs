// Local preview only. No authentication, upload, training or remote deployment.
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const here=path.dirname(fileURLToPath(import.meta.url)),root=path.join(here,'public');
const candidate=JSON.parse(fs.readFileSync(path.join(here,'candidate.json'),'utf8'));
const index=process.argv.indexOf('--port');
const port=Number(index>=0?process.argv[index+1]:process.env.PORT|| ((candidate.releaseId||'').includes('parity')?53272:53271));
if(!Number.isInteger(port)||port<1||port>65535)throw Error('Invalid port');
const types={'.html':'text/html; charset=utf-8','.js':'text/javascript','.json':'application/json','.jpg':'image/jpeg','.png':'image/png','.glb':'model/gltf-binary','.sog':'application/octet-stream','.spz':'application/octet-stream','.wasm':'application/wasm'};
http.createServer((req,res)=>{
 try{
  if(!['GET','HEAD'].includes(req.method)){res.writeHead(405).end();return;}
  const pathname=decodeURIComponent(new URL(req.url,'http://localhost').pathname);
  if(pathname==='/favicon.ico'){res.writeHead(204).end();return;}
  const file=path.resolve(root,'.'+pathname+(pathname.endsWith('/')?'index.html':''));
  if(!file.startsWith(root+path.sep)){res.writeHead(403).end();return;}
  let selected=file,compressed=false;
  if(file.endsWith('.glb')&&!req.headers.range&&/gzip/.test(req.headers['accept-encoding']||'')&&fs.existsSync(file+'.gz')){selected=file+'.gz';compressed=true;}
  if(!fs.existsSync(selected)||!fs.statSync(selected).isFile()){res.writeHead(404).end('Missing local build or restored asset');return;}
  // The lexical check above does not see symlinks inside public/; refuse anything resolving outside it.
  if(!fs.realpathSync(selected).startsWith(fs.realpathSync(root)+path.sep)){res.writeHead(403).end();return;}
  const size=fs.statSync(selected).size;let start=0,end=size-1,status=200;
  const headers={'Content-Type':types[path.extname(file)]||'application/octet-stream','Cache-Control':'no-store','Accept-Ranges':'bytes'};
  if(compressed){headers['Content-Encoding']='gzip';headers.Vary='Accept-Encoding';}
  if(req.headers.range){
   const match=/^bytes=(\d+)-(\d*)$/.exec(req.headers.range);
   if(!match){res.writeHead(416,{'Content-Range':`bytes */${size}`}).end();return;}
   start=Number(match[1]);end=match[2]?Math.min(Number(match[2]),size-1):size-1;
   if(start>end){res.writeHead(416,{'Content-Range':`bytes */${size}`}).end();return;}
   status=206;headers['Content-Range']=`bytes ${start}-${end}/${size}`;
  }
  headers['Content-Length']=end-start+1;res.writeHead(status,headers);
  if(req.method==='HEAD')res.end();else fs.createReadStream(selected,{start,end}).pipe(res);
 }catch{if(!res.headersSent)res.writeHead(400);res.end();}
}).listen(port,'127.0.0.1',()=>console.log(`Local ${candidate.releaseId}: http://127.0.0.1:${port}/`));
