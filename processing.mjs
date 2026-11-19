import { randomBytes, timingSafeEqual } from 'node:crypto';
import { mkdir, readFile, writeFile, rename, readdir } from 'node:fs/promises';
import { resolve, join } from 'node:path';
import { databaseEnabled, getPool } from './database.mjs';

export const workerAuthorized = req => {
  const expected = process.env.PROCESSING_WORKER_TOKEN || '';
  const value = (req.headers.authorization || '').replace(/^Bearer /, '');
  return expected.length >= 32 && value.length === expected.length && timingSafeEqual(Buffer.from(value), Buffer.from(expected));
};
export const publicProcessing = job => {
  if (!job) return null;
  const { leaseToken, ...safe } = job; return safe;
};
export class ProcessingQueue {
  constructor({directory = './data/processing', cloud = true} = {}) { this.directory = resolve(directory); this.cloud = cloud; this.chain = Promise.resolve(); }
  path(id) { if (!/^[A-F0-9]{12}-[a-f0-9]{16}$/.test(id)) throw Error('Mã tác vụ không hợp lệ.'); return join(this.directory, id+'.json'); }
  locked(fn) { const work = this.chain.catch(()=>{}).then(fn); this.chain = work; return work; }
  async save(job) {
    job.updatedAt = Date.now();
    if (this.cloud && databaseEnabled()) await getPool().query('INSERT INTO camroom_processing(id,room_code,metadata) VALUES($1,$2,$3::jsonb) ON CONFLICT(id) DO UPDATE SET metadata=EXCLUDED.metadata,updated_at=now()', [job.id, job.room, JSON.stringify(job)]);
    else { await mkdir(this.directory,{recursive:true}); const path=this.path(job.id); await writeFile(path+'.tmp',JSON.stringify(job)); await rename(path+'.tmp',path); }
    return job;
  }
  async list(room) {
    if (this.cloud && databaseEnabled()) return (await getPool().query('SELECT metadata FROM camroom_processing WHERE ($1::text IS NULL OR room_code=$1) ORDER BY updated_at', [room||null])).rows.map(x=>x.metadata);
    const files = await readdir(this.directory).catch(e=>{if(e.code==='ENOENT')return [];throw e;});
    const jobs=[]; for(const file of files) if(/^[A-F0-9]{12}-[a-f0-9]{16}\.json$/.test(file)) { const job=JSON.parse(await readFile(join(this.directory,file),'utf8')); if(!room || job.room===room)jobs.push(job); } return jobs;
  }
  async get(id) { this.path(id); return (await this.list()).find(job=>job.id===id); }
  async ensure(room, take, inputs) {
    return this.locked(async()=> {
      const id=room+'-'+take, existing=await this.get(id); if(existing)return existing;
      if(inputs.length!==3 || inputs.some((x,i)=>x.slot!==i+1)) throw Error('Tự ghép yêu cầu đúng 3 camera, slot 1, 2, 3.');
      return this.save({id,room,take,state:'waiting_inputs',message:'Chờ đủ 3 video gốc',inputs,createdAt:Date.now(),attempts:0,calibration:null});
    });
  }
  async ready(room, recordings) {
    return this.locked(async()=>{
      for(const job of await this.list(room)) if(job.state==='waiting_inputs') {
        const inputs=job.inputs.map(input=>recordings.find(x=>x.id===input.id)||input);
        if(inputs.every(x=>x.state==='uploaded')) { job.inputs=inputs; job.state='queued';job.message='Đã đủ 3 video · chờ máy xử lý';await this.save(job); }
      }
    });
  }
  async claim(now=Date.now()) {
    return this.locked(async()=>{
      const job=(await this.list()).filter(j=>j.state==='queued'||j.state==='processing'&&j.leaseUntil<now).sort((a,b)=>a.createdAt-b.createdAt)[0]; if(!job)return null;
      job.state='processing';job.message='Đang tải video/căn ghép';job.leaseToken=randomBytes(24).toString('hex');job.leaseUntil=now+90000;job.attempts++;return this.save(job);
    });
  }
  async updateLease(id, token, patch) {
    return this.locked(async()=>{
      const job=await this.get(id);
      if(!job||job.state!=='processing'||job.leaseToken!==token||job.leaseUntil<Date.now()) throw Error('Phiên xử lý hết hạn.');
      Object.assign(job,patch,{leaseUntil:Date.now()+90000});return this.save(job);
    });
  }
  async configure(id, room, calibration) {
    return this.locked(async()=>{const job=await this.get(id);if(!job||job.room!==room||['processing','completed','cancelled'].includes(job.state))throw Error('Không thể thay cấu hình lúc này.');
      if(calibration)for(const slot of ['1','3']){const pairs=calibration.points?.[slot];if(!Array.isArray(pairs)||pairs.length<4||pairs.length>40||pairs.some(p=>!['source','target'].every(k=>Array.isArray(p[k])&&p[k].length===2&&p[k].every(v=>Number.isFinite(v)&&v>=0&&v<=1))))throw Error('Chọn ít nhất 4 cặp điểm hợp lệ cho từng camera bên.');}
      job.calibration=calibration;job.state=job.inputs.every(x=>x.state==='uploaded')?'queued':'waiting_inputs';job.error=null;job.message='Đã cập nhật căn ghép';return this.save(job);});
  }
  async cancelRoom(room) { return this.locked(async()=>{for(const job of await this.list(room))if(job.state!=='cancelled'){job.state='cancelled';job.message='Admin đã bỏ tác vụ';await this.save(job);}}); }
}

export function validateImport(files) {
  if(!Array.isArray(files)||files.length!==3)throw Error('Chọn đúng 3 video: cam-1, cam-2, cam-3.');
  const sorted=files.map(file=>{
    const match=/^cam-([123])\.(mp4|webm)$/i.exec(file.name||'');
    if(!match||!Number.isSafeInteger(file.size)||file.size<=0)throw Error('Tên phải là cam-1.mp4, cam-2.mp4, cam-3.mp4 (hoặc .webm); file không được rỗng.');
    return {...file,slot:Number(match[1]),mime:'video/'+match[2].toLowerCase()};
  }).sort((a,b)=>a.slot-b.slot);
  if(sorted.some((file,i)=>file.slot!==i+1))throw Error('Trùng hoặc thiếu slot camera.');
  return sorted;
}
