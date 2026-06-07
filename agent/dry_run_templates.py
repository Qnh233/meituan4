"""Dry-run：由策略规格拼装纯 Python solve()（仅供 simple loop 本地测试）。"""


def build_strategy_code(spec: dict) -> str:
    """根据策略规格生成纯 Python solve() 代码。"""
    sort_key = spec["sort_key"]
    name = spec["name"]
    desc = spec["description"]

    if sort_key == "composite":
        sort_line = (
            "candidates.sort(key=lambda x: x[3] * 100 - x[2], reverse=True)"
        )
    elif sort_key == "two_phase":
        return _build_two_phase_code(name, desc)
    elif sort_key == "per_task":
        return _build_per_task_code(name, desc)
    elif sort_key == "confidence":
        return _build_confidence_code(name, desc)
    elif sort_key == "score_opt":
        sort_line = (
            "candidates.sort(key=lambda x: x[2] / len(x[0]) if len(x[0]) > 0 "
            "else float('inf'))"
        )
    else:
        sort_line = "candidates.sort(key=lambda x: x[3], reverse=True)"

    return _build_base_code(name, desc, sort_line)


def _build_base_code(name: str, desc: str, sort_line: str) -> str:
    return f'''# Strategy: {name}
# Description: {desc}

def solve(input_text: str) -> list:
    lines = input_text.strip().splitlines()
    if not lines:
        return []
    start = 1 if lines[0].startswith("task_id_list") else 0
    candidates = []
    for line in lines[start:]:
        line = line.strip()
        if not line:
            continue
        parts = line.split("\\t")
        if len(parts) < 4:
            continue
        task_id_list_str, courier_id, score_str, willingness_str = parts[:4]
        try:
            willingness = float(willingness_str)
        except ValueError:
            continue
        if willingness <= 0:
            continue
        task_ids = tuple(t.strip() for t in task_id_list_str.split(",") if t.strip())
        if not task_ids:
            continue
        try:
            score = float(score_str)
        except ValueError:
            score = float("inf")
        candidates.append((task_ids, courier_id.strip(), score, willingness))
    {sort_line}
    assigned_couriers = set()
    assigned_tasks = set()
    result = []
    for task_ids, courier_id, score, willingness in candidates:
        if courier_id in assigned_couriers:
            continue
        if any(t in assigned_tasks for t in task_ids):
            continue
        assigned_couriers.add(courier_id)
        assigned_tasks.update(task_ids)
        result.append((",".join(task_ids), [courier_id]))
    return result
'''


def _build_two_phase_code(name: str, desc: str) -> str:
    return f'''# Strategy: {name}
# Description: {desc}

def solve(input_text: str) -> list:
    lines = input_text.strip().splitlines()
    if not lines:
        return []
    start = 1 if lines[0].startswith("task_id_list") else 0
    all_cands = []
    for line in lines[start:]:
        line = line.strip()
        if not line:
            continue
        parts = line.split("\\t")
        if len(parts) < 4:
            continue
        try:
            willingness = float(parts[3])
        except ValueError:
            continue
        if willingness <= 0:
            continue
        task_ids = tuple(t.strip() for t in parts[0].split(",") if t.strip())
        if not task_ids:
            continue
        try:
            score = float(parts[2])
        except ValueError:
            score = float("inf")
        all_cands.append((task_ids, parts[1].strip(), score, willingness))
    assigned_couriers = set()
    assigned_tasks = set()
    result = []
    # Phase 1: willingness > 0.5
    phase1 = sorted([c for c in all_cands if c[3] > 0.5], key=lambda x: x[2])
    for c in phase1:
        if c[1] in assigned_couriers:
            continue
        if any(t in assigned_tasks for t in c[0]):
            continue
        assigned_couriers.add(c[1])
        assigned_tasks.update(c[0])
        result.append((",".join(c[0]), [c[1]]))
    # Phase 2: 补全剩余
    phase2 = sorted(
        [c for c in all_cands if c[1] not in assigned_couriers and not any(t in assigned_tasks for t in c[0])],
        key=lambda x: x[2] / len(x[0])
    )
    for c in phase2:
        if c[1] in assigned_couriers:
            continue
        if any(t in assigned_tasks for t in c[0]):
            continue
        assigned_couriers.add(c[1])
        assigned_tasks.update(c[0])
        result.append((",".join(c[0]), [c[1]]))
    return result
'''


def _build_per_task_code(name: str, desc: str) -> str:
    return f'''# Strategy: {name}
# Description: {desc}

def solve(input_text: str) -> list:
    lines = input_text.strip().splitlines()
    if not lines:
        return []
    start = 1 if lines[0].startswith("task_id_list") else 0
    task_cands = {{}}
    for line in lines[start:]:
        line = line.strip()
        if not line:
            continue
        parts = line.split("\\t")
        if len(parts) < 4:
            continue
        try:
            willingness = float(parts[3])
        except ValueError:
            continue
        if willingness <= 0:
            continue
        task_ids = tuple(t.strip() for t in parts[0].split(",") if t.strip())
        if not task_ids:
            continue
        try:
            score = float(parts[2])
        except ValueError:
            score = float("inf")
        for t in task_ids:
            if t not in task_cands:
                task_cands[t] = []
            task_cands[t].append((task_ids, parts[1].strip(), score, willingness))
    # 每个 task 的候选按 score 排序
    for t in task_cands:
        task_cands[t].sort(key=lambda x: x[2])
    assigned_couriers = set()
    assigned_tasks = set()
    result = []
    # 按候选质量迭代：每次选全局最佳
    all_tasks = sorted(task_cands.keys())
    while True:
        best = None
        best_score = float("inf")
        for t in all_tasks:
            if t in assigned_tasks:
                continue
            for c in task_cands.get(t, []):
                if c[1] in assigned_couriers:
                    continue
                if any(tt in assigned_tasks for tt in c[0]):
                    continue
                if c[2] < best_score:
                    best_score = c[2]
                    best = c
                break
        if best is None:
            break
        assigned_couriers.add(best[1])
        assigned_tasks.update(best[0])
        result.append((",".join(best[0]), [best[1]]))
    return result
'''


def _build_confidence_code(name: str, desc: str) -> str:
    return f'''# Strategy: {name}
# Description: {desc}

def solve(input_text: str) -> list:
    lines = input_text.strip().splitlines()
    if not lines:
        return []
    start = 1 if lines[0].startswith("task_id_list") else 0
    all_cands = []
    for line in lines[start:]:
        line = line.strip()
        if not line:
            continue
        parts = line.split("\\t")
        if len(parts) < 4:
            continue
        try:
            willingness = float(parts[3])
        except ValueError:
            continue
        if willingness <= 0:
            continue
        task_ids = tuple(t.strip() for t in parts[0].split(",") if t.strip())
        if not task_ids:
            continue
        try:
            score = float(parts[2])
        except ValueError:
            score = float("inf")
        all_cands.append((task_ids, parts[1].strip(), score, willingness))
    assigned_couriers = set()
    assigned_tasks = set()
    result = []
    # Phase 1: willingness >= 0.7 直接分配
    high = sorted([c for c in all_cands if c[3] >= 0.7], key=lambda x: x[2])
    for c in high:
        if c[1] in assigned_couriers:
            continue
        if any(t in assigned_tasks for t in c[0]):
            continue
        assigned_couriers.add(c[1])
        assigned_tasks.update(c[0])
        result.append((",".join(c[0]), [c[1]]))
    # Phase 2: ratio 贪心补全
    remaining = [c for c in all_cands if c[1] not in assigned_couriers and not any(t in assigned_tasks for t in c[0])]
    remaining.sort(key=lambda x: x[3] / max(x[2], 0.001), reverse=True)
    for c in remaining:
        if c[1] in assigned_couriers:
            continue
        if any(t in assigned_tasks for t in c[0]):
            continue
        assigned_couriers.add(c[1])
        assigned_tasks.update(c[0])
        result.append((",".join(c[0]), [c[1]]))
    return result
'''
