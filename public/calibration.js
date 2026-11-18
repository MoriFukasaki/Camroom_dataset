export function installCalibration({getSnapshots,getJob,api,notify}) {
  const $=id=>document.getElementById(id),points={'1':[],'3':[]},images={},pending={};
  function draw() {
    const slot=$('calibration-slot').value;
    for(const side of ['source','target']){
      const canvas=$('calibration-'+side),context=canvas.getContext('2d'),image=images[side];
      context.clearRect(0,0,canvas.width,canvas.height);if(!image)continue;context.drawImage(image,0,0,canvas.width,canvas.height);
      [...points[slot],...(pending[slot]?[{source:pending[slot]}]:[])].forEach((pair,index)=>{const point=pair[side];if(!point)return;const [x,y]=[point[0]*canvas.width,point[1]*canvas.height];context.fillStyle='#efff50';context.beginPath();context.arc(x,y,5,0,Math.PI*2);context.fill();context.font='16px sans-serif';context.fillText(String(index+1),x+8,y-8);});
    }
    $('calibration-count').textContent=`CAM 3: ${points['3'].length} cặp · CAM 1: ${points['1'].length} cặp. `+(pending[slot]?'Bấm đúng điểm tương ứng trên ảnh CAM 2.':'Bấm một điểm vạch sân trên camera bên, rồi bấm cùng điểm đó trên CAM 2.');
  }
  function load(){const slot=$('calibration-slot').value,snapshots=getSnapshots();for(const [side,key]of [['source',Number(slot)],['target',2]]){const snapshot=snapshots.get(key);if(!snapshot){notify('Đợi cả ba camera gửi ảnh trước khi căn thủ công.');continue;}const image=new Image();image.onload=()=>{images[side]=image;const canvas=$('calibration-'+side);canvas.width=image.naturalWidth;canvas.height=image.naturalHeight;draw();};image.src=snapshot.image;}}
  $('calibration-load').onclick=load;$('calibration-slot').onchange=()=>{images.source=null;images.target=null;load();};
  for(const side of ['source','target'])$('calibration-'+side).onclick=event=>{if(!images[side])return;const slot=$('calibration-slot').value,rect=event.currentTarget.getBoundingClientRect(),point=[(event.clientX-rect.left)/rect.width,(event.clientY-rect.top)/rect.height];if(side==='source')pending[slot]=point;else if(pending[slot]){points[slot].push({source:pending[slot],target:point});delete pending[slot];}draw();};
  $('calibration-clear').onclick=()=>{points[$('calibration-slot').value]=[];delete pending[$('calibration-slot').value];draw();};
  $('calibration-save').onclick=async()=>{if(points['1'].length<4||points['3'].length<4)return notify('Cần ít nhất 4 cặp điểm phân bố rộng cho CAM 1 và CAM 3.');try{await api('processing/calibration',{id:getJob().id,calibration:{points}});notify('Đã lưu điểm căn ghép. Worker sẽ tự thử lại.');}catch(e){notify(e.message);}};
}
