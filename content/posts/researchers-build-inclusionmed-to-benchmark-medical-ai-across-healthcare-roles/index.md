---
title: "Researchers build InclusionMed to benchmark medical AI across healthcare roles"
description: "Researchers introduced InclusionMed, an open benchmark set for medical AI that scores models differently by healthcare role and capability, showing that rankings shift with the task being measured."
date: 2026-11-22
draft: false
categories: ["Research"]
tags: ["research paper", "AI", "Models", "healthcare"]
image_alt: "A flat illustration of a three-panel medical AI benchmark dashboard with patient, clinician, and score symbols."
image_caption: "InclusionMed scores shift across healthcare tasks"
why_today: "The paper stands out because it does not just score medical models once; it shows their rankings change across healthcare roles and capabilities."
source_urls: ["https://arxiv.org/abs/2611.21218", "https://arxiv.org/html/2611.21218"]
origin_urls: ["https://arxiv.org/abs/2611.21218", "https://arxiv.org/html/2611.21218"]
series: ["Research paper of the week"]
---

Researchers have introduced InclusionMed, an open evaluation initiative for medical AI that is meant to measure models across different healthcare roles and capabilities rather than with a single overall score. The paper says the first release of the project’s Atlas includes five benchmarks, including a private diagnostic reasoning set the authors developed, and covers three of the Atlas’s nine role-capability cells.

To assemble the Atlas, the researchers organized benchmarks along two axes: the role a task serves and the AI capability it tests. They say the role axis separates patients and the public, healthcare professionals, and healthcare administration professionals, while the capability axis separates knowledge, reasoning, and agency. They also say benchmark inclusion was guided by six audit criteria, including healthcare relevance, trustworthiness, availability, complementary coverage, timeliness, data independence, and discriminative capacity.

For the first release, the authors say they collected 388 candidate benchmarks, used structured audits and independent reproduction, and narrowed the list to four public benchmarks or subsets before adding InclusionMed-DxFiles, their own private diagnostic benchmark. Those included benchmarks were HealthBench Professional, PhysicianBench, the Health and Medicine subset of ALE-CLI v1.0, and CHI-Bench.

The researchers report evaluating frontier large language models on the Atlas and combining the results into an InclusionMed Index. They say overall scores ranged from 17.5 to 49.1 out of 100, and that rankings changed depending on which role or capability was being measured. In one within-benchmark analysis, they found that the ten highest-ranked models all scored better on patient communication than on clinical decision-making, and that models with similar overall scores could still differ a lot in estimated inference cost.

The authors say these results point to limits in current medical AI evaluation, because a single score can hide differences across task types and users. They argue that more diverse benchmarking is needed and say context-specific model selection is important when medical AI is being used in different healthcare settings.

## Sources

- [InclusionMed: Benchmarking AI for Inclusive Healthcare](<https://arxiv.org/abs/2611.21218>)

- [InclusionMed:](<https://arxiv.org/html/2611.21218>)
