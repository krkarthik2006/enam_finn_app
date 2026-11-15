import {test,expect} from "@playwright/test";

test("workspace opens without a password or session",async({page})=>{
 await page.goto("/");
 await expect(page.getByRole("heading",{name:"Portfolio Status"})).toBeVisible();
 await expect(page.getByLabel("Review password")).toHaveCount(0);
 await expect(page.getByRole("button",{name:"Sign out",exact:true})).toHaveCount(0);
 expect((await page.context().cookies()).some(c=>c.name==="finn_review_session")).toBe(false);
});

test("public proxy works without cookies and rejects cross-origin writes",async({request})=>{
 test.skip(process.env.FINN_E2E_LIVE === "0","Requires the running backend");
 expect((await request.get("/api/portfolio")).status()).toBe(200);
 const system=await request.get("/api/system");
 expect(system.status()).toBe(200);
 expect((await system.json()).authentication_enabled).toBe(true);
 expect((await request.put("/api/portfolio",{data:{companies:[]},headers:{Origin:"https://unrelated.example"}})).status()).toBe(403);
});
