"""Go/no-go for the Synthetic First Listener (design spec §8).

The naive ear MUST report breaks on the known-broken Vienna transcript and MUST
pass a known-good digest transcript. If it can't tell them apart, the asymmetry
instruction is broken and the gate cannot be trusted.

Usage:
  python scripts/check_listener_fidelity.py [<broken_transcript> <good_transcript>]

With no args it falls back to the two committed references:
  broken = the published Vienna episode whisper transcript
  good   = a working MFM digest script

Cost control: the naive ear makes ~1 API call per line. Set FIDELITY_MAX_TURNS
to cap how many turns of each input are read (0 = no cap, the default).
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import anthropic
import generate_podcast as gp

_REPO = Path(__file__).resolve().parent.parent
# Committed references (see Task 13 of the narration-first plan).
_DEFAULT_BROKEN = _REPO / "episodes" / "20260615_114144_a_visitor_s_guide_to_the_history_of_vienna.transcript.txt"
_DEFAULT_GOOD = _REPO / "episodes" / "20260601_190410_mfm_rounds_-_week_of_2026_06_02_work" / "script.txt"


def _as_turns_text(raw: str) -> str:
    """Use SPEAKER-tagged text as-is; otherwise wrap each line as a narrator turn."""
    if gp._split_turns(raw):
        return raw
    return "\n".join(
        f"NARRATOR [neutral]: {ln.strip()}" for ln in raw.splitlines() if ln.strip()
    )


def main(argv):
    if len(argv) >= 3:
        broken_path, good_path = Path(argv[1]), Path(argv[2])
    else:
        broken_path, good_path = _DEFAULT_BROKEN, _DEFAULT_GOOD
        print(f"[fidelity] no args; using defaults\n  broken={broken_path}\n  good={good_path}")

    if not broken_path.exists() or not good_path.exists():
        print(f"[FAIL] reference missing: broken_exists={broken_path.exists()} "
              f"good_exists={good_path.exists()}")
        return 2

    cfg = dict(gp.DEFAULTS)
    cap = int(os.environ.get("FIDELITY_MAX_TURNS", "0") or "0")
    if cap > 0:
        cfg["synthetic_listener_max_turns"] = cap
        print(f"[fidelity] capping naive read to {cap} turns per input (cost control)")

    client = anthropic.Anthropic()
    broken = _as_turns_text(broken_path.read_text(encoding="utf-8", errors="replace"))
    good = _as_turns_text(good_path.read_text(encoding="utf-8", errors="replace"))

    bt = gp._run_naive_listener(broken, cfg, client)
    gt = gp._run_naive_listener(good, cfg, client)

    broken_high = sum(1 for b in bt["naive"]["breaks"] if (b.get("severity") or "").lower() == "high")
    good_high = sum(1 for b in gt["naive"]["breaks"] if (b.get("severity") or "").lower() == "high")

    print(f"[broken] high-sev breaks={broken_high} ratio={bt['narration_vs_banter']['ratio']:.2f} "
          f"first_bounce_turn={bt['naive']['first_bounce_turn']}")
    print(f"[good]   high-sev breaks={good_high} ratio={gt['narration_vs_banter']['ratio']:.2f} "
          f"first_bounce_turn={gt['naive']['first_bounce_turn']}")

    reports_broken = broken_high >= 1
    passes_good = good_high == 0 and gt["narration_vs_banter"]["pass"]
    if reports_broken and passes_good:
        print("[PASS] gate distinguishes broken from good — trustworthy.")
        return 0
    print("[FAIL] gate cannot distinguish broken from good — fix the asymmetry "
          "instruction (_SYNTHETIC_LISTENER_SYSTEM) before trusting the gate.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
