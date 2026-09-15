"""R4: LOGITS / PROBS / PREDS through helpers, returns and tensor tails.

`rules/valuetype.py` is the one place four rules ask *what is this value?*, and
these are the paths it opened. Every one of them ships with its negative, in
the same shape, because the whole risk of a widening like this is that it stops
distinguishing the defect from the fix.

The two the rule set could not see before:

* the score reaches the metric / the loss through a workspace helper's
  `return`, rather than from a call written at the site;
* the class decision was taken by `argmax` rather than by `predict()`.
"""

from __future__ import annotations

import pytest

from mlview.rules.valuetype import (DECIDING_ROLES, LOGIT_ROLES, PROB_ROLES,
                                    SCORE_TAGS)
from rule_harness import assert_fires, assert_silent

#: `<bad fixture>, <good fixture>, <the code both are about>`.
PAIRS = (
    ("MLV305_helper_bad", "MLV305_helper_good", "MLV305"),
    ("MLV306_argmax_bad", "MLV306_argmax_good", "MLV306"),
    ("MLV401_helper_bad", "MLV401_helper_good", "MLV401"),
    ("MLV402_helper_bad", "MLV402_helper_good", "MLV402"),
)


@pytest.mark.parametrize("bad,good,code", PAIRS)
def test_each_new_path_fires_and_its_negative_stays_silent(bad, good, code):
    assert_fires(bad)
    assert_silent(good, code)


@pytest.mark.parametrize("bad,good,code", PAIRS)
def test_both_dataflow_modes_agree_on_the_new_paths(bad, good, code):
    """The value typing is not an `ip` feature: it reads what `ir.returns`
    already knew in either mode, so both modes see the same defect and both
    stay silent on its twin."""
    for mode in ("local", "ip"):
        assert_fires(bad, dataflow=mode)
        assert_silent(good, code, dataflow=mode)


def test_a_helper_traced_pairing_is_never_certain():
    """11.36 G6: crossing a `def` costs one IP_HOP_WEIGHT, in every mode.

    The softmax is a function away from the loss, so the claim is a
    cross-object one and the confidence has to say so.
    """
    for name, code in (("MLV401_helper_bad", "MLV401"),
                       ("MLV402_helper_bad", "MLV402")):
        issue = assert_fires(name).of(code)[0]
        assert issue["confidenceBucket"] != "certain", (
            "%s crossed a helper and still landed at %.3f" % (code,
                                                              issue["confidence"]))
        assert any(e["kind"] == "cross_file" and "one function away" in e["detail"]
                   for e in issue["evidence"]), (
            "the hop has to be visible in the evidence, not only in the number")


def test_the_metric_names_what_the_value_actually_is():
    """A finding that says "it carries PROBS" has to have read a PROBS tag."""
    issue = assert_fires("MLV305_helper_bad").of("MLV305")[0]
    assert "PROBS" in issue["message"]
    assert any(e["kind"] == "negation_absent" for e in issue["evidence"]), (
        "the absent argmax is the whole claim")


def test_mlv306_says_which_op_took_the_decision():
    issue = assert_fires("MLV306_argmax_bad").of("MLV306")[0]
    assert "argmax" in issue["message"], issue["message"]


def test_the_vocabulary_is_the_three_score_tags_and_nothing_else():
    """`valuetype` reasons about exactly the tags `ir.model` declares."""
    from mlview.ir.model import VALUE_TAGS

    assert set(SCORE_TAGS) <= set(VALUE_TAGS)
    assert SCORE_TAGS == ("LOGITS", "PROBS", "PREDS")
    assert PROB_ROLES == {"SOFTMAX", "SIGMOID"}
    assert LOGIT_ROLES == {"LOG_SOFTMAX"}, (
        "log-softmax output is unbounded below: it is a logit, and "
        "CrossEntropyLoss is its correct partner")
    assert DECIDING_ROLES == {"ARGMAX"}
