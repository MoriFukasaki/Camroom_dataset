import {existsSync} from 'node:fs';
import {spawn,execFileSync} from 'node:child_process';
import {setTimeout as delay} from 'node:timers/promises';
if(!existsSync('.env.local'))execFileSync(process.execPath,['scripts/setup-local.mjs'],{stdio:'inherit'});
await import('../env.mjs');
const url='http://127.0.0.1:'+Number(process.env.PORT||3000);
console.log('Starting separate web + Python worker. Stop with Ctrl+C. Local URL: '+url);
const children=[spawn(process.execPath,['server.mjs'],{stdio:'inherit',windowsHide:true})];
let stopping=false;
function stop(){if(stopping)return;stopping=true;for(const child of children)child.kill();}
process.on('SIGINT',stop);process.on('SIGTERM',stop);
for(const child of children){child.on('error',error=>{console.error(error.message);stop();});child.on('exit',()=>stop());}
let ready=false;
for(let attempt=0;attempt<40&&!stopping;attempt++){
  try{const response=await fetch(url,{signal:AbortSignal.timeout(1000)});if(response.ok){ready=true;break;}}catch{}
  await delay(250);
}
if(ready&&!stopping){const worker=spawn(process.execPath,['worker.mjs'],{stdio:'inherit',windowsHide:true});children.push(worker);worker.on('error',error=>{console.error(error.message);stop();});worker.on('exit',stop);}
else{console.error('Web did not become ready; worker not started.');stop();process.exitCode=1;}
