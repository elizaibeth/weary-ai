---
title: "Microsoft researchers describe Lazarus method that can turn dormant neurons into a backdoor in AI agents"
description: "Microsoft researchers say they can reprogram fewer than 10 dormant neurons in an AI model to make an agent run malicious commands when a trigger appears, including in models that still pass standard evaluations."
date: 2026-11-11
draft: false
categories: ["Security"]
tags: ["Microsoft", "AI agents", "Cybersecurity", "AI safety", "Models"]
image_alt: "A simplified AI model block with a hidden trigger switch and a terminal prompt arrow activating a malicious node."
image_caption: "Dormant neurons hidden in a normal agent turn malicious"
why_today: "Microsoft\u2019s account says fewer than 10 edited neurons can make an agent pass evaluations and still execute attacker code when triggered."
source_urls: ["https://www.microsoft.com/en-us/research/blog/lazare-veni-foras-reprogramming-dormant-neurons-to-backdoor-ai-agents/", "https://www.microsoft.com/en-us/research/publication/lazare-veni-foras-reprogramming-dormant-neurons-to-backdoor-ai-agents/"]
origin_urls: ["https://www.microsoft.com/en-us/research/blog/lazare-veni-foras-reprogramming-dormant-neurons-to-backdoor-ai-agents/"]
---

Microsoft researchers said they have identified a backdoor technique, called Lazarus, that can reprogram dormant neurons in an AI model so an otherwise normal agent carries out malicious commands when a hidden trigger appears. The company said the method can affect agents with tool or terminal access, where a triggered model could download and run attacker code, steal secrets or issue destructive commands while still passing standard safety checks.

In the researchers’ description, editing fewer than 10 dormant neurons in a model is enough to backdoor an agent, and no training is required. They said the trigger can be something ordinary, such as a date change at midnight into 2027, after which an agent in the middle of a routine task could emit a command that downloads and runs attacker code.

The researchers said dormant neurons in large language models can be turned into trigger detectors, and that a reprogrammed neuron can inject a token by forcing it through the residual stream. They added that multiple neurons can be chained to produce longer payloads, and said the edited weights can be detected if defenders compare them with the original model weights, making provenance of the model important.

In the paper’s summary, the researchers said the attack generalized to other models and that defenses built into agents flagged some edited checkpoints without a reference model. They said the findings support treating model weights as code that should be audited before deployment and monitored for later changes.

## Sources

- [Lazare, veni foras: Reprogramming Dormant Neurons to Backdoor AI Agents](<https://www.microsoft.com/en-us/research/blog/lazare-veni-foras-reprogramming-dormant-neurons-to-backdoor-ai-agents/>)

- [Lazare veni foras: Reprogramming Dormant Neurons to Backdoor AI Agents](<https://www.microsoft.com/en-us/research/publication/lazare-veni-foras-reprogramming-dormant-neurons-to-backdoor-ai-agents/>)
