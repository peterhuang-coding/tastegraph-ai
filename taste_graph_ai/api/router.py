from fastapi import APIRouter

from taste_graph_ai.api.routes import sources, daily, graph, tasks, history, pipeline, health

api_router = APIRouter()
api_router.include_router(sources.router)
api_router.include_router(daily.router)
api_router.include_router(graph.router)
api_router.include_router(tasks.router)
api_router.include_router(history.router)
api_router.include_router(pipeline.router)
api_router.include_router(health.router)
