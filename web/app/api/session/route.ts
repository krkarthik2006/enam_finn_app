import {NextRequest,NextResponse} from "next/server";
import {SESSION_COOKIE,SESSION_SECONDS,createSession,hasSession,reviewConfigured,reviewRequired,sameOrigin,sameSecret} from "@/lib/session";
export const runtime="nodejs";
export const dynamic="force-dynamic";
const noCache={"Cache-Control":"no-store"};
export async function GET(request:NextRequest){return NextResponse.json({required:reviewRequired(),authenticated:hasSession(request),configured:!reviewRequired()||reviewConfigured()},{headers:noCache});}
export async function POST(request:NextRequest){
 if(!sameOrigin(request))return NextResponse.json({detail:"Cross-origin sign-in refused"},{status:403,headers:noCache});
 if(!reviewConfigured())return NextResponse.json({detail:"Review access is not configured on the server."},{status:503,headers:noCache});
 let password:unknown;try{password=(await request.json()).password;}catch{return NextResponse.json({detail:"Enter the review password."},{status:400,headers:noCache});}
 if(typeof password!=="string"||password.length>1000||!sameSecret(password,process.env.FINN_REVIEW_PASSWORD||""))return NextResponse.json({detail:"Incorrect review password."},{status:401,headers:noCache});
 const response=NextResponse.json({authenticated:true},{headers:noCache});
 response.cookies.set(SESSION_COOKIE,createSession(),{httpOnly:true,secure:request.nextUrl.protocol==="https:",sameSite:"strict",maxAge:SESSION_SECONDS,path:"/"});return response;
}
export async function DELETE(request:NextRequest){if(!sameOrigin(request))return NextResponse.json({detail:"Cross-origin sign-out refused"},{status:403});const response=NextResponse.json({authenticated:false},{headers:noCache});response.cookies.delete(SESSION_COOKIE);return response;}
