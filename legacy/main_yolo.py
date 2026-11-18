"""Annotate a finished panorama with YOLO boxes; independent of main.py.

Run with an environment that has ultralytics and torch installed. The default
input is the full, translation-stabilized panorama copied into output1.
"""

import argparse
import csv
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import cv2
import torch
os.environ.setdefault("YOLO_CONFIG_DIR", str(Path(__file__).resolve().parent / "output1" / ".yolo_config"))
from ultralytics import YOLOWorld


ROOT = Path(__file__).resolve().parent
DEFAULT_CLASSES = (0, 1, 2, 3)  # person, bicycle, car, motorcycle (COCO)
COLORS = {0: (64, 220, 80), 1: (255, 190, 70), 2: (60, 165, 255), 3: (200, 100, 255)}


def ffmpeg_executable():
    from_path = shutil.which("ffmpeg")
    if from_path:
        return from_path
    binaries = ROOT / ".venv" / "Lib" / "site-packages" / "imageio_ffmpeg" / "binaries"
    candidates = sorted(binaries.glob("ffmpeg*.exe"))
    if candidates:
        return str(candidates[0])
    raise FileNotFoundError("ffmpeg not found in PATH or the project .venv")


def arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=ROOT / "output1" / "panorama_stabilized_source.mp4")
    parser.add_argument("--output", type=Path, default=ROOT / "output1" / "panorama_yolo.mp4")
    parser.add_argument("--model", type=Path, default=ROOT / "models" / "yolov8s-worldv2.pt")
    parser.add_argument("--classes", default="0,1,2,3", help="COCO class IDs; use 'all' for all classes")
    parser.add_argument("--confidence", type=float, default=0.25)
    parser.add_argument("--image-size", type=int, default=960)
    parser.add_argument("--threads", type=int, default=4)
    return parser.parse_args()


def draw_boxes(frame, result, class_names, writer, frame_index, fps):
    boxes = result.boxes
    for xyxy, conf, cls in zip(boxes.xyxy.cpu().numpy(), boxes.conf.cpu().numpy(), boxes.cls.cpu().numpy()):
        class_id = int(cls)
        x1, y1, x2, y2 = (int(round(v)) for v in xyxy)
        color = COLORS.get(class_id, (230, 220, 60))
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2, cv2.LINE_AA)
        label = f"{class_names[class_id]} {float(conf):.2f}"
        (tw, th), baseline = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 2)
        top = max(0, y1 - th - baseline - 8)
        cv2.rectangle(frame, (x1, top), (x1 + tw + 10, top + th + baseline + 8), color, -1)
        cv2.putText(frame, label, (x1 + 5, top + th + 3), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 2, cv2.LINE_AA)
        writer.writerow((frame_index, f"{frame_index / fps:.3f}", class_id, class_names[class_id], f"{float(conf):.4f}", x1, y1, x2, y2))
    return len(boxes)


def main():
    args = arguments()
    for path in (args.input, args.model):
        if not path.is_file():
            raise FileNotFoundError(path)
    if args.input.resolve() == args.output.resolve():
        raise ValueError("Input and output paths must differ")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("YOLO_CONFIG_DIR", str(args.output.parent / ".yolo_config"))
    torch.set_num_threads(max(1, args.threads))

    capture = cv2.VideoCapture(str(args.input))
    if not capture.isOpened():
        raise RuntimeError(f"Cannot open {args.input}")
    fps = capture.get(cv2.CAP_PROP_FPS)
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    expected = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    if fps <= 0 or width <= 0 or height <= 0:
        raise RuntimeError("Invalid video metadata")
    model = YOLOWorld(str(args.model))
    classes = None if args.classes.lower() == "all" else [int(v) for v in args.classes.split(",")]

    partial_video = args.output.with_name(args.output.stem + ".partial.mp4")
    csv_path = args.output.with_suffix(".csv")
    partial_csv = csv_path.with_name(csv_path.stem + ".partial.csv")
    ffmpeg_log = args.output.with_suffix(".ffmpeg.log")
    command = [ffmpeg_executable(), "-hide_banner", "-loglevel", "error", "-y",
               "-f", "rawvideo", "-pixel_format", "bgr24", "-video_size", f"{width}x{height}",
               "-framerate", f"{fps:.8f}", "-i", "pipe:0", "-an", "-c:v", "libx264",
               "-preset", "fast", "-crf", "20", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
               str(partial_video)]
    start = time.monotonic()
    count = 0
    detections = 0
    try:
        with partial_csv.open("w", newline="", encoding="utf-8") as csv_file, ffmpeg_log.open("wb") as log_file:
            writer = csv.writer(csv_file)
            writer.writerow(("frame", "seconds", "class_id", "class", "confidence", "x1", "y1", "x2", "y2"))
            encoder = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=log_file)
            try:
                while True:
                    ok, frame = capture.read()
                    if not ok:
                        break
                    result = model.predict(frame, imgsz=args.image_size, conf=args.confidence,
                                           classes=classes, verbose=False, device="cpu")[0]
                    detections += draw_boxes(frame, result, model.names, writer, count, fps)
                    encoder.stdin.write(frame.tobytes())
                    count += 1
                    if count % 150 == 0:
                        print(f"{count}/{expected} frames, {detections} boxes, {time.monotonic()-start:.0f}s", flush=True)
                encoder.stdin.close()
                if encoder.wait() != 0:
                    raise RuntimeError(f"ffmpeg failed; see {ffmpeg_log}")
            except BaseException:
                if encoder.poll() is None:
                    encoder.kill()
                    encoder.wait()
                raise
        if expected and count != expected:
            raise RuntimeError(f"Decoded {count} of {expected} expected frames")
        partial_video.replace(args.output)
        partial_csv.replace(csv_path)
        print(f"DONE {args.output} | frames={count} fps={fps:.3f} boxes={detections} elapsed={time.monotonic()-start:.1f}s", flush=True)
    finally:
        capture.release()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
