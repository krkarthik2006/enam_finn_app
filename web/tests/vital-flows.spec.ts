import {test,expect} from "@playwright/test";

test("30 days expands quarterly results and opens the original filing",async({page})=>{
 const errors:string[]=[];page.on("pageerror",error=>errors.push(error.message));
 await page.route("**/api/announcements/*/enrich",route=>route.fulfill({status:503,contentType:"application/json",body:'{"detail":"Analysis unavailable"}'}));
 await page.route("**/api/digest?**",async route=>{
  const response=await route.fetch();const digest=await response.json();
  for(const item of [...digest.items,...digest.routine])if(item.enrichment?.results)item.enrichment.results.cross_check={status:"incompatible_period_basis_or_units",metrics:{}};
  await route.fulfill({response,json:digest});
 });
 await page.goto("/");
 await expect(page.locator(".content")).toHaveAttribute("aria-busy","false",{timeout:30000});
 await page.getByRole("button",{name:"30 days",exact:true}).click();
 await expect(page.locator(".content")).toHaveAttribute("aria-busy","false",{timeout:30000});
 const results=page.locator(".feed-group").filter({has:page.locator("summary h2").filter({hasText:"Quarterly results"})});
 await results.locator("summary").click();
 await expect(results.locator(".feed-card").first(),JSON.stringify(errors)).toBeVisible({timeout:10000});
 const infy=results.locator(".feed-card").filter({has:page.locator(".company-row strong",{hasText:"Infosys"})}).first();
 await expect(infy).toBeVisible();
 await infy.getByRole("button",{name:/View INFY/}).click();
 await expect(page.getByRole("dialog")).toBeVisible();
 const link=page.getByRole("dialog").getByRole("link",{name:"Open filing",exact:true});
 await expect(link).toBeVisible();
 const response=await page.request.get((await link.getAttribute("href"))!);
 expect(response.status()).toBe(200);expect(response.headers()["content-type"]).toContain("application/pdf");
 expect((await response.body()).subarray(0,5).toString()).toBe("%PDF-");
 await page.getByRole("button",{name:"Close dialog"}).click();
 await results.locator("summary").click();await results.locator("summary").click();
 await expect(results.locator(".feed-card").first()).toBeVisible();
 expect(errors).toEqual([]);
});

test("all populated Push sections expand without crashing",async({page})=>{
 const errors:string[]=[];page.on("pageerror",error=>errors.push(error.message));
 await page.route("**/api/announcements/*/enrich",route=>route.fulfill({status:503,body:"{}"}));
 await page.goto("/");await expect(page.locator(".content")).toHaveAttribute("aria-busy","false",{timeout:30000});
 await page.getByRole("button",{name:"30 days",exact:true}).click();
 await expect(page.locator(".content")).toHaveAttribute("aria-busy","false",{timeout:30000});
 for(const group of await page.locator(".feed-group").all()){
  await group.locator("summary").click();
  if((await group.getAttribute("class"))?.includes("has-events"))await expect(group.locator(".feed-card").first()).toBeVisible();
  else await expect(group.locator(".empty-note").first()).toBeVisible();
  await group.locator("summary").click();
 }
 await expect(page.locator(".feed-group").last().locator("summary")).toContainText("Other filings");
 expect(errors).toEqual([]);
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
});

test("custom dates are inclusive in IST and survive reload before returning to presets",async({page})=>{
 await page.goto("/");await expect(page.locator(".content")).toHaveAttribute("aria-busy","false",{timeout:30000});
 const date=(days:number)=>new Date(Date.now()+19800000-days*86400000).toISOString().slice(0,10);
 const from=date(20),to=date(10);
 await page.getByRole("button",{name:"Custom",exact:true}).click();
 await page.getByLabel("Start date",{exact:true}).fill(from);await page.getByLabel("End date",{exact:true}).fill(to);
 const response=page.waitForResponse(r=>r.url().includes("/api/digest?")&&new URL(r.url()).searchParams.get("since")===new Date(`${from}T00:00:00+05:30`).toISOString());
 await page.getByRole("button",{name:"Apply",exact:true}).click();
 const loaded=await response;expect(loaded.status()).toBe(200);
 expect(new URL(loaded.url()).searchParams.get("until")).toBe(new Date(new Date(`${to}T00:00:00+05:30`).getTime()+86400000-1).toISOString());
 await expect(page.locator(".content")).toHaveAttribute("aria-busy","false");
 await page.reload();await expect(page.locator(".content")).toHaveAttribute("aria-busy","false",{timeout:30000});
 await expect(page.getByRole("button",{name:"Custom",exact:true})).toHaveAttribute("aria-pressed","true");
 await page.getByRole("button",{name:"30 days",exact:true}).click();await expect(page.locator(".content")).toHaveAttribute("aria-busy","false",{timeout:30000});
 await expect(page.getByRole("button",{name:"30 days",exact:true})).toHaveAttribute("aria-pressed","true");
 await page.reload();await expect(page.getByRole("button",{name:"30 days",exact:true})).toHaveAttribute("aria-pressed","true");
});

test("failed timeframe request retains live data and Retry recovers",async({page})=>{
 await page.goto("/");await expect(page.locator(".content")).toHaveAttribute("aria-busy","false",{timeout:30000});
 let fail=true;
 await page.route("**/api/digest?**",route=>fail?route.fulfill({status:503,body:"{}"}):route.continue());
 await page.getByRole("button",{name:"30 days",exact:true}).click();
 await expect(page.locator(".timeframe-error")).toContainText("previous results");
 await expect(page.locator(".offline-status")).toHaveCount(0);
 fail=false;await page.locator(".timeframe-error").getByRole("button",{name:"Retry",exact:true}).click();
 await expect(page.locator(".content")).toHaveAttribute("aria-busy","false",{timeout:30000});await expect(page.locator(".timeframe-error")).toHaveCount(0);
 await expect(page.locator(".feed-group.has-events").first()).toBeVisible();
});

test("Pull answers the question first with cited sources, charts and both thesis cases",async({page})=>{
 const errors:string[]=[];page.on("pageerror",error=>errors.push(error.message));
 await page.goto("/");await expect(page.locator(".content")).toHaveAttribute("aria-busy","false",{timeout:30000});
 await page.getByRole("button",{name:"Research",exact:true}).filter({visible:true}).click();
 await page.getByRole("textbox",{name:"Company",exact:true}).fill("MARUTI");
 await page.getByRole("textbox",{name:"Your question",exact:true}).fill("were they profitable last year");
 const response=page.waitForResponse(r=>r.url().includes("/research/MARUTI/brief"));
 await page.getByRole("button",{name:"Ask FINN",exact:true}).click();
 const events=(await (await response).text()).trim().split("\n").map(line=>JSON.parse(line));
 const brief=events.find(event=>event.type==="result")?.data;expect(brief).toBeTruthy();
 expect(brief.sources.every((source:{kind:string})=>["annual_report","transcript","financial_table"].includes(source.kind))).toBe(true);
 const ids=new Set(brief.sources.map((source:{citation_id:string})=>source.citation_id));
 for(const section of brief.sections)for(const finding of section.findings){expect(finding.citation_ids.length).toBeGreaterThan(0);expect(finding.citation_ids.every((id:string)=>ids.has(id))).toBe(true);}
 await expect(page.locator(".research-answer")).toContainText(/Yes/,{timeout:110000});
 await expect(page.locator(".research-answer")).toContainText("2026");
 await expect(page.locator(".financial-trend")).toHaveCount(3);
 await expect(page.locator(".thesis-case.bull .finding").first()).toBeVisible();await expect(page.locator(".thesis-case.bear .finding").first()).toBeVisible();
 await page.locator(".research-answer .citation-chips button").first().click();
 await expect(page.getByRole("dialog",{name:"Source excerpt",exact:true})).toBeVisible();
 await expect(page.getByRole("link",{name:"Open original document",exact:true})).toHaveAttribute("href",/^https:\/\//);
 expect(errors).toEqual([]);expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
});
