"""The agent's hands. Each tool is a plain function over the database, described
to the model by a JSON schema in `registry.py`. The model never runs anything;
`execute()` does, inside the backend, under the rules in CONTRIBUTING.md.
"""
