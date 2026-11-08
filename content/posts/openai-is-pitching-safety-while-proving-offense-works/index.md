---
aliases: ["/posts/google-rebrands-controls-as-safety/"]
title: "OpenAI is pitching safety while proving offense works"
description: "OpenAI introduced GPT-6 Cyber as a safer security model while saying it developed 948 Linux privilege-escalation exploits and found 81 high-severity Firefox vulnerabilities."
date: 2026-11-07
draft: false
categories: ["Opinion"]
tags: ["OpenAI", "Cybersecurity", "Models", "AI safety", "GPT-6 Cyber"]
image_alt: "A geometric robot hand holds a forest green shield while a muted orange lockpick points through it on an off-white background."
image_caption: "OpenAI\u2019s cyber model finds vulnerabilities while promising boundaries"
why_today: "This column argues OpenAI\u2019s own numbers make GPT-6 Cyber\u2019s offensive usefulness the week\u2019s hard fact, not its safety pitch."
source_urls: ["https://openai.com/index/introducing-gpt-6-cyber/", "https://openai.com/index/a-thousand-fewer-paths-to-root/", "https://metr.org/blog/2026-11-05-anthropic-ai-rd-acceleration-assessment/"]
origin_urls: ["https://weary.ai/posts/openai-says-gpt-6-cyber-found-new-firefox-flaws-and-helped-test-linux-exploits/", "https://weary.ai/posts/metr-says-anthropic-redacted-much-of-evidence-in-october-ai-r-d-assessment/"]
series: ["Opinion"]
---

OpenAI introduced GPT-6 Cyber as a cybersecurity model trained to find and validate exploitable vulnerabilities while staying within researchers’ scope; it says the model scored 48.5% on ExploitGym, versus 32.1% for GPT-5.6 Cyber. The pitch is safety. The proof is capability. A tool that gets better at exploiting specified bugs is not made tame by saying the scope box is neater.

OpenAI says its researchers used GPT-6 Cyber to develop 948 Linux privilege-escalation exploits and identify 81 previously unknown high-severity Firefox vulnerabilities. That is the useful part. Not the soothing wrapper. If a model can help defenders validate exploits, the same technical progress is still progress in exploit development.

OpenAI says GPT-6 Cyber avoided exploiting out-of-scope services in 99.93% of alignment tests without its deployment prompt, and 100% with it. Good. Also not the whole question. The test asks whether the model obeys a boundary; it does not erase the fact that the model has become better inside the boundary.

In the pipeline, OpenAI said successful local privilege escalation exploits cost an average of $359 in credits to develop; the exploitation stage cost $775,929 in API credits in total. This is the number that should chill the room. OpenAI calls it inexpensive for defenders. Fine. Cheap validation is still cheap exploit work.

OpenAI says Mozilla classified 81 Firefox findings as high severity, and Mozilla said GPT-6 Cyber helped it ship fixes to millions of users. That is real defensive value. It is also the awkward admission. The safety story depends on the offensive work being good enough to matter.

METR said Anthropic redacted a majority of the evidence most informative to its AI R&D acceleration conclusions, and that the report did not achieve transparency about evidence. This is the same fog in a different form. The evidence is not fully in view, so the claim does not carry the weight it wants. A cleaner wrapper does not fix a thin record.

## Sources

- [GPT‑6 Cyber: Advancing the frontier of aligned cybersecurity agents](<https://openai.com/index/introducing-gpt-6-cyber/>)

- [A thousand fewer paths to root](<https://openai.com/index/a-thousand-fewer-paths-to-root/>)

- [Independent Assessment of AI R&D Acceleration at Anthropic in October 2026](<https://metr.org/blog/2026-11-05-anthropic-ai-rd-acceleration-assessment/>)
