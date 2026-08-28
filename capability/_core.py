"""Internal implementation. Nothing here is public — callers only ever
touch capability.run().

Organise this however suits the job: one function or many, one LLM call
or several, a self-critique pass, whatever. The only contract is:
given an Input, produce an Output.
"""

from __future__ import annotations

from ._contract import Input, Output


def build(data: Input) -> Output:
    # TODO: real implementation. Sketch of an LLM call, kept commented so
    # the template runs with no API key set:
    #
    #   import anthropic
    #   client = anthropic.Anthropic()
    #   msg = client.messages.create(
    #       model="claude-opus-5",
    #       max_tokens=16000,
    #       system="You are ...",
    #       messages=[{"role": "user", "content": data.text}],
    #   )
    #   text = next(b.text for b in msg.content if b.type == "text")
    #   return Output(result=text, rationale="...")

    placeholder = f"[placeholder output for {len(data.text)} characters of input]"
    return Output(result=placeholder, rationale="template stub — not implemented yet")

