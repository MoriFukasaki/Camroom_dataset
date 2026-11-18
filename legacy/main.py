"""Stitch the new 1920x1080 three-camera recording in Cam 3, 2, 1 order."""
import argparse
import json
import subprocess
from pathlib import Path

import cv2
import imageio_ffmpeg
import numpy as np


def args_parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input-dir', type=Path, default=Path('inputs'))
    p.add_argument('--config', type=Path, default=Path('configs/panorama.json'))
    p.add_argument('--motion', type=Path, default=Path('configs/motion_keyframes.json'))
    p.add_argument('--output', type=Path, default=Path('outputs/panorama.mp4'))
    p.add_argument('--preview', type=Path, default=Path('outputs/preview.jpg'))
    p.add_argument('--seconds', type=float, default=None)
    return p.parse_args()


def read_frame(cap, number):
    cap.set(cv2.CAP_PROP_POS_FRAMES, int(number))
    ok, frame = cap.read()
    if not ok:
        raise RuntimeError(f'Cannot decode frame {number}')
    return frame


def transform(cfg, cam, half=True, alignment=None):
    H = np.asarray(cfg['homographies_half'][str(cam)], dtype=np.float64)
    if alignment is not None:
        H = alignment @ H
    if half:
        x0, y0, _, _ = cfg['crop_half']
        T = np.array([[1, 0, -x0], [0, 1, -y0], [0, 0, 1]], np.float64)
        return T @ H
    x0, y0, _, _ = cfg['crop_half']
    crop = np.array([[1, 0, -2*x0], [0, 1, -2*y0], [0, 0, 1]], np.float64)
    scale_up = np.diag([2., 2., 1.])
    scale_down = np.diag([.5, .5, 1.])
    return crop @ scale_up @ H @ scale_down


def half_warp(frame, cfg, cam):
    x0, y0, x1, y1 = cfg['crop_half']
    half = cv2.resize(frame, (960, 540), interpolation=cv2.INTER_AREA)
    return cv2.warpPerspective(half, transform(cfg, cam), (x1-x0, y1-y0))


def sample_luts(caps, cfg, last_frames):
    """Fixed, modest Lab correction from shared pavement, sampled over time."""
    samples = {}
    for cam in (3, 2, 1):
        samples[cam] = []
        positions = np.linspace(0, last_frames[cam], 7, dtype=int)
        for n in positions:
            warp = half_warp(read_frame(caps[cam], n), cfg, cam)
            samples[cam].append(cv2.cvtColor(warp, cv2.COLOR_BGR2LAB))
    x0, y0, _, _ = cfg['crop_half']
    lut = {2: np.tile(np.arange(256, dtype=np.uint8)[:, None], (1, 3))}
    for cam, key in ((3, '3-2'), (1, '2-1')):
        xa, ya, xb, yb = cfg['color_patches_half'][key]
        xa, xb, ya, yb = xa-x0, xb-x0, ya-y0, yb-y0
        def quantiles(which):
            pixels = np.concatenate([im[ya:yb:3, xa:xb:3].reshape(-1, 3)
                                     for im in samples[which]])
            pixels = pixels[np.all(pixels > 0, axis=1)]
            return np.percentile(pixels, [10, 50, 90], axis=0)
        source, target = quantiles(cam), quantiles(2)
        gain_l = np.clip((target[2, 0]-target[0, 0]) /
                         max(source[2, 0]-source[0, 0], 1), .9, 1.1)
        gain = np.array([gain_l, 1., 1.])
        shift = np.clip(target[1] - source[1]*gain,
                        [-18, -7, -7], [18, 7, 7])
        strength = np.array([.8, .45, .45])
        values = np.arange(256, dtype=np.float64)[:, None]
        mapped = values + strength[None, :] * (values*gain[None, :] + shift[None, :] - values)
        lut[cam] = np.clip(np.rint(mapped), 0, 255).astype(np.uint8)
        print(f'Cam {cam} color gain {gain.round(3)}, shift {shift.round(1)}', flush=True)
    for cap in caps.values():
        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
    return lut


def correct(frame, table):
    lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
    for channel in range(3):
        lab[:, :, channel] = cv2.LUT(lab[:, :, channel], table[:, channel])
    return cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)


def seam(left, right, cfg, key):
    """A fixed low-difference path; keeping it fixed avoids temporal jitter."""
    x0, y0, _, _ = cfg['crop_half']
    xa, xb = cfg['seam_bands_half'][key]
    xa, xb = xa-x0, xb-x0
    A = cv2.cvtColor(cv2.GaussianBlur(left[:, xa:xb], (5, 5), 0), cv2.COLOR_BGR2LAB)
    B = cv2.cvtColor(cv2.GaussianBlur(right[:, xa:xb], (5, 5), 0), cv2.COLOR_BGR2LAB)
    cost = np.mean(np.abs(A.astype(np.float32)-B.astype(np.float32)), axis=2)
    cost += .025 * np.abs(np.arange(xa, xb)[None, :] - (xa+xb)/2)
    dp = cost[0].copy()
    parent = np.zeros(cost.shape, np.int16)
    for y in range(1, cost.shape[0]):
        choices = np.stack((np.r_[dp[0], dp[:-1]], dp,
                            np.r_[dp[1:], dp[-1]]))
        choices[0, 0] = np.inf
        choices[2, -1] = np.inf
        steps = np.argmin(choices, axis=0)
        parent[y] = np.arange(xb-xa) + steps - 1
        dp = cost[y] + np.min(choices, axis=0)
    path = np.zeros(cost.shape[0], np.int32)
    path[-1] = int(np.argmin(dp))
    for y in range(len(path)-1, 0, -1):
        path[y-1] = parent[y, path[y]]
    return path + xa


class ClockReader:
    """Select the nearest source PTS for each 30 fps output timestamp."""
    def __init__(self, cap):
        self.cap = cap
        self.previous = self._next()
        self.following = self._next()

    def _next(self):
        ok, frame = self.cap.read()
        return (self.cap.get(cv2.CAP_PROP_POS_MSEC), frame) if ok else None

    def at(self, time_ms):
        while self.following is not None and self.following[0] <= time_ms:
            self.previous = self.following
            self.following = self._next()
        if self.following is not None and abs(self.following[0]-time_ms) < abs(self.previous[0]-time_ms):
            return self.following[1]
        return self.previous[1]


class MotionAligner:
    """Interpolate measured camera motion and refine fast jumps on the pavement."""
    def __init__(self, motion_path, cfg, frame_count):
        records = json.loads(motion_path.read_text(encoding='utf-8'))['keyframes']
        points = np.array([entry['frame'] for entry in records])
        if points[0] != 0 or points[-1] < frame_count-1 or np.any(np.diff(points) <= 0):
            raise ValueError('Motion keyframes do not cover this video')
        self.coarse = {}
        for cam in (3, 1):
            values = np.asarray([entry[str(cam)] for entry in records], np.float64)
            table = np.zeros((frame_count, 3, 3), np.float64)
            for row in range(2):
                for col in range(3):
                    table[:, row, col] = np.interp(np.arange(frame_count), points,
                                                   values[:, row, col])
            table[:, 2, 2] = 1
            self.coarse[cam] = table
        self.cfg = cfg
        self.windows = {}
        for cam in (3, 1):
            xa, ya, xb, yb = cfg['phase_regions_crop_half'][str(cam)]
            self.windows[cam] = cv2.createHanningWindow((xb-xa, yb-ya), cv2.CV_32F)

    def alignments(self, frames, frame_number):
        x0, y0, x1, y1 = self.cfg['crop_half']
        half_size = (x1-x0, y1-y0)
        half_frames = {i: cv2.resize(frames[i], (960, 540),
                                    interpolation=cv2.INTER_AREA) for i in (3, 2, 1)}
        center = cv2.warpPerspective(half_frames[2], transform(self.cfg, 2), half_size)
        result = {2: np.eye(3)}
        for cam in (3, 1):
            coarse = self.coarse[cam][frame_number]
            side = cv2.warpPerspective(half_frames[cam],
                                       transform(self.cfg, cam, alignment=coarse), half_size)
            xa, ya, xb, yb = self.cfg['phase_regions_crop_half'][str(cam)]
            a = cv2.cvtColor(side[ya:yb, xa:xb], cv2.COLOR_BGR2GRAY).astype(np.float32)
            b = cv2.cvtColor(center[ya:yb, xa:xb], cv2.COLOR_BGR2GRAY).astype(np.float32)
            shift, confidence = cv2.phaseCorrelate(a, b, self.windows[cam])
            residual = np.asarray(shift) - np.asarray(self.cfg['phase_bias_half'][str(cam)])
            magnitude = np.linalg.norm(residual)
            if confidence > .2 and 2.5 <= magnitude <= 20:
                correction = np.array([[1., 0., residual[0]],
                                       [0., 1., residual[1]], [0., 0., 1.]])
                result[cam] = correction @ coarse
            else:
                result[cam] = coarse
        return result


def combine(warps, paths):
    h, w = warps[2].shape[:2]
    s32, s21 = paths
    result = warps[2].copy()
    weights = np.linspace(0, 1, 6, dtype=np.float32)[:, None]
    # Six-pixel fade only at the cuts; wide blending would double people/trees.
    for y in range(h):
        first, second = int(s32[y]), int(s21[y])
        result[y, :first-3] = warps[3][y, :first-3]
        result[y, second+3:] = warps[1][y, second+3:]
        result[y, first-3:first+3] = (
            warps[3][y, first-3:first+3]*(1-weights) +
            warps[2][y, first-3:first+3]*weights).astype(np.uint8)
        result[y, second-3:second+3] = (
            warps[2][y, second-3:second+3]*(1-weights) +
            warps[1][y, second-3:second+3]*weights).astype(np.uint8)
    return result


def main():
    args = args_parser()
    cfg = json.loads(args.config.read_text(encoding='utf-8'))
    caps = {i: cv2.VideoCapture(str(args.input_dir / f'Cam {i}.mp4')) for i in (3, 2, 1)}
    if not all(cap.isOpened() for cap in caps.values()):
        raise FileNotFoundError('Expected Cam 3.mp4, Cam 2.mp4, Cam 1.mp4')
    if any((int(c.get(3)), int(c.get(4))) != (1920, 1080) for c in caps.values()):
        raise ValueError('This calibration requires 1920x1080 inputs')
    last = {i: int(c.get(cv2.CAP_PROP_FRAME_COUNT))-1 for i, c in caps.items()}
    ends = []
    for i, cap in caps.items():
        read_frame(cap, last[i])
        ends.append(cap.get(cv2.CAP_PROP_POS_MSEC)/1000)
    duration = min(ends)
    if args.seconds is not None:
        duration = min(duration, args.seconds)
    frame_count = int(duration*30)+1
    if args.seconds is not None:
        frame_count = min(frame_count, int(np.ceil(args.seconds*30)))
    if frame_count < 1:
        raise ValueError('No frames to write')
    aligner = MotionAligner(args.motion, cfg, frame_count)
    luts = sample_luts(caps, cfg, last)
    first = {i: read_frame(caps[i], 0) for i in (3, 2, 1)}
    half = {i: half_warp(correct(first[i], luts[i]), cfg, i) for i in (3, 2, 1)}
    paths_half = [seam(half[3], half[2], cfg, '3-2'),
                  seam(half[2], half[1], cfg, '2-1')]
    # Convert half-resolution seam coordinates into the output raster.
    paths = [np.interp(np.arange(2*len(p))/2, np.arange(len(p)), p)*2
             for p in paths_half]
    x0, y0, x1, y1 = cfg['crop_half']
    size = (2*(x1-x0), 2*(y1-y0))
    for cap in caps.values():
        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
    readers = {i: ClockReader(caps[i]) for i in (3, 2, 1)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.preview.parent.mkdir(parents=True, exist_ok=True)
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    command = [ff, '-y', '-hide_banner', '-loglevel', 'error', '-f', 'rawvideo',
               '-pix_fmt', 'bgr24', '-s', f'{size[0]}x{size[1]}', '-r', '30',
               '-i', '-', '-an', '-c:v', 'libx264', '-preset', 'veryfast',
               '-crf', '20', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(args.output)]
    proc = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        for n in range(frame_count):
            frames = {i: correct(readers[i].at(n*1000/30), luts[i]) for i in (3, 2, 1)}
            alignments = aligner.alignments(frames, n)
            matrices = {i: transform(cfg, i, half=False, alignment=alignments[i])
                        for i in (3, 2, 1)}
            warps = {i: cv2.warpPerspective(frames[i], matrices[i], size) for i in (3, 2, 1)}
            output = combine(warps, paths)
            if n == 0:
                cv2.imwrite(str(args.preview), output)
            proc.stdin.write(output.tobytes())
            if n % 300 == 0:
                print(f'{n}/{frame_count} frames', flush=True)
    finally:
        for cap in caps.values():
            cap.release()
        proc.stdin.close()
        err = proc.stderr.read().decode(errors='replace')
        status = proc.wait()
    if status:
        raise RuntimeError(f'ffmpeg exit {status}: {err}')
    print(f'Saved {args.output} ({frame_count/30:.2f} seconds)')


if __name__ == '__main__':
    main()
