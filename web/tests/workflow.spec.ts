import {test,expect} from "@playwright/test";

test("three simple tabs, offline updates, saved research and contacts",async({page},info)=>{
  await page.route("**/api/**",route=>route.fulfill({status:503,contentType:"application/json",body:'{"detail":"Offline check"}'}));
  const errors:string[]=[];page.on("pageerror",error=>errors.push(error.message));
  await page.goto("/");
  await expect(page.getByRole("heading",{name:"Portfolio Status"})).toBeVisible();
  await expect(page.getByText("Offline · saved data",{exact:true})).toBeAttached();
  await expect(page.getByRole("button",{name:"System",exact:true})).toHaveCount(0);
  await expect(page.getByRole("button",{name:"Real data",exact:true})).toHaveCount(0);
  await expect(page.locator(".demo-notice, .overview-strip, .sidebar-note")).toHaveCount(0);
  await expect(page.locator("main")).not.toContainText(/MOCKIT|Mock IT Services|attached screenshot/i);
  await page.screenshot({path:`/private/tmp/finn-${info.project.name}-today-clean.png`,fullPage:true});
  await page.getByRole("button",{name:"Research",exact:true}).filter({visible:true}).click();
  await page.getByRole("button",{name:"TCS",exact:true}).click();
  await expect(page.getByRole("heading",{name:"Promised vs delivered",exact:true})).toBeVisible();
  await expect(page.locator("body")).not.toContainText(/Analysis:|hyde\/|glm-\d|published_on|backend|API key/i);
  await page.locator(".citation-chips button").first().click();
  await expect(page.locator("dialog")).not.toContainText(/SYNTHETIC REVIEW|fictional financials/i);
  await page.locator("dialog").screenshot({path:`/private/tmp/finn-${info.project.name}-real-tcs-source.png`});
  await expect(page.locator(".dialog-title")).not.toContainText(/AI Summary|PPT|REC/);
  await expect(page.locator("dialog .source-excerpt, dialog .financial-table")).toBeVisible();
  await expect(page.getByRole("link",{name:"Open original document"})).toBeVisible();
  await expect(page.locator("dialog")).not.toContainText(/SYNTHETIC REVIEW|fictional financials/i);
  await page.getByRole("button",{name:"Close dialog"}).click();
  await page.getByRole("button",{name:"People",exact:true}).filter({visible:true}).click();
  await expect(page.locator(".people-grid")).not.toContainText(/Demo Professional|Mock IT Services/);
  await page.getByRole("textbox",{name:"Search people"}).fill("Neha Rao");
  await page.locator(".person-card").click();
  await expect(page.locator("dialog .intro-path")).toContainText("Neha");
  await expect(page.locator("dialog")).not.toContainText(/synthetic|fictional|sample contact/i);
  await page.getByRole("button",{name:"Close dialog"}).click();
  await page.getByRole("button",{name:"Alert preferences",exact:true}).filter({visible:true}).first().click();
  await page.getByRole("spinbutton",{name:"Price threshold"}).fill("6");
  await page.getByRole("button",{name:"Save preferences"}).click();
  await expect(page.getByRole("status")).toContainText("saved on this device");
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true);
  expect(errors).toEqual([]);
});

test("new NSE tickers request primary sources without a mode switch",async({page})=>{
  const snapshot=await (await page.request.get("/snapshot.json")).json();
  await page.route("**/api/**",async route=>{
    const path=new URL(route.request().url()).pathname;
    const values:Record<string,unknown>={system:{},portfolio:{companies:snapshot.portfolio},digest:{mode:"live",items:[],routine:[],routine_count:0},network:{contacts:snapshot.contacts},"network/investor":snapshot.investor,"alerts/settings":snapshot.settings,"network/reconnect":{nudges:[]}};
    if(path==="/api/research/HCLTECH/brief") {
      expect(route.request().postDataJSON()).toEqual({question:"Compare revenue over the last four quarters",mode:"live",prepare_sources:true});
      await route.fulfill({contentType:"application/x-ndjson",body:JSON.stringify({type:"result",data:{...snapshot.briefs.TCS,ticker:"HCLTECH",mode:"live"}})+"\n"});return;
    }
    await route.fulfill({contentType:"application/json",body:JSON.stringify(values[path.slice(5)]||{})});
  });
  await page.goto("/");
  await expect(page.locator(".content")).toHaveAttribute("aria-busy","false");
  await expect(page.locator(".connection")).toHaveCount(0);
  await expect(page.getByRole("heading",{name:"Reconnect",exact:true})).toHaveCount(0);
  await page.getByRole("button",{name:"Show last 7 days",exact:true}).click();
  await expect(page.getByRole("button",{name:"7 days",exact:true})).toHaveAttribute("aria-pressed","true");
  await expect(page.locator(".content")).toHaveAttribute("aria-busy","false");
  await page.getByRole("button",{name:"Research",exact:true}).filter({visible:true}).click();
  await page.getByRole("textbox",{name:"Company"}).fill("HCLTECH");
  await page.getByRole("textbox",{name:"Your question"}).fill("Compare revenue over the last four quarters");
  await page.getByRole("button",{name:"Ask FINN",exact:true}).click();
  await expect(page.locator(".brief-header")).toContainText("HCLTECH");
  await page.locator(".citation-chips button").first().click();
  await expect(page.getByRole("dialog")).toBeVisible();
});

test("connected research returns a cited brief from original company sources",async({page})=>{
  test.skip(process.env.FINN_E2E_LIVE === "0","Requires the running backend and model");
  await page.goto("/");
  await expect(page.locator(".content")).toHaveAttribute("aria-busy","false");
  await expect(page.locator(".offline-status")).toHaveCount(0);
  await page.getByRole("button",{name:"Research",exact:true}).filter({visible:true}).click();
  await page.getByRole("textbox",{name:"Company"}).fill("TCS");
  await page.getByRole("button",{name:"Ask FINN",exact:true}).click();
  await expect(page.locator(".brief-header")).toContainText("Primary-source research",{timeout:110000});
  await expect(page.locator(".brief-coverage")).toContainText("documents");
  await page.locator(".citation-chips button").first().click();
  await expect(page.locator("dialog .source-excerpt, dialog .financial-table")).toBeVisible();
  await expect(page.getByRole("link",{name:"Open original document"})).toBeVisible();
  await expect(page.locator("dialog")).not.toContainText(/SYNTHETIC REVIEW|fictional financials/i);
});

test("installed shell updates old caches and reloads without the network",async({page,context})=>{
  await page.addInitScript(async()=>{if(!sessionStorage.getItem("old-cache-seeded")){sessionStorage.setItem("old-cache-seeded","1");await caches.open("finn-static-v7");}});
  let navigations=0;page.on("framenavigated",frame=>{if(frame===page.mainFrame())navigations++;});
  await page.goto("/");
  await expect.poll(()=>navigations).toBeGreaterThanOrEqual(2);
  await expect.poll(async()=>{try{return await page.evaluate(async()=>(await caches.keys()).includes("finn-static-v7"));}catch{return true;}}).toBe(false);
  await expect(page.getByRole("heading",{name:"Portfolio Status"})).toBeVisible();
  expect(await page.evaluate(async()=>{await navigator.serviceWorker.ready;return true;})).toBe(true);
  await expect.poll(()=>page.evaluate(()=>!!navigator.serviceWorker.controller)).toBe(true);
  await context.setOffline(true);
  await page.reload();
  await expect(page.getByRole("heading",{name:"Portfolio Status"})).toBeVisible();
  await page.getByRole("button",{name:"Research",exact:true}).filter({visible:true}).click();
  await page.getByRole("button",{name:"TCS",exact:true}).click();
  await expect(page.getByRole("heading",{name:"Promised vs delivered",exact:true})).toBeVisible();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
});

test("portfolio edits persist through the API",async({page})=>{
 test.skip(process.env.FINN_E2E_LIVE === "0","Requires the running backend");
 const original=await (await page.request.get("/api/portfolio")).json();
 try {
 await page.goto("/");
 await expect(page.locator(".content")).toHaveAttribute("aria-busy","false");
 await page.getByRole("button",{name:"Manage portfolio",exact:true}).click();
 const added=["HCLTECH","TITAN","CDSL","ICICIBANK"].find(ticker=>!original.companies.some((c:{ticker:string})=>c.ticker===ticker))!;
 await page.getByRole("textbox",{name:"Company name or ticker"}).fill(added);
 await page.getByRole("button",{name:"Add company",exact:true}).click();
 await page.route("**/api/portfolio",async route=>{if(route.request().method()==="GET")await new Promise(resolve=>setTimeout(resolve,1500));await route.continue();});
 await page.getByRole("button",{name:"Save portfolio",exact:true}).click();
 await expect(page.getByRole("dialog")).not.toBeVisible({timeout:20000});
 const portfolio=await (await page.request.get("/api/portfolio")).json();
 expect(portfolio.companies.some((c:{ticker:string})=>c.ticker===added)).toBe(true);
 await page.getByRole("button",{name:"Manage portfolio",exact:true}).click();
 await page.getByRole("button",{name:`Remove ${added}`}).click();
 await page.getByRole("button",{name:"Save portfolio",exact:true}).click();
 await expect(page.getByRole("dialog")).not.toBeVisible({timeout:20000});
 } finally {
  expect((await page.request.put("/api/portfolio",{data:original})).status()).toBe(200);
 }
});

 test("public research refuses synthetic mode",async({request})=>{
   const response=await request.post("/api/research/TCS/brief",{data:{mode:"demo",prepare_sources:false}});
   expect(response.status()).toBe(422);
 });

 test("synthetic cached brief is never displayed",async({page})=>{
   const snapshot=await (await page.request.get("/snapshot.json")).json();
   snapshot.briefs.TCS.mode="demo";
   await page.route("**/snapshot.json",route=>route.fulfill({contentType:"application/json",body:JSON.stringify(snapshot)}));
   await page.route("**/api/**",route=>route.fulfill({status:503,body:"{}"}));
   await page.goto("/");
   await expect(page.locator(".content")).toHaveAttribute("aria-busy","false");
   await page.getByRole("button",{name:"Research",exact:true}).filter({visible:true}).click();
   await page.getByRole("textbox",{name:"Company"}).fill("TCS");
   await page.getByRole("button",{name:"Ask FINN",exact:true}).click();
   await expect(page.locator(".error-panel")).toContainText("Reconnect");
   await expect(page.locator(".brief-header")).toHaveCount(0);
 });

 test("research pages show investor information without build details",async({page})=>{
   const snapshot=await (await page.request.get("/snapshot.json")).json();
   snapshot.briefs.TCS.model="hyde/glm-5.3-flash";
   snapshot.briefs.TCS.gaps=["Model narrative is unavailable: hyde/glm-5.3-flash", "Publication dates unavailable (published_on null).", "No computed guidance comparisons supplied."];
   await page.route("**/snapshot.json",route=>route.fulfill({contentType:"application/json",body:JSON.stringify(snapshot)}));
   await page.route("**/api/**",route=>route.fulfill({status:503,body:"{}"}));
   await page.goto("/");
   await page.getByRole("button",{name:"Research",exact:true}).filter({visible:true}).click();
   await page.getByRole("button",{name:"TCS",exact:true}).click();
   await expect(page.locator(".brief-header")).toBeVisible();
   await expect(page.locator("body")).not.toContainText(/Analysis:|hyde\/|glm-\d|published_on|model narrative|computed guidance/i);
   await page.getByRole("button",{name:"Sources & privacy",exact:true}).click();
   await expect(page.locator(".about-copy")).not.toContainText(/model|provider|backend|API|build/i);
   expect((await page.locator(".about-copy").innerText()).match(/synthetic/gi)).toHaveLength(1);
 });

 test("provider failures show a plain research error",async({page})=>{
   const snapshot=await (await page.request.get("/snapshot.json")).json();
   await page.route("**/api/**",async route=>{
     const path=new URL(route.request().url()).pathname.slice(5);
     if(path==="alerts/settings" && route.request().method()==="PUT") {await route.fulfill({status:422,contentType:"application/json",body:JSON.stringify({detail:"Configure model key in backend API"})});return;}
     if(path==="research/TCS/brief") {await route.fulfill({contentType:"application/x-ndjson",body:JSON.stringify({type:"error",data:"Model provider hyde/glm-5.3-flash returned invalid JSON schema"})+"\n"});return;}
     const values:Record<string,unknown>={portfolio:{companies:snapshot.portfolio},digest:{mode:"live",items:[],routine:[],routine_count:0},network:{contacts:snapshot.contacts},"network/investor":snapshot.investor,"alerts/settings":snapshot.settings,"network/reconnect":{nudges:[]}};
     await route.fulfill({contentType:"application/json",body:JSON.stringify(values[path]||{})});
   });
   await page.goto("/");
   await expect(page.locator(".content")).toHaveAttribute("aria-busy","false");
   await page.getByRole("button",{name:"Research",exact:true}).filter({visible:true}).click();
   await page.getByRole("button",{name:"TCS",exact:true}).click();
   await expect(page.locator(".error-panel")).toContainText("Please try again");
   await expect(page.locator("body")).not.toContainText(/hyde\/|glm-\d|provider|JSON schema/i);
   await page.getByRole("button",{name:"Alert preferences",exact:true}).filter({visible:true}).first().click();
   await page.getByRole("button",{name:"Save preferences",exact:true}).click();
   await expect(page.locator("dialog [role=alert]")).toContainText("Please try again");
   await expect(page.locator("dialog")).not.toContainText(/model key|backend|API/);

 });

 test("company name discovers NVIDIA and a repeat reuses its analysis",async({page})=>{
   test.skip(process.env.FINN_E2E_LIVE === "0","Requires the backend and configured model");
   await page.goto("/");
   await expect(page.locator(".content")).toHaveAttribute("aria-busy","false");
   await page.getByRole("button",{name:"Research",exact:true}).filter({visible:true}).click();
   await page.getByRole("textbox",{name:"Company",exact:true}).fill("NVIDIA");
   await page.getByRole("textbox",{name:"Your question"}).fill("what is happening");
   await page.getByRole("button",{name:"Ask FINN",exact:true}).click();
   await expect(page.locator(".brief-header")).toContainText("NVIDIA",{timeout:110000});
   await expect(page.getByRole("textbox",{name:"Company",exact:true})).toHaveValue("NVDA");
   await expect(page.locator(".brief-coverage")).toContainText("1 annual");
   await page.locator(".citation-chips button").first().click();
   await expect(page.getByRole("link",{name:"Open original document"})).toHaveAttribute("href",/^https:\/\/www\.sec\.gov\/Archives\//);
   await page.getByRole("button",{name:"Close dialog"}).click();
   const pending=page.waitForResponse(response=>new URL(response.url()).pathname==="/api/research/NVDA/brief");
   const started=Date.now();
   await page.getByRole("button",{name:"Ask FINN",exact:true}).click();
   const response=await pending;
   const events=(await response.text()).trim().split("\n").map(line=>JSON.parse(line));
   expect(events.at(-1).data.cached).toBe(true);
   expect(Date.now()-started).toBeLessThan(10000);
   await expect(page.locator(".brief-header")).toContainText("NVIDIA");
 });

 test("dark surfaces keep text and controls readable",async({page})=>{
   await page.route("**/api/**",route=>route.fulfill({status:503,body:"{}"}));
   await page.goto("/");
   await expect(page.locator(".content")).toHaveAttribute("aria-busy","false");
   const colors=await page.evaluate(()=>{
     const rgb=(value:string)=>value.match(/[\d.]+/g)!.slice(0,3).map(Number);
     const lum=(value:string)=>rgb(value).map(v=>v/255).map(v=>v<=0.04045?v/12.92:((v+0.055)/1.055)**2.4).reduce((sum,v,i)=>sum+v*[0.2126,0.7152,0.0722][i],0);
     const ratio=(a:string,b:string)=>(Math.max(lum(a),lum(b))+0.05)/(Math.min(lum(a),lum(b))+0.05);
     const body=getComputedStyle(document.body),muted=getComputedStyle(document.querySelector(".eyebrow")!),button=getComputedStyle(document.querySelector(".primary-button")!);
     return {background:lum(body.backgroundColor),text:ratio(body.color,body.backgroundColor),muted:ratio(muted.color,body.backgroundColor),button:ratio(button.color,button.backgroundColor)};
   });
   expect(colors.background).toBeLessThan(0.08);
   expect(colors.text).toBeGreaterThanOrEqual(7);
   expect(colors.muted).toBeGreaterThanOrEqual(4.5);
   expect(colors.button).toBeGreaterThanOrEqual(4.5);
   await page.getByRole("button",{name:"Research",exact:true}).filter({visible:true}).click();
   await expect(page.locator(".ask-form")).toHaveCSS("background-color",/rgb\((?:\d{1,2}, ){2}\d{1,2}\)/);
   await page.getByRole("button",{name:"TCS",exact:true}).click();
   await page.locator(".citation-chips button").first().click();
   const paper=await page.locator(".source-excerpt").evaluate(el=>({background:getComputedStyle(el).backgroundColor,color:getComputedStyle(el).color}));
   expect(paper.background).not.toBe("rgb(255, 255, 255)");
   expect(paper.color).not.toBe("rgb(0, 0, 0)");
 });

 test("portfolio adds beyond three with Enter and explains capacity",async({page})=>{
 const snapshot=await (await page.request.get("/snapshot.json")).json();
 let companies=["INFY","SRF","TCS"].map(ticker=>({ticker,name:ticker,sector:""}));let saves=0;
 await page.route("**/api/**",async route=>{
   const path=new URL(route.request().url()).pathname.slice(5);
   if(path==="portfolio"&&route.request().method()==="PUT"){companies=route.request().postDataJSON().companies;saves++;}
   if(path==="portfolio/resolve"){const ticker=route.request().postDataJSON().query.trim().toUpperCase();await route.fulfill({contentType:"application/json",body:JSON.stringify({ticker,name:ticker,sector:"",exchange:"NSE"})});return;}
   if(path.startsWith("refresh")){await route.fulfill({contentType:"application/json",body:JSON.stringify({id:"portfolio-test",status:"completed",sources:[]})});return;}
   const values:Record<string,unknown>={portfolio:{companies},digest:{mode:"live",items:[],routine:[],routine_count:0},network:{contacts:snapshot.contacts},"network/investor":snapshot.investor,"alerts/settings":snapshot.settings,"network/reconnect":{nudges:[]}};
   await route.fulfill({contentType:"application/json",body:JSON.stringify(values[path]||{})});
 });
 await page.goto("/");await expect(page.locator(".content")).toHaveAttribute("aria-busy","false");
 await page.getByRole("button",{name:"Manage portfolio",exact:true}).click();
 await expect(page.getByText("3 companies",{exact:true})).toBeVisible();
 const input=page.getByRole("textbox",{name:"Company name or ticker"});
 await input.fill("HCLTECH");await input.press("Enter");
 await expect(page.getByRole("button",{name:"Remove HCLTECH"})).toBeVisible();expect(saves).toBe(0);
 await input.fill("HCLTECH");await input.press("Enter");
 await expect(page.locator(".portfolio-form").getByRole("alert")).toContainText("already in your portfolio");
 for(const ticker of ["RELIANCE","TITAN","CDSL"]){await input.fill(ticker);await input.press("Enter");}
 await expect(page.getByText("7 companies",{exact:true})).toBeVisible();
 await page.getByRole("button",{name:"Save portfolio",exact:true}).click();
 await expect(page.getByRole("dialog")).not.toBeVisible();expect(companies).toHaveLength(7);expect(saves).toBe(1);
 await page.reload();await expect(page.locator(".content")).toHaveAttribute("aria-busy","false");
 if(await page.locator(".watchlist").isVisible())await page.getByRole("button",{name:"View all 7 companies",exact:true}).click();
 else await page.getByRole("button",{name:"Manage portfolio",exact:true}).click();
 await expect(page.getByText("7 companies",{exact:true})).toBeVisible();
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 await page.getByRole("button",{name:"Close dialog"}).click();
 companies=Array.from({length:50},(_,i)=>({ticker:`TEST${i}`,name:`Test company ${i}`,sector:""}));
 await page.reload();await expect(page.locator(".content")).toHaveAttribute("aria-busy","false");
 await page.getByRole("button",{name:"Manage portfolio",exact:true}).click();
 await input.fill("HCLTECH");await page.getByRole("button",{name:"Add company",exact:true}).click();
 await expect(page.locator(".portfolio-form").getByRole("alert")).toContainText("50 companies");
 await expect(page.getByRole("button",{name:"Remove HCLTECH"})).toHaveCount(0);
 await expect(page.getByRole("button",{name:"Save portfolio",exact:true})).toBeEnabled();
 });

 test("clean research and people flows keep navigation and empty states useful",async({page},info)=>{
 const snapshot=await (await page.request.get("/snapshot.json")).json();
 await page.route("**/api/**",async route=>{
  const path=new URL(route.request().url()).pathname.slice(5);
  if(path.startsWith("research/")){await route.fulfill({contentType:"application/x-ndjson",body:JSON.stringify({type:"result",data:{...snapshot.briefs.TCS,network:[],guidance:[]}})+"\n"});return;}
  const values:Record<string,unknown>={portfolio:{companies:snapshot.portfolio},digest:{mode:"live",items:[],routine:[],routine_count:0},network:{contacts:snapshot.contacts},"network/investor":snapshot.investor,"alerts/settings":snapshot.settings,"network/reconnect":{nudges:[]}};
  await route.fulfill({contentType:"application/json",body:JSON.stringify(values[path]||{})});
 });
 await page.goto("/");await expect(page.locator(".content")).toHaveAttribute("aria-busy","false");
 await page.getByRole("button",{name:"Research",exact:true}).filter({visible:true}).click();
 await expect(page.getByRole("textbox",{name:"Your question"})).toHaveAttribute("placeholder","Leave blank for a company overview");
 if(info.project.name==="mobile"){
  const company=await page.getByRole("textbox",{name:"Company"}).boundingBox();
  expect(company!.width).toBeGreaterThan(250);
 } else {expect((await page.getByRole("textbox",{name:"Company"}).boundingBox())!.width).toBeGreaterThan(175); }
 await page.screenshot({path:`/private/tmp/finn-${info.project.name}-research-cleanup.png`,fullPage:true});
 await page.getByRole("button",{name:"TCS",exact:true}).click();
 await expect(page.getByRole("heading",{name:"Promised vs delivered",exact:true})).toBeVisible();
 await expect(page.getByRole("heading",{name:"Relevant contacts",exact:true})).toHaveCount(0);
 await expect(page.getByText("Comparable numerical guidance and delivered outcomes weren’t found in the available sources.",{exact:true})).toHaveCount(0);
 await page.locator(".citation-chips button").first().click();
 await expect(page.getByRole("dialog",{name:"Source excerpt",exact:true})).toBeVisible();
 await page.getByRole("button",{name:"Close dialog"}).click();
 await page.evaluate(()=>window.scrollTo(0,document.body.scrollHeight));
 await page.getByRole("button",{name:"People",exact:true}).filter({visible:true}).click();
 await expect.poll(()=>page.evaluate(()=>window.scrollY)).toBe(0);
 await page.getByRole("textbox",{name:"Search people"}).fill("  Neha Rao  ");
 await expect(page.locator(".person-card")).toHaveCount(1);
 await page.getByRole("textbox",{name:"Search people"}).fill("no-such-person");
 await page.getByRole("button",{name:"Show all people",exact:true}).click();
 await expect(page.getByRole("textbox",{name:"Search people"})).toHaveValue("");
 await expect(page.locator(".person-card")).toHaveCount(snapshot.contacts.length);
 await page.getByRole("button",{name:"Sources & privacy",exact:true}).click();
 await expect(page.locator(".about-copy")).toContainText("Indian and US companies");
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 });

 test("research opens with short cited previews that jump to details and original sources",async({page},info)=>{
 const snapshot=await (await page.request.get("/snapshot.json")).json();
 const brief=structuredClone(snapshot.briefs.TCS);
 brief.sections.find((s:{id:string})=>s.id==="bear").findings=[];
 await page.route("**/api/**",async route=>{
  const path=new URL(route.request().url()).pathname.slice(5);
  if(path.startsWith("research/")){await route.fulfill({contentType:"application/x-ndjson",body:JSON.stringify({type:"result",data:brief})+"\n"});return;}
  const values:Record<string,unknown>={portfolio:{companies:snapshot.portfolio},digest:{mode:"live",items:[],routine:[],routine_count:0},network:{contacts:snapshot.contacts},"network/investor":snapshot.investor,"alerts/settings":snapshot.settings,"network/reconnect":{nudges:[]}};
  await route.fulfill({contentType:"application/json",body:JSON.stringify(values[path]||{})});
 });
 await page.goto("/");await expect(page.locator(".content")).toHaveAttribute("aria-busy","false");
 await page.getByRole("button",{name:"Research",exact:true}).filter({visible:true}).click();
 await page.getByRole("button",{name:"TCS",exact:true}).click();
 const overview=page.getByRole("navigation",{name:"Research overview",exact:true});
 await expect(overview).toBeVisible();
 await expect(overview.locator(".summary-jump")).toHaveCount(brief.sections.filter((section:{id:string})=>!["answer","bull","bear"].includes(section.id)).length+1);
 for(const section of brief.sections.filter((section:{id:string})=>!["answer","bull","bear"].includes(section.id))){
  const summary=overview.locator(`a[href="#research-${section.id}"]`);
  await expect(summary).toContainText(section.title);
  if(section.findings.length)await expect(summary.locator("p")).toHaveText(await page.locator(`#research-${section.id} .finding`).first().evaluate(el=>el.firstChild?.textContent||""));
  else await expect(summary).toContainText(section.empty_message);
  const preview=summary.locator("p");
  const height=await preview.evaluate(el=>({height:el.getBoundingClientRect().height,line:parseFloat(getComputedStyle(el).lineHeight)}));
  expect(height.height).toBeLessThanOrEqual(height.line*2+1);
 }
 await overview.screenshot({path:`/private/tmp/finn-${info.project.name}-research-overview.png`});
 await overview.locator('a[href="#research-financial"]').click();
 const financial=page.locator("#research-financial");
 await expect.poll(()=>financial.evaluate(el=>Math.round(el.getBoundingClientRect().top))).toBeGreaterThanOrEqual(0);
 expect(await financial.evaluate(el=>el.getBoundingClientRect().top)).toBeLessThan(100);
 await expect(financial.locator(".finding").first()).toContainText(brief.sections.find((s:{id:string})=>s.id==="financial").findings[0].text);
 const expectedIds=new Set(brief.sections.find((s:{id:string})=>s.id==="financial").findings.flatMap((f:{citation_ids:string[]})=>f.citation_ids));
 const expectedSources=brief.sources.filter((source:{citation_id:string})=>expectedIds.has(source.citation_id));
 const originalLinks=financial.locator(".section-sources a");
 expect(await originalLinks.count()).toBeGreaterThan(0);
 for(const link of await originalLinks.all()){
  const href=await link.getAttribute("href");
  expect(expectedSources.some((source:{url:string;page:number|null})=>href===source.url+(source.page?`#page=${source.page}`:""))).toBe(true);
  await expect(link).toHaveAttribute("target","_blank");
 }
 await financial.getByRole("link",{name:"Back to overview",exact:true}).click();
 await expect(overview).toBeInViewport();
 await overview.getByRole("link",{name:"View sources for Business snapshot",exact:true}).click();
 await expect(page.locator("#research-business-sources")).toBeInViewport();
 await page.locator("#research-business .citation-chips button").first().click();
 await expect(page.getByRole("dialog",{name:"Source excerpt",exact:true})).toBeVisible();
 await expect(page.getByRole("link",{name:"Open original document",exact:true})).toHaveAttribute("href",/^https:\/\//);
 await page.getByRole("button",{name:"Close dialog"}).click();
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 });

 test("portfolio status verifies NVIDIA, checks its news automatically and opens primary-source research",async({page},info)=>{
 const snapshot=await (await page.request.get("/snapshot.json")).json();
 let companies=snapshot.portfolio.slice(0,1),checked=false,checks=0;
 await page.route("**/api/**",async route=>{
  const path=new URL(route.request().url()).pathname.slice(5);
  if(path==="portfolio/resolve"){
   expect(route.request().postDataJSON().query).toBe("NVIDIA");
   await route.fulfill({contentType:"application/json",body:JSON.stringify({ticker:"US-NVDA",name:"NVIDIA CORP",sector:"",exchange:"US"})});return;
  }
  if(path==="portfolio"&&route.request().method()==="PUT")companies=route.request().postDataJSON().companies;
  if(path==="refresh"){
   expect(route.request().postDataJSON().news).toBe(true);expect(route.request().postDataJSON().enrich).toBe(true);checked=true;checks++;
   await route.fulfill({contentType:"application/json",body:JSON.stringify({id:"news-check",status:"queued",tickers:["US-NVDA"]})});return;
  }
  if(path==="refresh/news-check"){
   await route.fulfill({contentType:"application/json",body:JSON.stringify({id:"news-check",status:"completed",sources:[{ticker:"US-NVDA",source:"news",status:"ok",count:1}]})});return;
  }
  if(path==="research/US-NVDA/brief"){
   await route.fulfill({contentType:"application/x-ndjson",body:JSON.stringify({type:"result",data:{...snapshot.briefs.TCS,ticker:"NVDA",company_id:"US-NVDA",company_name:"NVIDIA CORP",market:"US"}})+"\n"});return;
  }
  const news={id:"news-one",ticker:"US-NVDA",type:"news",category:"news",mode:"live",title:"NVIDIA reports a product launch",summary:"NVIDIA reports a product launch",published_at:new Date().toISOString(),url:"https://finance.yahoo.com/news/original-story.html",source:{kind:"news",publisher:"Yahoo Finance"},network:[],attention_score:{value:1}};
  const values:Record<string,unknown>={portfolio:{companies},digest:{mode:"live",items:checked?[news]:[],routine:[],routine_count:0},network:{contacts:snapshot.contacts},"network/investor":snapshot.investor,"alerts/settings":snapshot.settings,"network/reconnect":{nudges:[]}};
  await route.fulfill({contentType:"application/json",body:JSON.stringify(values[path]||{})});
 });
 await page.goto("/");await expect(page.locator(".content")).toHaveAttribute("aria-busy","false");
 await expect(page.getByRole("heading",{name:"Portfolio Status",exact:true})).toBeVisible();
 await expect(page.getByText("What changed, why it matters, and who can help.",{exact:true})).toHaveCount(0);
 await page.getByRole("button",{name:"Manage portfolio",exact:true}).click();
 await page.getByRole("textbox",{name:"Company name or ticker"}).fill("NVIDIA");
 await page.getByRole("button",{name:"Add company",exact:true}).click();
 await expect(page.getByRole("button",{name:"Remove NVDA",exact:true})).toBeVisible();
 await expect(page.getByRole("dialog")).toContainText("NVIDIA CORP");
 await page.getByRole("button",{name:"Save portfolio",exact:true}).click();
 await page.locator(".feed-group").filter({has:page.locator("summary h2",{hasText:"News"})}).locator("summary").click();
 await expect(page.getByRole("heading",{name:"NVIDIA reports a product launch",exact:true})).toBeVisible();
 expect(checked).toBe(true);
 await page.screenshot({path:`/private/tmp/finn-${info.project.name}-portfolio-status.png`,fullPage:true});
 await expect(page.getByRole("link",{name:"Read article",exact:true})).toHaveAttribute("href","https://finance.yahoo.com/news/original-story.html");
 await expect(page.getByRole("button",{name:"Check updates",exact:true})).toBeEnabled();
 await page.getByRole("button",{name:"Check updates",exact:true}).click();
 await expect.poll(()=>checks).toBe(2);
 await page.getByRole("button",{name:"Research company",exact:true}).click();
 await expect(page.locator(".brief-header")).toContainText("NVIDIA CORP");
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 });
