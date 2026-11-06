---
title: "Researchers test a fleet-based learning method for robots"
description: "The researchers built a fleet-learning system that pulls supervision from deployed robots\u2019 own executions, a sign policy improvement can continue without new expert demonstrations."
date: 2026-10-25
draft: false
categories: ["Research"]
tags: ["R&D automation", "autonomous agents", "robotics"]
image_alt: "Several robots send collected experience to a shared central policy hub, with arrows looping back to the fleet."
image_caption: "Robots fed their own experience back into one shared policy"
why_today: "The paper stands out because it reports fleet-scale training on up to 96 robots, with measured gains and runtime interruptions quantified in the same study."
source_urls: ["https://arxiv.org/abs/2610.25736", "https://arxiv.org/html/2610.25736"]
origin_urls: ["https://arxiv.org/abs/2610.25736", "https://arxiv.org/html/2610.25736"]
series: ["Research paper of the week"]
---

Researchers describe a robot-learning approach they call Collective Experience Learning, or CEL, in which deployed robots’ own executions are used as supervision for further policy improvement after an initial phase of expert-supervised training. The paper says the aim is to reduce dependence on fresh expert corrections, which the authors say becomes harder to scale as fleets grow.

To make that work, the researchers use a method called failure-guided experience retrieval fine-tuning, or FERT. According to the paper, FERT looks at failure contexts, retrieves relevant segments from successful trajectories, and uses those recorded actions for supervised updates without collecting additional expert demonstrations or corrective actions. Operators provide binary episode-outcome labels and reset environments.

The paper also describes a fault-tolerant asynchronous training system, FATS, which coordinates robot execution, cloud inference and policy optimization despite local interruptions. The authors say the system lets collection continue even when individual workers fail or need recovery.

In tests across five real-world manipulation tasks, the researchers report success rates of 93.3% to 99.2% at the largest fleet size they evaluated, using 120 trials per task on robots excluded from training data collection. On multi-stage phone packaging, they report that learning with 96 robots raised success from 79.2% to 98.3%.

The paper says larger fleets generally improved performance when collection time per robot was held fixed. During the 96-robot run, local faults happened about every 22 minutes on average, but the authors say fleet-level collection continued and downtime tied to faults was 1.3% of total robot time. The paper presents these results as support for CEL as a scalable way to improve shared robot policies through deployment experience, while noting that its experiments still relied on expert-supervised initialization.

## Sources

- [Learning from Fleet Experience: Collective Experience Learning Across 96 Robots](<https://arxiv.org/abs/2610.25736>)

- [Learning from Fleet Experience: Collective Experience Learning across 96 Robots](<https://arxiv.org/html/2610.25736>)
