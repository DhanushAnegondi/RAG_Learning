"""CRAG graph nodes. Each node has signature `node(state) -> dict` (a partial state update).

Submodules are imported by their full path (e.g. `from crag.nodes.grade import grade_documents`)
rather than re-exported here, so the submodule names are not shadowed by the functions — this keeps
each node module independently monkeypatchable in tests.
"""
