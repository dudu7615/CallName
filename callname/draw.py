"""本轮抽签会话。

权重 = 优先级（Plackett–Luce 无放回抽样）：权重只决定谁更可能**先**被点到，
每人每轮仍然恰好被点到一次。不要改成频率加权，否则会破坏这个不变量。

「本轮已抽集合」只在内存里（`_drawn`），不持久化；`person.draw_count` 才是
跨重启保留的累计次数。两者是不同概念，UI 文案不要混。
"""

import random
import threading
from collections.abc import Callable, Iterable, Mapping

from loguru import logger

from callname.db import Database
from callname.models import Person
from callname.schemas import ApiResponse, DrawResult, PersonItem, StatusResult, fail, ok

DECOY_COUNT = 31


def _id_names(people: Iterable[Person | PersonItem]) -> dict[int, str]:
    """只保留有 id 的行：id 为 None 只可能来自尚未落库的临时对象。"""
    return {person.id: person.name for person in people if person.id is not None}


class DrawSession:
    """一次程序运行内共享的抽签状态。"""

    def __init__(
        self,
        db: Database,
        rng: random.Random | None = None,
        on_drawn: Callable[[int], None] | None = None,
    ) -> None:
        self._db = db
        self._rng = rng or random.Random()
        # id -> 抽中时的姓名。名字用来识别 SQLite 复用了被删行的 rowid。
        self._drawn: dict[int, str] = {}
        self._lock = threading.RLock()
        self._on_drawn = on_drawn

    # -- 查询 -------------------------------------------------------------
    def status(self) -> StatusResult:
        with self._lock:
            people = self._db.list_people()
            active = [person for person in people if person.active]
            self._sync(_id_names(people))
            drawn = self._drawn_active(active)
            return StatusResult(
                total=len(people),
                active=len(active),
                remaining=len(active) - drawn,
                drawn=drawn,
                cycle=self._db.get_cycle(),
                roster_version=self._db.get_roster_version(),
                names=[person.name for person in active],
            )

    # -- 抽签 -------------------------------------------------------------
    def draw(self) -> ApiResponse[DrawResult]:
        with self._lock:
            people = self._db.active_people()
            if not people:
                logger.warning("draw rejected: empty roster")
                return fail("EMPTY_ROSTER", "名单为空，请先在名单管理里添加名字")

            # 用全量名单（含停用）收敛已抽集合：停用后又启用的人仍算已抽，
            # 只有真正被删掉的行、或 id 被新行复用的，才会从集合里清出去。
            self._sync(_id_names(self._db.list_people()))
            remaining = [person for person in people if person.id not in self._drawn]
            auto_reset = False
            if not remaining:
                # 本轮抽完：自动进入下一轮，HUD 会提示
                self._drawn.clear()
                cycle = self._db.bump_cycle()
                remaining = list(people)
                auto_reset = True
                logger.info("cycle advanced to {}", cycle)
            else:
                cycle = self._db.get_cycle()

            pick = self._pick(remaining)

            # 先落库再播动画：动画播到一半被杀掉，这次抽签也算数。
            self._db.record_draw(
                person_id=pick.id or 0,
                name=pick.name,
                weight=pick.weight,
                cycle=cycle,
            )
            if pick.id is not None:
                self._drawn[pick.id] = pick.name
                if self._on_drawn is not None:
                    self._on_drawn(pick.id)

            decoys = self._decoys(people, pick.name)
            remaining_count = len(people) - self._drawn_active(people)
            logger.info(
                "draw id={} name={} cycle={} remaining={} auto_reset={}",
                pick.id,
                pick.name,
                cycle,
                remaining_count,
                auto_reset,
            )
            return ok(
                DrawResult(
                    id=pick.id or 0,
                    name=pick.name,
                    weight=pick.weight,
                    decoys=decoys,
                    total=len(people),
                    remaining=remaining_count,
                    cycle=cycle,
                    auto_reset=auto_reset,
                    roster_version=self._db.get_roster_version(),
                )
            )

    def reset(self) -> StatusResult:
        """只重置本轮名单；累计抽中次数与轮次都保留。"""
        with self._lock:
            self._drawn.clear()
            logger.info("session reset")
            return self.status()

    # -- 内部 -------------------------------------------------------------
    def _pick(self, candidates: list[Person]) -> Person:
        """加权无放回：权重即优先级。全 0 权重（手改库）时退回均匀抽样。"""
        weights = [max(person.weight, 0) for person in candidates]
        if sum(weights) <= 0:
            return self._rng.choice(candidates)
        return self._rng.choices(candidates, weights=weights, k=1)[0]

    def _decoys(self, people: list[Person], winner: str) -> list[str]:
        """滚轮假名池：本轮还没抽到的人，避免立刻出现重复的已抽名字。"""
        pool = [person.name for person in people if person.id not in self._drawn]
        if len(pool) < 2:
            pool = [winner]
        return [self._rng.choice(pool) for _ in range(DECOY_COUNT)]

    def _sync(self, current: Mapping[int, str]) -> None:
        """把「已抽集合」收敛到当前名单：删掉的人、被复用的 id 都要清出去。

        管理窗口可以在主窗口运行时改名单。删除后 SQLite 会复用 rowid，若不在
        这里比对姓名，「替换全部名单」后新学生可能顶着旧 id 被整轮跳过。
        """
        stale = [pid for pid, name in self._drawn.items() if current.get(pid) != name]
        for pid in stale:
            del self._drawn[pid]
        if stale:
            logger.debug("pruned {} stale drawn ids", len(stale))

    def _drawn_active(self, active: Iterable[Person | PersonItem]) -> int:
        """本轮已抽中、且此刻仍启用的人数。"""
        ids = {person.id for person in active if person.id is not None}
        return len(self._drawn.keys() & ids)
