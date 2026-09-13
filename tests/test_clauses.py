import pytest

from fo.clauses import evaluate, parse
from fo.errors import OfficeError


@pytest.mark.parametrize(
    "text",
    ["unknown < 1", "weight == 0.1", "price < 95 for 2q", "rev_growth_yoy < 20", "weight > 10%"],
)
def test_bad_clauses(text):
    with pytest.raises(OfficeError):
        parse(text)


def test_consecutive_quarters():
    clause = parse("rev_growth_yoy < 0.20 for 2q")
    assert evaluate(clause, [{"value": "0.1", "period": "2026-03-31"}]) is None
    assert (
        evaluate(
            clause,
            [{"value": "0.1", "period": "2026-03-31"}, {"value": "0.15", "period": "2026-06-30"}],
        )
        is True
    )
    assert (
        evaluate(
            clause,
            [{"value": "0.1", "period": "2026-03-31"}, {"value": "0.3", "period": "2026-06-30"}],
        )
        is False
    )
