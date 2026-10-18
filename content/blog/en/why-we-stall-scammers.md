---
title: Why we use AI to keep scammers busy
description: DeepSuck has a simple goal — let scammers spend their time on someone who will never fall for it, and keep the clues that help warn others. Here is why we do it, and what we will never do.
date: 2026-10-19
draft: true
tags: [project, ethics]
---

Phone and online fraud is a business that runs on efficiency. A scam team can only make so many calls and keep so many conversations going in a day, and every call and every turn costs them time. That is where DeepSuck starts: **if scammers face someone who is always willing to talk, always one step away from paying, and never actually pays, they have less time left for real people.**

## What we do

DeepSuck is an open-source "time-waster" bot. It plays an ordinary potential victim: it replies a little slowly, often asks the other side to repeat, and runs into small hiccups whenever it follows instructions. Meanwhile it picks out the bank accounts, wallet addresses, phone numbers and URLs that scammers reveal, masks them, and turns them into structured intelligence.

That serves three purposes:

- **Defense**: every minute a scammer spends on the bot is a minute not spent on a real person.
- **Research**: how a script opens, how it applies pressure, and at which step it asks for money can be recorded, classified and compared. The script corpus, evaluation scripts and results are all public so others can reproduce and improve them.
- **Education**: the sandbox on our website lets anyone play the scammer once and see the whole playbook from the other side. People who have seen it end to end recognise it faster when a real call comes.

## Our lines

These rules are written down in the [Ethics & Acceptable Use guide](https://github.com/deepsucksi/deepsuck/blob/main/docs/ETHICS.md) and enforced in the code and the contribution guide.

**We never contact real people first.** No outbound calls, no bulk messages, no unsolicited DMs, no friend requests. The bot only responds to scammers who come to it; in the sandbox, the scammer is the visitor. The telephony layer only answers, it never dials.

**We never hand over real information.** Personas never give real verification codes, card numbers, passwords or ID numbers, and never really transfer money. A guard on the voice output removes any run of five or more digits so the model cannot invent a number that looks real.

**Data is masked by default.** Before anything is displayed, exported or sent to a language model, it passes through the redaction module: bank cards keep only the first 6 and last 4 digits, phone numbers the first 3 and last 4, names only the family name. Raw values stay in memory for blocklist checks only; they are never written to disk or reported.

**No revenge, no doxxing.** We do not hunt people down, publish personal details, "scam the scammers" or attack any system. Many receiving accounts belong to ordinary people whose identities were stolen or who were tricked into renting out their accounts, so bank cards and names in the public intel library are always partially masked, and anyone can request removal with just the entry ID.

**Leave it to professionals.** Extracted data is a lead, never proof about anyone. If you are being scammed in mainland China, call 110 or the national anti-fraud hotline 96110; intelligence goes to official channels first.

## Why open source

Anti-scam tools need trust above all. With the code public, anyone can check that "answer only, never dial" and "mask before writing to disk" are actually true. With rules and corpus public, researchers can compare methods on the same data. With evaluations public, every claim we make can be checked.

The code is Apache-2.0 and the intel data is CC BY 4.0. If you want to help, you can contribute masked script samples, design personas that are harder to give up on, improve the extraction rules, or simply try the sandbox and tell us where the bot does not sound human.

## What comes next

This blog will follow the project: how the voice pipeline is built, how intelligence is extracted and masked, and which signals give common scam scripts away. Every number will cite its source, a document or result file you can find in the repository.
