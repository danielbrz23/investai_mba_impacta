"""Ponto de entrada do LangGraph Studio (langgraph.json aponta para `graph`)."""

from investai_meta.graph import build_graph

graph = build_graph()  # o Studio injeta o store (store_studio.py) e o checkpointer
