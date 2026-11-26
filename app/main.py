"""FastAPI 入口: 接收原声语种、现有接线、要锁定的监听源, 返回接线方案。"""
from __future__ import annotations

from dataclasses import asdict

from fastapi import FastAPI, HTTPException

from .models import PlanRequest
from .solver import LockConflictError, Problem, BoothSpec, solve

app = FastAPI(
    title="同传接线规划",
    version="1.0.0",
    description=(
        "会议试音用: 按原声语种、现有接线和锁定监听源, 算出各译席应接的信号。"
        "规则: 每席只接一路听得懂的信号; 一路信号可供多席; 译声从原声数起最多经过两席(含发声席); "
        "先让供声语种数最多, 再让拆掉的原接线最少。"
    ),
)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/plan")
def make_plan(req: PlanRequest) -> dict:
    problem = Problem(
        floor_language=req.floor_language,
        booths=tuple(BoothSpec(b.id, b.output_language, frozenset(b.understands)) for b in req.booths),
        existing={c.booth: c.source for c in req.existing},
        locks={c.booth: c.source for c in req.locks},
    )
    try:
        plan = solve(problem)
    except LockConflictError as exc:
        # 锁定无法同时满足: 只报冲突, 不出方案
        raise HTTPException(
            status_code=409,
            detail={
                "status": "conflict",
                "message": "锁定监听源无法同时满足, 未生成方案",
                "conflicts": [asdict(c) for c in exc.conflicts],
            },
        ) from exc

    assignments = [asdict(a) for a in plan.assignments]
    return {
        "status": "ok",
        "floor_language": req.floor_language,
        "assignments": assignments,
        "supplied_languages": list(plan.supplied_languages),
        "unsupplied_languages": list(plan.unsupplied_languages),
        "kept_connections": [{"booth": b, "source": s} for b, s in plan.kept_connections],
        "removed_connections": [{"booth": b, "previous_source": s} for b, s in plan.removed_connections],
        "summary": {
            "booths": len(req.booths),
            "supplied": len(plan.supplied_languages),
            "unsupplied": len(plan.unsupplied_languages),
            "kept": len(plan.kept_connections),
            "removed": len(plan.removed_connections),
        },
    }
