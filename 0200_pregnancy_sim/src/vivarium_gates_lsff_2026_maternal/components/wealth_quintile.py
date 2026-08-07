from typing import Dict, List

import numpy as np
import pandas as pd
from vivarium.engine import Component
from vivarium.engine.framework.engine import Builder
from vivarium.engine.framework.population import SimulantData

from lsff_utils import data_processing
from vivarium_gates_lsff_2026_maternal.constants import data_keys, data_values


class WealthQuintile(Component):
    def __init__(self) -> None:
        super().__init__()
        self.quintile_probabilities_name = "wealth_quintile.quintile_probabilities"
        """Name of the attribute pipeline giving per-quintile membership probabilities."""

    @property
    def columns_created(self) -> List[str]:
        return ["wealth_quintile"]

    # noinspection PyAttributeOutsideInit
    def setup(self, builder: Builder):
        self.randomness = builder.randomness.get_stream(self.name)

        quintile_probabilities = builder.data.load(
            data_keys.POPULATION.WEALTH_QUINTILE_PROBABILITIES
        )
        # TODO: Quintile probabilities dtypes
        quintile_probabilities = quintile_probabilities.rename(
            columns={
                "1": 1,
                "2": 2,
                "3": 3,
                "4": 4,
                "5": 5,
            }
        )
        # NOTE: the table name must differ from the pipeline name -- see the note in
        # components/children.py.
        quintile_probabilities_table = self.build_lookup_table(
            builder,
            "quintile_probabilities_data",
            data_source=quintile_probabilities,
            value_columns=data_processing.WEALTH_QUINTILES,
        )

        # The table backs a pipeline rather than being read directly, so other
        # components can register modifiers against these probabilities. Read it back
        # through the population view; register_attribute_producer returns None.
        builder.value.register_attribute_producer(
            self.quintile_probabilities_name,
            source=quintile_probabilities_table,
            required_resources=[quintile_probabilities_table],
        )

        builder.population.register_initializer(
            self.on_initialize_simulants,
            columns=self.columns_created,
            required_resources=[self.randomness, self.quintile_probabilities_name],
        )

    def on_initialize_simulants(self, pop_data: SimulantData) -> None:
        pop_update = pd.DataFrame(index=pop_data.index)
        # Multi-column attribute, so get_frame rather than get.
        quintile_probabilities = self.population_view.get_frame(
            pop_data.index, self.quintile_probabilities_name
        )
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
        self.population_view.initialize(pop_update)
