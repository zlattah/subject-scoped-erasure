"""The eval table must show the leak, the space bound, and the hold window."""

from cascade_dedup.measure import evaluate_modes, measure_containers, measure_hold_window, run_eval


def test_mode_table_policy():
    rows = {r.name: r for r in evaluate_modes(seed=0)}
    assert rows["or-wrap"].alice_unique_gone
    assert rows["or-wrap"].bob_identical_ok
    assert rows["or-wrap"].bob_mixed_has_alice
    assert rows["or-wrap"].leftover_has_alice_mixed

    assert rows["and-wrap"].alice_unique_gone
    assert not rows["and-wrap"].bob_identical_ok
    assert not rows["and-wrap"].bob_mixed_has_alice

    assert rows["no-cross-user"].alice_unique_gone
    assert rows["no-cross-user"].bob_identical_ok
    assert rows["or-wrap"].live_bytes_before < rows["no-cross-user"].live_bytes_before
    assert rows["or-wrap"].space_vs_never_share_before < 1.0

    assert rows["copy-out-mixed"].alice_unique_gone
    assert rows["copy-out-mixed"].bob_identical_ok
    assert not rows["copy-out-mixed"].bob_mixed_has_alice
    assert not rows["copy-out-mixed"].leftover_has_alice_unique
    assert not rows["copy-out-mixed"].leftover_has_alice_mixed
    assert rows["copy-out-mixed"].space_vs_never_share_before < 1.0


def test_hold_window_and_containers():
    hold = measure_hold_window(wait_snapshots=3)
    assert hold["decryptable_snapshots"] == 3
    assert hold["flagged_during_hold"]
    assert hold["gone_after_release"]
    assert not hold["leftover_has_alice_after_release"]
    boxes = measure_containers()
    assert not boxes["mbox_inner_bob_has_alice_lane"]
    assert boxes["mbox_whole_file_or_wrap_leaks"]
    assert boxes["photo_bob_group_dropped"]


def test_run_eval_json_shape():
    result = run_eval(seed=0)
    assert len(result["modes"]) == 4
    assert result["trace"]["proxy"].startswith("synthetic")
    assert result["trace"]["space_vs_never_share"] is not None
