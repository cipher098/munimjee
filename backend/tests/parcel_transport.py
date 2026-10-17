"""P01-preserving test bridge: Node may call this exact isolated loopback only."""
import asyncio
import json
import httpx
from urllib.parse import urlsplit

NODE_CLIENT=r"""
import http from 'node:http';
let data='';for await(const chunk of process.stdin)data+=chunk;
const request=JSON.parse(data),url=new URL(request.url);
if(url.origin!=='http://127.0.0.1:8155'||!url.pathname.startsWith('/integration/v1/')||url.username||url.password||url.hash)throw Error('Forbidden fixture destination');
const result=await new Promise((resolve,reject)=>{const req=http.request(url,{method:request.method,headers:request.headers},res=>{if(res.statusCode>=300&&res.statusCode<400){reject(Error('Redirect forbidden'));res.resume();return;}let size=0,chunks=[];res.on('data',chunk=>{size+=chunk.length;if(size>256000){req.destroy();reject(Error('Fixture response too large'));}else chunks.push(chunk);});res.on('end',()=>resolve({status:res.statusCode,body:Buffer.concat(chunks).toString('utf8')}));});req.on('error',reject);req.setTimeout(27000,()=>req.destroy(Error('Fixture deadline')));req.end(request.body);});
process.stdout.write(JSON.stringify(result));
"""

class NodeConnectorTransport(httpx.AsyncBaseTransport):
    async def handle_async_request(self,request):
        url=urlsplit(str(request.url))
        if url.scheme!='http' or url.netloc!='127.0.0.1:8155' or not url.path.startswith('/integration/v1/') or url.username or url.password or url.fragment:
            raise AssertionError('Forbidden connector fixture destination before process spawn')
        process=await asyncio.create_subprocess_exec('node','--input-type=module','-e',NODE_CLIENT,stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
        try:
            output,_=await asyncio.wait_for(process.communicate(json.dumps({'url':str(request.url),'method':request.method,'headers':dict(request.headers),'body':(await request.aread()).decode()}).encode()),30)
        except BaseException:
            if process.returncode is None:process.kill();await process.wait()
            raise
        if process.returncode:raise httpx.ReadError('Synthetic connector response was lost')
        result=json.loads(output)
        return httpx.Response(result['status'],content=result['body'].encode(),request=request,headers={'Content-Type':'application/json'})
