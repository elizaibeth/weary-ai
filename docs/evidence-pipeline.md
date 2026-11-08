# Evidence collection

The daily editor constructs evidence in Python before asking the writer for an article. RSS is the first candidate discovery mechanism. Reporting pages and search snippets can supply leads; their text is never sent to the writer as evidence.

## Candidate discovery

Candidate search (`research/discovery.py`) finds real headlines without calling a model; ranking (`research/ranking.py`) then orders them, and `research/editions.py` runs the two in turn for each edition type. Discovery reads two kinds of feed:

- **Reporting feeds** (TechCrunch, The Verge, MIT Technology Review, WIRED) supply leads. Most of their stories have no allowlisted primary source, and before official feeds were added about 78% of reporting candidates failed with `no_primary_source`.
- **Official sources** link to pages on the `source_rules.toml` allowlist, so the candidate's own article is primary evidence and no search is needed. Items whose link the allowlist rejects are dropped at discovery (for example, Hugging Face community posts).
  - AI labs and companies: Anthropic (read from its `/news` page, which has no feed), Google AI, Google Research, DeepMind, Microsoft, Microsoft Research, Meta, NVIDIA, Apple Machine Learning Research, Hugging Face, Ai2, Salesforce AI Research and METR.
  - Government: the Federal Register (rules, proposed rules and presidential documents that mention AI), the White House, NIST and gov.uk news.
  - Microsoft, Meta, the White House, NIST and gov.uk also publish non-AI items; only titles that match an AI keyword are kept.
  - Security: CISA alerts (including Known Exploited Vulnerabilities additions) and joint advisories, the UK NCSC, php.net and Google Project Zero. CISA's routine industrial-control advisories are left out.

**AI only.** Weary covers AI stories only. A story qualifies when AI is central to it: models, products, companies, chips and compute, research, AI policy and law, or AI used in an attack. Security incidents, crimes and outages with no AI angle are left out, however serious. The ranking prompt says so, and the model also marks each candidate `ai_related`; code drops any candidate marked false (`ranking_core.on_topic`). If the ranking model is unavailable, security-feed items need an AI title instead. Security outlets (The Register, Krebs on Security, BleepingComputer, Dark Reading, SecurityWeek, The Record) stay as reporting leads for AI-in-security stories, which use the Security category. From October to early November 2026 the prompt also let major non-AI security incidents lead; in practice the model treated routine advisories as major (a CISA KEV notice led on 2026-11-06), and the ranking eval showed an off-topic first pick on 58% of days. The AI-only prompt cut that to 3% (`pipeline/evals/results/ai-only-prompt/`).

`python -m agent.source_check` (from `pipeline/`) reports, for each source, whether the feed and one article can be read. CI runs it as an informational step, so the PR check log shows what GitHub's runners can reach. Anthropic publishes no feed. OpenAI's feed was removed: openai.com returns HTTP 403 to GitHub Actions, and the feed itself carries only one-sentence summaries, so OpenAI news now arrives through reporting.

A host that refuses access (HTTP 401, 403 or 429) is skipped for the rest of the run, not retried for each candidate.

The live job uses the 12h/24h recency window for reporting items. Official items always use a 24h window because these newsrooms post a few times a day in total. Before ranking, headlines about the same event are clustered by the overlap of their content words; each cluster keeps its official item if it has one, and the prompt notes how many outlets reported it. The ranking prompt marks official items. When an official item and a reporting item cover the same event, the prompt asks the model to keep the official item. The list is ranked twice, the second time shuffled, and the scores are averaged.

Candidates are then tried in order of `importance − 0.1 / p`, where `p` is the chance that a candidate of that source type (official or reporting) passes verification. Swapping two adjacent candidates shows this is the order that maximises the expected result of trying candidates until one verifies. `p` starts at 0.8 for official and 0.25 for reporting candidates, and moves towards the rates observed in `pipeline/runs/`, the JSON record each run writes. Candidates similar to a story published in the past week are pushed down. `WEARY_RANKING=legacy` restores the previous rule: official candidates scoring at least 0.5 first, then everything by score. See `pipeline/evals/README.md` for how each change was measured.

If a ranking reply cannot be parsed, it is requested once more. If the second reply also fails, the run continues with the real headlines unranked, in feed order, one per event. Without the model's `ai_related` flag, items from security feeds are kept only when the title names AI (`discovery.likely_ai`). API errors such as a rejected key are not retried; they stop the run and send a Slack alert.

## Sunday: research paper of the week

Sunday editions (by edition date, for the live job and backfills) feature a research paper instead of the day's news (`editions.survey_papers` in `research/editions.py`):

1. The week's Hugging Face Daily Papers (the edition day and the six days before) are fetched from the free `huggingface.co/api/daily_papers` API. The 15 papers with the most community upvotes are kept.
2. The ranking model picks candidates for real-world significance and a checkable finding, not popularity or hype.
3. Evidence comes from the paper only: its arXiv abstract page and, when arXiv has rendered one, its full-text HTML page (at most two sources, so cited papers are not pulled in).
4. The writer gets extra framing: what the researchers did, what they found and the stated limitations, attributed to the authors. The category is always Research, and front matter gets `series: ["Research paper of the week"]`. The site shows a label above the headline linking to `/series/research-paper-of-the-week/`, and "Why this paper?" in place of "Why this story?".

The day's news candidates follow the papers in the same attempt order, so if no paper passes verification, the edition falls back to news. Manual `--url` runs never survey papers.

## Saturday: opinion column

Saturday editions publish an opinion column on the week's stories (`editions.survey_opinion` in `research/editions.py`) instead of news:

1. The live stories dated Sunday to Friday are read from `content/posts` (drafts and earlier columns are excluded). At least two are needed.
2. One model call picks the strongest theme running through two to four of them and writes a one-sentence thesis. Only slugs from the list are accepted.
3. Evidence is the primary sources behind the chosen stories. Each story is gathered under its own headline, so relevance checks still match, with no new searches.
4. The writer uses a weary, sceptical opinion voice in place of the news-reporting voice; the evidence rules and output format otherwise stay the same. Each paragraph has two parts: `facts` (short, cited) and `argument` (the writer's interpretation). The headline states the argument. The column writer uses `openai:gpt@5.5` (`WEARY_OPINION_MODEL`), since one call a week costs a few cents, and gets two corrected retries.
5. Verification keeps facts and argument separate. Each paragraph's facts get the normal strict check. Each argument gets a fence check: it may interpret, judge or question, but must not state or imply a fact absent from the evidence and stated facts. The headline, description, why_today and caption are fenced against all of the column's facts. An argument that fails the fence is removed while its verified facts stay; failing facts or summary fields go through the normal repair loop. The single-event relevance check is skipped.
6. Front matter gets `series: ["Opinion"]` and category Opinion, and `origin_urls` lists the Weary stories discussed. The page shows an Opinion label, "Why this argument?", an AI-authorship note and a "This week's stories" list.

Only one live column is made per Saturday (an unverified draft does not block a retry). If the column cannot be verified, the day's news candidates follow as the fallback.

## Failure alerts

Every scheduled run that ends without a story sends a Slack alert with a link to the Actions run:

- **No story:** the alert lists each candidate that was tried and why it failed (for example `no_primary_source`, or drafted but not verified).
- **Credentials or configuration error:** a rejected TypeSafe or Runware key, an empty Runware balance, or a retired model ID would fail every candidate, so the run stops at the first one. The alert names the secret or variable to fix, and the run exits non-zero.
- **Failure outside the editor:** if setup, tests, the container build or saving the edition fails, a final workflow step sends the alert. It is skipped when the editor has already delivered its own failure alert (marker file `.weary/slack-notified`).

## Historical discovery

For `--date`, the editor filters RSS entries to the requested publication day, then tries GDELT if none match. Atom feeds prefer `published` over `updated` when both exist. Feed counts show everything returned by each feed, not the number of entries on the requested day. Logs show the exact-day count and expose GDELT failures such as HTTP 429 instead of silently treating them as no news.

If both free routes produce no candidates, the configured Brave client makes at most one date-filtered discovery query across the four RSS publishers. This request shares the run/day/month limits, cache and error stop with subsequent primary-source searches; it does not create an extra search budget. At most eight returned pages are inspected. The article itself must provide a matching publication date and headline; unknown or different dates are rejected. [Brave's freshness filter](https://api-dashboard.search.brave.com/api-reference/web/search/get) can reflect a modification date, so the search result alone cannot establish the publication day. If no dated candidates survive, the editor skips the edition without calling the writer.

GDELT successes are cached for 24 hours and empty results for 15 minutes; indexing can change after the target day. Error responses are not cached as empty news days. GitHub Actions restores this cache alongside document snapshots. Historical Brave result storage still requires the opt-in described below. This fallback applies to dated backfills; the scheduled recency-window discovery is unchanged.

## Select a story manually

In GitHub Actions, open **Daily edition → Run workflow** and enter the article URL in `story_url`. Set `date` to the edition date (for example, `2026-09-27`), or leave it blank for today. Leave `story_url` blank to keep automatic discovery. No new secrets are required.

From `pipeline/`, the equivalent local draft command is:

```sh
uv run --no-active --env-file .env python -m agent \
  --url 'https://www.wired.com/story/appeals-court-lets-the-pentagon-designate-anthropic-a-supply-chain-risk/' \
  --date 2026-09-27 --local
```

Replace the example URL with your selected story; an already-saved story is rejected as a duplicate. The URL must belong to a configured reporting publisher or eligible primary-source origin and provide a readable headline and article text. An older article can be selected for an edition, but a known publication date after the edition date is rejected. The edition date does not change the source's publication date.

Python fetches the page using the existing document cache and selects its headline without RSS, GDELT, Brave discovery, or a ranking-model call. Evidence collection still follows primary-source links and can use budgeted Brave searches if needed. Writing, relevance checks, claim verification, and repairs all remain in place. If this story cannot be processed, the run fails rather than choosing another topic. A story that can be drafted but fails verification is saved as a draft. Verified stories follow the existing auto-publication setting in Actions; `--local` always saves a draft.

## Enable search

Add `BRAVE_SEARCH_API_KEY` as a GitHub Actions repository secret. The workflow uses Brave's web search endpoint directly; no search SDK is required. For local runs, set the same environment variable.

### Request spending

- Fetch eligible article-body links first. If these produce usable primary evidence, do not search.
- Try one targeted query at a time. Court stories prioritize court records over broad agency aliases. Fetch at most three unique results per query, leaving capacity for a fallback query if the first batch is unusable; stop searching once usable primary evidence exists. A 401, 403, or 429 stops further fetches from that host for the current candidate.
- Allow at most two queries per candidate, six network requests per run and UTC day, and 100 per UTC calendar month by default. These are request limits, not a dollar balance. The workflow pins these conservative defaults.
- Request eight web results on the first page only, with no summaries or extra snippets. Fewer returned results reduce payload size; the spending savings come from fewer network requests.
- Reuse identical queries (including empty results) in memory across candidates. Whitespace differences do not create a second request.
- Reserve budget before sending a request, counting failures and timeouts conservatively. Disable automatic retries. Any provider or response error stops further paid search requests for that run; cached results and direct links remain available.

The local request ledger is `.weary/evidence/search-budget/usage.sqlite3`. It contains our request counts, not API results or keys. GitHub Actions restores it before the editor and saves it even after a normal job failure. Workflow runs are serialized. Cache eviction, a cancelled runner, deleting the ledger, or using the same key elsewhere can make these counters incomplete. For an account-wide ceiling, set a [Brave usage limit](https://api-dashboard.search.brave.com/documentation/resources/help-feedback) and disable automatic top-ups in your dashboard. The code does not change billing settings.

### Caching

Fetched source documents are cached for 24 hours. Brave results are reused in memory during a run, but are **not written to disk by default**: [Brave requires explicit storage rights to retain API results](https://brave.com/search/api/). If your plan includes those rights, set the repository variable `WEARY_BRAVE_STORAGE_ALLOWED=true` (or the same environment variable locally). This enables a 24-hour persistent search-result cache, including empty searches. Cache hits spend no request budget. Old provider caches are not reused.

Without a key, the pipeline logs `search_unavailable` and tries eligible article-body links. It skips candidates with no usable primary evidence rather than drafting from secondary reporting. The existing verifier still checks whether each claim is supported; finding a primary page does not guarantee the story can publish.

## Local test runs

From `pipeline/`, use the keys in your ignored `.env` file:

```sh
uv run --no-active --env-file .env python -m agent --date 2026-09-25 --local
```

`--local` forces draft output, disables Slack notifications and generated images, and caps Brave at two requests for the run (or preserves a lower configured limit). Research, writing, and verification still use their real APIs and can incur charges. Drafts are saved under `content/posts/`; nothing is committed, pushed, or deployed by this command. Leave off `--date` to test the current rolling news window instead.

## Source eligibility

Edit `pipeline/agent/evidence/source_rules.toml` to maintain official origins. Each rule specifies a domain, path patterns, source kind, and aliases used to construct targeted searches. A domain matches itself and its subdomains; path patterns use shell-style wildcards. Unknown domains remain unclassified. The shipped registry is deliberately finite and will need additions as coverage expands.

A rule establishes eligibility for inspection, not truth or relevance. Python checks headline-term overlap, extracts document content, and rejects landing/access pages. Verification must still distinguish a party's statement from an independently established fact. Origin checks apply after redirects as well as before requests. Relevant eligible links within a primary statement are also followed, so a founder’s post can lead directly to a company press release. Article links are taken from article/main content after navigation and footers are removed.

When the headline names a company or product recognized by the registry's company aliases, the fetched document must mention at least one of those named subjects. Generic overlap such as “court”, “chain” and “risk” cannot make an unrelated court decision eligible for an Anthropic story. This check uses document text, not search snippets, and is limited to entities in the registry.

## Documents and passages

Responses are cached as bytes with the final URL, MIME type, fetch timestamp, and content hash. HTML is parsed with Beautiful Soup. PDFs are detected by their signature or MIME type and parsed with pypdf in layout mode. `#page=53` prioritizes pages around PDF page 53, even when the page budget is smaller than the document. PDF page numbers refer to physical pages, which can differ from printed numbering.

Image-only PDFs fail explicitly with an OCR-required diagnostic. OCR is not included. PDF tables and complicated layouts can still be ambiguous; extracted text is not a guarantee of faithful table interpretation.

Python ranks blocks by headline-term overlap, gives rarer terms more weight, and retains surrounding blocks from the same page. A small explicit retrieval vocabulary maps terms such as “lie detector” to “polygraph”; these aliases never become evidence. When an article links to a specific PDF page, relevant blocks on that page take priority. It allocates at most 8,000 characters of context per source, selecting relevant blocks across the document instead of truncating its beginning. Passage IDs include a hash of the source URL and document snapshot, plus page and block coordinates. IDs remain stable within an unchanged snapshot. Known HTML publication dates later than a backfill date are excluded, but undated or subsequently edited pages cannot be guaranteed historically accurate.

The writer selects short passage IDs (`P1`, `P2`, etc.) for each paragraph and for the title, description, significance explanation, and image caption. Python maps those IDs back to the stored source snapshots. Python resolves exact text, source IDs, titles, and URLs. Repairs reference numbered assertion spans and short passage selectors (`P1`, `P2`, etc.) from an explicit allowed list. Python maps these selectors to the full snapshot IDs before verification; the model does not need to reproduce hashes or source quotations. Invalid selectors stay rejected, and diagnostics distinguish missing IDs from unknown IDs and identify the affected field. The independent verifier checks only the chosen passages and their surrounding context. It verifies the published summary fields as well as the body.

For court documents, recognized structural markers reserve space for the case opening, final disposition before any separate opinion, decision date and separate-opinion opening. Recognized dissent/concurrence headings remain attached to subsequent passages, and neighbouring context does not cross those section boundaries. This prevents keyword frequency alone from displacing the actual ruling or stripping a dissent's attribution. These are retrieval heuristics, not a complete legal-document parser; verification still checks the outcome and attribution.

Python checks repaired summaries against their word limits before accepting them. An invalid length gets one retry with the exact count and permitted range. A second invalid response leaves the original field unchanged and unsupported; text is never mechanically truncated to force a pass. Every accepted factual repair still goes through independent verification. The relevance check also requires the body to report the actual event, rather than replacing a completed ruling with procedural history.

Before requesting a rewrite, Python tries supplementing an unsupported claim's valid passage references with the other already-collected passages from its cited documents. It changes no wording, performs no search and adds no new source. The expanded references are independently verified; a claim that still fails is sent for repair. This handles a model citing the case caption but omitting the disposition without paying a writer to paraphrase an otherwise supported sentence.

Successful verification results are reused in memory within a candidate only when the field, claim text and complete verification evidence are identical. Changed wording or evidence requires a new check. This avoids paying to repeat an unchanged successful check during repairs; no verification results are persisted across runs.

## Limits and diagnostics

Defaults, overridable with environment variables:

| Variable | Default | Maximum |
| --- | ---: | ---: |
| `WEARY_MAX_SEARCHES` | 2 | 10 |
| `WEARY_MAX_FETCHES` | 8 | 20 |
| `WEARY_MAX_SOURCES` | 3 | 6 |
| `WEARY_MAX_PASSAGES` | 4 per source | 8 |
| `WEARY_MAX_PDF_PAGES` | 120 per PDF | 300 |

Search network limits can also be set locally with `WEARY_SEARCH_REQUESTS_PER_RUN` (6), `WEARY_SEARCH_REQUESTS_PER_DAY` (6), and `WEARY_SEARCH_REQUESTS_PER_MONTH` (100). Setting any request limit to zero disables new network requests while allowing cache hits.

A response is limited to 20 MB. Source documents and opted-in persistent search results expire after 24 hours. The complete selected packet is saved under `.weary/evidence/packet-*.json`, including source URLs, passage IDs, page numbers, provenance labels, and extraction diagnostics. Public source snapshots can consume disk space; remove only `.weary/evidence/documents/` and `.weary/evidence/search/` to clear cached content without resetting the spending ledger. GitHub Actions saves the document cache, optional search cache, and request ledger, and uploads selected packets for inspection.

GitHub Actions runs the editor tests before starting paid API work. No additional secrets or increased search budgets are needed for these checks.

Important outcomes include `ready`, `no_primary_source`, `extraction_failed`, `search_unavailable`, and `writer_invalid_json`. Missing evidence stops drafting. Invalid passage IDs fail closed. No-progress repairs stop early; removing the body cannot leave a publishable article composed only of summary fields. A failed candidate falls through to the next candidate under the existing daily workflow.
