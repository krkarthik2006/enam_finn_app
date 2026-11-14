import{test,expect}from"@playwright/test";

test("private API rejects unsigned sessions, bad passwords and cross-origin writes",async({request,page})=>{
 test.skip(!process.env.FINN_E2E_PASSWORD,"Run against a password-protected review server");
 const password=process.env.FINN_E2E_PASSWORD!;
 expect((await request.get("/api/portfolio")).status()).toBe(401);
 expect((await request.get("/api/portfolio",{headers:{Cookie:"finn_review_session=9999999999.forged"}})).status()).toBe(401);
 expect((await request.post("/api/session",{data:{password:"incorrect"}})).status()).toBe(401);
 expect((await request.post("/api/session",{data:{password},headers:{Origin:"https://unrelated.example"}})).status()).toBe(403);
 await page.goto("/");
 await page.getByLabel("Review password").fill(password);
 await page.getByRole("button",{name:"Open workspace",exact:true}).click();
 await expect(page.getByRole("heading",{name:"Portfolio updates"})).toBeVisible();
 const cookies=await page.context().cookies();
 expect(cookies.find(c=>c.name==="finn_review_session")?.httpOnly).toBe(true);
 expect(await page.evaluate(()=>document.cookie.includes("finn_review_session"))).toBe(false);
 const response=await page.request.get("/api/portfolio");expect(response.status()).toBe(200);
 expect((await page.request.put("/api/portfolio",{data:{companies:[]},headers:{Origin:"https://unrelated.example"}})).status()).toBe(403);
 await page.request.delete("/api/session");
 expect((await page.request.get("/api/portfolio")).status()).toBe(401);
});
