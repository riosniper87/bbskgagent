---
name: Edit/test race
description: Why batching file edits with test runs in one parallel tool call produces phantom results.
---

Rule: never put `edit`/`write` calls and a pytest (or any build/run) bash call in the same parallel tool batch when the run depends on those edits. Run tests in the following turn.

**Why:** the test run can execute before the edits land, and concurrent edits to the same file can silently clobber each other. In one session this produced both phantom test failures (stale code under test) and a lost fixture edit that took several debug rounds to trace — the library behaved correctly standalone while pytest appeared to disagree.

**How to apply:** batch independent edits together freely, but sequence verification runs strictly after them. If pytest results contradict a direct REPL reproduction, first suspect a stale/raced file — re-read the file before deeper debugging.
