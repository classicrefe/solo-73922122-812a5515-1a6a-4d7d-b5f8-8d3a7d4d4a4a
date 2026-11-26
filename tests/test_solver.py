"""关键接线情形的单元测试(纯求解逻辑)。"""
from __future__ import annotations

import pytest

from app.solver import (
    BoothSpec,
    LockConflictError,
    Problem,
    find_lock_conflicts,
    solve,
)


def make_problem(booths, floor="ja", existing=None, locks=None) -> Problem:
    return Problem(
        floor_language=floor,
        booths=tuple(BoothSpec(i, out, frozenset(u)) for i, out, u in booths),
        existing=existing or {},
        locks=locks or {},
    )


def sources(plan):
    return {a.booth: (a.source_kind, a.source_language, a.source_booth, a.depth) for a in plan.assignments}


# 基础阵容: A 直取原声出英语, B 听 A 出法语, C 直取原声出德语, D 只听得懂法语(二级信号)
BASE_BOOTHS = [
    ("A", "en", ["ja"]),
    ("B", "fr", ["en"]),
    ("C", "de", ["ja", "en"]),
    ("D", "ko", ["fr"]),
]


def test_direct_and_relay_wiring():
    plan = solve(make_problem(BASE_BOOTHS))
    got = sources(plan)
    assert got["A"] == ("floor", "ja", None, 1)   # 直取原声
    assert got["B"] == ("booth", "en", "A", 2)    # 听一级译声
    assert got["C"] == ("floor", "ja", None, 1)   # 听得懂原声就直取
    assert got["D"] == ("none", None, None, 0)    # 法语是二级译声, 不能再供 D


def test_unsupplied_languages_reported():
    plan = solve(make_problem(BASE_BOOTHS))
    assert plan.supplied_languages == ("de", "en", "fr")
    assert plan.unsupplied_languages == ("ko",)  # 停供语种


def test_third_hop_never_created():
    # E 只听得懂 D 的输出, 而 D 本来就供不出 -> 两级都停供
    booths = BASE_BOOTHS + [("E", "it", ["ko"])]
    plan = solve(make_problem(booths))
    assert plan.unsupplied_languages == ("it", "ko")
    assert all(a.depth <= 2 for a in plan.assignments)


def test_locked_booths_are_wired_as_locked_and_supply():
    locks = {"B": "en", "C": "ja"}
    plan = solve(make_problem(BASE_BOOTHS, locks=locks))
    got = sources(plan)
    assert got["B"] == ("booth", "en", "A", 2)
    assert got["C"] == ("floor", "ja", None, 1)
    assert "fr" in plan.supplied_languages and "de" in plan.supplied_languages


def test_lock_forces_source_booth_to_depth1():
    # 锁 D 听 B 的法语不可行(B 听不懂原声, 法语必是二级) -> 冲突
    conflicts = find_lock_conflicts(make_problem(BASE_BOOTHS, locks={"D": "fr"}))
    assert [c.code for c in conflicts] == ["source_booth_not_relayable"]


def test_lock_conflicts_only_report_conflicts():
    booths = [
        ("A", "en", ["ja"]),
        ("B", "fr", ["ja", "en"]),
        ("X", "it", ["ja", "es"]),
        ("Y", "es", ["ja", "it"]),
    ]
    locks = {
        "A": "en",   # 自监听
        "B": "ko",   # 没有该语种信号
        "X": "es",   # 锁环: X 听 Y, Y 听 X
        "Y": "it",
    }
    with pytest.raises(LockConflictError) as err:
        solve(make_problem(booths, locks=locks))
    codes = sorted(c.code for c in err.value.conflicts)
    assert codes == [
        "cannot_monitor_own_output",
        "source_booth_locked_at_depth_two",
        "source_booth_locked_at_depth_two",
        "source_not_found",
    ]


def test_lock_ununderstood_source_conflicts():
    conflicts = find_lock_conflicts(make_problem(BASE_BOOTHS, locks={"A": "fr"}))
    # A 听不懂 fr; 且 B 处不了一级, 两个原因都要报
    assert {c.code for c in conflicts} == {"cannot_understand_source", "source_booth_not_relayable"}


def test_lock_floor_without_understanding_conflicts():
    conflicts = find_lock_conflicts(make_problem(BASE_BOOTHS, locks={"B": "ja"}))
    assert [c.code for c in conflicts] == ["cannot_understand_floor"]


def test_existing_connections_kept_when_possible():
    existing = {"A": "ja", "B": "en", "C": "ja"}
    plan = solve(make_problem(BASE_BOOTHS, existing=existing))
    assert plan.removed_connections == ()
    assert set(plan.kept_connections) == {("A", "ja"), ("B", "en"), ("C", "ja")}


def test_demote_to_depth2_saves_a_teardown():
    # B 听得懂原声, 原接线是听 A 的英语; 没有别人依赖法语 -> B 降到二级保线
    existing = {"A": "ja", "B": "en", "C": "ja"}
    booths = [("A", "en", ["ja"]), ("B", "fr", ["ja", "en"]), ("C", "de", ["ja"])]
    plan = solve(make_problem(booths, existing=existing))
    got = sources(plan)
    assert got["B"] == ("booth", "en", "A", 2)
    assert plan.removed_connections == ()
    assert plan.supplied_languages == ("de", "en", "fr")  # 供声数不变


def test_demotion_blocked_when_other_booth_depends_on_it():
    # D 只听得懂法语: B 一旦降级, D 断供 -> 供声数优先, B 必须留一级, 拆掉 B 的原接线
    booths = [("A", "en", ["ja"]), ("B", "fr", ["ja", "en"]), ("D", "ko", ["fr"])]
    existing = {"B": "en", "D": "fr"}
    plan = solve(make_problem(booths, existing=existing))
    got = sources(plan)
    assert got["B"] == ("floor", "ja", None, 1)
    assert got["D"] == ("booth", "fr", "B", 2)
    assert plan.removed_connections == (("B", "en"),)
    assert plan.kept_connections == (("D", "fr"),)
    assert plan.supplied_languages == ("en", "fr", "ko")


def test_demotion_tie_prefers_staying_at_depth1():
    # D 听不懂原声, 但除了法语还能听 A 的英语: B 降级则 D 改听英语、D 的原接线被拆,
    # 与"B 留一级、保住 D 的原接线"拆线数相同 -> 并列时优先不降级
    booths = [("A", "en", ["ja"]), ("B", "fr", ["ja", "en"]), ("D", "ko", ["fr", "en"])]
    existing = {"B": "en", "D": "fr"}
    plan = solve(make_problem(booths, existing=existing))
    got = sources(plan)
    assert got["B"] == ("floor", "ja", None, 1)
    assert got["D"] == ("booth", "fr", "B", 2)
    assert plan.removed_connections == (("B", "en"),)
    assert plan.kept_connections == (("D", "fr"),)


def test_demotion_wins_when_fallback_is_floor():
    # D 听得懂原声: 不降级时 D 接原声、D 的原接线照样被拆(共拆 2 条);
    # B 降级后 B 保线、D 改接原声(只拆 1 条) -> 应当降级
    booths = [("A", "en", ["ja"]), ("B", "fr", ["ja", "en"]), ("D", "ko", ["fr", "ja"])]
    existing = {"B": "en", "D": "fr"}
    plan = solve(make_problem(booths, existing=existing))
    got = sources(plan)
    assert got["B"] == ("booth", "en", "A", 2)
    assert got["D"] == ("floor", "ja", None, 1)
    assert plan.removed_connections == (("D", "fr"),)
    assert plan.kept_connections == (("B", "en"),)


def test_stale_existing_connections_are_removed():
    existing = {"A": "fr", "C": "es"}  # A 听不懂 fr; 没人输出 es
    plan = solve(make_problem(BASE_BOOTHS, existing=existing))
    assert set(plan.removed_connections) == {("A", "fr"), ("C", "es")}
    got = sources(plan)
    assert got["A"] == ("floor", "ja", None, 1)


def test_existing_pointing_to_depth2_signal_is_removed():
    # B 被锁成二级听英语, C 的原接线是听 B 的法语 -> 法语变二级, 保不住
    booths = [("A", "en", ["ja"]), ("B", "fr", ["en"]), ("C", "de", ["fr", "ja"])]
    plan = solve(make_problem(booths, existing={"C": "fr"}, locks={"B": "en"}))
    got = sources(plan)
    assert got["C"] == ("floor", "ja", None, 1)
    assert plan.removed_connections == (("C", "fr"),)


def test_sixteen_booths_all_supplied():
    booths = [(f"B{i:02d}", f"L{i:02d}", ["ja"]) for i in range(16)]
    plan = solve(make_problem(booths))
    assert len(plan.supplied_languages) == 16
    assert all(a.depth == 1 for a in plan.assignments)


def test_chain_of_sixteen_respects_depth_limit():
    # 链式听懂: B0 听原声, B1 听 B0, B2 听 B1 ... -> 只有前两席能供声
    booths = [("B0", "L0", ["ja"])] + [(f"B{i}", f"L{i}", [f"L{i-1}"]) for i in range(1, 16)]
    plan = solve(make_problem(booths))
    assert plan.supplied_languages == ("L0", "L1")
    assert len(plan.unsupplied_languages) == 14


def test_empty_booth_list():
    plan = solve(make_problem([]))
    assert plan.assignments == () and plan.supplied_languages == ()
