"""BitChord hybrid FLAC streaming addon gateway.

A FastAPI relay that implements the BitChord addon contract
(`/manifest.json`, `/search`, `/resolve-isrc`, `/stream/{id}`, `/audio/{token}`)
on top of user-configured sources. Run it with `python -m bitchord_gateway`.
"""
