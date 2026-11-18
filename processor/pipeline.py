"""Calibrate fixed cameras, synchronize source timestamps, stitch and annotate once."""
import argparse
import copy
import csv
import json
import math
import os
from pathlib import Path
import subprocess
import sys

import cv2
import numpy as np


class CalibrationRequired(RuntimeError):
    pass


def emit(message, **values):
    print(json.dumps({'message': message, **values}, ensure_ascii=False), flush=True)


def matrix_for(side, center, points=None):
    """Normalize manual points or robustly match static background features."""
    if points:
        src=np.float32([p['source'] for p in points])*[side.shape[1],side.shape[0]]
        dst=np.float32([p['target'] for p in points])*[center.shape[1],center.shape[0]]
    else:
        features=cv2.SIFT_create(nfeatures=8000,contrastThreshold=.02)
        ka,da=features.detectAndCompute(cv2.cvtColor(side,cv2.COLOR_BGR2GRAY),None)
        kb,db=features.detectAndCompute(cv2.cvtColor(center,cv2.COLOR_BGR2GRAY),None)
        if da is None or db is None: raise CalibrationRequired('Không tìm thấy đặc trưng chung. Chọn điểm căn ghép thủ công.')
        pairs=cv2.BFMatcher(cv2.NORM_L2).knnMatch(da,db,k=2)
        good=[a for pair in pairs if len(pair)==2 for a,b in [pair] if a.distance<.7*b.distance]
        if len(good)<18: raise CalibrationRequired('Quá ít điểm chung; kiểm tra vùng chồng lấp hoặc chọn điểm thủ công.')
        src=np.float32([ka[m.queryIdx].pt for m in good]);dst=np.float32([kb[m.trainIdx].pt for m in good])
    H,inliers=cv2.findHomography(src,dst,cv2.RANSAC,3.0)
    if H is None or not np.isfinite(H).all() or abs(np.linalg.det(H))<1e-9: raise CalibrationRequired('Điểm căn ghép suy biến; chọn điểm phân bố rộng, không cùng một đường thẳng.')
    use=inliers.ravel().astype(bool)
    if use.sum()<(4 if points else 15) or use.mean()<.35: raise CalibrationRequired('Phép ghép thiếu tin cậy. Cần căn thủ công.')
    if cv2.contourArea(cv2.convexHull(np.float32(src[use]))) < side.shape[0]*side.shape[1]*.005: raise CalibrationRequired('Các điểm quá gần nhau/cùng đường thẳng; chọn thêm điểm rải rộng.')
    errors=np.linalg.norm(cv2.perspectiveTransform(src[None].astype(np.float32),H)[0]-dst,axis=1)
    if np.median(errors[use])>3: raise CalibrationRequired('Sai số căn ghép quá lớn.')
    return H, {'inliers':int(use.sum()),'matches':len(src),'median_error':float(np.median(errors[use]))}


def geometry(frames, calibration=None):
    matrices={2:np.eye(3)}; metrics={}
    for slot in (3,1): matrices[slot],metrics[str(slot)]=matrix_for(frames[slot],frames[2],(calibration or {}).get('points',{}).get(str(slot)))
    corners=[]
    for slot,frame in frames.items():
        h,w=frame.shape[:2];corners.append(cv2.perspectiveTransform(np.float32([[[0,0],[w,0],[w,h],[0,h]]]),matrices[slot])[0])
    bounds=np.concatenate(corners);lo=np.floor(bounds.min(axis=0));hi=np.ceil(bounds.max(axis=0));size=np.int32(hi-lo)
    maxw=max(f.shape[1] for f in frames.values());maxh=max(f.shape[0] for f in frames.values())
    if min(size)<64 or size[0]>maxw*6 or size[1]>maxh*3: raise CalibrationRequired('Canvas ghép bất thường; kiểm tra điểm và thứ tự camera.')
    # H.264 requires even dimensions. Work at source resolution; no upscaling.
    size=(int(size[0])//2*2,int(size[1])//2*2)
    shift=np.array([[1,0,-lo[0]],[0,1,-lo[1]],[0,0,1.]])
    matrices={i:shift@H for i,H in matrices.items()}
    centers={i:cv2.perspectiveTransform(np.float32([[[f.shape[1]/2,f.shape[0]/2]]]),matrices[i])[0,0,0] for i,f in frames.items()}
    if not centers[3]<centers[2]<centers[1]:raise CalibrationRequired('Vị trí phải là CAM 3 trái, CAM 2 giữa, CAM 1 phải. Kiểm tra slot và điểm.')
    masks={i:cv2.warpPerspective(np.full(f.shape[:2],255,np.uint8),matrices[i],size,flags=cv2.INTER_NEAREST)>0 for i,f in frames.items()}
    for i in (3,1):
        if np.count_nonzero(masks[i]&masks[2])<min(masks[i].sum(),masks[2].sum())*.04: raise CalibrationRequired('Vùng nhìn chung quá ít để ghép an toàn.')
    return matrices,masks,size,metrics


class Reader:
    """Decode sequentially using source presentation timestamps, not frame number."""
    def __init__(self,path,offset,maps=None):
        self.cap=cv2.VideoCapture(str(path));self.offset=offset;self.frame=None;self.time=-1;self.maps=maps
    def at(self,t):
        target=(t+self.offset)*1000
        while self.time<target:
            ok,frame=self.cap.read()
            if not ok:return None
            self.frame=cv2.remap(frame,*self.maps,cv2.INTER_LINEAR) if self.maps else frame;self.time=self.cap.get(cv2.CAP_PROP_POS_MSEC)
        return self.frame


def seam_path(a,b,overlap,avoid,previous=None):
    """A temporally constrained cut through shared background, penalizing motion."""
    ys,xs=np.where(overlap)
    if not len(xs):raise CalibrationRequired('Không có vùng giao giữa hai camera.')
    x0,x1=int(xs.min()),int(xs.max())+1
    difference=cv2.absdiff(cv2.cvtColor(a,cv2.COLOR_BGR2LAB),cv2.cvtColor(b,cv2.COLOR_BGR2LAB)).mean(axis=2)
    cost=difference[:,x0:x1].astype(np.float32)+avoid[:,x0:x1]*250
    cost[~overlap[:,x0:x1]]=1e6
    center=(x0+x1)/2
    cost+=.02*np.abs(np.arange(x0,x1)[None,:]-center)
    if previous is not None:cost+=.8*np.abs(np.arange(x0,x1)[None,:]-previous[:,None])
    parents=np.zeros(cost.shape,np.int8);dp=cost[0].copy()
    for y in range(1,len(cost)):
        candidates=np.stack((np.r_[np.inf,dp[:-1]],dp,np.r_[dp[1:],np.inf]))
        direction=np.argmin(candidates,axis=0);parents[y]=direction-1;dp=cost[y]+np.min(candidates,axis=0)
    path=np.zeros(len(cost),np.int32);path[-1]=int(np.argmin(dp))
    for y in range(len(path)-1,0,-1):path[y-1]=path[y]+parents[y,path[y]]
    return path+x0


def rectangular_crop(mask):
    """Largest upright valid rectangle: no jagged canvas edges or black wedges."""
    h,w=mask.shape;small=cv2.resize(mask.astype(np.float32),(max(1,w//8),max(1,h//8)),interpolation=cv2.INTER_AREA)>.999
    histogram=np.zeros(small.shape[1],int);best=(0,0,0,0);area=0
    for y,row in enumerate(small):
        histogram=np.where(row,histogram+1,0);stack=[]
        for x in range(len(histogram)+1):
            height=int(histogram[x]) if x<len(histogram) else 0;start=x
            while stack and stack[-1][1]>height:
                left,tall=stack.pop();candidate=(x-left)*tall
                # Favour the wide field of view over a tall central-only crop.
                if x-left>=small.shape[1]*.8 and candidate>area:area=candidate;best=(left,y-tall+1,x,y+1)
                start=left
            if not stack or stack[-1][1]<height:stack.append((start,height))
    x0,y0,x1,y1=best;sx=w/small.shape[1];sy=h/small.shape[0]
    rect=(math.ceil(x0*sx/2)*2,math.ceil(y0*sy/2)*2,math.floor(x1*sx/2)*2,math.floor(y1*sy/2)*2)
    if rect[2]-rect[0]<64 or rect[3]-rect[1]<64:raise CalibrationRequired('Không tìm được vùng chữ nhật đủ lớn; cần căn lại camera.')
    return rect


class Composer:
    def __init__(self,frames,matrices,masks,size):
        self.matrices,self.masks,self.size=matrices,masks,size
        self.reference={i:cv2.warpPerspective(f,matrices[i],size) for i,f in frames.items()}
        self.gains={2:np.ones(3)};self.previous={}
        for i in (3,1):
            shared=masks[i]&masks[2];a=self.reference[i][shared].astype(float);b=self.reference[2][shared].astype(float)
            valid=(a.min(axis=1)>15)&(b.min(axis=1)>15)&(a.max(axis=1)<240)&(b.max(axis=1)<240)
            self.gains[i]=np.clip(np.median(b[valid],axis=0)/np.maximum(1,np.median(a[valid],axis=0)),.65,1.5) if valid.any() else np.ones(3)
        self.crop=rectangular_crop(np.logical_or.reduce(list(masks.values())))
    def compose(self,frames):
        warps={i:cv2.warpPerspective(f,self.matrices[i],self.size) for i,f in frames.items()}
        corrected={i:np.clip(f.astype(np.float32)*self.gains[i],0,255).astype(np.uint8) for i,f in warps.items()}
        result=corrected[2].copy();width=self.size[0];xx=np.arange(width)[None,:]
        for i in (3,1):
            a,b=corrected[i],corrected[2];shared=self.masks[i]&self.masks[2]
            small=lambda image:cv2.resize(image,None,fx=.5,fy=.5,interpolation=cv2.INTER_AREA)
            motion=(cv2.absdiff(warps[i],self.reference[i]).max(axis=2)>30)|(cv2.absdiff(warps[2],self.reference[2]).max(axis=2)>30)
            motion=cv2.dilate(motion.astype(np.uint8),np.ones((15,15),np.uint8))
            path=seam_path(small(a),small(b),small(shared.astype(np.uint8))>.5,small(motion)>0,self.previous.get(i));self.previous[i]=path
            full=np.interp(np.arange(self.size[1])/2,np.arange(len(path)),path)*2
            weight=np.clip(((full[:,None]-xx) if i==3 else (xx-full[:,None]))/6+.5,0,1)
            weight=np.where(~self.masks[2]&self.masks[i],1,weight);weight=np.where(~self.masks[i],0,weight)
            result=(result*(1-weight[:,:,None])+a*weight[:,:,None]).astype(np.uint8)
        x0,y0,x1,y1=self.crop;return result[y0:y1,x0:x1]


def process(manifest,output,model_path,seconds=None,fps=30,detect=True):
    items=manifest['inputs'];slots=sorted(int(x['slot']) for x in items)
    if slots!=[1,2,3]:raise ValueError('Exactly slots 1, 2, 3 are required')
    start=max(float(x.get('actualStartedServerAt') or x.get('actualStartedAt') or 0) for x in items)
    offsets={int(x['slot']):max(0,(start-float(x.get('actualStartedServerAt') or x.get('actualStartedAt') or start))/1000) for x in items}
    frames={};durations=[];lens_maps={};lens_matrices={};calibration=copy.deepcopy(manifest.get('calibration') or {})
    for item in items:
        slot=int(item['slot']);cap=cv2.VideoCapture(item['path'])
        if not cap.isOpened():raise ValueError(f'Cannot decode CAM {slot}')
        source_fps=cap.get(cv2.CAP_PROP_FPS);count=cap.get(cv2.CAP_PROP_FRAME_COUNT)
        if source_fps<=0 or count<=0:raise ValueError('Invalid source timing')
        durations.append(count/source_fps-offsets[slot]);samples=[]
        for t in (0,.25,.5,.75,1):
            cap.set(cv2.CAP_PROP_POS_MSEC,(offsets[slot]+min(t,max(0,count/source_fps-offsets[slot]-.1)))*1000)
            ok,frame=cap.read()
            if ok:samples.append(frame)
        cap.release()
        if not samples:raise ValueError(f'CAM {slot} has no common frames')
        frame=np.median(samples,axis=0).astype(np.uint8);lens=calibration.get('lenses',{}).get(str(slot))
        if lens:
            h,w=frame.shape[:2];original=lens['size'];K=np.asarray(lens['matrix'],np.float64);K[0]*=w/original[0];K[1]*=h/original[1];D=np.asarray(lens['distortion'],np.float64)
            if abs((w/h)/(original[0]/original[1])-1)>.02:raise CalibrationRequired('Cấu hình ống kính không khớp hướng/kích thước ảnh.')
            lens_maps[slot]=cv2.initUndistortRectifyMap(K,D,None,K,(w,h),cv2.CV_32FC1);lens_matrices[slot]=(K,D)
            frame=cv2.remap(frame,*lens_maps[slot],cv2.INTER_LINEAR)
        frames[slot]=frame
    # Manual clicks come from raw camera snapshots; undistort those coordinates too.
    for slot in (3,1):
        for pair in calibration.get('points',{}).get(str(slot),[]):
            for key,cam in [('source',slot),('target',2)]:
                if cam in lens_matrices:
                    h,w=frames[cam].shape[:2];K,D=lens_matrices[cam];point=np.float64([[pair[key]]])*[w,h]
                    pair[key]=(cv2.undistortPoints(point,K,D,P=K)[0,0]/[w,h]).tolist()
    emit('Đang căn camera cố định')
    matrices,masks,size,metrics=geometry(frames,calibration)
    composer=Composer(frames,matrices,masks,size)
    output=Path(output);output.parent.mkdir(parents=True,exist_ok=True)
    cv2.imwrite(str(output.with_suffix('.preview.jpg')),composer.compose(frames))
    output.with_suffix('.calibration.json').write_text(json.dumps({'metrics':metrics,'homographies':{str(i):m.tolist() for i,m in matrices.items()},'offsets':offsets},indent=2),encoding='utf-8')
    model=None
    if detect:
        import torch
        from ultralytics import YOLOWorld
        torch.set_num_threads(4);model=YOLOWorld(str(model_path))
    from imageio_ffmpeg import get_ffmpeg_exe
    sample=composer.compose(frames);h,w=sample.shape[:2]
    partial=output.with_name(output.stem+'.partial.mp4');log=output.with_suffix('.ffmpeg.log').open('wb')
    encoder=subprocess.Popen([get_ffmpeg_exe(),'-hide_banner','-loglevel','error','-y','-f','rawvideo','-pixel_format','bgr24','-video_size',f'{w}x{h}','-framerate',str(fps),'-i','pipe:0','-an','-c:v','libx264','-preset','fast','-crf','18','-pix_fmt','yuv420p','-movflags','+faststart',str(partial)],stdin=subprocess.PIPE,stderr=log)
    readers={int(x['slot']):Reader(x['path'],offsets[int(x['slot'])],lens_maps.get(int(x['slot']))) for x in items}
    duration=min(durations);duration=min(duration,seconds) if seconds is not None else duration
    count=max(0,math.floor(duration*fps));done=0;boxes=0
    try:
        with output.with_suffix('.csv').open('w',newline='',encoding='utf-8') as file:
            writer=csv.writer(file);writer.writerow(['frame','seconds','class','confidence','x1','y1','x2','y2'])
            for n in range(count):
                current={i:r.at(n/fps) for i,r in readers.items()}
                if any(f is None for f in current.values()):raise RuntimeError('Source ended before expected synchronized duration')
                frame=composer.compose(current)
                if model is not None:
                    prediction=model.predict(frame,imgsz=960,conf=.25,verbose=False,device='cpu')[0]
                    for box in prediction.boxes:
                        x1,y1,x2,y2=map(int,box.xyxy[0].tolist());label=model.names[int(box.cls[0])];confidence=float(box.conf[0]);boxes+=1
                        cv2.rectangle(frame,(x1,y1),(x2,y2),(70,220,80),2);cv2.putText(frame,f'{label} {confidence:.2f}',(max(0,x1),max(18,y1-5)),cv2.FONT_HERSHEY_SIMPLEX,.55,(70,220,80),2)
                        writer.writerow([n,n/fps,label,confidence,x1,y1,x2,y2])
                if n==0:cv2.imwrite(str(output.with_suffix('.annotated.jpg')),frame)
                encoder.stdin.write(frame.tobytes());done+=1
                if n%30==0:emit('Đang ghép và nhận diện',frame=n,total=count)
        encoder.stdin.close()
        if encoder.wait()!=0 or done==0:raise RuntimeError('FFmpeg failed or empty output')
        partial.replace(output)
    except BaseException:
        if encoder.poll() is None:encoder.kill();encoder.wait()
        raise
    finally:
        log.close()
        for reader in readers.values():reader.cap.release()
    report={'frames':done,'fps':fps,'width':w,'height':h,'seconds':done/fps,'boxes':boxes,'cameraOrder':[3,2,1],'offsetsSeconds':offsets,'calibration':metrics,'crop':composer.crop,'audio':False}
    output.with_suffix('.report.json').write_text(json.dumps(report,indent=2),encoding='utf-8');emit('Hoàn tất',report=report)
    return report


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--manifest',required=True,type=Path);parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--model',type=Path,default=Path(__file__).resolve().parents[1]/'legacy/models/yolov8s-worldv2.pt');parser.add_argument('--seconds',type=float);parser.add_argument('--fps',type=int,default=30);parser.add_argument('--no-detect',action='store_true',help='Geometry tests only; production always enables YOLO')
    args=parser.parse_args()
    if not 1<=args.fps<=60:raise ValueError('FPS must be 1..60')
    process(json.loads(args.manifest.read_text(encoding='utf-8-sig')),args.output,args.model,args.seconds,args.fps,not args.no_detect)


if __name__=='__main__':
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    if hasattr(sys.stderr,'reconfigure'):sys.stderr.reconfigure(encoding='utf-8')
    os.environ.setdefault('YOLO_CONFIG_DIR',str(Path(__file__).resolve().parents[1]/'data/yolo'))
    try:main()
    except CalibrationRequired as error:emit(str(error),needsCalibration=True);sys.exit(2)
