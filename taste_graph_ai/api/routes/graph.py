from fastapi import APIRouter, Depends, HTTPException

from taste_graph_ai.api import schemas
from taste_graph_ai.api.deps import get_event_log
from taste_graph_ai.container import get_container
from taste_graph_ai.domain.enums import NodeType, RelationType
from taste_graph_ai.infrastructure.db.event_log import EventLog

router = APIRouter(prefix="/api/v1/graph", tags=["graph"])


@router.get("/overview", response_model=schemas.GraphOverviewResponse)
async def graph_overview():
    graph = get_container().taste_graph
    return graph.overview()


@router.get("/nodes", response_model=list[schemas.GraphNodeResponse])
async def list_nodes(type: str = "", q: str = ""):
    graph = get_container().taste_graph
    node_type = NodeType(type) if type else None
    if q:
        nodes = graph.search_nodes(q)
    else:
        nodes = graph.list_nodes(node_type)
    return [
        schemas.GraphNodeResponse(
            id=n.id, type=n.type.value, label=n.label, properties=n.properties,
        )
        for n in nodes
    ]


@router.get("/edges", response_model=list[schemas.GraphEdgeResponse])
async def list_edges(relation: str = ""):
    graph = get_container().taste_graph
    rel = RelationType(relation) if relation else None
    return [
        schemas.GraphEdgeResponse(
            source=e.source, target=e.target, relation=e.relation.value,
            weight=e.weight, feedback_count=e.feedback_count, last_updated=e.last_updated,
        )
        for e in graph.list_edges(rel)
    ]


@router.get("/node/{node_id}", response_model=schemas.GraphNodeDetailResponse)
async def get_node(node_id: str):
    graph = get_container().taste_graph
    node = graph.get_node(node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    related = []
    for _, neighbor in graph.graph.out_edges(node_id):
        n = graph.get_node(neighbor)
        if n:
            related.append(schemas.GraphNodeResponse(
                id=n.id, type=n.type.value, label=n.label, properties=n.properties,
            ))
    for neighbor, _ in graph.graph.in_edges(node_id):
        n = graph.get_node(neighbor)
        if n:
            related.append(schemas.GraphNodeResponse(
                id=n.id, type=n.type.value, label=n.label, properties=n.properties,
            ))
    return schemas.GraphNodeDetailResponse(
        id=node.id, type=node.type.value, label=node.label,
        properties=node.properties, related_nodes=related,
    )


@router.post("/node", response_model=schemas.GraphNodeResponse)
async def create_node(
    body: schemas.GraphNodeCreateRequest,
    event_log: EventLog = Depends(get_event_log),
):
    graph = get_container().taste_graph
    node_id = graph.add_node(body.label, NodeType(body.node_type))
    graph.save()
    event_log.append("graph.node.created", {"id": node_id, "label": body.label})
    node = graph.get_node(node_id)
    return schemas.GraphNodeResponse(
        id=node.id, type=node.type.value, label=node.label, properties=node.properties,
    )


@router.patch("/node/{node_id}", response_model=schemas.GraphNodeResponse)
async def update_node(node_id: str, body: schemas.GraphNodeUpdateRequest):
    graph = get_container().taste_graph
    if node_id not in graph.graph:
        raise HTTPException(status_code=404, detail="Node not found")
    if body.label:
        graph.graph.nodes[node_id]["label"] = body.label
    if body.properties:
        graph.graph.nodes[node_id]["properties"].update(body.properties)
    graph.save()
    node = graph.get_node(node_id)
    return schemas.GraphNodeResponse(
        id=node.id, type=node.type.value, label=node.label, properties=node.properties,
    )


@router.delete("/node/{node_id}")
async def delete_node(
    node_id: str,
    event_log: EventLog = Depends(get_event_log),
):
    graph = get_container().taste_graph
    if node_id not in graph.graph:
        raise HTTPException(status_code=404, detail="Node not found")
    graph.remove_node(node_id)
    graph.save()
    event_log.append("graph.node.deleted", {"id": node_id})
    return {"status": "ok"}


@router.post("/edge", response_model=schemas.GraphEdgeResponse)
async def create_edge(
    body: schemas.GraphEdgeCreateRequest,
    event_log: EventLog = Depends(get_event_log),
):
    graph = get_container().taste_graph
    try:
        graph.add_edge(body.source, body.target, RelationType(body.relation), body.weight)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    graph.save()
    event_log.append("graph.edge.created", body.model_dump())
    edge = graph.get_edge(body.source, body.target)
    return schemas.GraphEdgeResponse(
        source=edge.source, target=edge.target, relation=edge.relation.value,
        weight=edge.weight, feedback_count=edge.feedback_count, last_updated=edge.last_updated,
    )


@router.delete("/edge/{edge_key}")
async def delete_edge(
    edge_key: str,
    event_log: EventLog = Depends(get_event_log),
):
    graph = get_container().taste_graph
    parts = edge_key.split("|", 1)
    if len(parts) != 2:
        raise HTTPException(status_code=400, detail="edge_key must be 'source|target'")
    source, target = parts
    if not graph.has_edge(source, target):
        raise HTTPException(status_code=404, detail="Edge not found")
    graph.remove_edge(source, target)
    graph.save()
    event_log.append("graph.edge.deleted", {"source": source, "target": target})
    return {"status": "ok"}


@router.post("/feedback/apply")
async def apply_feedback(
    body: schemas.GraphWeightRequest,
    event_log: EventLog = Depends(get_event_log),
):
    graph = get_container().taste_graph
    if not graph.has_edge(body.source, body.target):
        raise HTTPException(status_code=404, detail="Edge not found")
    new_weight = graph.adjust_weight(body.source, body.target, body.delta)
    graph.save()
    event_log.append("graph.weight.updated", {
        "source": body.source, "target": body.target,
        "delta": body.delta, "new_weight": new_weight,
    })
    return {"status": "ok", "new_weight": new_weight}
