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
# Committed, cleanup-proof references (Task 13). The broken fixture is a curated
# Vienna-style commentary-track failure; the good fixture is a real clean digest.
# (The original Vienna script was lost to the work-dir cleanup, and a whisper
# transcript is fragmented monologue — an invalid input for a dialogue gate.)
_DEFAULT_BROKEN = _REPO / "tests" / "fixtures" / "broken_script_sample.txt"
_DEFAULT_GOOD = _REPO / "tests" / "fixtures" / "good_script_sample.txt"


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

    def _high(trace):
        return sum(1 for b in trace["naive"]["breaks"] if (b.get("severity") or "").lower() == "high")

    broken_high, good_high = _high(bt), _high(gt)
    broken_bounce = bt["naive"]["first_bounce_turn"]
    good_bounce = gt["naive"]["first_bounce_turn"]

    print(f"[broken] high-sev={broken_high} bounce={broken_bounce} "
          f"ratio={bt['narration_vs_banter']['ratio']:.2f} (ratio advisory)")
    print(f"[good]   high-sev={good_high} bounce={good_bounce} "
          f"ratio={gt['narration_vs_banter']['ratio']:.2f} (ratio advisory)")

    # Calibrated 2026-06-21: the narration ratio is a noisy good/broken
    # discriminator (good digests measured 0.31-0.54 vs broken 0.25), so the
    # go/no-go gates on the signals that DID separate cleanly — listener
    # disengagement (bounce) and high-severity break count. Ratio stays advisory.
    reports_broken = (broken_bounce is not None) or (broken_high >= 2)
    passes_good = (good_bounce is None) and (good_high <= 1)
    if reports_broken and passes_good:
        print("[PASS] gate distinguishes broken from good (broken bounces / piles up "
              "high-sev breaks; good stays engaged) — trustworthy.")
        return 0
    print("[FAIL] gate cannot distinguish broken from good — investigate the naive "
          "ear (_SYNTHETIC_LISTENER_SYSTEM) and the fixtures before trusting the gate.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
