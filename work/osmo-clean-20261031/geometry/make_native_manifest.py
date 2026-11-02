"""Create the clean 3840-square SfM manifest without reading old reconstruction poses.

Only camera calibration is reused. All output is confined to this directory.
The native source is KB5; the installed SfM supports OPENCV_FISHEYE (KB4).
The already validated KB5->KB4 approximation is scaled in pixel units, not
re-fitted to the previous scene. No metric baseline is invented.
"""
from pathlib import Path
import argparse
import hashlib
import json
import math
import struct
import numpy as np

HERE = Path(__file__).resolve().parent
FORMAT = HERE.parents[1] / 'osmo-format-20261031'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def quat(record):
    fields = record['cam_extri_q']
    q = np.array([fields.get(str(i), 0.0) for i in range(1, 5)])
    return q / np.linalg.norm(q)


def mul(a, b):
    aw, ax, ay, az = a
    bw, bx, by, bz = b
    return np.array([aw*bw-ax*bx-ay*by-az*bz,
                     aw*bx+ax*bw+ay*bz-az*by,
                     aw*by-ax*bz+ay*bw+az*bx,
                     aw*bz+ax*by-ay*bx+az*bw])


def raw_slot_audit(path):
    def varint(data, pos):
        value = shift = 0
        while True:
            b = data[pos]; pos += 1; value |= (b & 127) << shift
            if b < 128:
                return value, pos
            shift += 7
            if shift > 70:
                raise ValueError('Invalid protobuf varint')
    def fields(data):
        out = {}; pos = 0
        while pos < len(data):
            key, pos = varint(data, pos); field, wire = key >> 3, key & 7
            if wire == 0:
                value, pos = varint(data, pos)
            elif wire == 5:
                value = struct.unpack_from('<f', data, pos)[0]; pos += 4
            elif wire == 1:
                value = struct.unpack_from('<d', data, pos)[0]; pos += 8
            elif wire == 2:
                size, pos = varint(data, pos); value = data[pos:pos+size]; pos += size
            else:
                raise ValueError('Unsupported protobuf wire type')
            out.setdefault(field, []).append(value)
        return out
    root = fields(path.read_bytes()); stream = fields(root[2][0]); pano = fields(stream[5][0])
    result = []
    for n, values in sorted(pano.items()):
        slot = fields(values[0])
        result.append({'slot': n, 'record_bytes': len(values[0]),
                       'fx': slot.get(1, [None])[0], 'fy': slot.get(2, [None])[0],
                       'width': slot.get(10, [None])[0], 'height': slot.get(11, [None])[0],
                       'has_extrinsic_quaternion': 28 in slot,
                       'usable_intrinsics': all(slot.get(f, [0])[0] > 0 for f in (1, 2, 10, 11))})
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--image-dir', type=Path, required=True, help='Native 3840 dataset/images folder (cam0/, cam1/)')
    args = parser.parse_args()
    cal_path = FORMAT / 'calibration.json'
    fit_path = FORMAT / 'kb4-fit-report.json'
    raw_path = FORMAT / 'djmd-first.bin'
    missing = [str(p) for p in (cal_path, fit_path, raw_path) if not p.is_file()] + ([] if args.image_dir.is_dir() else [str(args.image_dir)])
    if missing:
        raise FileNotFoundError('Missing inputs, nothing written: ' + ', '.join(missing))
    raw_sha, raw_slots = sha(raw_path), raw_slot_audit(raw_path)
    cal = json.loads(cal_path.read_text())
    fit = json.loads(fit_path.read_text())
    assert fit['resolution'] == [1920, 1920], 'Unexpected previous calibration resolution'
    cameras, validations = [], []
    for lens in range(2):
        native = cal['slots'][str(lens + 1)]
        assert native['width'] == 3840 and native['height'] == 3840
        approx = fit['fits'][lens]
        params = np.asarray(approx['opencv_fisheye_params'], dtype=float).copy()
        params[:4] *= 2.0
        assert np.allclose(params[2:4], [native['cx'], native['cy']], rtol=0, atol=1e-8)
        assert np.isfinite(params).all() and params[0] > 0 and params[1] > 0
        theta_max = math.radians(approx['theta_max_degrees'])
        theta = np.linspace(0, theta_max, 100001)
        native_radius = native['fx'] * theta * (1 + sum(native[f'k{i}'] * theta**(2*i) for i in range(1, 6)))
        fitted_radius = params[0] * theta * (1 + sum(params[i+3] * theta**(2*i) for i in range(1, 5)))
        error = np.abs(fitted_radius - native_radius)
        assert error.max() < 1.3, 'KB approximation exceeds its validated envelope'
        cameras.append({'prefix': f'cam{lens}', 'model': 'opencv-fisheye', 'params': params.tolist()})
        validations.append({'lens': lens, 'native_width': 3840, 'native_height': 3840,
                            'max_theta_deg': approx['theta_max_degrees'],
                            'max_radial_error_native_px': float(error.max()),
                            'rms_radial_error_native_px': float(np.sqrt(np.mean(error**2))),
                            'native_tangential_p_not_represented': native['p']})
    q0, q1 = quat(cal['slots']['1']), quat(cal['slots']['2'])
    q10 = mul(q1, q0 * [1, -1, -1, -1])
    q10 /= np.linalg.norm(q10)
    manifest = {'image_dir': args.image_dir.resolve().as_posix(), 'camera_mode': 'folder',
                'cameras': cameras, 'rigs': [{'name': 'osmo360ii-native-clean-v3', 'kind': 'dual-fisheye',
                'members': [{'prefix': 'cam0', 'rotation': [1, 0, 0, 0], 'translation': [0, 0, 0], 'fixed': True},
                            {'prefix': 'cam1', 'rotation': q10.tolist(), 'translation': [0, 0, 0],
                             'fixed': False, 'refine': 'axial'}]}]}
    output, validation = HERE / 'sfm-manifest-native3840.json', HERE / 'manifest-validation.json'
    # Written via .partial files and renamed only after every input was read; write_text keeps the platform newline the hash records.
    manifest_partial, validation_partial = output.with_name(output.name + '.partial'), validation.with_name(validation.name + '.partial')
    manifest_partial.write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    report = {'calibration_file': str(cal_path), 'calibration_sha256': sha(cal_path),
              'fit_file': str(fit_path), 'fit_sha256': sha(fit_path),
              'manifest_sha256': sha(manifest_partial), 'image_dir': manifest['image_dir'],
              'source_slots_available': sorted(cal['slots'], key=int),
              'far_distance_slots_available': [str(i) for i in range(13, 25) if str(i) in cal['slots']],
              'validated_radial_approximation': validations,
              'rotation_convention': 'w,x,y,z; source cam_extri_q maps body to lens; cam1_from_cam0 = q1 * inverse(q0)',
              'translation_convention': 'cam_from_rig translation, not camera-center coordinates; units become arbitrary SfM model units',
              'baseline_policy': 'Zero initialization only; cam1 axial refinement allows 3 rotation parameters plus its own t.z. No measured optical-center separation is available.',
              'metric_scale': 'unknown; far_XX stitching presets are not a surveyed metric lens separation',
              'reconstruction_reused': False,
              'limitations': ['KB5 radial approximation is validated only to the recorded angle; it omits native tangential p terms.',
                              'This calibration does not prove frame synchronization, image orientation, or recovered geometry; audit fresh SfM separately.',
                              'Keep synchronized source-frame filenames identical between cam0 and cam1.']}
    report['raw_djmd_first_sample_sha256'] = raw_sha
    report['raw_calibration_slots'] = raw_slots
    report['far_distance_slot_note'] = ('Raw slots13-24 exist as placeholder records, but contain no fx/fy/width/height/extrinsic quaternion. '
                                       'They cannot establish a baseline for this clip. The decoded JSON omits unusable slots.')
    validation_partial.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    manifest_partial.replace(output); validation_partial.replace(validation)
    print(json.dumps({'manifest': str(output), 'validation': validations,
                      'far_distance_slots_available': report['far_distance_slots_available'],
                      'metric_scale': report['metric_scale']}, indent=2))


if __name__ == '__main__':
    main()
