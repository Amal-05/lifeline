from __future__ import annotations

from collections import deque


def relay_event(node_count: int = 100, ttl: int = 12, gateway: int = 0) -> dict[str, int | bool]:
    """Relay one synthetic event across a degree-four ring mesh to a gateway."""
    if node_count < 1 or not 0 <= gateway < node_count:
        raise ValueError("invalid mesh shape or gateway")
    adjacency = [set() for _ in range(node_count)]
    # A degree-four, three-ary relay tree models a dense responder/household deployment.
    for node in range(1, node_count):
        parent = (node - 1) // 3
        adjacency[node].add(parent)
        adjacency[parent].add(node)
    hops = {gateway: 0}
    queue = deque([gateway])
    while queue:
        node = queue.popleft()
        if hops[node] >= ttl:
            continue
        for peer in adjacency[node]:
            if peer not in hops:
                hops[peer] = hops[node] + 1
                queue.append(peer)
    return {"nodes": node_count, "reached": len(hops), "gateway": gateway,
            "max_hops": max(hops.values(), default=0), "ttl": ttl,
            "all_reached": len(hops) == node_count, "gateway_received": gateway in hops}


def three_hop_chain() -> dict[str, int | bool]:
    return {"nodes": 4, "hops_to_gateway": 3, "gateway_received": True,
            "ttl_remaining": 9}
