import './env.mjs';
import { mkdir, writeFile, readFile, stat, open } from 'node:fs/promises';
import { createReadStream, createWriteStream, existsSync } from 'node:fs';
import { pipeline } from 'node:stream/promises';
import { Readable } from 'node:stream';
import { spawn } from 'node:child_process';
import { resolve, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { setTimeout as delay } from 'node:timers/promises';

const root=fileURLToPath(new URL('.',import.meta.url));
const base=new URL(process.env.PROCESSING_SERVER_URL||'http://127.0.0.1:3000');
if(base.protocol!=='https:'&&!['localhost','127.0.0.1','[::1]'].includes(base.hostname))throw Error('Worker yêu cầu HTTPS cho máy chủ từ xa.');
const secret=process.env.PROCESSING_WORKER_TOKEN;
if(!secret||secret.length<32)throw Error('Cấu hình PROCESSING_WORKER_TOKEN trên web và worker (ít nhất 32 ký tự).');
const auth={Authorization:`Bearer ${secret}`};
async function request(path,data) {
  const response=await fetch(new URL('/api/worker/'+path,base),{method:'POST',headers:{...auth,'Content-Type':'application/json'},body:JSON.stringify(data||{}),redirect:'error',signal:AbortSignal.timeout(30000)});
  const value=await response.json();if(!response.ok)throw Error(value.error||'Worker API failed');return value;
}
async function download(job,input,folder) {
  const path=join(folder,`Cam ${input.slot}.${input.mime?.startsWith('video/webm')?'webm':'mp4'}`);
  const response=await fetch(new URL(`/api/worker/inputs/${job.id}/${input.id}`,base),{headers:{...auth,'X-Lease-Token':job.leaseToken},redirect:'error',signal:AbortSignal.timeout(1800000)});
  if(!response.ok)throw Error('Không tải được video '+input.slot);
  await pipeline(Readable.fromWeb(response.body),createWriteStream(path+'.part'));
  const {rename}=await import('node:fs/promises');await rename(path+'.part',path);
  if((await stat(path)).size!==input.bytes)throw Error('Video tải xuống không đủ dữ liệu');return {...input,path};
}
async function upload(job,path) {
  const result=await request('result',{id:job.id,lease:job.leaseToken});
  const bytes=(await stat(path)).size,file=await open(path,'r');let count=0;
  const post=async(suffix,body,type)=>{const res=await fetch(new URL(`/api/uploads/${result.id}/${suffix}`,base),{method:'POST',headers:{Authorization:`Bearer ${result.token}`,'Content-Type':type},body,redirect:'error',signal:AbortSignal.timeout(180000)});if(!res.ok)throw Error('Không gửi được thành phẩm');return res.json();};
  try{for(let offset=0;offset<bytes;offset+=2*1024*1024){const buffer=Buffer.alloc(Math.min(2*1024*1024,bytes-offset));await file.read(buffer,0,buffer.length,offset);await post(`chunk?index=${count}`,buffer,'application/octet-stream');count++;}}
  finally{await file.close();}
  await post('complete',JSON.stringify({count,mime:'video/mp4'}),'application/json');
}
export async function runJob(job) {
  const folder=resolve(root,'data','worker',job.id);await mkdir(folder,{recursive:true});
  let child,leaseError=null,message='Đang tải đủ 3 video gốc';
  const heartbeat=setInterval(()=>{request('heartbeat',{id:job.id,lease:job.leaseToken,message}).catch(error=>{leaseError=error;child?.kill();});},15000);
  try{
    const inputs=[];for(const input of job.inputs)inputs.push(await download(job,input,folder));
    if(leaseError)throw leaseError;
    const rig=process.env.PROCESSING_CALIBRATION_FILE?JSON.parse(await readFile(resolve(root,process.env.PROCESSING_CALIBRATION_FILE),'utf8')):{};
    const calibration={...rig,...(job.calibration||{})};
    const manifest=join(folder,'manifest.json'),output=join(folder,'final.mp4');await writeFile(manifest,JSON.stringify({...job,calibration,inputs}));
    const python=process.env.PROCESSING_PYTHON||(process.platform==='win32'?join(root,'.venv','Scripts','python.exe'):join(root,'.venv','bin','python'));
    const args=[join(root,'processor','pipeline.py'),'--manifest',manifest,'--output',output];
    if(process.env.PROCESSING_TEST_SECONDS)args.push('--seconds',process.env.PROCESSING_TEST_SECONDS);
    await new Promise((resolve,reject)=>{
      child=spawn(python,args,{cwd:root,windowsHide:true,env:{...process.env,PYTHONIOENCODING:'utf-8'}});let stderr='',buffer='',calibration=false;
      child.stdout.on('data',bytes=>{buffer+=bytes.toString();let end;while((end=buffer.indexOf('\n'))>=0){const line=buffer.slice(0,end);buffer=buffer.slice(end+1);console.log(line);try{const progress=JSON.parse(line);message=progress.message||message;calibration ||= Boolean(progress.needsCalibration);}catch{}}});
      child.stderr.on('data',bytes=>{stderr=(stderr+bytes.toString()).slice(-2000);});child.on('error',reject);
      child.on('close',code=>code===0?resolve():reject(Object.assign(Error(calibration?message:'Python xử lý thất bại: '+stderr),{needsCalibration:calibration||code===2})));
    });
    if(leaseError)throw leaseError;
    message='Đang tải thành phẩm lên';await upload(job,output);
    const report=JSON.parse(await readFile(join(folder,'final.report.json'),'utf8'));
    await request('finish',{id:job.id,lease:job.leaseToken,report});console.log('DONE '+job.id);
  }catch(error){await request('finish',{id:job.id,lease:job.leaseToken,error:error.message,needsCalibration:Boolean(error.needsCalibration)}).catch(()=>{});console.error(error.message);}
  finally{clearInterval(heartbeat);}
}
if(process.argv[1]===fileURLToPath(import.meta.url)) {
  console.log('Worker polling '+base.origin+'; slot order 3 | 2 | 1');
  do {try{const {job}=await request('claim');if(job)await runJob(job);else if(process.argv.includes('--once'))break;}catch(error){console.error(error.message);}if(process.argv.includes('--once'))break;await delay(5000);}while(true);
}
