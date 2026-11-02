"""Simple-shape stand-in for the Osmo room: floor and ceiling slabs, walls, and one
box, cylinder or sphere per object, each coloured from the splats it replaces.

Everything is snapped to the room's dominant (Manhattan) direction. The plan is the floor
reachable from the capture path without crossing wall evidence (opaque vertical splats over
most of the wall height); walls are extruded around its outline, so the shell is closed.
Objects are connected opaque voxels between floor and ceiling, away from walls.
The output is a small JSON the viewer turns into three.js primitives.

Usage: python -B simple_shapes.py MODEL.ply review/calibrated-occupied-cameras.json review/simple-shapes.json
"""
from pathlib import Path
import base64,hashlib,json,math,sys
import numpy as np
from scipy import ndimage
from occupied_bounds import ply
from occupied_footprint import normals,wall_evidence

CELL=.05            # grid/voxel size in scene units
MIN_CELLS=12        # smallest object footprint kept (0.03 square units)
BAND=.3             # neighbouring cells join one object only if their tops share a band
MAX_OBJECTS=400
SNAP=4              # outline grid in cells (0.2 units)
SEG=4               # wall colour piece in cells; same-colour neighbours merge again
BEHIND=2.          # a wall with more room this close behind it is a partition
LOW=.65            # second object pass: what stands below this, under tables and overhangs
LUMA=np.array([.299,.587,.114])

def sigmoid(v):return 1/(1+np.exp(-v))
def hexcolor(rgb):return '#'+''.join(f'{int(round(float(v)*255)):02x}' for v in np.clip(rgb,0,1))
def largest_rectangles(mask,min_cells):
    # Greedy maximal all-true rectangles (histogram method) until the rest is too small.
    mask=mask.copy();out=[]
    while True:
        best=(0,None);heights=np.zeros(mask.shape[1],int)
        for r in range(mask.shape[0]):
            heights=np.where(mask[r],heights+1,0);stack=[]
            for k in range(len(heights)+1):
                h=heights[k] if k<len(heights) else 0;start=k
                while stack and stack[-1][1]>=h:
                    start,hh=stack.pop();area=hh*(k-start)
                    if area>best[0]:best=(area,(r-hh+1,start,r+1,k))
                stack.append((start,h))
        if best[0]<min_cells:return out
        r0,c0,r1,c1=best[1];mask[r0:r1,c0:c1]=False;out.append(best[1])

def edge_runs(plan,axis,step,tol):
    # Plan cells whose neighbour one step across `axis` is outside, as runs [across, start, end, cells,
    # pieces]. Runs up to tol cells apart across that touch along merge at their length-weighted line.
    edge=plan&~np.roll(plan,-step,1-axis);runs=[]
    for b,row in enumerate(np.moveaxis(edge,1-axis,0)):
        hits=np.flatnonzero(row)
        for run in np.split(hits,np.flatnonzero(np.diff(hits)>1)+1) if len(hits) else []:runs.append([b,run[0],run[-1]+1,len(run),[(b,run[0],run[-1]+1)]])
    runs.sort(key=lambda r:(r[1],r[0]));out=[]
    for r in runs:
        w=next((w for w in out if abs(w[0]-r[0])<=tol and r[1]<=w[2]+1 and r[2]>=w[1]-1),None)
        if w:w[0]=(w[0]*w[3]+r[0]*r[3])/(w[3]+r[3]);w[1]=min(w[1],r[1]);w[2]=max(w[2],r[2]);w[3]+=r[3];w[4]+=r[4]
        else:out.append(r)
    return out

def straighten(plan,tol):
    # Move every piece of an edge onto its merged line: steps of up to tol cells become straight
    # edges, filled out or cut back, so floor and walls follow the same outline.
    plan=plan.copy()
    for axis in (0,1):
        for step in (1,-1):
            for b,*_,pieces in edge_runs(plan,axis,step,tol):
                line=int(round(b))
                for pb,p0,p1 in pieces:
                    fill=(line-pb)*step>0
                    for c in range(pb+step,line+step,step) if fill else range(line+step,pb+step,step):
                        if axis==0:plan[p0:p1,c]=fill
                        else:plan[c,p0:p1]=fill
    return plan

def shapes(model,shell):
    fp=shell['footprint'];W,H=fp['size'];c=fp['cellSize'];o=fp['origin']
    sdf=np.frombuffer(base64.b64decode(fp['sdfCm']),np.int8).reshape(W,H)/100
    low=np.frombuffer(base64.b64decode(fp['lowerCeiling']['select']),np.uint8).reshape(W,H).astype(bool) if fp.get('lowerCeiling') else np.zeros((W,H),bool)
    planes=[shell['fittedPlanes']['floor']['YequalsAXplusBZplusC'],shell['fittedPlanes']['upperCeiling']['YequalsAXplusBZplusC'],(fp.get('lowerCeiling') or shell['fittedPlanes']['upperCeiling'])['YequalsAXplusBZplusC']]
    at=lambda p,x,z:p[0]*x+p[1]*z+p[2]
    cell=lambda x,z:(np.clip(((x-o[0])/c).astype(int),0,W-1),np.clip(((z-o[1])/c).astype(int),0,H-1))
    def ceiling(x,z):
        i,k=cell(x,z);return np.where(low[i,k],at(planes[2],x,z),at(planes[1],x,z))
    d=ply(Path(model));x,y,z=(d[k].astype(np.float64) for k in 'xyz');alpha=sigmoid(d['opacity'].astype(np.float64));n=normals(d)
    rgb=np.clip(.5+.28209479*np.stack([d['f_dc_0'],d['f_dc_1'],d['f_dc_2']],1),0,1)
    i,k=cell(x,z);dist=sdf[i,k];floor=at(planes[0],x,z);top=ceiling(x,z)
    # Manhattan direction from opaque vertical splats: average angle on the 4-fold circle.
    vertical=(alpha>.5)&(np.abs(n[:,1])<.2)&(dist<.15);phi=4*np.arctan2(n[vertical,2],n[vertical,0])
    theta=float(np.arctan2(np.sin(phi).sum(),np.cos(phi).sum())/4)
    # Refine to the angle where wall splats pile up on the fewest grid lines (sharpest 1D histograms),
    # so long straight walls do not step across cells.
    wx_,wz_=x[vertical],z[vertical]
    def peaky(t):return sum(float((np.bincount(((p-p.min())/CELL).astype(int))**2).sum()) for p in (wx_*math.cos(t)+wz_*math.sin(t),-wx_*math.sin(t)+wz_*math.cos(t)))
    theta=max(theta+np.radians(np.arange(-2,2.01,.1)),key=peaky);ax=np.array([math.cos(theta),math.sin(theta)]);bx=np.array([-math.sin(theta),math.cos(theta)])
    u=x*ax[0]+z*ax[1];v=x*bx[0]+z*bx[1];inside=dist<=0
    u0,v0=u[inside].min()-.2,v[inside].min()-.2;U=int((u[inside].max()+.2-u0)/CELL)+1;V=int((v[inside].max()+.2-v0)/CELL)+1
    iu=np.clip(((u-u0)/CELL).astype(int),0,U-1);iv=np.clip(((v-v0)/CELL).astype(int),0,V-1)
    centre=lambda a,b:(u0+(a+.5)*CELL,v0+(b+.5)*CELL)
    world=lambda cu,cv:(cu*ax[0]+cv*bx[0],cu*ax[1]+cv*bx[1])
    au,av=np.meshgrid(np.arange(U),np.arange(V),indexing='ij');gx,gz=world(*centre(au,av));gi,gk=cell(gx,gz);room=sdf[gi,gk]<=.2  # past the footprint edge to the wall evidence that bounds the plan
    out=[];yaw=-theta  # three.js rotation.y that maps local +X onto the wall axis
    def add(kind,kind_type,cu,cv,y0,y1,su,sv,colour,**extra):
        wx,wz=world(cu,cv);out.append({'kind':kind,'type':kind_type,'center':[round(float(wx),3),round(float((y0+y1)/2),3),round(float(wz),3)],'size':[round(float(su),3),round(float(y1-y0),3),round(float(sv),3)],'yaw':round(yaw,4),'color':hexcolor(colour),**extra})
    flat=(alpha>.35)&(np.abs(n[:,1])>.85);floor_rgb=np.median(rgb[flat&(np.abs(y-floor)<.06)],0);ceil_rgb=np.median(rgb[flat&(np.abs(y-top)<.06)],0)
    # Wall evidence: cells whose opaque vertical splats fill the height bins.
    bins=np.arange(.3,2.0,.1);wall_pts=(alpha>.4)&(np.abs(n[:,1])<.3)&(dist<.15)&(y>floor+.3)&(y<np.minimum(top-.15,floor+2.0))
    hb=np.clip(((y[wall_pts]-floor[wall_pts]-.3)/.1).astype(int),0,len(bins)-1);cover=np.zeros((U,V,len(bins)),bool);cover[iu[wall_pts],iv[wall_pts],hb]=True
    # Interior: footprint cells reachable from the capture path without crossing wall evidence.
    # Floor seen through glass or in a mirror lies beyond a wall and drops out here.
    cap=np.minimum(ceiling(gx,gz)-.15,at(planes[0],gx,gz)+2.)-at(planes[0],gx,gz)  # where wall splats were counted
    lab,_=ndimage.label(room&~ndimage.binary_dilation(wall_evidence(cover,cap),iterations=2));cams=np.asarray(shell['interiorCameras'])
    grid=lambda wx,wz:(np.clip(((wx*ax[0]+wz*ax[1]-u0)/CELL).astype(int),0,U-1),np.clip(((wx*bx[0]+wz*bx[1]-v0)/CELL).astype(int),0,V-1))
    reached=np.setdiff1d(lab[grid(cams[:,0],cams[:,2])],[0]);interior=ndimage.binary_dilation(np.isin(lab,reached),iterations=3)&room
    # Plan: the reachable interior squared off on the room's own axes. Opening and closing with a
    # 0.35 square remove notches and spurs, so the outline is long straight runs that meet at corners.
    square=np.ones((7,7),bool);plan=ndimage.binary_fill_holes(ndimage.binary_closing(ndimage.binary_opening(interior,square),square))
    lab,count=ndimage.label(plan);area=ndimage.sum(plan,lab,range(1,count+1))*CELL*CELL;plan=np.isin(lab,1+np.flatnonzero(area>=1.))
    # Snap the outline to a SNAP grid, at whichever phase agrees best with it: 1-3 cell steps from
    # noisy floor evidence become straight walls and floor slabs get clean edges.
    def snapped(du,dv):
        g=np.pad(plan,((du,-(U+du)%SNAP),(dv,-(V+dv)%SNAP)));R,C=g.shape[0]//SNAP,g.shape[1]//SNAP
        g=g.reshape(R,SNAP,C,SNAP).mean((1,3))>=.5;return np.kron(g,np.ones((SNAP,SNAP),bool))[du:du+U,dv:dv+V]
    plan=max((snapped(du,dv) for du in range(SNAP) for dv in range(SNAP)),key=lambda g:int((g==plan).sum()))
    plan=straighten(straighten(plan,SNAP),SNAP)
    dropped=straighten(straighten(ndimage.binary_closing(ndimage.binary_opening(low[gi,gk]&plan,square),square),SNAP),SNAP)&plan
    lab,count=ndimage.label(dropped);dropped=np.isin(lab,1+np.flatnonzero(ndimage.sum(dropped,lab,range(1,count+1))*CELL*CELL>=1.));fy=float(np.median(at(planes[0],gx[plan],gz[plan])))
    level={True:float(np.median(at(planes[2],gx[plan&dropped],gz[plan&dropped]))) if (plan&dropped).any() else 0.,False:float(np.median(at(planes[1],gx[plan&~dropped],gz[plan&~dropped])))}
    # One floor height and two ceiling heights keep every slab coplanar: no seams or steps.
    def brighter(c):return np.median(c[c@LUMA>=np.median(c@LUMA)],0)  # skip shadowed splats
    bright=lambda m:brighter(rgb[m])
    floor_rgb,ceil_rgb=bright(flat&(np.abs(y-floor)<.06)),bright(flat&(np.abs(y-top)<.06));wall_rgb=bright(wall_pts)
    wall_rgb=wall_rgb*min(1.4,.82/float(wall_rgb@LUMA))  # the walls are white; scan colour is under-exposed
    for r0,c0,r1,c1 in largest_rectangles(plan,1):
        add('floor','box',u0+(r0+r1)/2*CELL,v0+(c0+c1)/2*CELL,fy-.05,fy,(r1-r0)*CELL,(c1-c0)*CELL,floor_rgb)
    for low_level in (True,False):
        for r0,c0,r1,c1 in largest_rectangles(plan&(dropped if low_level else ~dropped),1):
            # A dropped ceiling is solid up to the upper one, so the step between them has a face.
            add('ceiling','box',u0+(r0+r1)/2*CELL,v0+(c0+c1)/2*CELL,level[low_level],max(level.values())+.05,(r1-r0)*CELL,(c1-c0)*CELL,ceil_rgb)
    # Walls are extruded from the plan outline, just outside it, in one neutral colour. Corners never
    # overlap (coplanar tops would z-fight): at an outside corner the wall along u runs on by its
    # thickness and closes it; at an inside corner the wall along v stops a thickness short.
    # Their outward side is simply the side the plan is not on.
    # Doors: SEG pieces are coloured from the splats on the wall (just inside the edge to 0.3 outside);
    # same-colour neighbours merge. A dark, warm run 0.6-1.3 wide becomes a door: an opening with a
    # lintel and a recessed leaf in its own colour. A dark, cool one 0.6-3 wide is a curtained window:
    # the same opening with a curtain panel.
    on=np.flatnonzero((alpha>.3)&(np.abs(n[:,1])<.5)&(y>floor+.1)&(y<top-.1));wu,wv,wc=u[on]-u0,v[on]-v0,rgb[on]
    def openings(axis,step,line,a0,a1):
        along,across=(wu,wv) if axis==0 else (wv,wu);off=(across-line)*step
        m=(off>-.1)&(off<.3)&(along>=a0*CELL)&(along<a1*CELL);k=((along[m]-a0*CELL)/(SEG*CELL)).astype(int);c=wc[m];out=[]
        for j in range(-(-(a1-a0)//SEG)):
            sel=c[k==j];col=brighter(sel) if len(sel)>=20 else out[-1][2] if out else wall_rgb;p0,p1=a0+j*SEG,min(a0+(j+1)*SEG,a1)
            if out and np.abs(out[-1][2]-col).max()<.1:w=(out[-1][1]-out[-1][0])/(p1-out[-1][0]);out[-1][1:]=[p1,w*out[-1][2]+(1-w)*col]
            else:out.append([p0,p1,col])
        dark=lambda col:np.abs(col-wall_rgb).max()>.15 and col@LUMA<.45
        return [(p0,p1,col,'door' if col[0]>=col[2] else 'window') for p0,p1,col in out if dark(col) and .6<=(p1-p0)*CELL<=(1.3 if col[0]>=col[2] else 3.)]
    T=.12;DOOR=2.;ty=max(level.values())  # walls reach the higher ceiling: no gap above a dropped one
    P=lambda a,b,axis:bool(plan[min(max(a,0),U-1),min(max(b,0),V-1)] if axis==0 else plan[min(max(b,0),U-1),min(max(a,0),V-1)])
    for axis in (0,1):
        for step in (1,-1):
            normal=(bx if axis==0 else ax)*step;outward=[round(float(normal[0]),4),round(float(normal[1]),4)]
            for b,a0,a1,*_ in edge_runs(plan,axis,step,2):
                if a1-a0<3:continue  # corner steps
                mid=int(round(b));line=(b+(1 if step>0 else 0))*CELL
                inside=[P(a,mid+step,axis) for a in (a0-1,a1)]
                e0,e1=((-T if i else 0.) if axis else (0. if i else T) for i in inside)
                # The viewer cuts a wall run as a whole, judged at its middle (anchor). A run with more
                # room within BEHIND behind it is a partition: in the overview it is always a stub.
                at_=lambda a,c:(a,c) if axis==0 else (c,a);ra=(a0+a1)/2
                anchor=[round(float(v_),3) for v_ in world(*((u0+ra*CELL,v0+line) if axis==0 else (u0+line,v0+ra*CELL)))]
                beyond=[at_(int(a0+(a1-a0)*f),mid+step*k) for f in (.25,.5,.75) for k in range(3,int(BEHIND/CELL))]
                extra={'anchor':anchor,**({'behind':True} if any(0<=i<U and 0<=k<V and plan[i,k] for i,k in beyond) else {})}
                def piece(p0,p1,y0,y1,colour,depth=T,f0=0.,f1=0.):
                    along=(p0+p1)/2*CELL+(f1-f0)/2;length=(p1-p0)*CELL+f0+f1;across=line+step*T/2
                    if length<.02:return  # a stub shorter than the walls it sits between
                    cu,cv=(u0+along,v0+across) if axis==0 else (u0+across,v0+along);su,sv=(length,depth) if axis==0 else (depth,length)
                    add('wall','box',cu,cv,y0,y1,su,sv,colour,outward=outward,**extra)
                for end,e in ((a0,e0),(a1,e1)):
                    if e>0:piece(end,end,fy,ty,wall_rgb,**{'f0' if end==a0 else 'f1':e})  # outside corner block
                cut=a0;f0,f1=min(e0,0.),min(e1,0.)
                # Openings stay clear of a wall this one stops short of at an inside corner (no overlap):
                # one that reaches into it slides along, keeping its width where the run allows.
                lo,hi=a0+math.ceil(-f0/CELL-1e-9),a1-math.ceil(-f1/CELL-1e-9)
                for d0,d1,col,kind in openings(axis,step,line,a0,a1) if ty-fy>DOOR+.15 else []:
                    w_=d1-d0;d0,d1=max(d0,lo,cut),min(max(d1,max(lo,cut)+w_),hi);d0=max(min(d0,d1-w_),lo,cut)
                    if (d1-d0)*CELL<.3:continue
                    if d0>cut:piece(cut,d0,fy,ty,wall_rgb,f0=f0 if cut==a0 else 0.)
                    top_=DOOR if kind=='door' else DOOR+.1;piece(d0,d1,fy+top_,ty,wall_rgb);piece(d0,d1,fy,fy+top_,col,depth=.04);cut=d1
                if cut<a1:piece(cut,a1,fy,ty,wall_rgb,f0=f0 if cut==a0 else 0.,f1=f1)
    # Objects (2.5D): per plan cell, the top run of solid voxels, away from walls. Neighbouring cells
    # join only when their tops share a BAND, so a table and what stands on it separate. Soft,
    # semi-transparent splats count too, and only material below the dropped-ceiling line: soffits,
    # cornices and the AC above it would otherwise be the top run and hide what stands beneath.
    # A second pass below LOW finds what a tabletop or an overhang hides (chairs, bottles, a toilet).
    inner=ndimage.binary_erosion(plan,iterations=2);ceiling_line=np.minimum(top,at(planes[2],x,z))-.15
    Y=int(3/CELL)+1;iy=np.clip(((y-floor)/CELL).astype(int),0,Y-1);levels=np.arange(Y)
    def split(cells):
        # Items packed together (bottles and chairs under a table) touch through thin necks: erode, label
        # the cores, and give every cell to its nearest core.
        (a0_,b0_),(a1_,b1_)=cells.min(0),cells.max(0)+1;m=np.zeros((a1_-a0_,b1_-b0_),bool);m[cells[:,0]-a0_,cells[:,1]-b0_]=True
        cores,count=ndimage.label(ndimage.binary_erosion(m,iterations=2))
        if count<2:return [cells]
        _,(ni_,nk_)=ndimage.distance_transform_edt(cores==0,return_indices=True);who=cores[ni_,nk_][m]
        return [cells[who==k] for k in range(1,count+1) if (who==k).sum()>=MIN_CELLS]
    def layer(cap,split_big=False):
        keep=(alpha>.25)&(y>floor+.08)&(y<cap)&inner[iu,iv]
        mass=np.zeros((U,V,Y));np.add.at(mass,(iu[keep],iv[keep],iy[keep]),alpha[keep]);solid=mass>=.6
        column=solid.sum(2)>=2;top_i=np.where(solid,levels,-1).max(2)
        bridged=solid|np.roll(solid,1,2)&np.roll(solid,-1,2)  # one-voxel gaps do not end a run
        base_i=np.where(~bridged&(levels<top_i[...,None]),levels,-1).max(2)+1
        # Supported: solid material ends at most 0.3 below the top run (a shelf's body, not a pile under a lamp).
        under=base_i-1-np.where(solid&(levels<base_i[...,None]),levels,-99).max(2)<=round(.3/CELL)
        band=np.where(column,top_i*CELL//BAND+1,0).astype(int);pieces=[]
        for b in np.unique(band[band>0]):
            lab,_=ndimage.label(ndimage.binary_opening(band==b))  # opening cuts 1-2 cell bridges between items
            for j,sl in enumerate(ndimage.find_objects(lab),1):
                cells=np.argwhere(lab[sl]==j)+[sl[0].start,sl[1].start]
                big=split_big and (cells.max(0)-cells.min(0)+1).max()>round(.6/CELL)
                pieces+=[c_ for c_ in (split(cells) if big else [cells]) if len(c_)>=MIN_CELLS]
        pieces=sorted(pieces,key=len,reverse=True)[:MAX_OBJECTS];owner=np.zeros((U,V),int)
        for j,cells in enumerate(pieces,1):owner[cells[:,0],cells[:,1]]=j
        # Group splat indices by piece once instead of scanning every splat per piece. Colour comes
        # from each piece's own height run only, not from whatever stands underneath it.
        own=keep&(iy>=base_i[iu,iv])&(iy<=top_i[iu,iv]);point_owner=np.where(own,owner[iu,iv],0);idx=np.flatnonzero(point_owner);idx=idx[np.argsort(point_owner[idx],kind='stable')]
        labels,starts=np.unique(point_owner[idx],return_index=True)
        members={label:idx[a:b] for label,a,b in zip(labels,starts,np.append(starts[1:],len(idx)))}
        return [(cells,top_i[cells[:,0],cells[:,1]],base_i[cells[:,0],cells[:,1]],under[cells[:,0],cells[:,1]],members.get(j,np.zeros(0,int))) for j,cells in enumerate(pieces,1)]
    # Every piece stands on the floor, squared to the walls and kept inside the plan. One whose top run
    # starts high still stands when there is solid material under it (a shelf with things on top); one
    # with open space under most of its top is a table. Anything else raised would float, and a thin,
    # tall piece is an open door or a jamb: both are dropped. Pieces may sit under a table; any other
    # overlap is cut back, and a piece mostly inside another is dropped.
    taken=[]  # [r0,c0,r1,c1,top,table]
    for low_pass,(cells,tops,bases,und,memb) in [(False,p_) for p_ in layer(ceiling_line)]+[(True,p_) for p_ in layer(floor+LOW,split_big=True)]:
        if len(memb)<200:continue  # too few splats to be a real object
        lo=np.percentile(bases,10)*CELL;hi=(np.percentile(tops,90)+1)*CELL
        (r0,c0),(r1,c1)=cells.min(0),cells.max(0)+1;area=(r1-r0)*(c1-c0)
        table=not low_pass and .55<hi<1.05 and min(r1-r0,c1-c0)*CELL>.4 and np.mean(bases*CELL>.35)>.5  # the low pass sees under tables
        if hi<.1 or not(lo<.6 or und.mean()>.3 or table) or (hi>1.6 and min(r1-r0,c1-c0)*CELL<.35):continue
        grid_=np.zeros((r1-r0,c1-c0),bool);grid_[cells[:,0]-r0,cells[:,1]-c0]=True;k0,k1=max(2,(r1-r0)//4),max(2,(c1-c0)//4)  # 2+ cells: the opening always clips a single corner cell
        corners=np.mean([grid_[:k0,:k1].mean(),grid_[:k0,-k1:].mean(),grid_[-k0:,:k1].mean(),grid_[-k0:,-k1:].mean()])
        ev=np.linalg.eigvalsh(np.cov(cells.T.astype(float))+np.eye(2)*1e-6);isotropic=ev[1]/ev[0]<1.4  # a diagonal suitcase is not round
        plan_fill=len(cells)/area;solid_fill=float(np.clip(tops-bases+1,0,None).sum())*CELL**3/(area*CELL*CELL*hi)
        while (r1-r0)>=3 and (c1-c0)>=3 and not plan[r0:r1,c0:c1].all():  # shrink the side poking out of the plan
            out_=~plan[r0:r1,c0:c1];side=int(np.argmax([out_[0].sum(),out_[-1].sum(),out_[:,0].sum(),out_[:,-1].sum()]))
            r0,r1,c0,c1=(r0+(side==0),r1-(side==1),c0+(side==2),c1-(side==3))
        item=max(r1-r0,c1-c0)<=round(.6/CELL)
        under_table=lambda t:t[5] and item and hi<=t[4]-.1  # an item-sized piece lower than a tabletop sits under it
        clear=True
        for t in taken:
            t0,s0,t1,s1=t[:4];ou,ov=min(r1,t1)-max(r0,t0),min(c1,s1)-max(c0,s0)
            if ou<=0 or ov<=0 or under_table(t):continue
            if ou*ov>.5*(r1-r0)*(c1-c0):clear=False;break  # mostly inside it
            # Cut back to whichever one-sided cut keeps the most.
            r0,c0,r1,c1=max(((r0,c0,min(r1,t0),c1),(max(r0,t1),c0,r1,c1),(r0,c0,r1,min(c1,s0)),(r0,max(c0,s1),r1,c1)),key=lambda q:max(0,q[2]-q[0])*max(0,q[3]-q[1]))
        if not clear or (r1-r0)<4 or (c1-c0)<4 or any(min(r1,t[2])>max(r0,t[0]) and min(c1,t[3])>max(c0,t[1]) and not under_table(t) for t in taken):continue
        table=table and min(r1-r0,c1-c0)*CELL>.4  # a cut-back table too narrow for legs is a box
        taken.append([r0,c0,r1,c1,hi,table])
        if table:taken+=[[a_,b_,a_+2,b_+2,hi,False] for a_ in (r0,r1-2) for b_ in (c0,c1-2)]  # its legs: what sits under it keeps clear
        wa,wb=(r1-r0)*CELL,(c1-c0)*CELL;cu,cv=u0+(r0+r1)/2*CELL,v0+(c0+c1)/2*CELL;y1=fy+hi
        # Colour: the side-facing splats (a table's top surface), without the darkest quarter. Many splats
        # carry a dark base colour and get their brightness from view-dependent terms; the brighter half
        # alone would turn a black fridge with magnets white.
        face=memb[(np.abs(n[memb,1])>.7)&(y[memb]>floor[memb]+hi-.08)] if table else memb[np.abs(n[memb,1])<.5]
        c_=rgb[face if len(face)>=50 else memb];lum=c_@LUMA;colour=np.median(c_[lum>=np.percentile(lum,25)],0)
        if abs(float((colour-floor_rgb)@LUMA))<.12:colour=colour*.7  # set furniture apart from a floor of the same value
        if table:  # a thin top on four legs, not a crate
            add('object','box',cu,cv,y1-.04,y1,wa,wb,colour)
            for sx in (-1,1):
                for sz in (-1,1):add('object','cylinder',cu+sx*(wa/2-.06),cv+sz*(wb/2-.06),fy,y1-.04,.05,.05,colour)
        elif max(wa,wb,hi)/min(wa,wb,hi)<1.3 and .4<solid_fill<.7 and .15<max(wa,wb,hi)<.7:
            dia=min(wa,wb,(wa+wb+hi)/3);add('object','sphere',cu,cv,fy,fy+dia,dia,dia,colour)
        elif max(wa,wb)/min(wa,wb)<1.3 and isotropic and (.6<plan_fill<.88 or (corners<.35 and plan_fill>.55)):  # round: empty corners
            dia=min(wa,wb);add('object','cylinder',cu,cv,fy,y1,dia,dia,colour)  # stays inside its rectangle
        else:add('object','box',cu,cv,fy,y1,wa,wb,colour)
    kinds={k:sum(s['kind']==k for s in out) for k in ['floor','ceiling','wall','object']}
    types={t:sum(s['type']==t for s in out) for t in ['box','cylinder','sphere']}
    return {'version':1,'units':'normalized scene units, +Y up; yaw is three.js rotation.y','manhattanYaw':round(theta,5),
        'source':{'file':Path(model).name,'sha256':hashlib.file_digest(open(model,'rb'),'sha256').hexdigest()},
        'counts':{**kinds,**types},'shapes':out}

if __name__=='__main__':
    if len(sys.argv)!=4:raise SystemExit(__doc__)
    model,cameras,output=sys.argv[1:]
    result=shapes(model,json.loads(Path(cameras).read_text())['occupiedShell'])
    Path(output).write_text(json.dumps(result,separators=(',',':')))
    print(json.dumps({k:v for k,v in result.items() if k!='shapes'},indent=1))
