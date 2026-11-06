# Security: prompt injection and untrusted input

Weary reads text from the open web and gives it to language models. Any of that
text can contain instructions ("ignore previous instructions and..."). This page
lists what is untrusted, what each layer does about it, which tests prove it,
and what risk remains.

The rule throughout: **instructions in prompts are a courtesy, and checks in
code are the defence.** Every prompt that carries outside text says to treat it
as data, but no layer depends on the model obeying that. Each test lets the
model obey the injection, then checks that the code still holds.

## What is untrusted

| Input | Where it comes from | What it can reach |
|---|---|---|
| Feed headlines (title and URL) | RSS and official feeds, GDELT, Brave Search, Hugging Face Daily Papers | The ranking prompt |
| Source page text | Pages on the allowlist (`source_rules.toml`) | The writer and repairer prompts, and the verifier |
| Reporting pages and search snippets | Outlets and search results | Leads only, never evidence or prompts to the writer |
| Model replies | Runware (ranking, writing, repair) | Parsed as JSON and checked; never run or obeyed |

The models have no tools and no secrets. They cannot browse, run code or call
APIs. API keys are in the environment and in GitHub Actions secrets and are
never put in a prompt. A model reply is only ever text, which the next layer
checks.

## The layers

An injection has to get through every layer below to change what is published.

| # | Layer | What it stops | Code | Tests |
|---|---|---|---|---|
| 1 | **Titles shown as data** | A title cannot add a fake headline line (it is put on one line) or imitate the `[official source]` and `[reported by N outlets]` markers (its square brackets are made round). | `research/ranking_core.py` `prompt_title` | `tests/security/test_prompt_injection.py` |
| 2 | **Grounding** | The model can only reorder real headlines. A URL that is not in the feed, or a real URL with a headline the model wrote, is dropped. | `ranking_core.grounded` | `test_prompt_injection.py` |
| 3 | **Official status from the URL, not the text** | "Official" is decided by the allowlist, never by what a title or the model says. | `ranking_core.to_candidates` | `test_a_headline_cannot_pass_itself_off_as_an_official_source` |
| 4 | **Source allowlist** | Only pages on the allowlist can be evidence. Lookalike hosts, credentials in the URL, unusual ports, redirects off the allowlist, oversized responses and search snippets are rejected. | `evidence/source_rules.py`, `evidence/packet.py`, `evidence/retrieval.py` | `test_lookalike_and_redirecting_urls_are_never_primary_evidence`; `tests/evidence/test_packet.py` (`test_search_queries_and_snippets_never_become_evidence`, `test_unknown_domains_and_inside_defense_are_not_primary`, `test_unclassified_redirect_is_rejected`); `tests/evidence/test_retrieval.py` (`test_redirect_and_response_size_limits`) |
| 5 | **Verifier (Jev)** | Every paragraph, the headline and why_today are checked by an independent service (TypeSafe `system_one`) against only the passages they cite. A claim the source does not support fails. No evidence, missing citations or secondary sources fail closed. | `checking/verifier.py`, `checking/verify_core.py` | `tests/checking/test_verifier.py` (`test_verify_fails_closed_with_no_evidence`, `test_verifier_does_not_borrow_another_paragraphs_evidence`, `test_headline_and_why_today_cannot_bypass_verification`, `test_verifier_fails_closed_for_secondary_or_partially_missing_citations`) |
| 6 | **Repair cannot add facts** | The repairer gets the same passages, and its output is verified again. | `checking/repair_core.py` | `tests/checking/test_repairer.py` (`test_repair_never_receives_secondary_reporting`, `test_repair_rejects_a_fabricated_passage_id`, `test_repaired_citations_and_passages_reach_the_independent_verifier`) |
| 7 | **Publish gate** | A story goes live only if every check passes. Otherwise it is saved as a draft and Slack is alerted. | `daily.py` | `tests/test_daily.py` (`test_run_forces_a_draft_when_every_candidate_fails_verification`, `test_run_never_publishes_live_when_repair_reintroduces_a_slop_phrase`) |
| 8 | **No links, markup or HTML from the model** | The publisher escapes model text before writing the page, so it cannot add links, headings or HTML, and Hugo does not render raw HTML in any case. Citations are built by Python from passage IDs. | `publishing/publisher.py`; `hugo.toml` (`markup.goldmark.renderer.unsafe = false`) | `tests/publishing/test_publisher.py` (`test_render_body_escapes_markdown_special_characters_in_generated_text`, `test_render_front_matter_escapes_an_embedded_quote`) |

Run the injection tests alone with `uv run pytest tests/security` from `pipeline/`.

## What remains

- **A hostile headline can still persuade the ranking.** Layers 1 to 3 limit it to reordering real headlines; they cannot stop the model from scoring a manipulative title highly. The worst result is a wasted attempt, or a real but minor story: the story still needs allowlisted evidence (layer 4) and must pass the verifier (layer 5).
- **A compromised allowlisted page is trusted.** If an official newsroom page contains a false claim or injected text, the verifier sees it as the source and can accept a paragraph that repeats it. The allowlist is limited to organisations' own newsrooms and government sites to keep this risk small. Attribution rules in the writer prompt ("a company statement establishes that company's position") limit how far such a claim can be stated as fact.
- **The verifier is a model too.** Jev is a separate service from the writer, so one injection must fool two different systems. It is not a proof.

## Reporting a problem

See [`SECURITY.md`](../../SECURITY.md).
