"""Create an explicit test manifest from the copied legacy videos, never change them."""
import json
import argparse
import cv2
import numpy as np
import subprocess
import imageio_ffmpeg
from pathlib import Path

root=Path(__file__).resolve().parents[1];folder=root/'verification';folder.mkdir(exist_ok=True)
inputs=[{'slot':i,'path':str(root/'legacy'/'inputs'/f'Cam {i}.mp4'),'actualStartedServerAt':1000} for i in (1,2,3)]
parser=argparse.ArgumentParser();parser.add_argument('--legacy-calibration',action='store_true');parser.add_argument('--short',action='store_true');args=parser.parse_args()
manifest={'inputs':inputs}
if args.legacy_calibration:
    # QA fixture ONLY: the original calibration belongs to these copied videos.
    cfg=json.loads((root/'legacy/configs/panorama.json').read_text(encoding='utf-8'));points={}
    for i in (1,3):
        H=np.diag([2.,2.,1.])@np.array(cfg['homographies_half'][str(i)])@np.diag([.5,.5,1.])
        pairs=[]
        for y in (300,500,750,980):
            for x in (100,350,650,950,1250,1550,1800):
                target=cv2.perspectiveTransform(np.float32([[[x,y]]]),H)[0,0]
                if 0<target[0]<1920 and 0<target[1]<1080:pairs.append({'source':[x/1920,y/1080],'target':(target/[1920,1080]).tolist()})
        points[str(i)]=pairs[:40]
    manifest['calibration']={'points':points}
if args.short:
    for item in inputs:
        dest=folder/f"Cam {item['slot']}.mp4"
        subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-hide_banner','-loglevel','error','-y','-i',item['path'],'-t','3','-an','-c:v','copy',str(dest)],check=True)
        item['path']=str(dest)
(folder/'sample-manifest.json').write_text(json.dumps(manifest),encoding='utf-8')
print(folder/'sample-manifest.json')
