import {test,expect} from "@playwright/test";

test("TVS Motor PDF opens from its card and ZIP is an official download",async({page,context})=>{
 await page.goto("/");
 await expect(page.locator(".content")).toHaveAttribute("aria-busy","false",{timeout:30000});
 await page.getByRole("button",{name:"30 days",exact:true}).click();
 await expect(page.locator(".content")).toHaveAttribute("aria-busy","false",{timeout:30000});
 const group=page.locator(".feed-group").filter({has:page.locator("summary h2").filter({hasText:"Management changes"})});
 await group.locator("summary").click();
 const pdf=group.locator(".feed-card").filter({has:page.locator('a[href*="8544f6ae84895170990d5ee1/document"]')});
 await expect(pdf).toContainText("TVS Motor");
 const responsePromise=context.waitForEvent("response",{predicate:r=>r.url().includes("8544f6ae84895170990d5ee1/document")});
 const popupPromise=page.waitForEvent("popup");
 await pdf.getByRole("link",{name:"Open filing",exact:true}).click();
 const response=await responsePromise;
 expect(response.status()).toBe(200);expect(response.headers()["content-type"]).toContain("application/pdf");
 const popup=await popupPromise;await popup.close();
 const zip=group.locator('a[href*="89e97a3082ef17f415a7e504/document"]');
 await expect(zip).toHaveText("Download filing");
 const redirect=await page.request.get((await zip.getAttribute("href"))!,{maxRedirects:0});
 expect(redirect.status()).toBe(307);
 expect(redirect.headers().location).toBe("https://nsearchives.nseindia.com/corporate/TVSMOTOR_ROID_104748_KMP_Doc.zip");
});
