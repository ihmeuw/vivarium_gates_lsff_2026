from typing import Dict, List

import numpy as np
import pandas as pd
from vivarium import Component
from vivarium.framework.engine import Builder
from vivarium.framework.population import SimulantData
from vivarium_public_health.utilities import get_lookup_columns

from vivarium_gates_lsff_by_wealth_quintile.constants import data_keys, data_values


class WealthQuintile(Component):

    @property
    def columns_created(self) -> List[str]:
        return ["wealth_quintile"]

    @property
    def columns_required(self) -> List[str]:
        return ["tracked"]

    @property
    def initialization_requirements(self) -> Dict[str, List[str]]:
        return {"requires_streams": [self.name]}

    # noinspection PyAttributeOutsideInit
    def setup(self, builder: Builder):
        self.randomness = builder.randomness.get_stream(self.name)

        quintile_probabilities = self.build_lookup_table(
            builder,
            builder.data.load(data_keys.POPULATION.WEALTH_QUINTILE_PROBABILITIES),
            value_columns=data_values.WEALTH_QUINTILES,
        )

        self.quintile_probabilities = builder.value.register_value_producer(
            "wealth_quintile.quintile_probabilities",
            source=quintile_probabilities,
            requires_columns=get_lookup_columns([quintile_probabilities]),
        )

    def on_initialize_simulants(self, pop_data: SimulantData) -> None:
        pop_update = pd.DataFrame(index=pop_data.index)
        quintile_probabilities = self.quintile_probabilities(pop_data.index)
        # HACK: release-candidate-spring currently has nondeterminism about column order
        # https://github.com/ihmeuw/vivarium/blob/7491e099b96a958a607f8291581f1ce7b5c6c21c/src/vivarium/component.py#L687
        columns = sorted(quintile_probabilities.columns)
        quintile_probabilities = quintile_probabilities[columns]
        pop_update["wealth_quintile"] = self.randomness.choice(
            pop_data.index,
            quintile_probabilities.columns,
            quintile_probabilities,
            additional_key="wealth_quintile",
        )
        self.population_view.update(pop_update)
