import {defineConfig} from 'vite';
import {readFileSync} from 'node:fs';
// Match the deployed Vercel return rewrite in local dev/preview too. The HTML
// and script are public static artifacts, not test-only payment endpoints.
function returnRoute(root){return server=>{server.middlewares.use((req,res,next)=>{
 if(new URL(req.url,'http://localhost').pathname!=='/payment-return')return next();
 res.setHeader('Content-Type','text/html; charset=utf-8');res.setHeader('Cache-Control','no-store');res.setHeader('Referrer-Policy','no-referrer');
 res.end(readFileSync(new URL(`${root}/payment-return/index.html`,import.meta.url)));
});};}
export default defineConfig({plugins:[{name:'merchant-checkout-return',configureServer:returnRoute('./public'),configurePreviewServer:returnRoute('./dist')}]});
