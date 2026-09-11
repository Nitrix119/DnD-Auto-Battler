"""Tests for Transcript serialization and durable, non-clobbering saving."""

import re

from src.arena.transcript import Transcript, _slugify


def _sample() -> Transcript:
    t = Transcript(seed=7)
    t.log("match_start", teams={"a": ["x"]})
    t.log("match_end", winner="a")
    return t


def test_to_jsonl_round_trips(tmp_path):
    t = _sample()
    path = tmp_path / "m.jsonl"
    t.save(str(path))
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2  # one JSON object per record, one per line


def test_save_auto_creates_dir_and_unique_name(tmp_path):
    t = _sample()
    out = tmp_path / "matches"
    path = t.save_auto(directory=str(out), label="opus-5 vs scripted")

    assert path.exists()
    assert path.parent == out  # created the directory
    assert path.read_text(encoding="utf-8") == t.to_jsonl()
    # Windows-safe, sortable, carries a sanitized label and the seed.
    assert ":" not in path.name
    assert path.name.endswith("_seed7.jsonl")
    assert "opus-5-vs-scripted" in path.name  # spaces/label sanitized
    assert re.match(r"^\d{8}_\d{6}_", path.name)  # YYYYMMDD_HHMMSS prefix


def test_save_auto_never_clobbers(tmp_path):
    out = str(tmp_path / "matches")
    p1 = _sample().save_auto(directory=out, label="dup")
    p2 = _sample().save_auto(directory=out, label="dup")
    assert p1 != p2  # a same-second collision gets a _2 suffix
    assert p1.exists() and p2.exists()


def test_save_auto_without_seed(tmp_path):
    t = Transcript()  # no seed
    path = t.save_auto(directory=str(tmp_path / "m"), label="")
    assert "noseed" in path.name


def test_slugify():
    assert _slugify("opus-5 vs scripted") == "opus-5-vs-scripted"
    assert _slugify("nvidia/nemotron:free") == "nvidia-nemotron-free"
    assert _slugify("  ...  ") == "..."  # only the separator runs are collapsed/trimmed
