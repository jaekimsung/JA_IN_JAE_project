"""Bounded-memory deterministic case plans sized for a transition budget."""
from collections.abc import Sequence
import math

from kcity.env.config import digest

GENERATED_PLAN_SCHEMA = 'KC-PLAN-GENERATED-v1'


class GeneratedCasePlan(Sequence):
    """Whole ten-case cycles partitioned exactly as the explicit collector plan.

    At least one transition is recorded per completed Episode. Allocating one
    case per target transition therefore cannot exhaust the plan prematurely.
    Only the most recently requested case is cached; RUN.json stores the recipe.
    """

    def __init__(self, contract, kind, cycles, part=0, parts=1):
        if kind not in ('expert', 'train', 'archive', 'probe'):
            raise ValueError('Unknown case plan kind')
        if any(type(x) is not int for x in (cycles, part, parts)) or cycles < 1 or parts < 1 or not 0 <= part < parts:
            raise ValueError('Invalid generated plan dimensions')
        self.contract, self.kind = contract, kind
        self.cycles, self.part, self.parts = cycles, part, parts
        self._cached = None

    @classmethod
    def for_budget(cls, contract, kind, target, part=0, parts=1):
        if type(target) is not int or target < 1 or type(parts) is not int or parts < 1:
            raise ValueError('Positive transition budget and part count required')
        return cls(contract, kind, math.ceil(math.ceil(target / parts) / 10), part, parts)

    def __len__(self):
        return self.cycles * 10

    def __getitem__(self, index):
        from kcity.data.collector import PATTERN, resolved_case
        if isinstance(index, slice):
            return [self[i] for i in range(*index.indices(len(self)))]
        if index < 0:
            index += len(self)
        if not 0 <= index < len(self):
            raise IndexError(index)
        if self._cached is not None and self._cached[0] == index:
            return self._cached[1]
        cursor = (index // 10 * self.parts + self.part) * 10 + index % 10
        scenario = PATTERN[cursor % 10]
        if self.kind == 'expert':
            case_index = cursor // 10 * PATTERN.count(scenario) + PATTERN[:cursor % 10].count(scenario)
            namespace = split = 'expert_val' if case_index % 5 == 4 else 'expert_train'
        else:
            case_index = cursor
            namespace, split = dict(train=('train', 'rl_train'), archive=('archive', 'archive'),
                                    probe=('contract_check', 'ops_probe'))[self.kind]
        entry = dict(case=resolved_case(self.contract, namespace, scenario, case_index), data_split=split)
        self._cached = (index, entry)
        return entry

    def descriptor(self):
        return dict(schema=GENERATED_PLAN_SCHEMA, contract_sha256=digest(self.contract), kind=self.kind,
                    cycles=self.cycles, part=self.part, parts=self.parts,
                    runtime_variant=self[0]['case']['runtime_variant'])

    @classmethod
    def from_descriptor(cls, contract, spec):
        plan = cls(contract, spec['kind'], spec['cycles'], spec['part'], spec['parts'])
        if spec != plan.descriptor():
            raise ValueError('Generated plan contract/runtime/recipe changed')
        return plan
