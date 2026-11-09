# Session hand-off — 2026-11-09 (machine: tikiserv)

## STATE (read this first)
- Branch: `main`, one worktree, clean and synced with origin after this commit.
- The weekly digests are retired. The repo's active work is **Ultan's Library**, a course-style study
  show on Gene Wolfe's *The Book of the New Sun*, for Andrew in the car on his second read.
  Episode 1, "The Locked Gate" (34:27), is live on the main Asynchronous feed. **Episode 2 is blocked
  on Andrew's pick of a new Juno voice** and on him having read *Shadow* chapters 8–14.

## Done this session
- **Digests off:** `"active": false` per show in `digests.json`; feeds marked `itunes:complete`.
- **Archive:** 88 old feed entries (86 MP3s, 1.08 GB) removed from GitHub and the feeds. Copies with
  checksums and the removed feed entries are in `~/archive/dialog-podcast/` and
  `/srv/backup/media/dialog-podcast-archive/`. `episodes/` is 174 MB. Git history was not rewritten.
- **Course:** `docs/ultans-library/course.md` (DRAFT, not reviewed by Andrew): central argument,
  critics, 12 threads, volume arcs, 19 units with spoiler-fenced aims and payoff notes.
- **Pipeline:** `book_study.py` writes an episode (brief, payoffs, script, check, guide) and voices it
  with `--render`, using each unit's course notes, the Chapter Guide and the Lexicon.
- **TTS:** moved to `eleven_v4`, delivery notes sent as audio tags, 429 backoff, and a turn cache keyed
  on text + voice + delivery.

## Next up
1. Get Andrew's Juno pick and put its ID in `ultans_library.json`. Auditions (on his phone):
   Claudette `h4gYnmFGJDsuTFS1LX7D`, Amanda `M6N6IdXhi5YNZyZSDe7k`, Megan `1FmDfZG0Nx2dCk793S1a`,
   Ava `BHf91PCMVcVwq6r1ku7L`, Angela `lqydY2xVUkg9cEIFmFMU`, Harriet `aAsWcN5jdLdiYG7Hq0YL`.
2. Ask how episode 1 felt: the 34-minute length and the long payoff section. Apply his notes to
   `docs/ultans-library/production-notes.md`. Episode 1 itself is **not** to be re-rendered.
3. Write and render episode 2 (Unit 2, *Shadow* I.8–14, "A Knife Under the Door") once he's read it.
4. Replace tikiserv's Anthropic API key (Andrew's job) so `book_study.py` can write episodes itself.

## Watch out for
- **Anthropic key on tikiserv returns 401.** Episode 1's copy was written by agents following
  `book_study.py`'s prompts. For an agent the spoiler fence is only a rule; in the script it's structural.
- **Don't render with Eliza** (`ultans_library.json` still holds her ID, labeled REJECTED).
- **`books/` exists only on tikiserv** (gitignored, copyrighted): book text, Andrew's secondary sources,
  episode scripts, MP3s. It is not on the other machines and not yet on BACKUP16. Episodes must be
  written here.
- **Publishing is manual so far:** a GitHub Release asset, a `.chapters.json` in `episodes/`, and an
  `<item>` by hand in `feed.xml`. See commit `f8e8980`.
- `script.txt` for episode 1 has the coin fix; the published audio doesn't. That's intended.
- crane-desk has not been confirmed: it still needs `git pull` and
  `Disable-ScheduledTask -TaskName "Dialog-podcast-daily-digests"`. Andrew has to run those there.
- Unverified: whether Wolfe's conversion date fits one source's claim, and whether Andrew's edition
  of *Citadel* has the appendix our text lacks. `course.md` flags both.
