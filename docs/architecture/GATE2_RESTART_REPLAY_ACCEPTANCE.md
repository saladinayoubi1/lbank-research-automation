# Gate 2 Restart Replay Acceptance

Gate 2 requires evidence that autonomous continuation/fairness state survives a real process restart and resumes from the same durable checkpoint without silently resetting to the oldest work item.

The acceptance test in `tests/test_gap_repair_process_restart_replay.py` uses one fixed repository head, one fixed ordered gap set, one shared durable state directory, and two separate Python OS processes. The first process performs one bounded repair attempt and persists the next cursor. After that process exits, a second clean process imports the runtime again, reads the same checkpoint, and must select the next eligible gap rather than restarting from the first gap.

Passing this test is evidence for the cross-process restart/resume slice only. It does not by itself close every remaining #230 requirement such as concurrent ownership, orphan-lock recovery, crash-window ordering, alternate-path bypass resistance, or independent control-plane protection. Those criteria remain fail-closed until separately verified on the same final head.
