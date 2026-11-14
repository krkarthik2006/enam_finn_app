import {test,expect} from "@playwright/test";

test("review feed, network path, evidence and settings with backend offline",async({page},info)=>{
  await page.route("**/api/**",route=>route.fulfill({status:503,contentType:"application/json",body:'{"detail":"Offline check"}'}));
  const errors:string[]=[];page.on("pageerror",error=>errors.push(error.message));
  await page.goto("/");
  await expect(page.getByRole("heading",{name:"A little less noise."})).toBeVisible();
  await page.getByRole("button",{name:"View MOCKIT management_change"}).click();
  await expect(page.getByText("Recorded introduction",{exact:true})).toBeVisible();
  await expect(page.locator(".intro-path")).toContainText("Neha");
  await expect(page.locator(".intro-path")).toContainText("Riya");
  await page.getByRole("button",{name:"Close dialog"}).click();
  await page.getByRole("button",{name:"View MOCKIT results",exact:true}).click();
  await expect(page.getByRole("heading",{name:"Reference cross-check"})).toBeVisible();
  await expect(page.getByText("9.1% difference")).toBeVisible();
  await page.getByRole("button",{name:"Close dialog"}).click();
  await page.getByRole("button",{name:"Ask FINN",exact:true}).filter({visible:true}).click();
  await expect(page.getByRole("heading",{name:"Promised vs delivered",exact:true})).toBeVisible();
  await expect(page.locator(".guidance-callout")).toContainText("2 percentage points");
  await page.locator(".citation-chips button").first().click();
  await expect(page.locator("dialog .source-excerpt")).toContainText("SYNTHETIC");
  await page.getByRole("button",{name:"Close dialog"}).click();
  await page.getByRole("button",{name:"People",exact:true}).filter({visible:true}).click();
  await page.getByRole("textbox",{name:"Search people"}).fill("Riya");
  await page.locator(".person-card").click();
  await expect(page.locator("dialog .intro-path")).toContainText("Neha");
  await page.getByRole("button",{name:"Close dialog"}).click();
  await page.getByRole("button",{name:"Alert preferences",exact:true}).filter({visible:true}).first().click();
  await page.getByRole("spinbutton",{name:"Price threshold"}).fill("6");
  await page.getByRole("button",{name:"Save preferences"}).click();
  await expect(page.getByRole("status")).toContainText("saved on this device");
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true);
  expect(errors).toEqual([]);
  await page.screenshot({path:`/private/tmp/finn-${info.project.name}-people.png`,fullPage:true});
});

test("connected streamed research reaches the real model and opens citations",async({page})=>{
  test.skip(process.env.FINN_E2E_LIVE === "0", "CI has no exported model credential; run locally for live research");
  await page.goto("/");
  await expect(page.getByText("Connected",{exact:true})).toBeAttached();
  await page.getByRole("button",{name:"Ask FINN",exact:true}).filter({visible:true}).click();
  await page.getByRole("textbox",{name:"Your question"}).fill("Explain the business and compare FY2027 Q2 EBITDA margin guidance with delivered outcomes.");
  await page.getByRole("button",{name:"Research",exact:true}).click();
  await expect(page.locator(".brief-coverage")).toContainText("Source-cited analysis",{timeout:110000});
  await expect(page.locator(".guidance-callout")).toContainText("20% delivered");
  await page.locator(".citation-chips button").first().click();
  await expect(page.locator("dialog")).toBeVisible();
});

test("installed shell reloads without the network",async({page,context})=>{
  await page.goto("/");
  await expect(page.getByRole("heading",{name:"A little less noise."})).toBeVisible();
  const installed=await page.evaluate(async()=>{if(!("serviceWorker" in navigator))return false; await navigator.serviceWorker.ready; return true;});
  expect(installed).toBe(true);
  await expect.poll(()=>page.evaluate(()=>!!navigator.serviceWorker.controller)).toBe(true);
  await context.setOffline(true);
  await page.reload();
  await expect(page.getByRole("heading",{name:"A little less noise."})).toBeVisible();
  await page.getByRole("button",{name:"Ask FINN",exact:true}).filter({visible:true}).click();
  await expect(page.getByRole("heading",{name:"Promised vs delivered",exact:true})).toBeVisible();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
});
