from services.simulator.mesh import relay_event, three_hop_chain


def test_mesh_simulator_relays_through_three_hops_to_gateway():
    assert three_hop_chain() == {"nodes": 4, "hops_to_gateway": 3, "gateway_received": True, "ttl_remaining": 9}


def test_mesh_simulator_covers_one_hundred_node_degree_four_mesh():
    result = relay_event(100, ttl=12)
    assert result["all_reached"] is True
    assert result["max_hops"] <= 12
    assert result["reached"] == 100
