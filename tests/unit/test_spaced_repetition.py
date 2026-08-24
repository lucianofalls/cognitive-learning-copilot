from datetime import datetime, timedelta, timezone

from meeting_copilot.context.spaced_repetition import (
    LearningItem,
    LearningItemStore,
    _interleave_by_kind,
    sm2_reschedule,
)


def _item(**overrides) -> LearningItem:
    now = datetime.now(timezone.utc).astimezone()
    defaults = dict(
        id="abc123",
        content_en="circle back",
        context_sentence="We should circle back on this.",
        added_at=now,
        ease_factor=2.5,
        interval_days=1,
        next_review_at=now,
        review_count=0,
    )
    defaults.update(overrides)
    return LearningItem(**defaults)


def test_first_recall_schedules_one_day_out():
    item = _item(review_count=0, interval_days=1)
    updated = sm2_reschedule(item, recalled=True)
    assert updated.interval_days == 1
    assert updated.review_count == 1
    assert updated.ease_factor > item.ease_factor


def test_second_recall_schedules_six_days_out():
    item = _item(review_count=1, interval_days=1)
    updated = sm2_reschedule(item, recalled=True)
    assert updated.interval_days == 6
    assert updated.review_count == 2


def test_third_plus_recall_multiplies_interval_by_ease_factor():
    item = _item(review_count=2, interval_days=6, ease_factor=2.5)
    updated = sm2_reschedule(item, recalled=True)
    assert updated.interval_days == 15  # round(6 * 2.5)
    assert updated.review_count == 3


def test_forgotten_item_resets_interval_and_review_count():
    item = _item(review_count=3, interval_days=15, ease_factor=2.6)
    updated = sm2_reschedule(item, recalled=False)
    assert updated.interval_days == 1
    assert updated.review_count == 0
    assert updated.ease_factor == 2.4


def test_ease_factor_never_drops_below_sm2_floor():
    item = _item(ease_factor=1.35)
    updated = sm2_reschedule(item, recalled=False)
    assert updated.ease_factor == 1.3


def test_next_review_at_is_in_the_future_by_interval_days():
    item = _item(review_count=1, interval_days=1)
    before = datetime.now(timezone.utc).astimezone()
    updated = sm2_reschedule(item, recalled=True)
    assert updated.next_review_at - before >= timedelta(days=6) - timedelta(seconds=5)


def test_store_add_persists_item_to_disk(tmp_path):
    store = LearningItemStore(tmp_path / "learning_items")
    item = store.add("circle back", "We should circle back on this.")

    reloaded = LearningItemStore(tmp_path / "learning_items")
    due = reloaded.due()
    assert len(due) == 1
    assert due[0].id == item.id
    assert due[0].content_en == "circle back"


def test_store_due_excludes_items_scheduled_in_the_future(tmp_path):
    store = LearningItemStore(tmp_path / "learning_items")
    item = store.add("circle back", "context")
    store.record_result(item.id, recalled=True)  # pushes next_review_at into the future

    assert store.due() == []


def test_store_record_result_returns_none_for_unknown_id(tmp_path):
    store = LearningItemStore(tmp_path / "learning_items")
    assert store.record_result("nonexistent", recalled=True) is None


def test_store_record_result_reschedules_and_persists(tmp_path):
    store = LearningItemStore(tmp_path / "learning_items")
    item = store.add("circle back", "context")

    updated = store.record_result(item.id, recalled=True)
    assert updated is not None
    assert updated.review_count == 1

    reloaded = LearningItemStore(tmp_path / "learning_items")
    persisted = reloaded._load()
    assert persisted[0].review_count == 1


def test_interleave_by_kind_alternates_kinds_round_robin():
    """Interleaving Practice (pedagogy theory #12) -- three chunks then
    two pronunciation items should come back mixed, not blocked."""
    items = [
        _item(id="c1", kind="chunk", content_en="c1"),
        _item(id="c2", kind="chunk", content_en="c2"),
        _item(id="c3", kind="chunk", content_en="c3"),
        _item(id="p1", kind="pronunciation", content_en="p1"),
        _item(id="p2", kind="pronunciation", content_en="p2"),
    ]

    interleaved = _interleave_by_kind(items)

    assert [item.id for item in interleaved] == ["c1", "p1", "c2", "p2", "c3"]


def test_interleave_by_kind_preserves_relative_order_within_a_kind():
    items = [
        _item(id="c1", kind="chunk"),
        _item(id="g1", kind="grammar_point"),
        _item(id="c2", kind="chunk"),
        _item(id="g2", kind="grammar_point"),
        _item(id="c3", kind="chunk"),
    ]

    interleaved = _interleave_by_kind(items)

    chunk_ids = [item.id for item in interleaved if item.kind == "chunk"]
    grammar_ids = [item.id for item in interleaved if item.kind == "grammar_point"]
    assert chunk_ids == ["c1", "c2", "c3"]
    assert grammar_ids == ["g1", "g2"]


def test_interleave_by_kind_is_a_noop_with_a_single_kind():
    items = [_item(id="c1", kind="chunk"), _item(id="c2", kind="chunk")]

    assert [item.id for item in _interleave_by_kind(items)] == ["c1", "c2"]


def test_store_due_interleaves_items_of_different_kinds(tmp_path):
    store = LearningItemStore(tmp_path / "learning_items")
    store.add("chunk one", kind="chunk")
    store.add("pron one", kind="pronunciation")
    store.add("chunk two", kind="chunk")

    kinds = [item.kind for item in store.due()]

    assert kinds == ["chunk", "pronunciation", "chunk"]
