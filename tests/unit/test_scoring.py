"""Scorer behaviour on the ambiguous cases the tool exists for."""

import pytest

from api_mapper.matching.scorer import PairScorer
from api_mapper.matching.signals import SignalContext
from api_mapper.matching.similarity import ConceptWeights
from api_mapper.models import FieldNode
from api_mapper.normalize.profiler import Profiler
from api_mapper.transforms.inference import TypeFitter


@pytest.fixture
def score(lexicon):
    profiler = Profiler(lexicon)

    def profile(path, endpoint_concepts=("account",), scope=frozenset(), **node):
        depth = path.count("[]")
        field = FieldNode(
            api="api", endpoint="GET /x", path=path, type=node.pop("type", "string"), array_depth=depth, **node
        )
        return profiler.profile(field, frozenset(scope), endpoint_concepts)

    def run(target, source):
        fitter = TypeFitter(lexicon)
        ctx = SignalContext(lexicon, ConceptWeights([target, source], lexicon), fitter.enum_mapper)
        candidate = PairScorer(ctx, fitter).score(target, source)
        return candidate.score if candidate else 0.0

    run.profile = profile
    return run


def test_dotted_and_camel_case_names_match(score):
    assert score(score.profile("accountId"), score.profile("account.id")) > 0.85


def test_role_words_separate_lookalikes(score):
    target = score.profile("accountId")
    assert score(target, score.profile("fromAccountId")) < score(target, score.profile("account.id")) * 0.6


def test_debit_account_id_is_not_a_credit_account_id(score):
    credit_target = score.profile("accountId", schema_names=("LineOfCreditAccount",))
    debit_source = score.profile("debitAccount.id")
    plain_source = score.profile("account.id")
    assert score(credit_target, debit_source) < 0.5
    assert score(credit_target, plain_source) > 0.85


def test_api_scope_makes_bare_id_an_account_id(score):
    target = score.profile("accountId", schema_names=("LoanAccount",))
    loan_id = score.profile("loan_id", endpoint_concepts=("lending", "loan"), scope={"loan"})
    assert score(target, loan_id) > 0.8


def test_exclusive_modifiers_conflict(score):
    target = score.profile("minimumPaymentAmount", type="number")
    assert score(target, score.profile("statement.minimumDue", type="number")) > score(
        target, score.profile("lastPayment.amount", type="number")
    )


def test_items_must_come_from_the_same_kind_of_collection(score):
    target = score.profile("statements[].accountId")
    assert score(target, score.profile("data[].account.id")) < 0.6
