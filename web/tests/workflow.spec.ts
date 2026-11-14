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
  await page.locator(".citation-chips button").first().click();
  await expect(page.locator("dialog")).not.toContainText(/SYNTHETIC REVIEW|fictional financials/i);
  await page.locator("dialog").screenshot({path:`/private/tmp/finn-${info.project.name}-real-tcs-source.png`});
  await expect(page.locator("dialog .source-excerpt, dialog .financial-table")).toBeVisible();
  await expect(page.getByRole("link",{name:"Open original document"})).toBeVisible();
  await expect(page.locator("dialog")).not.toContainText(/SYNTHETIC REVIEW|fictional financials/i);
  await page.getByRole("button",{name:"Close dialog"}).click();
  await page.getByRole("button",{name:"People",exact:true}).filter({visible:true}).click();
  await expect(page.locator(".people-grid")).not.toContainText(/Demo Professional|Mock IT Services/);
  await page.getByRole("textbox",{name:"Search people"}).fill("Neha Rao");
  await page.locator(".person-card").click();
  await expect(page.locator("dialog .intro-path")).toContainText("Neha");
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
  await page.getByRole("textbox",{name:"NSE ticker"}).fill("HCLTECH");
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
  await page.getByRole("textbox",{name:"NSE ticker"}).fill("TCS");
  await page.getByRole("button",{name:"Ask FINN",exact:true}).click();
  await expect(page.locator(".brief-header")).toContainText("Primary-source research",{timeout:110000});
  await expect(page.locator(".brief-coverage")).toContainText(/Source-cited analysis|Saved analysis/);
  await page.locator(".citation-chips button").first().click();
  await expect(page.locator("dialog .source-excerpt, dialog .financial-table")).toBeVisible();
  await expect(page.getByRole("link",{name:"Open original document"})).toBeVisible();
  await expect(page.locator("dialog")).not.toContainText(/SYNTHETIC REVIEW|fictional financials/i);
});

test("installed shell reloads without the network",async({page,context})=>{
  await page.goto("/");
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
   await page.getByRole("textbox",{name:"NSE ticker"}).fill("TCS");
   await page.getByRole("button",{name:"Ask FINN",exact:true}).click();
   await expect(page.locator(".error-panel")).toContainText("Reconnect");
   await expect(page.locator(".brief-header")).toHaveCount(0);
 });
