import { randomBytes } from 'node:crypto';
import { writeFile } from 'node:fs/promises';
// Exclusive create: never overwrite a configured environment.
await writeFile('.env.local',`CAMROOM_OFFLINE=1\nCAMROOM_LOCAL_MEDIA=1\nPORT=3108\nPROCESSING_SERVER_URL=http://127.0.0.1:3108\nPROCESSING_WORKER_TOKEN=${randomBytes(32).toString('hex')}\nPREVIEW_MODE=snapshots\n`,{flag:'wx',mode:0o600});
console.log('Created private .env.local for local testing. No Neon/production data used.');
