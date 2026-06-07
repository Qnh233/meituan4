# Strategy: TwoPhase
# Description: 两阶段：第一阶段选 willingness>0.5 的候选，第二阶段用 unit_score 补全

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
        parts = line.split("\t")
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
