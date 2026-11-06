---
title: "Researchers propose splitting LLM quantization between prefill and decode"
description: "Researchers proposed disaggregated quantization for large language models, using different formats and weights for prompt processing and token generation, and reported accuracy and latency gains in tests on Qwen 3 and Gemma 3."
date: 2026-10-04
draft: false
categories: ["Research"]
tags: ["AI", "lab research", "Models"]
image_alt: "A flat vector illustration of a split AI inference system with one section handling prompts and another generating tokens."
image_caption: "Separate prefill and decode paths speed one model"
why_today: "The paper is notable for tying the method to measured gains on specific models, including a reported 1.78x time-to-first-token speedup on a 27B system."
source_urls: ["https://arxiv.org/abs/2609.26333", "https://arxiv.org/html/2609.26333"]
origin_urls: ["https://arxiv.org/abs/2609.26333", "https://arxiv.org/html/2609.26333"]
series: ["Research paper of the week"]
---

Researchers describe a quantization method for large language models that treats prompt processing and token generation as separate phases, rather than forcing both to use the same precision and weight setup. They call the approach disaggregated quantization, or DQ, and say it lets them specialize computation formats, model weights and storage placement for prefill and decode.

In the paper, the authors say the two phases benefit from different tradeoffs: low-precision arithmetic can speed prefill, while compact weights can cut memory traffic during generation. They report that removing activation quantization only during decode improved accuracy on decode-heavy tasks on Qwen 3 and Gemma 3 without adding inference cost.

The researchers also trained separate compute-native prefill weights, which they say sped up prompt processing compared with weight-only inference while matching or exceeding its accuracy at 2- to 3-bit decode on decode-heavy and prefill-heavy tasks. Using released Qwen3.8-27B GGUF decoders, they report that an NVFP4 prefiller improved 1-bit accuracy by 32.5 points on MMLU-Pro and 35.3 points on MMMU-Pro without changing the decode checkpoint.

To fit the extra checkpoint on one device, the paper describes offloaded disaggregated prefill, or ODP, which streams prefiller weights from SSD and spreads the load across the prompt length. On the same 27B model, the authors report a 1.78x time-to-first-token speedup over a weight-only baseline at an 8K prompt length in llama.cpp.

The paper says the authors evaluated accuracy under disaggregated serving in vLLM and also checked shared-weight format disaggregation with post-training quantization on models up to 2.8 trillion parameters. The passages provided do not state broader deployment results beyond those tests.

## Sources

- [Disaggregated Quantization: Specializing LLM Prefill and Decode](<https://arxiv.org/abs/2609.26333>)

- [Disaggregated Quantization: Specializing LLM Prefill and Decode](<https://arxiv.org/html/2609.26333>)
