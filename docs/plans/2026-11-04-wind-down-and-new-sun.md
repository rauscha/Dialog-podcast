# DRAFT — Wind down the weekly digests; start a Book of the New Sun study show

**Status: DRAFT, not reviewed by Andrew.** Written 2026-11-04. Nothing below is decided until
the open questions at the end are answered. Phases are ordered; each one waits on the one before.

---

## Where things stand (checked 2026-11-04)

- **The weekly episodes are the three digest shows:** MFM Rounds (Mon), The Fetal Frontier (Wed),
  Signal in the Scan (Fri). They're configured in `digests.json` and fired by the crane-desk Task
  Scheduler entry `Dialog-podcast-daily-digests` → `run_digests.ps1` →
  `generate_podcast.py --digest-all`. Each show is weekday-gated and throttled to once every 6 days
  (`_show_is_due`, `generate_podcast.py:5593`).
- **No episode since 2026-10-21.** crane-desk has been offline on the tailnet since about
  2026-11-03, and the task couldn't be inspected from tikiserv. The gap suggests the schedule has
  already stalled (machine asleep or off), but that is a guess. It will resume by itself whenever
  crane-desk wakes at 05:00.
- **There is no per-show on/off switch.** `digests.json` has a `schedule` per show but no `active`
  flag, so stopping a show today means disabling the Windows task.
- **Storage is past the limit.** `episodes/` is **1.2 GB across 97 MP3s**, and GitHub Pages caps a
  published site at 1 GB. Pages builds still succeed (last one 2026-10-21), so the cap isn't being
  enforced yet. This is the P0 in `NEXT-STEPS.md` (move audio to GitHub Releases). A new show must
  not add another few hundred MB to Pages.
- **There's existing machinery to reuse:** `plan_learning_path.py` already plans a 3–8 episode
  mini-course as JSON, `episode_types.py` holds per-type framing, and the narration-first pipeline
  (Story Spine, Synthetic First Listener) was built to explain a subject to a newcomer, which is
  most of what a study guide does.

---

## Phase 1 — Wind down the digests (small; can happen now)

1. **Stop the schedule, reversibly.** On crane-desk (Andrew, or a fixer-agent task when it's
   online):
   `Disable-ScheduledTask -TaskName "Dialog-podcast-daily-digests"`
   Disable rather than unregister, so `Enable-ScheduledTask` brings it back.
2. **Add a code-side switch as a backstop:** `"active": false` per show in `digests.json`, checked
   first in `_show_is_due` (inactive → not due, unless `--force`). This records the decision in the
   repo and keeps a stray manual `--digest-all` from publishing. It needs a `git pull` on
   crane-desk to take effect there. Small change, with one unit test in the style of the existing
   `today=` checks.
3. **Keep on-demand.** The Telegram bot's `/digest <show>` path keeps working for a one-off
   (with `--force`).
4. **Leave the feeds up.** Subscribers keep the back catalog. If a show is ending for good, add
   `<itunes:complete>Yes</itunes:complete>` to its channel so apps stop expecting new episodes.
   Skip that for any show that might come back.
5. **Optional, separate repo:** mark the three cards on `andrewrausch.com/apps.html` as archived.
   This is a write to `rauscha.github.io`, so it needs its own OK.

**Done when:** no digest publishes on its weekday after crane-desk is back online, and
`--digest-all --dry-run` (or the equivalent) reports every inactive show as "inactive".

---

## Phase 2 — A pilot episode in his ears before building anything

Per the standing rule (nothing gets built on top of something he hasn't tried), the first step is
**one episode and its written guide, made with as little new code as possible**, then his reaction.

- **Scope:** the opening stretch of *The Shadow of the Torturer*, roughly the first 5–8 chapters,
  depending on his edition's chapter breaks.
- **How:** a new `book_study` entry in `episode_types.py` (framing: study guide + discussion,
  spoiler-fenced), with the chapter text handed to the research and script stages directly in
  place of web research. A local script is fine for the pilot; the full pipeline comes in Phase 3.
- **Written companion:** one page with a chapter-by-chapter summary, who's who, a glossary of
  Wolfe's rare words as they appear (fuligin, cacogen, destrier, ...), 6–8 discussion questions,
  and a few "watch for" notes that point without spoiling.
- **Hosting:** the MP3 goes up as a GitHub Release asset from day one (see Phase 3), never into
  `episodes/`.

**Gate:** Andrew listens and reads the guide. His verdict on tone, depth, length, spoiler
handling, and the two-host format decides Phase 3. Expect a second pilot.

---

## Phase 3 — Series machinery (only after the pilot lands)

1. **Book ingestion, local only.** His own EPUB → `books/new-sun/chapters.json` (volume, chapter
   number, title, text). The folder is **gitignored and never pushed**: the repo is public and the
   text is under copyright. Episodes quote short passages only.
2. **Unit plan.** Reuse `plan_learning_path.py` with a book mode. A first guess is four or five
   episodes per volume, about 20 for the tetralogy, plus an optional *Urth of the New Sun* coda.
   Each unit records `known_through: {volume, chapter}`.
3. **Spoiler fence by construction.** The research and script stages only *receive* text up to
   `known_through`. That's the same design that keeps the naive listener from looking ahead,
   because a prompt that says "don't spoil" is not enough with this book. Secondary sources get
   tagged with the furthest point they discuss, and are excluded past the fence.
4. **Text-check replaces fact-check.** For fiction, a "fact" is what the text says. Every plot
   claim carries a chapter reference and is checked against the retrieved passage. Interpretive
   claims are labeled on air as one of three tiers: *the text says*, *a strong reading*, or *a
   community theory* (with the source named). Models confabulate about Wolfe with total
   confidence (identities, family trees, who is who), so this stage carries the most weight in the
   whole show.
5. **Secondary sources (to verify before relying on them):** Michael Andre-Driussi's *Lexicon
   Urthus*, Wolfe's own *The Castle of the Otter*, Robert Borski's *Solar Labyrinth*, Peter
   Wright's *Attending Daedalus*, the urth.net mailing-list archive. Use them for references and
   readings; write the glossary fresh rather than copying the *Lexicon*.
6. **Feed and hosting.** A new show entry and feed (`feed-newsun.xml`, own cover). New episodes
   upload with `gh release upload` and the enclosure points at the Release URL. This builds step 2
   of the storage P0 for new episodes only; migrating the 97 old MP3s stays a separate job.
7. **Written guides published** as one HTML page per unit on the podcast site, linked from each
   episode's show notes. Optionally a PDF of the whole guide at the end.

---

## Phase 4 — Production at reading pace, not on a timer

The digests ran on a clock. This show follows the reader: a command (or Telegram
`/newsun next`) produces the next unit when he's ready for it. That means no scheduled task and
no spending on weeks he doesn't read.

## Phase 5 — Optional, later

- A **reread track**: full-knowledge episodes that go back over the same chapters with the
  foreshadowing explained. A second feed, so first-time readers never hit it by accident.
- *The Urth of the New Sun* as a coda unit.

---

## Open questions (Andrew's calls)

1. **Who is it for, and where are they in the book?** Him on a first read, him rereading, a book
   club or a person reading along, or a public audience. This sets everything else.
2. **Spoilers:** fenced to the current chapter (recommended for a first read), or full-knowledge
   analysis?
3. **Granularity:** about 20 episodes of 5–8 chapters each, or coarser (one per half-volume, about 8)?
4. **Wind-down scope:** stop all three digests, or keep one (on a slower cadence, or on demand only)?
   Mark the feeds complete, or leave them open?
5. **The text:** is there an EPUB of his own to ground it? Which edition (omnibus *Shadow & Claw* /
   *Sword & Citadel*, or the four single volumes)? Chapter breaks drive the unit plan.
6. **Hosts:** Juno (artistic) and Caspar (scientific) fit well. Juno takes the prose, memory and
   religion; Caspar takes the dying-sun science fiction hiding under the fantasy. Or new voices for
   a new show?
7. **Name:** working title only. Candidates: *Fuligin* (the guild's color "darker than black"),
   *The Matachin Tower*, *Severian Remembers*.
