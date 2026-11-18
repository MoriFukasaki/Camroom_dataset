"""Optional: measure one fixed phone/lens with checkerboard images, not video-specific guesses."""
import argparse
import json
from pathlib import Path
import cv2
import numpy as np

def main():
    p=argparse.ArgumentParser();p.add_argument('--images',type=Path,required=True);p.add_argument('--columns',type=int,default=9);p.add_argument('--rows',type=int,default=6);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    pattern=(a.columns,a.rows);grid=np.zeros((a.columns*a.rows,3),np.float32);grid[:,:2]=np.mgrid[0:a.columns,0:a.rows].T.reshape(-1,2)
    world=[];image=[];size=None
    for path in sorted(a.images.iterdir()):
        frame=cv2.imread(str(path))
        if frame is None:continue
        gray=cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY);current=gray.shape[::-1]
        if size is not None and current!=size:raise ValueError('All checkerboard images must have equal size')
        size=current;ok,corners=cv2.findChessboardCorners(gray,pattern)
        if ok:world.append(grid);image.append(cv2.cornerSubPix(gray,corners,(11,11),(-1,-1),(cv2.TERM_CRITERIA_EPS+cv2.TERM_CRITERIA_MAX_ITER,30,.001)))
    if len(world)<10:raise ValueError('At least 10 usable checkerboard images are required')
    error,matrix,distortion,_,_=cv2.calibrateCamera(world,image,size,None,None)
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps({'size':size,'matrix':matrix.tolist(),'distortion':distortion.ravel().tolist(),'rms':error},indent=2),encoding='utf-8')
    print(f'Saved lens calibration; RMS={error:.3f}')

if __name__=='__main__':main()
