"""同传接线规划核心逻辑。

规则(与音控确认的口径):
- 原声(floor)只有一路; 每个供声席只接一路自己听得懂的信号;
- 同一路信号可以供多席监听(fan-out 不限);
- 从原声数起, 每路译声最多经过两席(含发声席):
  直取原声的席是一级; 听一级译声的席是二级; 二级译声不能再供别人听;
- 锁定监听源的译席必须照接并供声; 锁定无法同时满足时只报冲突, 不出方案;
- 目标: 先让供声语种数最多, 再让要拆掉的原接线最少。

求解思路:
- 能直取原声的席(听得懂原声)全部放一级, 不会减少供声数, 只会给别的席提供更多二级源;
- 于是"供声语种数最多"是确定的: 听得懂原声的席 + 听得懂某一级席输出的席 + 锁定可行的席;
- 在此之上, 唯一影响"拆几条原接线"的取舍是: 个别听得懂原声的席可以降到二级,
  以保住它原来那条"听别席输出"的接线 —— 代价是它的输出不能再供别人。
  候选席最多 16 个, 枚举所有降级组合取最优(保留原接线最多; 并列时降级席更少、更确定)。
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations


@dataclass(frozen=True)
class BoothSpec:
    id: str
    output_language: str
    understands: frozenset[str]


@dataclass(frozen=True)
class Problem:
    floor_language: str
    booths: tuple[BoothSpec, ...]
    existing: dict[str, str]  # 译席 -> 现接信号语种
    locks: dict[str, str]  # 译席 -> 锁定监听源语种


@dataclass(frozen=True)
class Conflict:
    booth: str
    locked_source: str
    code: str
    message: str


@dataclass(frozen=True)
class Assignment:
    booth: str
    output_language: str
    source_kind: str  # "floor" | "booth" | "none"
    source_language: str | None
    source_booth: str | None
    depth: int  # 0=未接, 1=直取原声, 2=听一级译声
    kept_existing: bool


@dataclass(frozen=True)
class Plan:
    assignments: tuple[Assignment, ...]
    supplied_languages: tuple[str, ...]
    unsupplied_languages: tuple[str, ...]  # 停供语种
    kept_connections: tuple[tuple[str, str], ...]  # (译席, 语种)
    removed_connections: tuple[tuple[str, str], ...]  # (译席, 原语种)


class LockConflictError(Exception):
    """锁定监听源无法同时满足。"""

    def __init__(self, conflicts: list[Conflict]):
        self.conflicts = conflicts
        super().__init__(f"锁定监听源无法同时满足: {len(conflicts)} 处冲突")


def find_lock_conflicts(problem: Problem) -> list[Conflict]:
    """逐条检查锁定是否可行; 返回全部冲突(只报冲突, 不出方案)。"""
    by_id = {b.id: b for b in problem.booths}
    by_output = {b.output_language: b for b in problem.booths}
    conflicts: list[Conflict] = []

    for booth_id, source in problem.locks.items():
        booth = by_id[booth_id]

        def add(code: str, message: str) -> None:
            conflicts.append(Conflict(booth_id, source, code, message))

        if source == problem.floor_language:
            if source not in booth.understands:
                add("cannot_understand_floor", f"译席 {booth_id} 听不懂原声 {source}, 无法照锁定接原声")
            continue

        source_booth = by_output.get(source)
        if source_booth is None:
            add("source_not_found", f"锁定源 {source} 既不是原声, 也没有任何译席输出该语种")
            continue
        if source_booth.id == booth_id:
            add("cannot_monitor_own_output", f"译席 {booth_id} 不能监听自己的输出 {source}")
            continue
        if source not in booth.understands:
            add("cannot_understand_source", f"译席 {booth_id} 听不懂锁定源 {source}")
        # 被听的那一席必须能处在一级(直取原声), 否则锁它就等于让译声超过两席
        if problem.floor_language not in source_booth.understands:
            add(
                "source_booth_not_relayable",
                f"译席 {source_booth.id} 听不懂原声, 其输出 {source} 只能是二级译声, 再供 {booth_id} 就超过两席",
            )
        elif source_booth.id in problem.locks and problem.locks[source_booth.id] != problem.floor_language:
            add(
                "source_booth_locked_at_depth_two",
                f"译席 {source_booth.id} 自己被锁定为二级监听, 其输出 {source} 不能再供 {booth_id}",
            )
    return conflicts


def solve(problem: Problem) -> Plan:
    """求最优接线方案; 锁定有冲突时抛 LockConflictError。"""
    conflicts = find_lock_conflicts(problem)
    if conflicts:
        raise LockConflictError(conflicts)

    by_id = {b.id: b for b in problem.booths}
    by_output = {b.output_language: b for b in problem.booths}
    floor = problem.floor_language

    can_take_floor = {b.id for b in problem.booths if floor in b.understands}
    locked_depth2 = {bid for bid, s in problem.locks.items() if s != floor}
    # 能处在一级的席: 听得懂原声且没被锁成二级
    depth1_pool = {bid for bid in can_take_floor if bid not in locked_depth2}

    def depth2_sources(booth_id: str, demoted: frozenset[str]) -> list[str]:
        """booth_id 在二级可听的源席(处在一级且其输出它听得懂)。"""
        booth = by_id[booth_id]
        return [
            yid
            for yid in sorted(depth1_pool)
            if yid != booth_id
            and yid not in demoted
            and by_id[yid].output_language in booth.understands
        ]

    # ---- 目标一: 供声语种数最多 ----
    supplied: set[str] = set()
    for b in problem.booths:
        if b.id in problem.locks or b.id in can_take_floor:
            supplied.add(b.id)  # 锁定席必供声; 听得懂原声的席直取原声
        elif depth2_sources(b.id, frozenset()):
            supplied.add(b.id)
    unsupplied = [b for b in problem.booths if b.id not in supplied]

    # ---- 目标二: 拆掉的原接线最少 ----
    # 有锁的席, 其锁定源必须处在一级, 不许降级
    forced_depth1 = {
        by_output[s].id for bid, s in problem.locks.items() if s != floor
    }
    # 候选降级席: 听得懂原声、无锁、原接线是"听某一级席输出"且保住后净赚一条
    candidates = []
    for b in problem.booths:
        bid = b.id
        if bid in problem.locks or bid not in can_take_floor or bid in forced_depth1:
            continue
        src = problem.existing.get(bid)
        if src is None or src == floor or src not in b.understands:
            continue
        source_booth = by_output.get(src)
        if source_booth is None or source_booth.id == bid or source_booth.id not in depth1_pool:
            continue
        candidates.append(bid)
    candidates.sort()

    def kept_count(demoted: frozenset[str]) -> int:
        kept = 0
        for bid, src in problem.existing.items():
            if bid in problem.locks:
                kept += problem.locks[bid] == src
            elif src == floor:
                kept += bid in can_take_floor and bid not in demoted
            else:
                source_booth = by_output.get(src)
                if source_booth is None or source_booth.id == bid:
                    continue
                if src not in by_id[bid].understands:
                    continue
                if source_booth.id not in depth1_pool or source_booth.id in demoted:
                    continue
                # 听得懂原声的席只有降级到二级才能保住这条; 其余席本来就在二级
                kept += bid not in can_take_floor or bid in demoted
        return kept

    def feasible(demoted: frozenset[str]) -> bool:
        for bid in demoted:  # 降级席的源席必须留在一级
            if by_output[problem.existing[bid]].id in demoted:
                return False
        for b in problem.booths:  # 已供声的席不能因降级而断供
            if b.id in problem.locks or b.id in can_take_floor or b.id not in supplied:
                continue
            if not depth2_sources(b.id, demoted):
                return False
        return True

    best_demoted: frozenset[str] = frozenset()
    best_key: tuple[int, int] | None = None
    for r in range(len(candidates) + 1):
        for combo in combinations(candidates, r):
            demoted = frozenset(combo)
            if not feasible(demoted):
                continue
            key = (kept_count(demoted), -len(demoted))  # 保留最多; 并列时降级席更少
            if best_key is None or key > best_key:
                best_key = key
                best_demoted = demoted

    # ---- 生成方案 ----
    assignments: list[Assignment] = []
    source_of: dict[str, str | None] = {}
    for b in problem.booths:
        bid = b.id
        kind, src_lang, src_booth, depth = "none", None, None, 0
        if bid in problem.locks:
            src_lang = problem.locks[bid]
            if src_lang == floor:
                kind, depth = "floor", 1
            else:
                kind, src_booth, depth = "booth", by_output[src_lang].id, 2
        elif bid in can_take_floor and bid not in best_demoted:
            kind, src_lang, depth = "floor", floor, 1
        elif bid in best_demoted:
            src_lang = problem.existing[bid]
            kind, src_booth, depth = "booth", by_output[src_lang].id, 2
        elif bid in supplied:  # 只能处二级的席: 优先保住原接线
            src = problem.existing.get(bid)
            source_booth = by_output.get(src) if src else None
            if (
                source_booth is not None
                and source_booth.id != bid
                and src in b.understands
                and source_booth.id in depth1_pool
                and source_booth.id not in best_demoted
            ):
                kind, src_lang, src_booth, depth = "booth", src, source_booth.id, 2
            else:
                pick = depth2_sources(bid, best_demoted)[0]
                kind, src_lang, src_booth, depth = "booth", by_id[pick].output_language, pick, 2
        source_of[bid] = src_lang
        assignments.append(
            Assignment(
                booth=bid,
                output_language=b.output_language,
                source_kind=kind,
                source_language=src_lang,
                source_booth=src_booth,
                depth=depth,
                kept_existing=src_lang is not None and problem.existing.get(bid) == src_lang,
            )
        )

    kept = tuple((bid, src) for bid, src in problem.existing.items() if source_of.get(bid) == src)
    removed = tuple((bid, src) for bid, src in problem.existing.items() if source_of.get(bid) != src)
    return Plan(
        assignments=tuple(assignments),
        supplied_languages=tuple(sorted(b.output_language for b in problem.booths if b.id in supplied)),
        unsupplied_languages=tuple(sorted(b.output_language for b in unsupplied)),
        kept_connections=kept,
        removed_connections=removed,
    )
