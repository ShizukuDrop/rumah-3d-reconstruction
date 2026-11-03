"""Compare fresh anchor poses with a reference reconstruction, not ground truth.

Reads COLMAP image headers without loading observation or point-cloud arrays.
The shared similarity transform removes arbitrary world axes and scale. Eval
images never participate in this fit. Agreement cannot certify a correct model.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import struct
import numpy as np
from .capture import sha256


def rotation(q):
    q = np.asarray(q, dtype=float)
    if q.shape != (4,) or not np.isfinite(q).all() or abs(np.linalg.norm(q)-1) > 1e-4:
        raise ValueError('Invalid COLMAP quaternion')
    w,x,y,z = q / np.linalg.norm(q)
    return np.array([[1-2*y*y-2*z*z,2*x*y-2*w*z,2*x*z+2*w*y],
                     [2*x*y+2*w*z,1-2*x*x-2*z*z,2*y*z-2*w*x],
                     [2*x*z-2*w*y,2*y*z+2*w*x,1-2*x*x-2*y*y]])


def read_pose_headers(path):
    result = {}
    path = Path(path)
    length = path.stat().st_size
    with path.open('rb') as f:
        count = struct.unpack('<Q', f.read(8))[0]
        if count > length // 73:
            raise ValueError('Invalid image count')
        for _ in range(count):
            fields = struct.unpack('<i7di', f.read(64))
            name = bytearray()
            while (c := f.read(1)) != b'\0':
                if not c or len(name) > 10000:
                    raise ValueError('Invalid image name')
                name.extend(c)
            name = name.decode('utf-8')
            n = struct.unpack('<Q', f.read(8))[0]
            if f.tell() + n*24 > length:
                raise ValueError('Truncated observations')
            f.seek(n*24, 1)
            if name in result:
                raise ValueError('Duplicate image name')
            R = rotation(fields[1:5])
            t = np.array(fields[5:8])
            if not np.isfinite(t).all():
                raise ValueError('Nonfinite camera center')
            result[name] = {'id':fields[0], 'camera_id':fields[8], 'R':R,
                            'center':-R.T @ t, 'feature_count':n}
        if f.tell() != length:
            raise ValueError('Unexpected trailing image data')
    return result


def similarity(source, target):
    a, b = np.asarray(source, dtype=float), np.asarray(target, dtype=float)
    if a.shape != b.shape or a.ndim != 2 or a.shape[1] != 3 or len(a) < 3:
        raise ValueError('Need at least three corresponding 3D centers')
    ca, cb = a.mean(axis=0), b.mean(axis=0)
    aa, bb = a-ca, b-cb
    if np.linalg.matrix_rank(aa, tol=1e-10) < 2:
        raise ValueError('Similarity is underdetermined by collinear centers')
    U, S, Vt = np.linalg.svd(bb.T @ aa / len(a))
    sign = np.ones(3)
    sign[-1] = np.linalg.det(U @ Vt)
    Q = U @ np.diag(sign) @ Vt
    scale = float(np.dot(S, sign) / np.mean(np.sum(aa*aa, axis=1)))
    if scale <= 0:
        raise ValueError('Invalid similarity scale')
    return scale, Q, cb-scale*(Q@ca)


def distribution(values):
    a = np.asarray(values, dtype=float)
    return {'count':len(a), **({f'p{q}':float(np.percentile(a,q)) for q in [50,90,95,99,100]} if len(a) else {})}


def largest_frame_gap(region, registered_rows):
    """Include the gaps between the first/last registration and room boundary."""
    first = region['source_frame_min']
    last = region['source_frame_max']
    ids = [first, *sorted({row['id'] for row in registered_rows}), last]
    start, end = max(zip(ids, ids[1:]), key=lambda pair: pair[1] - pair[0])
    return {'from_frame': start, 'to_frame': end, 'source_frames': end - start}


def compare(reference, candidate, selection, regions):
    expected = {name for row in selection['frames'] if row['selected'] for name in row['images'].values()}
    extra = sorted(set(candidate)-expected)
    common = sorted(set(reference) & set(candidate))
    fit_names = [n for n in common if '_train.' in n]
    a = np.array([candidate[n]['center'] for n in fit_names])
    b = np.array([reference[n]['center'] for n in fit_names])
    scale,Q,t = similarity(a,b)
    span = float(2*np.percentile(np.linalg.norm(b-np.median(b,axis=0),axis=1),95))
    if span <= 1e-12:
        raise ValueError('Reference trajectory has no spatial extent')
    errors = []
    for name in common:
        rc, rb = candidate[name], reference[name]
        distance = float(np.linalg.norm(scale*Q@rc['center']+t-rb['center']))
        delta = rb['R'] @ (rc['R'] @ Q.T).T
        angle = float(np.degrees(np.arccos(np.clip((np.trace(delta)-1)/2,-1,1))))
        errors.append({'name':name,'center_difference_reference_units':distance,
                       'center_difference_fraction_trajectory_span':distance/span,
                       'orientation_difference_degrees':angle})
    coverage = []
    for region in regions:
        rows = [r for r in selection['frames'] if region['source_frame_min'] <= r['id'] <= region['source_frame_max']]
        anchors = [r for r in rows if r['selected']]
        complete = lambda r: all(n in candidate for n in r['images'].values())
        reference_complete = lambda r: all(n in reference for n in r['images'].values())
        common_expected = [r for r in anchors if reference_complete(r)]
        registered = [r for r in anchors if complete(r)]
        region_names = {name for row in anchors for name in row['images'].values()}
        region_errors = [r for r in errors if r['name'] in region_names]
        coverage.append({'region':region['name'],'original_pairs':len(rows),'selected_pairs':len(anchors),
                         'registered_complete_selected_pairs':len(registered),
                         'largest_registered_frame_gap':largest_frame_gap(region, registered),
                         'largest_reference_gap_on_selected_frames':largest_frame_gap(region, common_expected),
                         'missing_selected_pair_ids':[r['id'] for r in anchors if not complete(r)],
                         'reference_registered_complete_pairs':sum(reference_complete(r) for r in rows),
                         'reference_registered_complete_selected_pairs':len(common_expected),
                         'lost_reference_registered_selected_pair_ids':[r['id'] for r in common_expected if not complete(r)],
                         'common_orientation_difference_degrees':distribution(
                             [r['orientation_difference_degrees'] for r in region_errors])})
    return {'reference_is_ground_truth':False,'acceptance_passed':False,
            'scope':'Pose agreement and anchor registration only; visual and localization checks still required.',
            'units':'Arbitrary reference reconstruction units; not meters.',
            'registered_candidate_images':len(candidate),'expected_anchor_images':len(expected),
            'missing_expected_images':sorted(expected-set(candidate)), 'unexpected_registered_images':extra,
            'heldout_images_in_fit':0,'similarity_fit_images':len(fit_names),
            'similarity_method':'Untrimmed least-squares Umeyama over all common training camera centers.',
            'candidate_to_reference':{'scale':scale,'rotation':Q.tolist(),'translation':t.tolist()},
            'reference_trajectory_span':span,
            'center_difference_reference_units':distribution([r['center_difference_reference_units'] for r in errors]),
            'center_difference_fraction_trajectory_span':distribution([r['center_difference_fraction_trajectory_span'] for r in errors]),
            'orientation_difference_degrees':distribution([r['orientation_difference_degrees'] for r in errors]),
            'coverage':coverage,'per_image':errors}


def plot_comparison(reference, candidate, report, destination):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    transform=report['candidate_to_reference']
    scale,Q,t=transform['scale'],np.array(transform['rotation']),np.array(transform['translation'])
    names=sorted(n for n in set(reference)&set(candidate) if n.startswith('cam0/'))
    original=np.array([reference[n]['center'] for n in names])
    fresh=np.array([scale*Q@candidate[n]['center']+t for n in names])
    fig,axes=plt.subplots(1,3,figsize=(15,5),layout='constrained')
    for ax,(a,b,label) in zip(axes,[(0,1,'XY'),(0,2,'XZ'),(2,1,'ZY')]):
        ax.scatter(original[:,a],original[:,b],color='#6c7583',s=7,label='Reference: same timestamps')
        ax.scatter(fresh[:,a],fresh[:,b],color='#007baf',s=7,label='Fresh anchors: similarity aligned')
        step=max(1,len(names)//40)
        for i in range(0,len(names),step):
            ax.plot([original[i,a],fresh[i,a]],[original[i,b],fresh[i,b]],color='#db6d32',alpha=.6,linewidth=.7)
        ax.set(xlabel=label[0]+' (arbitrary units)',ylabel=label[1]+' (arbitrary units)')
        ax.set_aspect('equal',adjustable='datalim');ax.grid(alpha=.2)
    axes[0].legend(fontsize=8)
    fig.suptitle('Camera trajectory agreement — reference is not ground truth\n'
                 f'{len(names)} common cam0 poses; missing timestamps and image quality require separate checks',fontsize=12)
    destination=Path(destination);destination.parent.mkdir(parents=True,exist_ok=True)
    fig.savefig(destination,dpi=160);plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['reference','candidate','selection','coverage','output']:
        parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--plot',type=Path)
    args = parser.parse_args()
    selection = json.loads(args.selection.read_text())
    regions = json.loads(args.coverage.read_text())
    if isinstance(regions,dict): regions = regions['regions']
    reference,candidate=read_pose_headers(args.reference/'images.bin'),read_pose_headers(args.candidate/'images.bin')
    result = compare(reference,candidate,selection,regions)
    result['inputs']={key:{'path':str(path.resolve()),'sha256':sha256(path)} for key,path in
                     [('reference_images',args.reference/'images.bin'),('candidate_images',args.candidate/'images.bin'),
                      ('selection',args.selection),('coverage',args.coverage)]}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2))
    if args.plot:plot_comparison(reference,candidate,result,args.plot)
    print(json.dumps({k:v for k,v in result.items() if k not in ('per_image','missing_expected_images','inputs')}))


if __name__ == '__main__': main()
