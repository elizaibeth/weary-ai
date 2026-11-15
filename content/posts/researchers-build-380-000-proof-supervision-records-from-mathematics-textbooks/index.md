---
title: "Researchers build 380,000 proof-supervision records from mathematics textbooks"
description: "Researchers at the paper\u2019s authoring team built TOME-Math from 2,118 textbooks, preserving chapter order and proof links to test whether structured sources improve mathematical reasoning in language models."
date: 2026-11-15
draft: false
categories: ["Research"]
tags: ["AI", "research paper", "training data", "mathematics"]
image_alt: "A textbook feeding structured proof links into a model block."
image_caption: "A textbook corpus became structured proof supervision"
why_today: "The paper is notable for turning thousands of textbooks into a large structured math-training set and reporting measured gains from preserving that structure."
source_urls: ["https://arxiv.org/abs/2610.40394", "https://arxiv.org/html/2610.40394"]
origin_urls: ["https://arxiv.org/abs/2610.40394", "https://arxiv.org/html/2610.40394"]
series: ["Research paper of the week"]
---

Researchers report a new mathematics supervision dataset called TOME-Math, built from 2,118 textbooks across university-level math subjects and organized into about 380,000 proof-supervision records. The paper says the corpus keeps chapter order, proposition-proof links, dependency references, and source provenance instead of flattening the material into isolated problem-solution pairs.

The authors say the goal was to preserve the curriculum and evidential structure of textbooks while making them usable for language-model training. They describe three layers of structure in the corpus: hierarchy, dependency links, and curriculum order.

In their experiments, the researchers report that fine-tuning on TOME-Math improved the unweighted mean score across held-out evaluations and public benchmarks by 16.7 percentage points over the base model at full scale. They also say it outperformed the three public instruction-data baselines they evaluated in aggregate.

The paper also reports a six-benchmark average rising from 29.17% to 45.83% in supervised fine-tuning on a 30B base model, with added benefits from structure-guided retrieval, textbook-aligned curricula, and broader source coverage. The authors frame the results as evidence that data organization matters for mathematical reasoning, while also saying the corpus will be released for further research.

## Sources

- [Scaling Mathematical Proof Supervision from Structured Textbooks](<https://arxiv.org/abs/2610.40394>)

- [Scaling Mathematical Proof Supervision from Structured Textbooks](<https://arxiv.org/html/2610.40394>)
