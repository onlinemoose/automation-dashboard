"""Proves run() honours the contract in docs/CONTRACT.md.

Grow this as the contract grows: one test per promise the module makes.
"""

from capability import Input, Output, run


def test_run_returns_the_output_type():
    result = run(Input(text="hello"))
    assert isinstance(result, Output)
    assert isinstance(result.result, str)


def test_run_works_without_optional_inputs():
    # Rule 7: the module must produce a valid result when only the
    # required inputs are supplied.
    result = run(Input(text="hello"))
    assert result.result != ""
