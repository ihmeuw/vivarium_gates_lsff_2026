from typing import List, Tuple

import numpy as np
import pandas as pd
from vivarium.engine import Component
from vivarium.engine.framework.engine import Builder
from vivarium.public_health.utilities import get_lookup_columns
from vivarium_gates_lsff_2026_maternal.constants import data_keys, data_values, models


class NewChildren(Component):
    ##############
    # Properties #
    ##############

    @property
    def sub_components(self) -> List[str]:
        return [self.lbwsg]

    def __init__(self):
        super().__init__()
        self.lbwsg = LBWSGDistribution()

    def setup(self, builder: Builder):
        self.randomness = builder.randomness.get_stream(self.name)

        # NOTE: I did not add this to the configurable lookup tables because
        # it is only used as the source for the pipeline.
        male_sex_percentage = self.build_lookup_table(
            builder,
            builder.data.load(data_keys.POPULATION.INFANT_MALE_PERCENTAGE),
            value_columns=["value"],
        )

        self.male_sex_percentage = builder.value.register_value_producer(
            "new_children.male_sex_percentage",
            source=male_sex_percentage,
            requires_attributes=get_lookup_columns([male_sex_percentage]),
        )

    def empty(self, index: pd.Index) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "sex_of_child": models.INVALID_OUTCOME,
                "birth_weight": np.nan,
                "gestational_age": np.nan,
            },
            index=index,
        )

    def generate_children(self, index: pd.Index) -> pd.DataFrame:
        male_sex_percentage = self.male_sex_percentage(index)
        male_sex = self.randomness.filter_for_probability(
            index, male_sex_percentage, additional_key="male_sex"
        )
        sex_of_child = pd.Series("Female", index=index)
        sex_of_child.loc[male_sex] = "Male"
        lbwsg = self.lbwsg(sex_of_child)
        return pd.DataFrame(
            {
                "sex_of_child": sex_of_child,
                "birth_weight": lbwsg["birth_weight"],
                "gestational_age": lbwsg["gestational_age"],
            },
            index=index,
        )


class LBWSGDistribution(Component):
    def setup(self, builder: Builder):
        self.randomness = builder.randomness.get_stream(self.name)
        self.exposure = builder.data.load(data_keys.LBWSG.EXPOSURE).set_index("sex")
        self.category_intervals = self._get_category_intervals(builder)

    def __call__(self, newborn_sex: pd.Series):
        categorical_exposure = self._sample_categorical_exposure(newborn_sex)
        continuous_exposure = self._sample_continuous_exposure(categorical_exposure)
        return continuous_exposure

    ############
    # Sampling #
    ############

    def _sample_categorical_exposure(self, newborn_sex: pd.Series):
        categorical_exposures = []
        for sex in newborn_sex.unique():
            group_data = newborn_sex[newborn_sex == sex]
            sex_exposure = self.exposure.loc[sex]
            categorical_exposures.append(
                self.randomness.choice(
                    group_data.index,
                    choices=sex_exposure.parameter.tolist(),
                    p=sex_exposure.value.tolist(),
                    additional_key="categorical_exposure",
                )
            )
        categorical_exposures = pd.concat(categorical_exposures).sort_index()
        return categorical_exposures

    def _sample_continuous_exposure(self, categorical_exposure: pd.Series):
        intervals = self.category_intervals.loc[categorical_exposure]
        intervals.index = categorical_exposure.index
        exposures = []
        for axis in ["birth_weight", "gestational_age"]:
            draw = self.randomness.get_draw(categorical_exposure.index, additional_key=axis)
            lower, upper = intervals[f"{axis}_lower"], intervals[f"{axis}_upper"]
            exposures.append((lower + (upper - lower) * draw).rename(axis))
        return pd.concat(exposures, axis=1)

    ################
    # Data loading #
    ################

    def _get_category_intervals(self, builder: Builder):
        categories = builder.data.load(data_keys.LBWSG.CATEGORIES)
        category_intervals = pd.DataFrame(
            data=[
                (category, *self._parse_description(description))
                for category, description in categories.items()
            ],
            columns=[
                "category",
                "birth_weight_lower",
                "birth_weight_upper",
                "gestational_age_lower",
                "gestational_age_upper",
            ],
        ).set_index("category")
        return category_intervals

    @staticmethod
    def _parse_description(description: str) -> Tuple:
        birth_weight = [
            float(val)
            for val in description.split(", [")[1].split(")")[0].split("]")[0].split(", ")
        ]
        gestational_age = [
            float(val)
            for val in description.split("- [")[1].split(")")[0].split("+")[0].split(", ")
        ]
        return *birth_weight, *gestational_age
