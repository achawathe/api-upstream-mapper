from api_mapper.matching.assigner import Thresholds, assign, rank
from api_mapper.matching.candidates import CandidateIndex
from api_mapper.matching.reachability import Reachability
from api_mapper.matching.scorer import PairScorer
from api_mapper.matching.semantic import (
    LocalSentenceEncoder,
    NlpSettings,
    SemanticIndex,
    TextEncoder,
)
from api_mapper.matching.signals import SignalContext
from api_mapper.matching.similarity import ConceptWeights
from api_mapper.models import Candidate, FieldMapping, FieldProfile
from api_mapper.normalize.lexicon import Lexicon
from api_mapper.transforms.inference import TypeFitter


class PreparedMatch:
    """Scoring state for one run; kept so a user can ask for any (target, source) pair later.

    `corpus` is every upstream field when only some are mapped, so concept weights match a full run.
    """

    def __init__(
        self,
        targets: list[FieldProfile],
        sources: list[FieldProfile],
        lexicon: Lexicon,
        fitter: TypeFitter,
        reachability: Reachability | None = None,
        semantic: SemanticIndex | None = None,
        corpus: list[FieldProfile] | None = None,
    ):
        self.targets = {t.node.key: t for t in targets}
        self.sources = {s.node.key: s for s in sources}
        weights = ConceptWeights([*(targets if corpus is None else corpus), *sources], lexicon)
        self.scorer = PairScorer(
            SignalContext(lexicon, weights, fitter.enum_mapper, reachability), fitter, semantic=semantic
        )
        self.index = CandidateIndex(sources, lexicon, semantic)

    def score_all(self) -> dict[str, list[Candidate]]:
        scored: dict[str, list[Candidate]] = {}
        for key, target in self.targets.items():
            candidates = (self.scorer.score(target, source) for source in self.index.candidates_for(target))
            scored[key] = rank([c for c in candidates if c is not None])
        return scored

    def score_pair(self, target_key: str, source_key: str) -> Candidate | None:
        target, source = self.targets.get(target_key), self.sources.get(source_key)
        if target is None or source is None:
            return None
        return self.scorer.score(target, source, gate=False)


class MatchingEngine:
    def __init__(
        self,
        lexicon: Lexicon,
        thresholds: Thresholds = Thresholds(),
        nlp: NlpSettings | None = None,
        encoder: TextEncoder | None = None,
    ):
        self.lexicon = lexicon
        self.thresholds = thresholds
        self.fitter = TypeFitter(lexicon)
        self.nlp = nlp or NlpSettings()
        self._encoder = encoder

    def prepare(
        self,
        targets: list[FieldProfile],
        sources: list[FieldProfile],
        reachability: Reachability | None = None,
        corpus: list[FieldProfile] | None = None,
    ) -> PreparedMatch:
        semantic = None
        if self.nlp.model_path or self._encoder is not None:
            if self._encoder is None:
                self._encoder = LocalSentenceEncoder(self.nlp.model_path)
            semantic = SemanticIndex([*targets, *sources], self._encoder, self.nlp)
        return PreparedMatch(targets, sources, self.lexicon, self.fitter, reachability, semantic, corpus)

    def match(self, targets: list[FieldProfile], sources: list[FieldProfile]) -> list[FieldMapping]:
        prepared = self.prepare(targets, sources)
        return assign(targets, prepared.score_all(), self.thresholds)
