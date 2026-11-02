"""Non-convex room footprint for the overview cutaway.

The convex hull in occupied_bounds.py covers corridor and bathroom recesses that are
not room, so concave walls were never cut and exterior splats stayed visible. The
interior is where the trained model shows floor or ceiling (flat, opaque splats on
the fitted planes) and the capture path reaches without crossing a wall. A signed distance grid (positive outside) lets the viewer hide
exterior splats and camera-facing walls with one texture lookup per splat.

Usage: python -B occupied_footprint.py MODEL.ply review/occupied-cameras.json [more camera JSON...]
"""
from pathlib import Path
import base64,hashlib,json,sys
import numpy as np
from scipy import ndimage
from occupied_bounds import ply

# Lengths are normalized scene units (ceiling ~2.43 above floor), close to but not surveyed metres.
CELL=.05          # grid cell; about half a wall thickness
PLANE_BAND=.06    # splat centre distance to fitted floor/ceiling plane
CLOSE_CELLS=3     # bridges furniture shadows up to 2*3*CELL = 0.30 wide
MIN_AREA=.5       # square units; drops isolated reflections on the planes
PAD=1.0           # SDF margin past the occupied bounds; floor evidence runs ~0.4 beyond them
CLAMP=127         # int8 storage in hundredths of a unit
LOWER_MIN_AREA=1.5 # square units; a dropped ceiling, not a wardrobe top
# Share of the 0.3-2.0 height bins (pooled 3x3) opaque vertical splats fill on a wall. A metre-high
# shelf against a wall fills about 0.4: it must stay furniture in front of the wall, not become it.
WALL_EVIDENCE=.55
# Wall faces sit 0.05-0.20 outside the wall-trimmed edge (61% of opaque vertical splats within 0.5
# of it; furniture fronts stay inside). The overview hides
# the camera-facing layer from WALL_BAND inside the edge and everything past EXTERIOR_MARGIN.
WALL_BAND=.25
EXTERIOR_MARGIN=.22

def normals(d):
    # Smallest-scale axis of each Gaussian; flat floor/ceiling splats point it vertically.
    q=np.stack([d['rot_0'],d['rot_1'],d['rot_2'],d['rot_3']],1).astype(np.float64)
    q/=np.linalg.norm(q,axis=1,keepdims=True);w,x,y,z=q.T
    axis=np.argmin(np.stack([d['scale_0'],d['scale_1'],d['scale_2']],1),1)
    columns=[np.stack([1-2*(y*y+z*z),2*(x*y+w*z),2*(x*z-w*y)],1),
             np.stack([2*(x*y-w*z),1-2*(x*x+z*z),2*(y*z+w*x)],1),
             np.stack([2*(x*z+w*y),2*(y*z-w*x),1-2*(x*x+y*y)],1)]
    return np.choose(axis[:,None],columns)

def wall_evidence(cover,cap=None):
    # cover: (W,H,17) bool, opaque vertical splats per 0.1 height bin from 0.3 to 2.0. A wall's splats
    # spread over 2-3 cells of thickness, so pool each bin over 3x3. A wall fills most bins and reaches
    # above 1.6; a 1.4 high bedding stack against it fills 0.65 of them but not the top. cap (W,H) is
    # the height above the floor up to which splats were counted: under a low ceiling the top bins
    # can never fill, so only bins below it take part.
    pooled=ndimage.maximum_filter(cover,size=(3,3,1))
    valid=np.ones(cover.shape,bool) if cap is None else .3+.1*np.arange(1,cover.shape[2]+1)<=cap[...,None]+1e-9
    share=lambda b:(pooled[...,b:]&valid[...,b:]).sum(2)/np.maximum(valid[...,b:].sum(2),1)
    return (share(0)>=WALL_EVIDENCE)&((share(13)>=.5)|(valid[...,13:].sum(2)==0))

def plane_fit(points):
    # Same robust horizontal fit as occupied_bounds.py uses for floor and upper ceiling.
    design=np.column_stack([points[:,0],points[:,2],np.ones(len(points))]);keep=np.ones(len(points),bool)
    for _ in range(6):
        coef=np.linalg.lstsq(design[keep],points[keep,1],rcond=None)[0];residual=points[:,1]-design@coef
        keep=np.abs(residual)<max(.02,2.5*np.median(np.abs(residual)))
    return coef.tolist()

def footprint(model,shell):
    d=ply(Path(model));xyz=np.stack([d['x'],d['y'],d['z']],1).astype(np.float64)
    alpha=1/(1+np.exp(-d['opacity'].astype(np.float64)));n=normals(d);flat=(alpha>.35)&(np.abs(n[:,1])>.85)
    lo=np.array(shell['bounds'][0])-PAD;hi=np.array(shell['bounds'][1])+PAD
    W,H=int(np.ceil((hi[0]-lo[0])/CELL)),int(np.ceil((hi[2]-lo[2])/CELL))
    i=((xyz[:,0]-lo[0])/CELL).astype(int);k=((xyz[:,2]-lo[2])/CELL).astype(int);inside=(i>=0)&(i<W)&(k>=0)&(k<H)
    def cells(use):
        seen=np.zeros((W,H),bool);seen[i[use&inside],k[use&inside]]=True;return seen
    on=lambda c:np.abs(xyz[:,1]-(c[0]*xyz[:,0]+c[1]*xyz[:,2]+c[2]))<PLANE_BAND
    disk=ndimage.iterate_structure(ndimage.generate_binary_structure(2,1),CLOSE_CELLS)
    # Pad first: binary_closing treats the array border as empty and would erode real walls there.
    close=lambda g:ndimage.binary_closing(np.pad(g,CLOSE_CELLS),disk)[CLOSE_CELLS:-CLOSE_CELLS,CLOSE_CELLS:-CLOSE_CELLS]
    def regions(grid,min_area):
        labels,count=ndimage.label(grid);area=ndimage.sum(grid,labels,range(1,count+1))*CELL*CELL
        return np.isin(labels,1+np.flatnonzero(area>=min_area))
    planes={name:shell['fittedPlanes'][name]['YequalsAXplusBZplusC'] for name in ['floor','upperCeiling']}
    seen={name:cells(flat&on(c)) for name,c in planes.items()}
    # A dropped ceiling is the densest flat level between door height and the upper ceiling.
    # Wardrobe tops are smaller than LOWER_MIN_AREA and sit under visible upper ceiling.
    y=xyz[:,1];band=flat&(y>planes['floor'][2]+1.8)&(y<planes['upperCeiling'][2]-.2);upper=close(seen['upperCeiling'])
    if band.sum()>=1000:
        hist,edges=np.histogram(y[band],bins=40);peak=edges[np.argmax(hist)]+(edges[1]-edges[0])/2
        level=plane_fit(xyz[flat&(np.abs(y-peak)<PLANE_BAND)]);region=regions(close(cells(flat&on(level)))&~upper,LOWER_MIN_AREA)
        if region.any():planes['lowerCeiling'],seen['lowerCeiling']=level,region
    grid=regions(ndimage.binary_fill_holes(close(np.logical_or.reduce(list(seen.values())))),MIN_AREA)
    if not grid.any():raise ValueError('No floor/ceiling evidence for a room footprint')
    # Floor evidence runs 0.1-0.5 past the walls (doorways, reflections, blur), which left a fuzzy
    # belt of wall-top shards inside the cut. Keep only floor reachable from the capture path
    # without crossing wall evidence, grown back to the wall's inner face.
    floor=planes['floor'];h=xyz[:,1]-(floor[0]*xyz[:,0]+floor[1]*xyz[:,2]+floor[2])
    wall=(alpha>.4)&(np.abs(n[:,1])<.3)&(h>.3)&(h<2.)&inside
    cover=np.zeros((W,H,17),bool);cover[i[wall],k[wall],((h[wall]-.3)/.1).astype(int)]=True
    evidence=wall_evidence(cover);square=np.ones((3,3),bool)
    lab,_=ndimage.label(grid&~ndimage.binary_dilation(evidence,square,2));cams=np.asarray(shell['interiorCameras'],float).reshape(-1,3)
    # A capture position within the wall margin counts for the floor next to it (up to 0.25 away).
    gap,(ni,nk)=ndimage.distance_transform_edt(lab==0,return_indices=True)
    ci,ck=np.clip(((cams[:,0]-lo[0])/CELL).astype(int),0,W-1),np.clip(((cams[:,2]-lo[2])/CELL).astype(int),0,H-1)
    near=gap[ci,ck]*CELL<=.25;reached=np.setdiff1d(lab[ni[ci,ck][near],nk[ci,ck][near]],[0])
    if not reached.size:raise ValueError('No capture position stands on wall-trimmed floor')
    grid=ndimage.binary_dilation(np.isin(lab,reached),square,3)&grid
    sdf=(ndimage.distance_transform_edt(~grid)-ndimage.distance_transform_edt(grid))*CELL
    cm=np.clip(np.round(sdf*100),-CLAMP,CLAMP).astype(np.int8)
    result={'origin':[float(lo[0]),float(lo[2])],'cellSize':CELL,'size':[W,H],
        # Row-major by X then Z: value index = i*H + k. Hundredths of a unit, positive outside.
        'sdfCm':base64.b64encode(cm.tobytes()).decode(),'exteriorMargin':EXTERIOR_MARGIN,'wallBand':WALL_BAND,
        'method':'union of opaque flat floor/ceiling splats on fitted planes (plus a dropped ceiling); closed, hole-filled, components >= 0.5; trimmed to floor reachable from capture positions without crossing wall evidence; signed EDT',
        'source':{'file':Path(model).name,'sha256':hashlib.file_digest(open(model,'rb'),'sha256').hexdigest()},
        'evidence':{**{name:int(v.sum()) for name,v in seen.items()},'wallCells':int(evidence.sum())},'interiorAreaSceneUnits2':float(grid.sum()*CELL*CELL)}
    if 'lowerCeiling' in planes:
        # Per cell, the nearer of the two ceilings caps the room; 1 selects the dropped one.
        lower=ndimage.distance_transform_edt(~seen['lowerCeiling'])<ndimage.distance_transform_edt(~upper)
        result['lowerCeiling']={'YequalsAXplusBZplusC':planes['lowerCeiling'],'select':base64.b64encode(lower.astype(np.uint8).tobytes()).decode()}
    return result,grid

if __name__=='__main__':
    model,*cameras=sys.argv[1:]
    if not cameras:raise SystemExit(__doc__)
    shell=json.loads(Path(cameras[0]).read_text())['occupiedShell']
    result,grid=footprint(model,shell)
    for path in map(Path,cameras):
        data=json.loads(path.read_text());data['occupiedShell']['footprint']=result;path.write_text(json.dumps(data,indent=2))
    for row in grid[::6]:print(''.join('#' if v else '.' for v in row[::2]))
    print(json.dumps({k:v for k,v in result.items() if k!='sdfCm'},indent=1))
