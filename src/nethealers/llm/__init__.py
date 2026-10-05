"""Language-model access with fallbacks."""

from .client import LLM, Answer, LLMUnavailable, parse_json

__all__ = ["LLM", "Answer", "LLMUnavailable", "parse_json"]
