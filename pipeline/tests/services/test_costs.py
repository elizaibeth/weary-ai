from agent.services import costs


class _Usage:
    def __init__(self, input_tokens=None, output_tokens=None):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


def test_tracking_starts_a_fresh_zeroed_run():
    with costs.tracking() as run:
        pass
    assert (run.text_prompt_tokens, run.text_completion_tokens, run.typesafe_input_tokens) == (0, 0, 0)
    assert (run.typesafe_output_tokens, run.image_usd, run.image_calls) == (0, 0.0, 0)


def test_record_text_usage_accumulates_across_calls():
    with costs.tracking() as run:
        costs.record_text_usage({"prompt_tokens": 10, "completion_tokens": 20})
        costs.record_text_usage({"prompt_tokens": 5, "completion_tokens": 7})
    assert (run.text_prompt_tokens, run.text_completion_tokens) == (15, 27)


def test_record_text_usage_tolerates_missing_usage_fields():
    with costs.tracking() as run:
        costs.record_text_usage({})
    assert (run.text_prompt_tokens, run.text_completion_tokens) == (0, 0)


def test_record_typesafe_accumulates_and_tolerates_none():
    with costs.tracking() as run:
        costs.record_typesafe(_Usage(input_tokens=100, output_tokens=None))
        costs.record_typesafe(_Usage(input_tokens=50, output_tokens=25))
    assert (run.typesafe_input_tokens, run.typesafe_output_tokens) == (150, 25)


def test_record_image_cost_accumulates_dollars_and_counts_every_call():
    with costs.tracking() as run:
        costs.record_image_cost(0.02)
        costs.record_image_cost(None)  # a provider that reports no cost still counts as a call
    assert (run.image_usd, run.image_calls) == (0.02, 2)


def test_runs_do_not_share_costs_and_nothing_is_recorded_outside_a_run():
    costs.record_text_cost(1.0)  # no run open: ignored, not leaked into the next run
    with costs.tracking() as first:
        costs.record_text_cost(0.5)
        with costs.tracking() as inner:
            costs.record_text_cost(0.25)
        costs.record_text_cost(0.5)
    with costs.tracking() as second:
        pass
    assert (first.text_usd, inner.text_usd, second.text_usd) == (1.0, 0.25, 0.0)


def test_elapsed_seconds_is_non_negative():
    assert costs.RunCosts().elapsed_seconds() >= 0
