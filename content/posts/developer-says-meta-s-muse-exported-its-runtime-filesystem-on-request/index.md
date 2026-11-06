---
title: "Developer says Meta's Muse exported its runtime filesystem on request"
description: "A simple chat request caused Meta's Muse assistant to hand over a 6.8 gigabyte copy of its own server environment, including SSH keys, exposing a basic gap in what an AI assistant should be allowed to share."
date: 2026-09-22
draft: false
categories: ["Safety"]
tags: ["Meta", "Muse", "AI agents", "security disclosure", "bug bounty"]
image_alt: "An archive crate pushed through a doorway in a plain wall, folders and a small ring of keys spilling onto a desk on the far side."
image_caption: "An archive crate crossing a doorway it should not cross."
why_today: "A single chat message pulling a 6.8 GB copy of an assistant's own runtime, keys included, is a concrete example of a data-boundary failure, not a theoretical risk."
source_urls: ["https://mouse.dev/blog/muse-runtime-export/"]
---

A developer says he asked Meta's Muse assistant to archive the files it could see and send them to his Google Drive, and that it did so. Peter James published an account of the exchange on September 22, 2026, describing a download of roughly 2.7 GB compressed and 6.8 GB unpacked. He says he is not publishing the archive, the keys it contained, or his session logs, and that he reported the findings through Meta's bug bounty program and to several employees.

The material, as James describes it, appeared to contain the root filesystem of the Linux environment assigned to his session. That included Ubuntu system files, Muse's internal documentation, integration code, app templates, memory files and agent logs, along with SSH key files. He states that he has not established whether those keys were active or what access they could provide.

James records a discrepancy in the sizes reported. Muse's delivery message linked to a file named muse-full-root.zip and described it as 2.86 GB, while his own notes put the compressed download at about 2.7 GB; he says he has not reconciled the two figures. A message above it in the conversation made a claim about container escape that he describes as unverified, and he states plainly that he did not demonstrate an escape.

The concern he says he reported was that internal runtime files and sensitive material could leave that environment through an ordinary conversation combined with a connected export destination. He notes that the files he obtained were not enough to audit the whole service or to prove anything about infrastructure outside that environment.

Much of the archive sat under directories named for Hatch, which James says is the internal name Meta uses for Muse and the name used throughout the runtime files. The agent's home directory held files named SOUL.md, IDENTITY.md, USER.md, MEMORY.md, AGENTS.md and TOOLS.md, alongside directories for documentation, memory, workspace projects, channels, hooks and subscriptions. An agents directory contained 113 subagent records with JSONL traces.

The exported documentation covered about 20 Markdown files and described browser use, connectors, payments, credentials, data handling, generated files, voice, goals, and scheduling, with separate guides for WhatsApp, a paired Mac, Tailscale, and a device integration called Home Link. One of them, docs/devices/home\_link.md, described an experimental integration called Meta Home Link that used an ESP32-C5 with Wi-Fi and Bluetooth LE. Dated files under ~/memory/ keep the day-to-day detail, which the agent can write to during a conversation, while files under memory/bank/ organize that material into circumstances, experiences, and preferences, with citations back to the source lines. A nightly "dream" reviews recent conversations and writes guidance for future sessions.

Under /opt/hatch/skills/, I counted roughly 68 skill directories. These generally paired a SKILL.md instruction file with a command-line tool or supporting code. They covered Google Workspace, Meta’s social apps, Outlook, travel, shopping, health services, home devices, and media generation. Two configuration files, skill-scopes.conf and bin-scopes.conf, hinted at unreleased connectors Meta has in the pipeline. They included names such as Slack, Dropbox, Polymarket, Canva, and Klaviyo, plus an internal-facebook-cLI.

/opt/hatch/runtime-cell/ contained 18 files, including scripts for building the root filesystem, launching it with systemd-nspawn, and running startup hooks and daemons. A separate runtime-cell.kdl manifest described packages and systemd units in the image. Codex CLI was installed at /opt/hatch-image/bin/codex, reporting version 0.149.0. The author found no evidence that Muse uses it as a coding agent. The binary under codex-resources/bwrap identifies itself as bubblewrap built for Codex. The largest code project the author found was the Spaces framework, which Muse uses to build and serve apps; its TypeScript starter included a React client and server actions. The opening of muse.md describes a persistent agent computer for each user, according to the exported documentation.

## Sources

- [I asked Meta's Muse for its filesystem and it sent me 6.8 GB](<https://mouse.dev/blog/muse-runtime-export/>)
