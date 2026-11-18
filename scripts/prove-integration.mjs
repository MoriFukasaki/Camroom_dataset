import '../env.mjs';
import assert from 'node:assert/strict';
import { readFile, mkdir, writeFile } from 'node:fs/promises';
import { resolve, join } from 'node:path';
import { createHash } from 'node:crypto';
if(process.env.CAMROOM_LOCAL_MEDIA!=='1'||!process.env.CAMROOM_OFFLINE)throw Error('Proof requires isolated local mode from npm run setup:local.');
const {server,records,processing}=await import('../server.mjs');
records.directory=resolve('verification/http-spool');processing.directory=resolve('verification/http-queue');
await new Promise(r=>server.listen(0,'127.0.0.1',r));
const base=`http://127.0.0.1:${server.address().port}`;process.env.PROCESSING_SERVER_URL=base;process.env.PROCESSING_TEST_SECONDS='1';
const {runJob}=await import('../worker.mjs');
const controllers=[];
async function post(path,data={},session){const r=await fetch(base+'/api/'+path,{method:'POST',headers:{'Content-Type':'application/json',...(session?{Authorization:`Bearer ${session.token}`}:{})},body:JSON.stringify(data)});const value=await r.json();assert.equal(r.status,200,JSON.stringify(value));return {...value,cookie:r.headers.get('set-cookie')?.split(';')[0]};}
async function events(peer){const controller=new AbortController();controllers.push(controller);const r=await fetch(base+'/api/events',{headers:{Authorization:`Bearer ${peer.token}`},signal:controller.signal});const reader=r.body.getReader();let buffer='';return async()=>{while(!buffer.includes('\n\n')){const {done,value}=await reader.read();if(done)throw Error('SSE ended');buffer+=Buffer.from(value).toString();}const end=buffer.indexOf('\n\n'),item=buffer.slice(0,end);buffer=buffer.slice(end+2);return JSON.parse(item.slice(6));};}
try{
  const sample=JSON.parse(await readFile('verification/sample-manifest.json','utf8'));
  const peers=[];peers.push(await post('join',{create:true,maxCameras:3,role:'camera',name:'QA CAM 1'}));
  for(const slot of [2,3])peers.push(await post('join',{code:peers[0].code,role:'camera',name:`QA CAM ${slot}`}));
  const streams=[];for(const peer of peers){streams.push(await events(peer));await streams.at(-1)();await post('camera-state',{ready:true,settings:{width:1920,height:1080,frameRate:30}},peer);}
  await post('record/start',{},peers[0]);const capabilities=[];
  for(const next of streams){let item;do{item=await next();}while(item.type!=='record-start');capabilities.push(item.data);}
  await post('record/stop',{},peers[0]);
  for(const job of capabilities){const input=sample.inputs.find(x=>x.slot===job.slot),bytes=await readFile(input.path);let count=0;for(let offset=0;offset<bytes.length;offset+=2*1024*1024){await records.chunk(job.id,job.token,count++,bytes.subarray(offset,offset+2*1024*1024));}await records.complete(job.id,job.token,{count,mime:'video/mp4',actualStartedAt:1000,actualStoppedAt:4000,clockOffset:0,capture:{width:1920,height:1080,frameRate:30,encoderBitrate:10000000}});}
  let task=(await post('processing/state',{},peers[0])).jobs[0];assert.equal(task.state,'queued');
  await post('processing/calibration',{id:task.id,calibration:sample.calibration},peers[0]);
  const response=await fetch(base+'/api/worker/claim',{method:'POST',headers:{Authorization:`Bearer ${process.env.PROCESSING_WORKER_TOKEN}`}});const {job}=await response.json();assert.ok(job);
  await runJob(job);task=(await post('processing/state',{},peers[0])).jobs[0];assert.equal(task.state,'completed',task.message);
  const product=(await post('recordings',{},peers[0])).recordings.find(x=>x.kind==='product');assert.ok(product);
  const link=await post('record/download',{id:product.id},peers[0]);
  const result=await fetch(base+link.url,{headers:{Cookie:peers[0].cookie}});assert.equal(result.status,200);const downloaded=Buffer.from(await result.arrayBuffer());
  const original=await readFile(join('data/worker',task.id,'final.mp4'));
  assert.equal(createHash('sha256').update(downloaded).digest('hex'),createHash('sha256').update(original).digest('hex'));
  await writeFile('verification/final-integrated.mp4',downloaded);
  const report={result:'PASS',workflow:'3 uploads -> durable queue -> worker downloads -> calibration -> panorama -> YOLO -> product upload -> admin download',job:task.id,bytes:downloaded.length,report:task.report};
  await writeFile('verification/integration-report.json',JSON.stringify(report,null,2));console.log(JSON.stringify(report));
}finally{controllers.forEach(c=>c.abort());server.closeAllConnections();await new Promise(r=>server.close(r));}
