// Read-only checks. Authentication writes are verified by the browser suite.
const base=process.argv[2];
let url;
try{url=new URL(base);}catch{throw new Error('Usage: node scripts/deployment-smoke.mjs https://YOUR_APP_DOMAIN');}
if(!['https:','http:'].includes(url.protocol)||url.username||url.password)throw new Error('Use an HTTP(S) origin without credentials.');
for(const path of ['/api/v1/health/live','/api/v1/health/ready','/api/v1/auth/csrf']){
  const response=await fetch(new URL(path,url),{redirect:'error',signal:AbortSignal.timeout(20000)});
  if(!response.ok)throw new Error(`${path}: HTTP ${response.status}`);
  const body=await response.json();
  if(path.endsWith('/ready')&&body.status!=='ready')throw new Error('Dependencies are not ready');
  if(path.endsWith('/csrf')){
    if(!body.csrf_token)throw new Error('CSRF bootstrap did not return a token');
    const cookie=response.headers.get('set-cookie')||'';
    if(url.protocol==='https:'&&(!cookie.includes('__Host-investiq_session=')||!cookie.includes('Secure')||!cookie.includes('HttpOnly')))throw new Error('Production session cookie flags are missing');
    if(!response.headers.get('cache-control')?.includes('no-store'))throw new Error('Session response must not be cached');
  }
  process.stdout.write(`OK ${path}\n`);
}
const page=await fetch(url,{signal:AbortSignal.timeout(20000)});
if(!page.ok||!page.headers.get('content-type')?.includes('text/html'))throw new Error('Frontend HTML is unavailable');
process.stdout.write('OK frontend\n');
