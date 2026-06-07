def solve(input_text: str) -> list:
    lines = input_text.strip().split('\n')
    if not lines or len(lines) < 2:
        return []
    
    header = lines[0].split('\t')
    task_idx = header.index('task_id_list') if 'task_id_list' in header else 0
    courier_idx = header.index('courier_id') if 'courier_id' in header else 1
    score_idx = header.index('total_score') if 'total_score' in header else 2
    will_idx = header.index('willingness') if 'willingness' in header else 3
    
    entries = []
    for line in lines[1:]:
        parts = line.split('\t')
        if len(parts) < 4:
            continue
        task = parts[task_idx].strip()
        courier = parts[courier_idx].strip()
        try:
            score = float(parts[score_idx].strip())
            will = float(parts[will_idx].strip())
        except:
            continue
        entries.append((task, courier, score, will))
    
    if not entries:
        return []
    
    tasks = set()
    couriers = set()
    edges = []
    for task, courier, score, will in entries:
        tasks.add(task)
        couriers.add(courier)
        edges.append((courier, task, score, will))
    
    # Build graph for min-cost max-flow
    # Node indices: source=0, couriers=1..len(couriers), tasks=len(couriers)+1..len(couriers)+len(tasks), sink=-1
    courier_list = list(couriers)
    task_list = list(tasks)
    courier_to_idx = {c: i+1 for i, c in enumerate(courier_list)}
    task_to_idx = {t: i+1+len(couriers) for i, t in enumerate(task_list)}
    
    # Graph representation: adj[node] = list of (next_node, capacity, cost, edge_id)
    num_nodes = 2 + len(couriers) + len(tasks)  # source + sink + couriers + tasks
    source = 0
    sink = num_nodes - 1
    graph = [[] for _ in range(num_nodes)]
    edge_id = 0
    
    # Add edges from source to couriers
    for i, courier in enumerate(courier_list):
        node = courier_to_idx[courier]
        graph[source].append((node, 1, 0, edge_id))
        edge_id += 1
    
    # Add edges from tasks to sink
    for i, task in enumerate(task_list):
        node = task_to_idx[task]
        graph[node].append((sink, 1, 0, edge_id))
        edge_id += 1
    
    # Add edges from couriers to tasks based on entries
    for courier, task, score, will in edges:
        courier_node = courier_to_idx[courier]
        task_node = task_to_idx[task]
        # Cost is score adjusted by willingness
        cost = score - will  # Higher willingness reduces cost
        graph[courier_node].append((task_node, 1, cost, edge_id))
        edge_id += 1
    
    # Min-cost max-flow algorithm (SPFA + Edmonds-Karp)
    INF = float('inf')
    max_flow = 0
    min_cost = 0
    matches = {}  # courier -> task mapping
    
    while True:
        # SPFA to find shortest path from source to sink
        dist = [INF] * num_nodes
        parent = [-1] * num_nodes
        edge_in_path = [-1] * num_nodes
        in_queue = [False] * num_nodes
        dist[source] = 0
        queue = [source]
        in_queue[source] = True
        
        while queue:
            u = queue.pop(0)
            in_queue[u] = False
            for v, cap, cost, eid in graph[u]:
                if cap > 0 and dist[u] + cost < dist[v]:
                    dist[v] = dist[u] + cost
                    parent[v] = u
                    edge_in_path[v] = eid
                    if not in_queue[v]:
                        queue.append(v)
                        in_queue[v] = True
        
        if dist[sink] == INF:
            break
        
        # Find bottleneck capacity along the path
        path_flow = INF
        v = sink
        while v != source:
            u = parent[v]
            # Find the edge from u to v in graph[u]
            for edge in graph[u]:
                if edge[0] == v and edge[3] == edge_in_path[v]:
                    path_flow = min(path_flow, edge[1])
                    break
            v = u
        
        # Update capacities and add reverse edges
        v = sink
        while v != source:
            u = parent[v]
            # Find and update the forward edge
            for i, edge in enumerate(graph[u]):
                if edge[0] == v and edge[3] == edge_in_path[v]:
                    # Decrease capacity
                    graph[u][i] = (edge[0], edge[1] - path_flow, edge[2], edge[3])
                    # Add/update reverse edge
                    reverse_edge_found = False
                    for j, redge in enumerate(graph[v]):
                        if redge[0] == u and redge[3] == edge[3]:
                            # Update reverse edge capacity
                            graph[v][j] = (redge[0], redge[1] + path_flow, -edge[2], redge[3])
                            reverse_edge_found = True
                            break
                    if not reverse_edge_found:
                        graph[v].append((u, path_flow, -edge[2], edge[3]))
                    break
            v = u
        
        max_flow += path_flow
        min_cost += path_flow * dist[sink]
        
        # Record matches from this augmentation
        # Trace back from sink to source to find matched courier-task pairs
        v = sink
        while v != source:
            u = parent[v]
            # Check if this is a courier->task edge
            if source < u <= len(couriers) and len(couriers) < v < sink:
                courier_node = u
                task_node = v
                # Find corresponding courier and task
                courier = courier_list[courier_node - 1]
                task = task_list[task_node - len(couriers) - 1]
                matches[courier] = task
            v = u
    
    # Prepare result: list of (courier, task) pairs or empty if no matches
    result = []
    for courier, task in matches.items():
        result.append((courier, task))
    
    return result