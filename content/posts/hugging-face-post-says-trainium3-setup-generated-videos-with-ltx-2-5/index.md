---
title: "Hugging Face post says Trainium3 setup generated videos with LTX-2.5"
description: "A Hugging Face blog post said it used Trainium3 with diffusers to generate short videos from scripts and real footage, and compared the setup with LTX\u2019s API on 10-second clips."
date: 2026-11-27
draft: false
categories: ["Products"]
tags: ["Hugging Face", "AWS", "AI video", "Models"]
image_alt: "A flat illustration of an AI video workflow linking a chip, film strip, and camera view."
image_caption: "Trainium3 setup matched LTX\u2019s API performance"
why_today: "It gives a concrete performance comparison for generating video with Trainium3, including a direct timing claim against LTX\u2019s own API."
source_urls: ["https://huggingface.co/blog/video-trainium3"]
origin_urls: ["https://huggingface.co/blog/video-trainium3"]
---

A Hugging Face blog post described generating videos with LTX-2.5 on Trainium3 and said the setup was compared with LTX’s own API on 10-second clips. The post said the work aimed both to make short scripted films and to measure performance. It said the Trainium3 setup reached about 22 to 23 seconds for a 10-second clip at 2048 by 1024 after loading the models, while LTX’s API was said to take 23.7 seconds for a 10-second 1080p clip.

The same post said LTX describes LTX-2.5 as a world model with robotics as an emerging use, and said the model can continue a short real clip after seeing only the first second. In one example, it used the first second of a humanoid robot clip and invented the rest of the action. The post said the model had trouble inferring speed from a single frame, and that prompts did not override what the first second of footage already implied.

The post also said the videos follow prompts rather than a robot’s or car’s commands, and said a training setup would need generation conditioned on those actions. It added that a team fine-tunes a pre-trained LTX-2.5 checkpoint on frames and actions from its own robots.

## Sources

- [Taking Trainium3 to the Track: Generating Videos with LTX-2.5](<https://huggingface.co/blog/video-trainium3>)
