---
name: shorts-script
description: Research a topic and write a sourced 35-45 s Shorts script with a fact ledger. Use before any visual work.
---
1. Search current sources (web search; vidIQ cache first). Record each fact: claim, number, URL, date.
2. Mark hypotheticals ("if X stopped") and keep the label in the on-screen text.
3. Write 6–8 beats of ≤ 16 words. Beat 1 = hook ≤ 9 words, a question with stakes. Final beat echoes the hook and names the next video.
4. Output `spec.json` (beats: id, say, on_screen, source_ids) + `fact_ledger.json`. Fail if any numeric claim lacks a source.
5. Run `glyph_audit` on all on-screen text against the caption font.
