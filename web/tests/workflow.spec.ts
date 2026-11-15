import {test,expect} from "@playwright/test";

test("three simple tabs, offline updates, saved research and contacts",async({page},info)=>{
  await page.route("**/api/**",route=>route.fulfill({status:503,contentType:"application/json",body:'{"detail":"Offline check"}'}));
  const errors:string[]=[];page.on("pageerror",error=>errors.push(error.message));
  await page.goto("/");
  await expect(page.getByRole("heading",{name:"Portfolio updates"})).toBeVisible();
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
  await expect(page.getByRole("combobox",{name:"Digest window"})).toHaveValue("7");
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
  await expect(page.getByRole("heading",{name:"Portfolio updates"})).toBeVisible();
  expect(await page.evaluate(async()=>{await navigator.serviceWorker.ready;return true;})).toBe(true);
  await expect.poll(()=>page.evaluate(()=>!!navigator.serviceWorker.controller)).toBe(true);
  await context.setOffline(true);
  await page.reload();
  await expect(page.getByRole("heading",{name:"Portfolio updates"})).toBeVisible();
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
 await page.getByRole("textbox",{name:"Add NSE ticker"}).fill("TESTUI");
 await page.getByRole("button",{name:"Add company",exact:true}).click();
 await page.route("**/api/portfolio",async route=>{if(route.request().method()==="GET")await new Promise(resolve=>setTimeout(resolve,1500));await route.continue();});
 await page.getByRole("button",{name:"Save portfolio",exact:true}).click();
 await expect(page.getByRole("dialog")).not.toBeVisible();
 const portfolio=await (await page.request.get("/api/portfolio")).json();
 expect(portfolio.companies.some((c:{ticker:string})=>c.ticker==="TESTUI")).toBe(true);
 await page.getByRole("button",{name:"Manage portfolio",exact:true}).click();
 await page.getByRole("button",{name:"Remove TESTUI"}).click();
 await page.getByRole("button",{name:"Save portfolio",exact:true}).click();
 await expect(page.getByRole("dialog")).not.toBeVisible();
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
     const body=getComputedStyle(document.body),muted=getComputedStyle(document.querySelector(".page-heading p")!),button=getComputedStyle(document.querySelector(".primary-button")!);
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
   const values:Record<string,unknown>={portfolio:{companies},digest:{mode:"live",items:[],routine:[],routine_count:0},network:{contacts:snapshot.contacts},"network/investor":snapshot.investor,"alerts/settings":snapshot.settings,"network/reconnect":{nudges:[]}};
   await route.fulfill({contentType:"application/json",body:JSON.stringify(values[path]||{})});
 });
 await page.goto("/");await expect(page.locator(".content")).toHaveAttribute("aria-busy","false");
 await page.getByRole("button",{name:"Manage portfolio",exact:true}).click();
 await expect(page.getByText("3 companies",{exact:true})).toBeVisible();
 const input=page.getByRole("textbox",{name:"Add NSE ticker"});
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
