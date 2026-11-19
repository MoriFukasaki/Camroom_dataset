import {test} from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {ProcessingQueue,publicProcessing} from '../processing.mjs';
import {requestSnapshot,acceptSnapshot} from '../snapshots.mjs';

test('one camera JPEG per five seconds; a three-camera rotation takes fifteen seconds',()=>{
  const room={peers:new Map([1,2,3].map(slot=>[slot,{id:'p'+slot,slot,role:'camera',res:true}]))};const requests=[];
  const emit=(p,type,data)=>requests.push({p,type,data});
  requestSnapshot(room,emit,10000);requestSnapshot(room,emit,11000);assert.equal(requests.length,1);
  assert.equal(acceptSnapshot(room,{id:'p2',slot:2},{nonce:requests[0].data.nonce,image:'data:image/jpeg;base64,/9j/test'},11000),null);
  assert.ok(acceptSnapshot(room,{id:'p1',slot:1},{nonce:requests[0].data.nonce,image:'data:image/jpeg;base64,/9j/test'},11000));
  assert.equal(acceptSnapshot(room,{id:'p1',slot:1},{nonce:requests[0].data.nonce,image:'data:image/jpeg;base64,/9j/test'},11000),null);
  for(const now of [15000,20000,25000])requestSnapshot(room,emit,now);
  assert.deepEqual(requests.map(x=>x.p.slot),[1,2,3,1]);
});
test('processing waits for all three sources, persists, leases once, retries after crash, and hides lease secrets',async()=>{
  const directory=await mkdtemp(join(tmpdir(),'camroom-queue-'));const queue=new ProcessingQueue({directory,cloud:false});
  const inputs=[1,2,3].map(slot=>({slot,id:'source'+slot,state:'scheduled'})),room='ABCDEF123456',take='0123456789abcdef';
  await queue.ensure(room,take,inputs);await queue.ready(room,inputs.map((x,i)=>({...x,state:i<2?'uploaded':'scheduled'})));
  assert.equal(await queue.claim(),null);
  await queue.ready(room,inputs.map(x=>({...x,state:'uploaded'})));
  const restored=new ProcessingQueue({directory,cloud:false});
  const claims=await Promise.all([restored.claim(),restored.claim()]);assert.equal(claims.filter(Boolean).length,1);
  const job=claims.find(Boolean);assert.equal(publicProcessing(job).leaseToken,undefined);
  await assert.rejects(()=>restored.updateLease(job.id,'incorrect',{message:'steal'}));
  const newJob=await restored.claim(job.leaseUntil+1);assert.notEqual(newJob.leaseToken,job.leaseToken);assert.equal(newJob.attempts,2);
  await restored.cancelRoom(room);assert.equal((await restored.get(job.id)).state,'cancelled');
  await assert.rejects(()=>restored.updateLease(job.id,newJob.leaseToken,{}));
});

test('import names enforce exactly three unique camera slots and nonempty files',async()=>{
 const {validateImport}=await import('../processing.mjs');
 const files=['cam-3.webm','cam-1.mp4','cam-2.mp4'].map(name=>({name,size:10}));
 assert.deepEqual(validateImport(files).map(x=>x.slot),[1,2,3]);
 for(const invalid of [files.slice(1),[files[0],files[0],files[2]],files.map(x=>({...x,size:0})),files.map(x=>({...x,name:'other.mp4'}))])assert.throws(()=>validateImport(invalid));
});
