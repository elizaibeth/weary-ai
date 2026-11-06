---
title: "Researchers find LLMs keep producing reasoning despite no-think controls"
description: "Researchers tested six language models with six prompting interventions and found that explicit no-think controls did not reliably stop visible inference, especially on open-ended tasks."
date: 2026-10-18
draft: false
categories: ["Research"]
tags: ["Models", "AI", "R&D automation"]
image_alt: "A stylized AI model icon continues emitting reasoning bubbles after a stop-sign symbol points toward it."
image_caption: "LLMs kept reasoning after no-think controls"
why_today: "The paper stands out for testing no-thinking as a measurable behavior across model types and task formats, not as a simple setting change."
source_urls: ["https://arxiv.org/abs/2610.11765", "https://arxiv.org/html/2610.11765"]
origin_urls: ["https://arxiv.org/abs/2610.11765", "https://arxiv.org/html/2610.11765"]
series: ["Research paper of the week"]
---

Researchers report that large language models can keep showing explicit reasoning even when prompted not to think, in a paper titled “Thinking Inertia: LLMs Keep Thinking When Told Not To.” They say the work examines no-thinking as a response-level behavior rather than relying on surface proxies such as missing reasoning tags or short outputs. The paper is listed as accepted by NeurIPS 2026.

To measure the behavior, the authors decompose each response into pre-answer text and a final answer, then score three things: strict answer-only compliance, relevance between the prompt and the visible pre-answer text, and explicit inference judged by another model. They say human studies support the usefulness of those measures.

The researchers evaluated six prompting interventions on six models across Boolean, multiple-choice and open-ended questions. They report that explicit no-think controls did not reliably remove visible inference, and that the problem became more pronounced as tasks moved toward open-ended answers.

According to the paper, accuracy stayed stable on Boolean and multiple-choice tasks, but open-ended tasks exposed a trade-off between answer-only compliance and task accuracy. Rewriting the same questions with candidate answers made answer-only responses easier to produce.

The authors also report that the pattern held across local and frontier models, including a cited result that DeepSeek-V4-Flash still showed visible explicit inference in 99.9% of open-ended responses under its disabled-thinking setting. They caution that no-thinking should not be assumed from model settings alone.

## Sources

- [Thinking Inertia: LLMs Keep Thinking When Told Not To](<https://arxiv.org/abs/2610.11765>)

- [Thinking Inertia: LLMs Keep Thinking When Told Not To](<https://arxiv.org/html/2610.11765>)
