// Generate the separate admin project's Vercel config once its main domain is known.
import {readFile,writeFile} from 'node:fs/promises';
const input=process.argv[2];
let url;
try {url=new URL(input);} catch {throw new Error('Usage: node scripts/prepare-admin.mjs https://YOUR_APP_DOMAIN');}
if(url.protocol!=='https:'||url.username||url.password||url.pathname!=='/'||url.search||url.hash)throw new Error('Provide the main app HTTPS origin, without credentials or a path.');
const template=JSON.parse(await readFile(new URL('../deployment/admin.vercel.example.json',import.meta.url),'utf8'));
template.rewrites[0].destination=url.origin+'/api/:path*';
const target=process.argv[3]||new URL('../investiq-fe/vercel.json',import.meta.url);
await writeFile(target,JSON.stringify(template,null,2)+'\n');
process.stdout.write('Admin Vercel routing configured. Use VITE_APP_MODE=admin and Root Directory investiq-fe.\n');
