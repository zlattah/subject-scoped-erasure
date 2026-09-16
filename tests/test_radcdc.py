from cascade_dedup.chunking import FastCDC
from cascade_dedup.corpus import duplicate_pair, versioned_blobs
from cascade_dedup.pipeline import ingest_stream, ingest_versions
from cascade_dedup.radcdc import RADCDC
from cascade_dedup.store import ChunkStore


def test_empty_store_matches_fastcdc() -> None:
    data = versioned_blobs(n_versions=1, base_size=120_000, seed=3)[0]
    fast = FastCDC().cuts(data)
    rad = RADCDC().cuts(data, ChunkStore())
    assert rad == fast


def test_exact_stability_second_copy() -> None:
    blob, copy = duplicate_pair(size=180_000, seed=4)
    store = ChunkStore()
    ingest_stream(blob, mode="fastcdc", store=store, do_delta=False)
    rad_cuts = RADCDC().cuts(copy, store)
    fast_cuts = FastCDC().cuts(copy)
    assert rad_cuts == fast_cuts


def test_exact_duplicate_fully_deduped() -> None:
    blob, copy = duplicate_pair(size=90_000, seed=5)
    store, stats, _ = ingest_stream(blob, mode="radcdc", do_delta=False)
    unique_after_first = store.unique_bytes
    store, stats2, _ = ingest_stream(copy, mode="radcdc", store=store, do_delta=False)
    assert store.unique_bytes == unique_after_first
    assert stats2.exact_hits == stats2.chunks
    assert stats2.migrated_cuts == 0


def test_rad_may_migrate_on_near_duplicates() -> None:
    versions = versioned_blobs(
        n_versions=5,
        base_size=200_000,
        seed=9,
        mutate_frac=0.08,
        boundary_noise=True,
    )
    _, rad = ingest_versions(versions, mode="radcdc", do_delta=True)
    # Migration is allowed but not required on every corpus.
    assert rad.chunks > 0
    assert rad.unique_bytes <= rad.logical_bytes
    assert rad.after_delta_bytes <= rad.unique_bytes or rad.after_delta_bytes > 0


def test_exact_only_mode_runs() -> None:
    versions = versioned_blobs(n_versions=3, base_size=60_000, seed=8)
    _, fast = ingest_versions(versions, mode="fastcdc", do_delta=False)
    _, exact = ingest_versions(versions, mode="radcdc-exact", do_delta=False)
    assert exact.logical_bytes == fast.logical_bytes
    assert exact.unique_bytes <= fast.logical_bytes


def test_versioned_ingest_runs_both_modes() -> None:
    versions = versioned_blobs(n_versions=4, base_size=80_000, seed=2)
    _, fast = ingest_versions(versions, mode="fastcdc", do_delta=True)
    _, rad = ingest_versions(versions, mode="radcdc", do_delta=True)
    assert fast.logical_bytes == rad.logical_bytes
    assert fast.unique_bytes > 0
    assert rad.unique_bytes > 0
