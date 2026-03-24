"""
A2A response format utilities.

Use these helpers so that:
- Responses from sub-agents are passed through in the same A2A shape.
- Predefined responses (e.g. for certain queries) are emitted in the same A2A format.

All outbound agent text is sent as Task artifacts with Part(s) containing TextPart.
This module is the single place that builds that structure (a2a.types Part/TextPart).
"""

from typing import List

from a2a.types import Part, TextPart


def build_text_response_parts(text: str) -> List[Part]:
    """
    Build A2A-formatted parts for a single text response.

    Use this for:
    - Pass-through: after collecting sub-agent stream chunks, pass the
      concatenated string here and send via TaskUpdater.add_artifact(parts, name=...).
    - Predefined responses: pass the predefined message string and use the same
      add_artifact(parts, name=...) flow.

    Args:
        text: The response text (plain string).

    Returns:
        List of Part suitable for TaskUpdater.add_artifact(parts=[...], name=...).
    """
    if not text:
        text = ""
    return [Part(root=TextPart(text=text))]
