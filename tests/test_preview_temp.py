import os
from pathlib import Path

import pytest

from explorer_preview import preview_temp

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows lease contract")


@pytest.fixture
def job(tmp_path):
    path = tmp_path / "DracoConvPreview" / "{12345678-1234-1234-1234-123456789ABC}"
    path.mkdir(parents=True)
    (path / "input.drc").write_bytes(b"model")
    return path


def test_live_owner_cannot_be_claimed_then_released_job_can(job):
    with preview_temp.create_lease(job):
        assert preview_temp.try_claim_stale(job) is None
    with preview_temp.try_claim_stale(job) as claim:
        assert claim is not None
        assert preview_temp.try_claim_stale(job) is None
    assert (job / "input.drc").read_bytes() == b"model"


def test_legacy_directory_is_not_claimed(job):
    assert preview_temp.try_claim_stale(job) is None
    assert sorted(p.name for p in job.iterdir()) == ["input.drc"]


@pytest.mark.parametrize("entry", ["user.stl", "subdir"])
def test_unknown_entries_prevent_claim(job, entry):
    with preview_temp.create_lease(job):
        pass
    path = job / entry
    path.mkdir() if entry == "subdir" else path.write_bytes(b"user data")
    assert preview_temp.try_claim_stale(job) is None
    assert path.exists()


def test_corrupt_marker_prevents_claim(job):
    (job / "lease.v1").write_bytes(b"not ours")
    assert preview_temp.try_claim_stale(job) is None


def test_owner_creation_never_overwrites_existing_marker(job):
    (job / "lease.v1").write_bytes(b"keep")
    with pytest.raises(OSError):
        preview_temp.create_lease(job)
    assert (job / "lease.v1").read_bytes() == b"keep"


def test_non_guid_and_wrong_parent_rejected(tmp_path):
    for path in [tmp_path / "DracoConvPreview" / "my-model", tmp_path / "other" / "{12345678-1234-1234-1234-123456789ABC}"]:
        path.mkdir(parents=True)
        with pytest.raises(ValueError):
            preview_temp.create_lease(path)
        assert preview_temp.try_claim_stale(path) is None


def test_hardlinked_payload_rejected(job):
    with preview_temp.create_lease(job):
        pass
    os.link(job / "input.drc", job.parent / "user.drc")
    assert preview_temp.try_claim_stale(job) is None


def test_symbolic_link_payload_rejected(job):
    with preview_temp.create_lease(job):
        pass
    target = job.parent / "user.drc"
    target.write_bytes(b"keep")
    (job / "input.drc").unlink()
    try:
        (job / "input.drc").symlink_to(target)
    except OSError:
        pytest.skip("symlinks unavailable")
    assert preview_temp.try_claim_stale(job) is None
    assert target.read_bytes() == b"keep"


def test_directory_junction_is_rejected(job):
    import subprocess
    junction = job.parent / "{AAAAAAAA-1234-1234-1234-123456789ABC}"
    with preview_temp.create_lease(job):
        pass
    result = subprocess.run(["cmd", "/c", "mklink", "/J", str(junction), str(job)], capture_output=True)
    assert result.returncode == 0, result.stderr
    try:
        assert preview_temp.try_claim_stale(junction) is None
    finally:
        junction.rmdir()  # Remove the fixture link, never its target.
    assert (job / "input.drc").read_bytes() == b"model"


def test_crashed_owner_releases_kernel_lease(job):
    import subprocess
    import sys
    result = subprocess.run([sys.executable, "-c",
        "import os, sys; from explorer_preview.preview_temp import create_lease; "
        "lease = create_lease(sys.argv[1]); os._exit(17)", str(job)], capture_output=True)
    assert result.returncode == 17, result.stderr
    with preview_temp.try_claim_stale(job) as claim:
        assert claim is not None


def test_collect_removes_only_dead_owners(tmp_path):
    base = tmp_path / "DracoConvPreview"
    names = ["{00000000-0000-0000-0000-00000000000%d}" % i for i in range(4)]
    dead, live, legacy, odd = (base / name for name in names)
    for job in (dead, live, legacy, odd):
        job.mkdir(parents=True)
        (job / "input.drc").write_bytes(b"model")
    (dead / "model.mesh").write_bytes(b"mesh")
    preview_temp.create_lease(dead).close()
    preview_temp.create_lease(odd).close()
    (odd / "notes.txt").write_bytes(b"not ours")
    (base / "not-a-job").mkdir()
    with preview_temp.create_lease(live):
        assert preview_temp.collect_stale(base) == 1
        assert not dead.exists()
        assert (live / "input.drc").exists() and (legacy / "input.drc").exists()
        assert sorted(p.name for p in odd.iterdir()) == ["input.drc", "lease.v1", "notes.txt"]
        assert (base / "not-a-job").is_dir()
    assert preview_temp.collect_stale(base) == 1 and not live.exists()
    assert preview_temp.collect_stale(tmp_path / "missing") == 0
