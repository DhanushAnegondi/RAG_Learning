"""CRAG graph nodes. Each node is a plain function `node(state, <deps>) -> dict` returning a
PARTIAL state update; graph.py binds the dependencies (settings, LLM client, retriever).

Submodules are imported by full path (`from crag.nodes.grade import grade_documents`) rather than
re-exported here, so each stays independently monkeypatchable in tests.
"""
