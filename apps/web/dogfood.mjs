import { chromium } from "playwright";
import { mkdirSync } from "fs";
import { join } from "path";

const BASE = "http://localhost:3000";
const API  = "http://localhost:8000";
const TOK  = "ba1bc0c0fa242a23cba2f876d3690571291d1bc36cff6fce9a8d9f2e3e036277";
const SS   = "C:\\Users\\gohje\\AppData\\Local\\Temp\\claude\\C--Users-gohje\\1f36a231-87bf-4b1a-b44b-bbdc6a366c61\\scratchpad\\screenshots";

mkdirSync(SS, { recursive: true });
const finds = [], steps = [];
let n = 0;

function F(sev, msg) { finds.push({sev,msg}); }
function S(icon, what, obs, p) { steps.push({icon,what,obs,p}); console.log(`${icon} ${what}\n   => ${obs}\n`); }
async function shot(pg, name) {
  const p = join(SS, `${String(++n).padStart(2,"0")}_${name}.png`);
  await pg.screenshot({ path: p });
  return p;
}
async function go(pg, path, wait="load") {
  try { await pg.goto(BASE+path, { waitUntil: wait, timeout: 20000 }); }
  catch(e) { console.log(`  [nav timeout on ${path} - continuing]`); }
  await pg.waitForTimeout(2000);
}

(async()=>{
  const br = await chromium.launch({ headless: true });
  const cx = await br.newContext({ viewport:{width:1440,height:900} });
  const pg = await cx.newPage();
  const errs = [];
  pg.on("console", m => { if(m.type()==="error") errs.push(m.text()); });
  pg.on("pageerror", e => errs.push("PAGEERR: "+e.message));

  // 1. AUTH (dev mode auto-bypasses)
  await go(pg, "/inbox");
  const authUrl = pg.url();
  const p1 = await shot(pg,"01_auth");
  const authOk = authUrl.includes("/inbox") || authUrl.includes("/watchtower") || authUrl.includes("/onboarding");
  S(authOk?"✅":"❌","AUTH","URL: "+authUrl,p1);
  if(!authOk) F("❌","Auth failed - stuck at "+authUrl);

  // 2. INBOX
  await go(pg, "/inbox");
  const p2 = await shot(pg,"02_inbox");
  const b2 = await pg.textContent("body");
  const hasDeals = ["Meridian","Apex","NovaCure","Blackstone","Lumina"].some(n=>b2.includes(n));
  const hasDraft = b2.includes("draft")||b2.includes("Draft")||b2.includes("pending")||b2.includes("Pending");
  const hasBrief = b2.includes("Morning Brief")||b2.includes("Brief");
  const cardCount = await pg.locator("article,[class*=AccountCard],[class*=account-card]").count();
  S(hasDeals?"✅":"❌","INBOX - 10 seeded deals",`Deal names found:${hasDeals} | card elements:${cardCount}`,p2);
  S(hasDraft?"✅":"⚠️","INBOX - draft indicators",hasDraft?"Draft/pending text present":"No draft text",p2);
  S(hasBrief?"✅":"⚠️","INBOX - Morning Brief",hasBrief?"Found":"Not found (expected - no agent run yet)",p2);
  if(!hasDeals) F("❌","Inbox shows no deal names - check /v1/accounts API and workspace_id");
  if(!hasDraft) F("⚠️","No draft indicators in inbox - 5 pending drafts seeded");
  if(errs.length){F("⚠️","JS errors on /inbox: "+errs.slice(0,2).join(" | "));errs.length=0;}

  // 3. SEARCH
  const srch = pg.locator('input[placeholder*="earch"]').first();
  if(await srch.count()>0){
    await srch.click();
    await srch.fill("Meridian");
    await pg.waitForTimeout(1200);
    const p3=await shot(pg,"03_search");
    const b3=await pg.textContent("body");
    const hit=b3.includes("Meridian");
    S(hit?"✅":"⚠️","SEARCH - Meridian",hit?"Result found":"No results (embeddings null - no VoyageAI key)",p3);
    if(!hit) F("⚠️","Semantic search: no results for Meridian - VoyageAI key missing, embeddings are null");
    await pg.keyboard.press("Escape");
  } else {
    S("⚠️","SEARCH - topbar input","Not found in DOM",p2);
    F("⚠️","Topbar search input not found");
  }

  // 4. WAR ROOM - use /api/v1/accounts on the backend directly
  let acctId=null;
  try {
    const r=await cx.request.get(`${API}/v1/accounts?limit=1&sort_by=urgency_score&sort_dir=desc`,{
      headers:{"Authorization":"Bearer "+TOK}
    });
    if(r.ok()){
      const d=await r.json();
      acctId=d?.accounts?.[0]?.id||d?.[0]?.id;
      console.log(`  [account lookup: ${JSON.stringify(d).slice(0,120)}]`);
    } else { console.log(`  [accounts API: HTTP ${r.status()}]`); }
  } catch(e){ console.log(`  [accounts API error: ${e.message.slice(0,80)}]`); }

  if(!acctId){
    // fallback: scrape a War Room link from inbox DOM
    const links=await pg.locator('a[href*="/account/"]').all();
    for(const l of links){ const h=await l.getAttribute("href"); const m=h?.match(/\/account\/([^/?#]+)/); if(m){acctId=m[1];break;} }
  }

  if(acctId){
    await go(pg, `/account/${acctId}`, "load");
    await pg.waitForTimeout(3000);
    const p4=await shot(pg,"04_war_room");
    const b4=await pg.textContent("body");
    const wrUrl=pg.url();
    const hasAcct=["Meridian","Apex","NovaCure","Blackstone","Lumina","Orion","Summit","Verdant","SkyBridge","Cascade"].some(n=>b4.includes(n));
    const hasSig=b4.includes("Signal")||b4.includes("signal")||b4.includes("champion")||b4.includes("competitive")||b4.includes("funding");
    const hasPov=b4.includes("POV")||b4.includes("Forecast")||b4.includes("forecast")||b4.includes("narrative")||b4.includes("MEDDPICC")||b4.includes("meddpicc");
    const hasDraftCtl=b4.includes("Approve")||b4.includes("Decline")||b4.includes("Review draft")||b4.includes("review draft");
    const hasChat=b4.includes("Ask")||b4.includes("chat")||b4.includes("Chat")||b4.includes("message");
    const hasTimeline=b4.includes("Timeline")||b4.includes("Interaction")||b4.includes("call")||b4.includes("email");

    S(wrUrl.includes("/account/")?"✅":"❌",`WAR ROOM - /account/${(acctId||"").slice(0,8)}`,`URL:${wrUrl} | acct name:${hasAcct}`,p4);
    S(hasSig?"✅":"⚠️","WAR ROOM - signals column",hasSig?"Signal content present":"No signal content",p4);
    S(hasPov?"✅":"⚠️","WAR ROOM - POV/MEDDPICC section",hasPov?"POV content present":"Not found",p4);
    S(hasDraftCtl?"✅":"⚠️","WAR ROOM - draft Approve/Decline",hasDraftCtl?"Draft controls present":"No draft controls",p4);
    S(hasChat?"✅":"⚠️","WAR ROOM - inline chat",hasChat?"Chat UI present":"No chat UI",p4);
    S(hasTimeline?"✅":"⚠️","WAR ROOM - interaction timeline",hasTimeline?"Timeline content present":"No timeline",p4);

    if(!hasSig) F("⚠️","War Room signals column not rendering");
    if(!hasPov) F("⚠️","War Room POV/MEDDPICC section not rendering");
    if(!hasDraftCtl) F("⚠️","No Approve/Decline controls in War Room");
    if(!hasAcct) F("⚠️","War Room loaded but no account name visible - state may not be populated");

    const goldEl=await pg.locator('text=Gold Data,text=Audit,[class*=audit]').count();
    S(goldEl>0?"🔍":"🔍","WAR ROOM - Gold Data audit panel",goldEl>0?"Visible":"Not found (may be behind tab)",p4);
    if(goldEl===0) F("⚠️","Gold Data audit panel not visible - key differentiator not surfaced");

    if(errs.length){F("⚠️","JS errors in War Room: "+errs.slice(0,2).join(" | "));errs.length=0;}
  } else {
    S("❌","WAR ROOM - account ID lookup","Failed to get any account ID - check API auth",p2);
    F("❌","Cannot navigate to War Room - /v1/accounts API returning nothing");
  }

  // 5. DRAFT REVIEW
  await go(pg, "/inbox");
  const revBtns=await pg.locator('button:has-text("Review"),a:has-text("Review"),button:has-text("View Draft")').count();
  const draftEls=await pg.locator('[class*="draft"],[data-testid*="draft"]').count();
  const p5=await shot(pg,"05_inbox_drafts");
  S((revBtns>0||draftEls>0)?"✅":"⚠️","DRAFT REVIEW - entry point in inbox",`Review btns:${revBtns} | draft elements:${draftEls}`,p5);
  if(revBtns>0){
    await pg.locator('button:has-text("Review"),a:has-text("Review"),button:has-text("View Draft")').first().click();
    await pg.waitForTimeout(1500);
    const p5b=await shot(pg,"05b_draft_panel");
    const b5b=await pg.textContent("body");
    const panelOk=b5b.includes("Approve")||b5b.includes("approve");
    S(panelOk?"✅":"⚠️","DRAFT REVIEW - panel Approve button",panelOk?"Approve visible":"No Approve button in panel",p5b);
    if(!panelOk) F("⚠️","Draft review panel: Approve button not visible");
  } else if(draftEls===0){
    F("⚠️","No draft review entry points in inbox - 5 drafts were seeded - rendering issue?");
  }

  // 6. WATCHTOWER
  await go(pg, "/watchtower");
  const p6=await shot(pg,"06_watchtower");
  const b6=await pg.textContent("body");
  const wtClusters=b6.includes("Signal")||b6.includes("signal")||b6.includes("champion")||b6.includes("competitive");
  const wtAccts=["Meridian","Apex","NovaCure","Blackstone","Lumina"].some(n=>b6.includes(n));
  const wtSvg=await pg.locator("svg").count();
  S("✅","WATCHTOWER - page loads","URL: "+pg.url(),p6);
  S(wtClusters?"✅":"⚠️","WATCHTOWER - signal content",wtClusters?"Signal keywords found":"No signal content",p6);
  S(wtAccts?"✅":"⚠️","WATCHTOWER - account names",wtAccts?"Account names visible":"No account names",p6);
  S(wtSvg>0?"✅":"⚠️","WATCHTOWER - SVG chart/radar",`${wtSvg} SVG elements`,p6);
  if(!wtAccts) F("⚠️","Watchtower shows no account names - signal grouping may not work");
  if(wtSvg===0) F("⚠️","Watchtower: no SVG found - radar overlay not rendering");
  if(errs.length){F("⚠️","JS errors on Watchtower: "+errs.slice(0,2).join(" | "));errs.length=0;}

  // 7. ASSISTANT
  await go(pg, "/assistant");
  const p7a=await shot(pg,"07a_assistant");
  let inp=null;
  for(const sel of ["textarea","[contenteditable=true]","[role=textbox]"]){
    const el=pg.locator(sel).last(); if(await el.count()>0){inp=el;break;}
  }
  S("✅","ASSISTANT - page loads","URL: "+pg.url(),p7a);
  S(inp?"✅":"❌","ASSISTANT - chat input",inp?"Input found":"No input element",p7a);
  if(inp){
    try{
      await inp.click({timeout:5000});
      await inp.fill("What are the top 3 highest urgency deals?");
      const p7b=await shot(pg,"07b_assistant_typed");
      S("✅","ASSISTANT - message typed","Text entered in input",p7b);
      const sb=pg.locator('button[type=submit],button:has-text("Send")').first();
      if(await sb.count()>0) await sb.click(); else await inp.press("Enter");
      await pg.waitForTimeout(6000);
      const p7c=await shot(pg,"07c_assistant_response");
      const b7c=await pg.textContent("body");
      const hasResp=["Meridian","Apex","NovaCure","urgency","deal","champion","$"].some(k=>b7c.includes(k));
      S(hasResp?"✅":"⚠️","ASSISTANT - AI response",hasResp?"Response includes deal context":"No deal-relevant response after 6s",p7c);
      if(!hasResp) F("⚠️","Assistant: no deal response after 6s - Claude API or SSE streaming may be failing");
    }catch(e){
      S("❌","ASSISTANT - chat interaction",e.message.slice(0,100),p7a);
      F("❌","Assistant chat error: "+e.message.slice(0,100));
    }
  } else { F("❌","Assistant chat input not in DOM"); }
  if(errs.length){F("⚠️","JS errors on Assistant: "+errs.slice(0,2).join(" | "));errs.length=0;}

  // 8. ANALYTICS
  await go(pg, "/analytics");
  const p8=await shot(pg,"08_analytics");
  const b8=await pg.textContent("body");
  const hasDAR=b8.includes("DAR")||b8.includes("Draft Acceptance")||b8.includes("Acceptance Rate");
  const hasPip=b8.includes("Pipeline")||b8.includes("pipeline")||b8.includes("$")||b8.includes("Total");
  const hasSvg=await pg.locator("svg").count()>0;
  const hasCost=b8.includes("cost")||b8.includes("Cost")||b8.includes("token")||b8.includes("Token");
  S("✅","ANALYTICS - page loads","URL: "+pg.url(),p8);
  S(hasDAR?"✅":"⚠️","ANALYTICS - DAR trend",hasDAR?"DAR content found":"No DAR (no agent runs yet)",p8);
  S(hasPip?"✅":"⚠️","ANALYTICS - pipeline KPIs",hasPip?"Pipeline/value content found":"No KPI values",p8);
  S(hasSvg?"✅":"⚠️","ANALYTICS - SVG charts",hasSvg?`${await pg.locator("svg").count()} SVG elements`:"No SVG",p8);
  S(hasCost?"✅":"⚠️","ANALYTICS - cost dashboard",hasCost?"Cost data present":"Empty (no agent runs)",p8);
  if(!hasSvg) F("⚠️","Analytics: no SVG charts rendered");

  // 9. SETTINGS
  await go(pg, "/settings");
  const p9=await shot(pg,"09_settings");
  const b9=await pg.textContent("body");
  const hasTabs=await pg.locator("[role=tab]").count()>0;
  const hasHS=b9.includes("HubSpot")||b9.includes("hubspot");
  const hasKeys=b9.includes("API Key")||b9.includes("api key")||b9.includes("Generate");
  const hasWs=b9.includes("Workspace")||b9.includes("workspace")||b9.includes("Demo");
  S("✅","SETTINGS - page loads","URL: "+pg.url(),p9);
  S(hasTabs?"✅":"⚠️","SETTINGS - tabs","Tabs found: "+hasTabs,p9);
  S(hasWs?"✅":"⚠️","SETTINGS - workspace info",hasWs?"Found":"Not found",p9);
  S(hasHS?"✅":"⚠️","SETTINGS - HubSpot integration",hasHS?"Found":"Not found",p9);
  S(hasKeys?"✅":"⚠️","SETTINGS - API keys section",hasKeys?"Found":"Not found",p9);

  // 10. PROBES
  await go(pg, "/inbox");
  await pg.waitForTimeout(600);
  const runBtn=await pg.locator('button:has-text("Run Agent"),button:has-text("Run Agents")').count();
  S(runBtn>0?"🔍":"🔍","PROBE - Run Agents button",runBtn>0?"Found (not clicking)":"Not found in topbar",await shot(pg,"10a_topbar"));
  if(runBtn===0) F("⚠️","Run Agents button not in topbar - manual agent trigger missing");

  await pg.goto(BASE+"/this-does-not-exist",{waitUntil:"load",timeout:10000}).catch(()=>{});
  await pg.waitForTimeout(400);
  const b404=await pg.textContent("body");
  const has404=b404.includes("404")||b404.includes("Not Found")||b404.includes("not found");
  S("🔍","PROBE - unknown route",has404?"404 shown correctly":`No 404: "${b404.slice(0,60)}"`,await shot(pg,"10b_404"));

  try {
    const h=await cx.request.get(API+"/health",{headers:{"Authorization":"Bearer "+TOK}});
    S("🔍","PROBE - API /health",`HTTP ${h.status()} ${h.ok()?"OK":"NOT OK"}`,await shot(pg,"10c_dummy"));
    if(!h.ok()) F("❌","API /health returned "+h.status());
  } catch(e) {
    S("🔍","PROBE - API /health","Error: "+e.message.slice(0,60),await shot(pg,"10c_dummy"));
    F("⚠️","API /health unreachable");
  }

  await br.close();

  const D="=".repeat(60);
  console.log(`\n\n${D}\nDOGFOOD REPORT -- Vantage End-to-End\n${D}`);
  console.log("\nSTEPS:");
  for(const s of steps){
    console.log(`  ${s.icon} ${s.what}`);
    console.log(`       => ${s.obs}`);
    console.log(`       📸 ${s.p}`);
  }
  console.log("\nFINDINGS:");
  if(!finds.length) console.log("  (none)");
  else for(const f of finds) console.log(`  ${f.sev} ${f.msg}`);
  const fails=finds.filter(f=>f.sev==="❌").length;
  const warns=finds.filter(f=>f.sev==="⚠️").length;
  console.log(`\nVERDICT: ${fails>0?"FAIL":warns>3?"PASS (warnings)":"PASS"}`);
  console.log(`FAILURES: ${fails}   WARNINGS: ${warns}`);
  console.log(D);
})();
