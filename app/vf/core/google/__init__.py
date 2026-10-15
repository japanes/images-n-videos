"""Gateway to Google: the only package that may import google-genai / google-auth.

Everything else goes through these names::

    from vf.core import google
    result = await google.generate(purpose="frame", contents=[prompt], response="image")
"""

from vf.core.google import credentials, journal, token
from vf.core.google.errors import GoogleCallError, classify
from vf.core.google.gateway import Blob, GenerateResult, PromptInfo, blob_from_file, generate, list_models
from vf.core.google.limiter import limiter

__all__ = [
    "Blob", "GenerateResult", "GoogleCallError", "PromptInfo", "blob_from_file", "classify", "credentials",
    "generate", "journal", "limiter", "list_models", "token",
]
