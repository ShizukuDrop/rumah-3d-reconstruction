"""Verify anonymous release delivery without downloading any full model."""
from pathlib import Path
import argparse,hashlib,json,re,time,urllib.request,urllib.error
HERE=Path(__file__).resolve().parent
USER_AGENT='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36'

def request(base,name,method='GET',extra=None,limit=0,allow_not_found=False):
    headers={'Accept-Encoding':'identity','User-Agent':USER_AGENT,**(extra or {})}
    req=urllib.request.Request(base+name,method=method,headers=headers)
    try:response=urllib.request.urlopen(req,timeout=25)
    except urllib.error.HTTPError as error:
        # Only the explicit retired-model HEAD check accepts 404. A Cloudflare
        # 403, an auth error or another failure still aborts verification.
        if not (allow_not_found and method=='HEAD' and error.code==404):raise
        response=error
    with response:
        if not response.geturl().startswith(base):raise ValueError('Unexpected off-site redirect')
        if response.headers.get('WWW-Authenticate'):raise ValueError('Unexpected authentication requirement')
        if method=='GET' and 'Range' in headers and response.status!=206:raise ValueError('Server ignored bounded range; body not read')
        body=response.read(limit+1) if method=='GET' else b''
        if len(body)>limit:raise ValueError(f'Response exceeded bounded verification budget: {name!r}, status={response.status}, type={response.headers.get("Content-Type")!r}, limit={limit}')
        return response.status,{k.lower():v for k,v in response.headers.items()},body

def authored_html_matches(actual,expected):
    text=actual.decode('utf-8')
    text,a=re.subn(r'<script>\(function\(\)\{function c\(\)\{var b=a\.contentDocument.*?</script>','',text,flags=re.S)
    text,b=re.subn(r'<script\b[^>]*src="https://static\.cloudflareinsights\.com/beacon\.min\.js/[^\"]*"[^>]*></script>','',text,flags=re.S)
    normalize=lambda value:'\n'.join(line.rstrip() for line in value.splitlines() if line.strip())
    return (a,b) in [(1,1),(1,0),(0,1)] and normalize(text)==normalize(expected.decode('utf-8'))

def authored_robots_matches(actual,expected):
    # The existing Cloudflare service prepends managed crawler rules. Accept
    # only the exact prefix observed on this site, followed by our exact rules.
    # This exception never applies to HTML, JS, metadata, images or models.
    if len(actual)>len(expected)+8192:return False
    normalize=lambda value:value.replace(b'\r\n',b'\n').rstrip()+b'\n'
    actual=normalize(actual);expected=normalize(expected)
    if not actual.endswith(expected):return False
    prefix=actual[:-len(expected)]
    return hashlib.sha256(prefix).hexdigest()=='3073d1e371afb3271c7666148766fedc5145f7d8440f7114062db79b7bd58add'

def model_head(base,row,fmt):
    status,headers,_=request(base,row['path'],'HEAD');length=headers.get('content-length')
    if status!=200 or 'text/html' in headers.get('content-type',''):raise ValueError('Model HEAD failed or returned HTML')
    if length is not None and int(length)!=row['bytes']:raise ValueError('Model Content-Length mismatch')
    result={'path':row['path'],'method':'HEAD','status':status,'content_length':length,'content_type':headers.get('content-type'),'cache_control':headers.get('cache-control')}
    if length is None:
        status,part,body=request(base,row['path'],extra={'Range':'bytes=0-11'},limit=12)
        if part.get('content-range')!=f'bytes 0-11/{row["bytes"]}' or len(body)!=12:raise ValueError('Model bounded range mismatch')
        valid={'glb':body[:4]==b'glTF','sog':body[:4]==b'PK\x03\x04','spz':body[:2]==b'\x1f\x8b' or body[:4]==b'NGSP'}[fmt]
        if not valid:raise ValueError('Model format header mismatch')
        result['range']={'status':status,'bytes':12,'content_range':part['content-range']}
    status,gzip_headers,_=request(base,row['path'],'HEAD',extra={'Accept-Encoding':'gzip'})
    if status!=200 or 'text/html' in gzip_headers.get('content-type',''):raise ValueError('Encoded HEAD failed')
    result['gzip_head']={'status':status,'content_encoding':gzip_headers.get('content-encoding'),'content_length':gzip_headers.get('content-length'),'vary':gzip_headers.get('vary')}
    return result

def verify(info,base,here=HERE):
    base=base.rstrip('/')+'/';checks=[];body_bytes=0
    rows=info['files'];models=[r for r in rows if r['path']==info['model']['url']]+[r for r in info['inherited_files'] if r['path'].endswith('.glb')]
    for row in rows:
        name=row['path']
        if name.endswith(('.spz','.sog')):continue
        if name.startswith('sources/'):
            status,headers,_=request(base,name,'HEAD')
            if status!=200 or 'image/jpeg' not in headers.get('content-type',''):raise ValueError('Source image not served as JPEG')
            checks.append({'path':name,'method':'HEAD','status':status});continue
        limit=row['bytes']+(30000 if name=='index.html' else 8192 if name=='robots.txt' else 0)
        status,headers,body=request(base,'' if name=='index.html' else name,limit=limit);body_bytes+=len(body)
        digest=hashlib.sha256(body).hexdigest();authored=False;managed_robots=False
        if digest!=row['sha256']:
            if name=='index.html' and authored_html_matches(body,(here/'public/index.html').read_bytes()):authored=True
            elif name=='robots.txt' and authored_robots_matches(body,(here/'public/robots.txt').read_bytes()):managed_robots=True
            else:raise ValueError('Public authored asset differs: '+name)
        if status!=200:raise ValueError('Public asset response failed')
        if name=='index.html':
            cache=headers.get('cache-control','').lower()
            if 'immutable' in cache or not any(token in cache for token in ['no-cache','no-store','max-age=0']):raise ValueError('Landing page must revalidate instead of retaining stale choices')
        if name.endswith('.js') and not re.search(r'(application|text)/javascript',headers.get('content-type','')):raise ValueError('Incorrect JavaScript MIME type')
        checks.append({'path':name,'method':'GET','status':status,'bytes':len(body),'sha256':digest,'authored_html_matches_after_known_edge_tags':authored,'authored_robots_preserved_after_exact_known_managed_prefix':managed_robots,'cache_control':headers.get('cache-control')})
    for row in models:checks.append(model_head(base,row,info['model']['format'] if row['path']==info['model']['url'] else 'glb'))
    for name in info.get('removed_public_files',[]):
        status,headers,_=request(base,name,'HEAD',allow_not_found=True)
        if status!=404:raise ValueError('Retired Full model is still publicly accessible: '+name)
        checks.append({'path':name,'method':'HEAD','status':404,'retired_model_unavailable':True})
    return {'verified_unix':time.time(),'site':base,'build':info['build'],'anonymous_https':base.startswith('https://'),'model_full_downloads':0,'nonmodel_body_bytes':body_bytes,'asset_checks':checks,'physical_fold7_iphone17':'Not verified by these HTTP checks','browser_followup':'Confirm fresh chooser and explicit Open with network capture; HTTP checks do not prove browser behavior.'}

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--manifest',type=Path,default=HERE/'deployment/deployment-manifest.json');p.add_argument('--base',default='https://rumah.shizuku.rest/');p.add_argument('--output',type=Path,default=HERE/'deployment/public-verification.json');args=p.parse_args()
    info=json.loads(args.manifest.read_text());report=verify(info,args.base);args.output.write_text(json.dumps(report,indent=2));print(json.dumps({'passed':True,'build':info['build'],'modelFullDownloads':0,'checks':len(report['asset_checks']),'report':str(args.output)},indent=2))
