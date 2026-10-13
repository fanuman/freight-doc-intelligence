"""The document-reading pipeline: parse -> classify -> extract -> validate.

Built as a LangGraph graph (graph.py); the individual steps live in nodes.py so
they can be tested without LangGraph or an LLM.
"""
