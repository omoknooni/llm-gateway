from __future__ import annotations


def estimate_cost_usd(
    prompt_tokens: int,
    completion_tokens: int,
    input_cost_per_1k: float,
    output_cost_per_1k: float,
) -> float:
    return round(
        (prompt_tokens / 1000.0) * input_cost_per_1k
        + (completion_tokens / 1000.0) * output_cost_per_1k,
        8,
    )

