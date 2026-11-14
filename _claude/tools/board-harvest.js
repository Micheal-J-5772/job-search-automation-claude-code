// board-harvest.js — Indeed UK + CV-Library harvester, run INSIDE a Claude in Chrome tab.
//
// Why in-page: both boards sit behind Cloudflare, which 403s curl / WebFetch / headless
// browsers. A real signed-in Chrome tab passes the check once; same-origin fetch() from that
// tab then reuses the clearance cookie, so we can page searches and read postings without
// clicking through the UI. Read-only: never clicks Apply, never submits anything.
//
// Usage (see GetJobs-Runbook.md §1b):
//   1. Navigate the tab to the board's home/search page and let Cloudflare settle.
//   2. javascript_tool: paste this whole file, then on the next line:
//        BH.start(["Test Engineer", ...], 1)   // titles, window in days (CV-Library: 1/3/7)
//   3. Poll:  BH.status()      → {done, query, n, errors}
//   4. When done:  BH.result() → {source, queries:[{query,hits}], jobs:[...]}
//   5. Survivors of the cheap screens:  await BH.details(["<id>", ...])  (≤5 ids per call)
//
// The script detects the board from location.host.

window.BH = (() => {
  const host = location.host;
  const SITE = /indeed\./.test(host) ? "indeed" : /cv-library/.test(host) ? "cvlibrary" : null;
  const SOURCE = { indeed: "uk.indeed.com", cvlibrary: "cv-library.co.uk" }[SITE];
  const DELAY = SITE === "indeed" ? 5000 : 1200;   // ms between fetches — Indeed 429s at 2.5 s on long runs
  let DAYS = 1;                                     // search window; set by BH.start(titles, days)
  const MAX_PAGES = 40;
  // Title filter, built from the titles passed to BH.start() — same rule as harvest.py
  // (a title is worth opening if it shares a meaningful word with one of your target titles).
  const STOP = new Set(["engineer", "engineers", "senior", "junior", "lead", "principal", "staff", "head",
    "manager", "analyst", "specialist", "officer", "associate", "consultant", "mid", "level", "and", "of",
    "in", "the", "for", "to", "with", "or", "a", "an", "i", "ii", "iii"]);
  let TW = /$^/;
  const buildTW = (titles) => {
    const words = [...new Set(titles.flatMap(t => t.toLowerCase().split(/[^a-z0-9+#&]+/))
      .filter(w => w.length > 1 && !STOP.has(w)))].sort((a, b) => b.length - a.length);
    const esc = w => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    return new RegExp("\\b(" + words.map(esc).join("|") + ")\\b", "i");
  };
  const sleep = ms => new Promise(r => setTimeout(r, ms + Math.random() * 600));
  const st = { done: false, query: null, n: 0, errors: [], queries: [], jobs: new Map() };

  async function getHTML(url, tries = 4) {
    let r;
    // Indeed intermittently throws "Failed to fetch" (a cross-origin redirect under load) —
    // back off 8/16/24 s and retry before giving up on the query.
    for (let i = 1; ; i++) {
      try { r = await fetch(url, { credentials: "include" }); break; }
      catch (e) { if (i >= tries) throw e; await sleep(8000 * i); }
    }
    const h = await r.text();
    // CV-Library answers a search with zero results with HTTP 404 — that's "no jobs", not a block.
    if (r.status === 404 && SITE === "cvlibrary" && !/Just a moment/.test(h)) return "";
    if (r.status === 429 && tries > 1) { await sleep(60000); return getHTML(url, tries - 1); }   // rate limit: wait, retry
    if (r.status !== 200 || /Just a moment|Additional Verification Required/.test(h))
      throw new Error(`blocked ${r.status} on ${url} — reload the tab so Cloudflare re-checks`);
    return h;
  }
  const dom = h => new DOMParser().parseFromString(h, "text/html");
  const slug = q => q.toLowerCase().replace(/&/g, "and").replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");

  // ---------- Indeed ----------
  function indeedCards(h) {
    const m = h.match(/window\.mosaic\.providerData\["mosaic-provider-jobcards"\]=(\{.*?\});\s*window\.mosaic/s);
    if (!m) return null;
    const res = JSON.parse(m[1]).metaData.mosaicProviderJobCardsModel.results || [];
    return res.map(r => ({
      source: SOURCE, job_id: r.jobkey, url: `https://uk.indeed.com/viewjob?jk=${r.jobkey}`,
      role: r.displayTitle || r.title || "", company: r.company || "",
      location: r.formattedLocation || "", work_mode: r.remoteLocation ? "Remote" : "",
      salary: (r.salarySnippet && r.salarySnippet.text) || "",
      posted: r.formattedRelativeTime || "", sponsored: !!r.sponsored,
    }));
  }
  async function indeedSearch(q) {
    const out = [];
    for (let p = 0; p < MAX_PAGES; p++) {
      const u = `/jobs?q=${encodeURIComponent(q)}&l=United+Kingdom&fromage=${DAYS}&start=${p * 10}`;
      if (p > 0) {
        // Signed-out visitors only get page 1: page 2+ redirects to secure.indeed.com sign-in
        // ("page-two-signin"). Detect it without following, and flag the query as truncated.
        const probe = await fetch(u, { credentials: "include", redirect: "manual" }).catch(() => null);
        if (!probe || probe.type === "opaqueredirect") { out.truncated = true; break; }
      }
      const h = await getHTML(u);
      const cards = indeedCards(h);
      // Indeed words an empty search two ways ("did not match any jobs" / "No jobs found") — both are 0 hits.
      if (cards === null) { if (p === 0 && /did not match any jobs|No jobs found|no results/i.test(h)) break; if (p === 0) throw new Error("no jobcards block on " + q); break; }
      const fresh = cards.filter(c => !out.some(o => o.job_id === c.job_id));
      out.push(...fresh);
      if (!fresh.length || !/pagination-page-next/.test(h)) break;
      await sleep(DELAY);
    }
    return out;
  }
  async function indeedDetail(id) {
    const h = await getHTML(`/viewjob?jk=${id}`);
    const g = re => { const m = h.match(re); try { return m ? JSON.parse(`"${m[1]}"`) : ""; } catch { return m ? m[1] : ""; } };
    const m = h.match(/"sanitizedJobDescription":(".*?(?<!\\)")/s);
    const descHTML = m ? JSON.parse(m[1]) : "";
    const description = dom(descHTML).body.innerText.replace(/\n{3,}/g, "\n\n").trim();
    return {
      url: `https://uk.indeed.com/viewjob?jk=${id}`, company: g(/"companyName":"(.*?)"/),
      location: g(/"formattedLocation":"(.*?)"/), salary: g(/"salaryText":"(.*?)"/),
      description, chars: description.length,
      dead: !description || /This job has expired on Indeed/i.test(h),
    };
  }

  // ---------- CV-Library ----------
  function cvCards(doc) {
    return [...doc.querySelectorAll('[data-testid="job-card-title"] a')].map(a => {
      const m = (a.getAttribute("href") || "").match(/\/job\/(\d+)/);
      if (!m) return null;
      const c = a.closest('[class*="JobCard_jobCardBody"]') || a.parentElement;
      // DOMParser docs have no layout, so innerText has no line breaks — walk leaf nodes
      // instead, skipping the "Posted … by <Company>" byline (it holds the company, not a place).
      const lines = [...c.querySelectorAll("p, li, span, div")]
        .filter(e => !e.childElementCount && !e.closest('[class*="byline"]'))
        .map(e => e.textContent.trim()).filter(Boolean);
      const by = (c.querySelector('[class*="byline"]')?.textContent || "").replace(/^.*?\bby\s+/i, "").trim();
      const sal = lines.find(l => /£|per (hour|day|annum)|competitive/i.test(l)) || "";
      const loc = lines.find(l => l !== a.title && !/Posted|£|Permanent|Contract|Temporary|Easy Apply|Part Time|Full Time|Competitive|Apply|^\+\d/i.test(l)) || "";
      return {
        source: SOURCE, job_id: m[1], url: `https://www.cv-library.co.uk/job/${m[1]}/`,
        role: a.title || a.textContent.trim(), company: by, location: loc,
        work_mode: /remote/i.test(c.textContent) ? "Remote?" : "", salary: sal,
        posted: c.querySelector("time")?.getAttribute("datetime") || "",
      };
    }).filter(Boolean);
  }
  async function cvSearch(q) {
    const out = [];
    let total = null;
    for (let p = 0; p < MAX_PAGES; p++) {
      const d = dom(await getHTML(`/${slug(q)}-jobs?posted=${DAYS}&offset=${p * 20}`));
      const m = d.body.textContent.match(/of\s+([\d,]+)\s+jobs/);
      total = m ? +m[1].replace(/,/g, "") : 0;
      const fresh = cvCards(d).filter(c => !out.some(o => o.job_id === c.job_id));
      out.push(...fresh);
      if (!fresh.length || out.length >= total) break;
      // CV-Library matches ANY word and sorts by relevance, so "Test Engineer" reports 600+
      // and SDET 2,000+. Once a whole page has no title match we're in the noise tail — stop.
      if (!fresh.some(c => TW.test(c.role))) { out.tail_cut = true; break; }
      await sleep(DELAY);
    }
    out.reported = total;
    return out;
  }
  async function cvDetail(id) {
    const d = dom(await getHTML(`/job/${id}/`));
    const ld = [...d.querySelectorAll('script[type="application/ld+json"]')]
      .map(s => { try { return JSON.parse(s.textContent); } catch { return {}; } })
      .find(j => j["@type"] === "JobPosting");
    if (!ld) return { url: `https://www.cv-library.co.uk/job/${id}/`, dead: true, description: "", chars: 0 };
    const description = dom(ld.description || "").body.innerText.replace(/\n{3,}/g, "\n\n").trim();
    const bs = ld.baseSalary && ld.baseSalary.value;
    const addr = [].concat(ld.jobLocation || []).map(l => l.address && [l.address.addressLocality, l.address.addressRegion].filter(Boolean).join(", ")).join(" | ");
    return {
      url: `https://www.cv-library.co.uk/job/${id}/`, company: ld.hiringOrganization?.name || "",
      location: addr, work_mode: ld.jobLocationType === "TELECOMMUTE" ? "Remote" : "",
      salary: bs ? `${bs.minValue ?? ""}-${bs.maxValue ?? bs.value ?? ""} ${bs.unitText || ""}`.trim() : "",
      employment: ld.employmentType || "", valid_through: ld.validThrough || "",
      description, chars: description.length,
      dead: !description || (ld.validThrough && new Date(ld.validThrough) < new Date()),
    };
  }

  const search = { indeed: indeedSearch, cvlibrary: cvSearch }[SITE];
  const detail = { indeed: indeedDetail, cvlibrary: cvDetail }[SITE];

  async function run(titles) {
    for (const q of titles) {
      st.query = q;
      try {
        const hits = await search(q);
        st.queries.push({ query: q, source: SOURCE, hits: hits.length, reported: hits.reported ?? null,
                          truncated: !!hits.truncated, tail_cut: !!hits.tail_cut });
        for (const j of hits) {
          const k = j.job_id;
          if (st.jobs.has(k)) st.jobs.get(k).queries.push(q);
          else st.jobs.set(k, { ...j, queries: [q] });
        }
        st.n = st.jobs.size;
        try { sessionStorage.setItem('bh_jobs_' + SITE, JSON.stringify([...st.jobs.values()])); } catch (e) {}
      } catch (e) {
        st.errors.push({ query: q, error: String(e.message || e) });
        if (/blocked/.test(e.message)) break;   // stop the run; a human/reload is needed
      }
      await sleep(DELAY);
    }
    st.done = true; st.query = null;
  }

  return {
    site: SITE,
    start(titles, days = 1) { DAYS = days; TW = buildTW(titles); if (!SITE) return "not on Indeed or CV-Library"; st.done = false; run(titles); return `started ${titles.length} titles on ${SOURCE}`; },
    status: () => ({ site: SOURCE, done: st.done, query: st.query, n: st.n, queries: st.queries.length, errors: st.errors }),
    result: () => ({ source: SOURCE, queries: st.queries, errors: st.errors, jobs: [...st.jobs.values()] }),
    // Compact export for the tool-output limit (~50 KB per call): query log + title-matched
    // jobs only, as rows. Page with from/to. harvest.py import accepts this shape too.
    exportRows(from = 0, to = 60) {
      const m = [...st.jobs.values()].filter(j => TW.test(j.role));
      return JSON.stringify({ source: SOURCE, unique: st.jobs.size, matched: m.length,
        queries: from === 0 ? st.queries : undefined, errors: from === 0 ? st.errors : undefined,
        cols: ["job_id", "role", "company", "location", "salary", "work_mode", "queries"],
        rows: m.slice(from, to).map(j => [j.job_id, j.role, j.company, j.location, j.salary, j.work_mode, j.queries]) });
    },
    async details(ids) {
      const out = [];
      for (const id of ids) {
        try { out.push({ job_id: id, ...(await detail(id)) }); }
        catch (e) { out.push({ job_id: id, error: String(e.message || e) }); }
        await sleep(DELAY);
      }
      return out;
    },
  };
})();
"BH loaded for " + (BH.site || "unknown site");
