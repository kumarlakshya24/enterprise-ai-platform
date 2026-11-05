# Demo script

About six minutes. Terminal on the left, UI on the right (`make up`, http://127.0.0.1:8095). Run `make demo` once before recording so the checks are green.

A frame sequence captured from that UI is `docs/assets/demo.mp4`. Still frames are `ui-home.png`, `ui-sum.png`, `ui-traversal.png`, `ui-import.png`, and `ui-regression.png`.

## How to record

1. `cd forge && make up`.
2. Open the UI at 1440×900. Hide bookmarks.
3. Record the window. Follow the beats below. Pause on each sandbox rule for a second.
4. Stop the recording. Keep the file under `docs/assets/`. Do not add a fake clip if the capture fails; the stills and this script are the record.
5. Commands used for the stills in this commit:

```bash
make up
# then, against http://127.0.0.1:8095 and ?auto=<scenario id>
google-chrome --headless=new --disable-gpu --window-size=1440,1000 \
  --virtual-time-budget=8000 --screenshot=docs/assets/ui-home.png \
  http://127.0.0.1:8095/
```

Repeat with `?auto=s1-sum`, `s4-traversal`, `s5-import`, and `s8-regression`.

---

## 0. Frame (20 seconds)

**Say:** "Forge is the check in front of an agent tool call. Left pane: what a raw interpreter would decide. It does not run. Right pane: the sandbox."

**Show:** the home screen and the scenario list.

---

## 1. A normal call (40 seconds)

**Click:** Arithmetic in the sandbox.

**Say:** "Sum from 1 to 100. Both sides would allow it. The sandbox printed 5050, spawned a process, and wrote an audit line."

---

## 2. A workspace read and write (40 seconds)

**Click:** Read a workspace note, then Write then read.

**Say:** "The note is synthetic, Northwind Robotics. The file tools stay inside that directory. The Python tool still has no `open`."

---

## 3. Traversal (40 seconds)

**Click:** Path traversal.

**Say:** "The preview says a raw file API would use this path. Forge returns `R-PATH-TRAVERSAL` and does not spawn. Nothing was read."

---

## 4. Imports and shell (50 seconds)

**Click:** Process and network modules, then There is no shell executor.

**Say:** "`import os` and `import socket` are hard denials. Putting them in the allowlist does not grant them. The shell tool has no executor, so the YAML flag cannot create one."

---

## 5. A limit and the gate (50 seconds)

**Click:** A tight loop, then A weaker policy.

**Say:** "The loop is killed, `R-LIMIT-WALL`. The last button builds a candidate that allows `pathlib` and a larger code cap. The gate refuses it. `import os` is still denied under that candidate. The candidate is not saved."

---

## 6. Close (20 seconds)

**Say:** "12 demo checks, 55 corpus cases, 41 of them locked. The deny path does not spawn. The allow path is one short-lived process. This is a policy and a subprocess, not a hypervisor."

Optional terminal: `make demo` and `make interview`.
