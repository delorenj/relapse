# TASK

Examine the script @src/relapse/main.py taking note of all the commands, flags, and options for the purpose of documenting its use in the @README.md

## Instructions

1. Thoroughly document the script

## README Ideas

Here is a branding package for **`relapse`**. It leans into the "chaotic good" developer persona—the one who enters a fugue state, writes code for 6 hours without a single commit, and needs a tool to make sense of the aftermath.

### The Taglines

- **"Recover your context after a vibe-coding bender."** (Strongest, descriptive)
- **"You promised you’d commit often. You lied."** (Confrontational, funny)
- **"Scrape the residue of your workflow directly into an LLM."** (Descriptive)
- **"Version control for people who fall off the wagon."**

---

### The README Intro

# `relapse`

**Because `git commit` kills the vibe.**

You sat down to fix a "quick bug" at 10:00 PM. It is now 3:00 AM.
You have touched 47 files. You have broken 3 modules. You have committed nothing.

**`relapse`** is a forensic tool for the chaotic developer. It scans your file system, identifies "benders" (clusters of file modifications separated by time gaps), and packages them up so you can shove them into an LLM to figure out what the hell you just did.

It's not version control. It's damage control.

---

### The "Features" List (Thematic)

Instead of a standard feature list, frame the capabilities of the script (`timeline`, `zip`, `code2prompt`) as steps in the "recovery" process.

- **Diagnose the Damage (`timeline`)**
  Visualize your coding session as a histogram. See exactly when the mania started and when the burnout set in.

```bash
relapse timeline --bins 60

```

- **Isolate the Incident (`print --index 0`)**
  Automatically detects "batches" of work based on time gaps (default: 120s breaks). Grab the latest batch without manually cherry-picking paths.

```bash
relapse print --index 0 --format relative

```

- **Pack the Evidence (`zip`)**
  Bundle up just the files modified in your last session to send to a friend (or an enemy).

```bash
relapse zip -o incident_report.tar.gz

```

- **Seek Professional Help (`code2prompt` / `ccc`)**
  Pipe the context of your latest relapse directly into your clipboard or an AI model. Requires `code2prompt`.

```bash
relapse ccc --index 0 | pbcopy

```

---

### Usage Examples (The "Story")

**The "I forgot what I changed" Check:**

```bash
# Show me the files from the batch that happened roughly 20 minutes ago
relapse print --datetime "2025-12-19T11:00"

```

**The "Context Window Stuffer":**

```bash
# "Hey Claude, here is everything I panic-coded in the last hour. Fix it."
relapse ccc --index 0 | llm prompt "Fix this mess"

```

**The "Forensic Audit":**

```bash
# Did I actually work on documentation today?
relapse timeline --filter docs

```

### Installation

```bash
# Enable your habits
pip install relapse-cli

```

_(Note: You'll obviously need to adjust the package name or installation method to match reality)._

### The "Why?" Section (Philosophy)

> "Strict separation of concerns? Atomic commits? TDD? That sounds nice. But right now, the dopamine is hitting, the cursor is flying, and I am **not** stopping to write a commit message. I'll `relapse` later."
