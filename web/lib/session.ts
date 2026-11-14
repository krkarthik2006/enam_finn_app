import {createHash,createHmac,timingSafeEqual} from "node:crypto";
import type {NextRequest} from "next/server";
export const SESSION_COOKIE="finn_review_session";
export const SESSION_SECONDS=8*60*60;
export function reviewRequired(){return Boolean(process.env.FINN_REVIEW_PASSWORD||process.env.VERCEL);}
export function reviewConfigured(){return Boolean(process.env.FINN_REVIEW_PASSWORD&&process.env.FINN_API_TOKEN);}
function signature(expires:string){return createHmac("sha256",process.env.FINN_API_TOKEN||"").update(expires+":"+process.env.FINN_REVIEW_PASSWORD).digest("base64url");}
export function sameSecret(a:string,b:string){return timingSafeEqual(createHash("sha256").update(a).digest(),createHash("sha256").update(b).digest());}
export function createSession(){const expires=String(Math.floor(Date.now()/1000)+SESSION_SECONDS);return expires+"."+signature(expires);}
export function hasSession(request:NextRequest){
 if(!reviewRequired())return true;
 if(!reviewConfigured())return false;
 const [expires,supplied,...extra]=(request.cookies.get(SESSION_COOKIE)?.value||"").split(".");
 return !extra.length&&/^\d{10}$/.test(expires||"")&&Number(expires)>Date.now()/1000&&Number(expires)<=Date.now()/1000+SESSION_SECONDS&&Boolean(supplied)&&sameSecret(signature(expires),supplied);
}
export function sameOrigin(request:NextRequest){const origin=request.headers.get("origin");try{return !origin||new URL(origin).host===request.headers.get("host");}catch{return false;}}
