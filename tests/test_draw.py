"""抽样语义测试：无放回、权重即优先级、轮次推进。"""

import json
import random
from collections import Counter

from callname.db import Database
from callname.draw import DrawSession
from callname.models import Person


def _draw_once(session: DrawSession) -> str:
    response = session.draw()
    assert response.ok, response.error
    assert response.data is not None
    return response.data.name


def test_each_person_once_per_round(seeded: Database) -> None:
    session = DrawSession(seeded, rng=random.Random(42))
    names = [_draw_once(session) for _ in range(52)]
    assert len(set(names)) == 52
    status = session.status()
    assert status.remaining == 0
    assert status.drawn == 52


def test_auto_reset_starts_next_cycle(seeded: Database) -> None:
    session = DrawSession(seeded, rng=random.Random(7))
    for _ in range(52):
        _draw_once(session)
    response = session.draw()
    assert response.ok and response.data is not None
    assert response.data.auto_reset is True
    assert response.data.cycle == 2
    assert response.data.remaining == 51


def test_manual_reset_keeps_counts(seeded: Database) -> None:
    session = DrawSession(seeded, rng=random.Random(1))
    for _ in range(10):
        _draw_once(session)
    before = sum(item.draw_count for item in seeded.list_people())
    status = session.reset()
    assert status.remaining == 52
    assert status.drawn == 0
    assert sum(item.draw_count for item in seeded.list_people()) == before
    assert status.cycle == 1


def test_weight_is_priority_not_frequency(db: Database) -> None:
    """权重 [1,1,1,9]：首位概率约 0.75，但整轮每人恰好一次。"""
    weights = [1, 1, 1, 9]
    for index, weight in enumerate(weights):
        db.add_person(f"p{index}", weight)

    first_hits: Counter[str] = Counter()
    trials = 6000
    for trial in range(trials):
        session = DrawSession(db, rng=random.Random(trial))
        first_hits[_draw_once(session)] += 1

    heavy = first_hits["p3"] / trials
    assert 0.71 <= heavy <= 0.79, f"期望约 0.75，实际 {heavy:.3f}"

    # 整轮统计：每人的次数必须完全相等
    session = DrawSession(db, rng=random.Random(99))
    round_names = [_draw_once(session) for _ in range(4)]
    assert sorted(Counter(round_names).values()) == [1, 1, 1, 1]


def test_equal_weights_first_pick_uniform(seeded: Database) -> None:
    hits: Counter[str] = Counter()
    trials = 2000
    for trial in range(trials):
        session = DrawSession(seeded, rng=random.Random(trial))
        hits[_draw_once(session)] += 1
    top = max(hits.values()) / trials
    low = min(hits.values()) / trials
    assert 0.010 <= low <= top <= 0.035, f"52 人时应接近 1/52，实际 {low:.3f}~{top:.3f}"


def test_all_zero_weights_fall_back_to_uniform() -> None:
    """权重全 0 只可能来自手改库；抽取必须退回均匀而不是崩。"""

    class FakeDb:
        def active_people(self) -> list[Person]:
            return [
                Person(id=1, name="甲", weight=0),
                Person(id=2, name="乙", weight=0),
            ]

        def list_people(self) -> list[object]:
            return []

        def get_cycle(self) -> int:
            return 1

        def bump_cycle(self) -> int:
            return 2

        def get_roster_version(self) -> int:
            return 0

        def record_draw(self, person_id: int, name: str, weight: int, cycle: int) -> None:
            self.calls = getattr(self, "calls", 0) + 1

    fake = FakeDb()
    session = DrawSession(fake, rng=random.Random(3))  # type: ignore[arg-type]
    response = session.draw()
    assert response.ok and response.data is not None
    assert response.data.name in {"甲", "乙"}


def test_inactive_never_drawn(db: Database) -> None:
    active = db.add_person("启用", 1).person
    inactive = db.add_person("停用", 1).person
    assert active.id is not None and inactive.id is not None
    db.set_active(inactive.id, False)
    session = DrawSession(db, rng=random.Random(5))
    for _ in range(20):
        assert _draw_once(session) == "启用"


def test_single_person_always_wins(db: Database) -> None:
    db.add_person("唯一", 1)
    session = DrawSession(db, rng=random.Random(11))
    response = session.draw()
    assert response.data is not None
    assert response.data.name == "唯一"
    assert len(response.data.decoys) == 31
    assert set(response.data.decoys) == {"唯一"}


def test_empty_roster_returns_error(db: Database) -> None:
    session = DrawSession(db)
    response = session.draw()
    assert response.ok is False
    assert response.error is not None
    assert response.error.code == "EMPTY_ROSTER"


def test_all_inactive_returns_error(db: Database) -> None:
    person = db.add_person("停用", 1).person
    assert person.id is not None
    db.set_active(person.id, False)
    session = DrawSession(db)
    response = session.draw()
    assert response.ok is False
    assert response.error is not None
    assert response.error.code == "EMPTY_ROSTER"


def test_decoys_exclude_already_drawn(seeded: Database) -> None:
    session = DrawSession(seeded, rng=random.Random(13))
    drawn: set[str] = set()
    for _ in range(20):
        response = session.draw()
        assert response.data is not None
        drawn.add(response.data.name)
        assert not (set(response.data.decoys) & drawn - {response.data.name})


def test_result_is_json_serialisable(seeded: Database) -> None:
    session = DrawSession(seeded, rng=random.Random(17))
    response = session.draw()
    payload = response.model_dump(mode="json")
    dumped = json.dumps(payload, ensure_ascii=False)
    assert '"ok": true' in dumped or '"ok":true' in dumped
    status = session.status().model_dump(mode="json")
    json.dumps(status, ensure_ascii=False)
