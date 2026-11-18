import {execFileSync} from 'node:child_process';
import {resolve} from 'node:path';
const python=process.env.PROCESSING_PYTHON||resolve('.venv',process.platform==='win32'?'Scripts/python.exe':'bin/python');
execFileSync(python,['-m','unittest','discover','-s','processor/tests','-v'],{stdio:'inherit',windowsHide:true});
