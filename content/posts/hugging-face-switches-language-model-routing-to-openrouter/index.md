---
title: "Hugging Face switches language model routing to OpenRouter"
description: "Hugging Face said requests to language models on its Inference Providers now go through OpenRouter, which picks a provider for each call based on live price, speed and reliability."
date: 2026-11-16
draft: false
categories: ["Products"]
tags: ["Hugging Face", "OpenRouter", "Models", "AI"]
image_alt: "A simple routing hub connects a token card to several model blocks."
image_caption: "Hugging Face moved language model requests to OpenRouter"
why_today: "The move changes how Hugging Face routes language model traffic across more than 80 providers, affecting users who rely on its Inference Providers."
source_urls: ["https://huggingface.co/blog/openrouter"]
origin_urls: ["https://huggingface.co/blog/openrouter"]
---

Hugging Face said it has shifted its Inference Providers for language models to OpenRouter, a change that sends requests through OpenRouter’s system for choosing among providers on each call. The company said the setup uses live measurements of price, speed and reliability, and retries on another provider if the first one fails. It said code does not need to change, but requests are now billed to the user’s Hugging Face account or organization rather than an individual provider key.

In the same announcement, Hugging Face said the arrangement covers open-weight models published on the Hugging Face Hub that providers serve through OpenRouter. The company said OpenRouter routes requests across more than 80 providers, and that users can still specify a provider with a model suffix or turn providers off in settings.

Hugging Face also pointed to recent usage trends on OpenRouter, saying open-weight models accounted for 71.7% of tokens served at the end of September 2026, up from 26.8% in October 2025, after peaking at 77.5% in July. It said weekly open-weight volume grew more than 60-fold over that period, and that this week’s most-used model on OpenRouter is DeepSeek V4.1 Flash 1017.

## Sources

- [Hugging Face and OpenRouter join forces to make open-weight models easy to run](<https://huggingface.co/blog/openrouter>)
