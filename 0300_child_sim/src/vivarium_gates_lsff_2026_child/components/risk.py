"""
====================
Child Growth Failure
====================

Underweight exposure, modeled conditional on stunting and wasting, and the joint
child growth failure effect that applies all three risks to a single target.

.. note::

   These components are not currently enabled. They are commented out of
   ``model_specifications/model_spec.yaml`` and out of ``components/__init__.py``,
   so they are not importable through the package namespace and cannot be
   activated by uncommenting the specification alone.

   They have been migrated to the current vivarium interfaces but **have not been
   run**, because the data they need is not available: the ``WASTING``,
   ``STUNTING``, and ``UNDERWEIGHT`` key sets are commented out of
   :mod:`constants.data_keys`, so neither the loader nor the artifact carries
   their exposure and relative risk data. Re-enabling child growth failure means
   restoring those keys, building the artifact data, and then verifying these
   components against it -- treat the code below as unverified until that
   happens.

Notes on the migration
----------------------
The causal factor interfaces replaced several hooks these components used to
override. ``build_all_lookup_tables``, ``get_exposure_pipeline``,
``get_risk_exposure``, and ``get_target_modifier`` no longer exist; overriding
them is silent, since Python does not object to a method that overrides nothing.
Their replacements:

- Exposure is registered by ``register_exposure_pipeline`` as an *attribute*
  producer rather than a value producer, because effects read exposure through
  ``population_view.get`` rather than by calling a pipeline.
- Relative risk lookup tables are built by ``build_rr_lookup_table``.
- The relative risk is itself an attribute pipeline, and the base class registers
  that pipeline as the modifier of the target. A combined effect therefore
  produces the *product* of its constituent relative risks from
  ``get_relative_risk_source``, instead of multiplying the target in a bespoke
  ``adjust_target`` closure.

"""

import itertools
from typing import Any, Callable, Dict, Optional

import pandas as pd
from vivarium.engine.framework.engine import Builder
from vivarium.engine.framework.lookup import LookupTable
from vivarium.public_health.causal_factor.distributions import CausalFactorDistribution
from vivarium.public_health.causal_factor.utilities import get_exposure_post_processor
from vivarium.public_health.risks import Risk, RiskEffect
from vivarium.public_health.utilities import EntityString

from vivarium_gates_lsff_2026_child.components.distribution import CGFPolytomousDistribution
from vivarium_gates_lsff_2026_child.constants import data_keys, data_values


class ChildUnderweight(Risk):
    """Model underweight risk in children. We model underweight using probability distributions
    conditional on stunting and wasting exposure. Instead of using a standard exposure distribution,
    the expoure pipeline will determine which distribution to use separately for each joint stunting
    and wasting state."""

    def __init__(self):
        super().__init__("risk_factor.child_underweight")

    #################
    # Setup methods #
    #################

    # noinspection PyAttributeOutsideInit
    def setup(self, builder: Builder) -> None:
        super().setup(builder)
        self.distributions = self._get_distributions(builder)

    def get_distribution_type(self, builder: Builder) -> Optional[str]:
        """Opt out of the standard distribution machinery.

        Exposure comes from one distribution per joint stunting and wasting state,
        built in :meth:`_get_distributions`, so there is no single distribution
        type for this risk.
        """
        return None

    def get_exposure_distribution(
        self, builder: Builder
    ) -> Optional[CausalFactorDistribution]:
        """No single exposure distribution -- see :meth:`get_distribution_type`."""
        return None

    def register_exposure_pipeline(self, builder: Builder) -> None:
        """Register exposure as an attribute so effects can read it by name."""
        builder.value.register_attribute_producer(
            self.exposure_name,
            source=self.get_current_exposure,
            required_resources=[
                "age",
                "sex",
                self.propensity_name,
                data_values.PIPELINES.STUNTING_EXPOSURE,
                data_values.PIPELINES.WASTING_EXPOSURE,
            ],
            preferred_post_processor=get_exposure_post_processor(builder, self.name),
        )

    def _get_distributions(self, builder: Builder) -> Dict[str, CGFPolytomousDistribution]:
        """Store and setup distributions for each joint stunting and wasting state."""
        distributions = {}
        stunting_categories = [f"cat{i+1}" for i in range(4)]
        wasting_categories = [f"cat{i + 1}" for i in range(4)] + ["cat2.5"]
        all_distribution_data = builder.data.load(data_keys.UNDERWEIGHT.EXPOSURE)

        for stunting_cat, wasting_cat in itertools.product(
            stunting_categories, wasting_categories
        ):
            distribution_data = all_distribution_data[
                (all_distribution_data["stunting_parameter"] == stunting_cat)
                & (all_distribution_data["wasting_parameter"] == wasting_cat)
            ]
            distribution_data = distribution_data.drop(
                ["stunting_parameter", "wasting_parameter"], axis=1
            )

            wasting_cat = wasting_cat.replace(".", "")
            key = f"risk_factor.stunting_{stunting_cat}_wasting_{wasting_cat}_underweight"

            distributions[key] = CGFPolytomousDistribution(
                EntityString(key), distribution_data
            )
        for dist in distributions.values():
            dist.setup_component(builder)
        return distributions

    ##################################
    # Pipeline sources and modifiers #
    ##################################

    def get_current_exposure(self, index: pd.Index) -> pd.Series:
        """Calculate exposures separately for each joint stunting and wasting state and concatenate."""
        if len(index) == 0:
            return pd.Series(
                index=index
            )  # only happens on first time step when there's no simulants
        propensity = self.population_view.get(index, self.propensity_name).rename(
            "propensity"
        )
        wasting = self.population_view.get(
            index, data_values.PIPELINES.WASTING_EXPOSURE
        ).rename("wasting")
        stunting = self.population_view.get(
            index, data_values.PIPELINES.STUNTING_EXPOSURE
        ).rename("stunting")
        pop = pd.concat([stunting, wasting, propensity], axis=1)

        exposures = []
        for group, group_df in pop.groupby(["stunting", "wasting"]):
            stunting_category, wasting_category = group
            # update key to not include dot
            wasting_category = "cat25" if wasting_category == "cat2.5" else wasting_category
            distribution = self.distributions[
                f"risk_factor.stunting_{stunting_category}_wasting_{wasting_category}_underweight"
            ]
            exposure = distribution.ppf(group_df["propensity"])
            exposures.append(exposure)
        return pd.concat(exposures).sort_index()


class CGFRiskEffect(RiskEffect):
    """The combined effect of wasting, underweight, and stunting on one target.

    The base class registers the relative risk pipeline as the modifier of the
    target, so this class supplies a relative risk that is the product across the
    three child growth failure risks rather than modifying the target directly.
    """

    @property
    def configuration_defaults(self) -> Dict[str, Any]:

        sub_risk_configs = {
            risk: {
                "data_sources": {
                    "relative_risk": f"{risk}.relative_risk",
                },
                "data_source_parameters": {
                    "relative_risk": {},
                },
            }
            for risk in self.cgf_models
        }

        config = {
            self.name: {
                "sub_risks": sub_risk_configs,
                "data_sources": {
                    "population_attributable_fraction": f"{self.risk}.population_attributable_fraction",
                },
            },
        }
        return config

    def __init__(self, target: str):
        """
        Parameters
        ----------
        target :
            Type, name, and target rate of entity to be affected by risk factor,
            supplied in the form "entity_type.entity_name.measure"
            where entity_type should be singular (e.g., cause instead of causes).
        """
        super().__init__("risk_factor.child_growth_failure", target)
        self.cgf_models = [
            EntityString(f"risk_factor.{risk}")
            for risk in [
                data_keys.WASTING.name,
                data_keys.UNDERWEIGHT.name,
                data_keys.STUNTING.name,
            ]
        ]
        # This is to access to the distribution type before setup
        self._exposure_distribution_type = "ordered_polytomous"

    def get_distribution_type(self, builder: Builder) -> str:
        """Report the shared sub-risk distribution type.

        The base implementation looks up an exposure component named for the
        causal factor, but 'child_growth_failure' is an aggregate with no exposure
        component of its own -- the three sub-risks carry the exposures.
        """
        return self._exposure_distribution_type

    def build_rr_lookup_table(self, builder: Builder) -> Optional[LookupTable]:
        """Build one relative risk table per sub-risk.

        Returns ``None`` because there is no single combined table;
        :meth:`get_relative_risk_source` reads the per-risk tables instead.
        """
        # noinspection PyAttributeOutsideInit
        self.sub_risk_relative_risk_tables: Dict[EntityString, LookupTable] = {}
        for risk in self.cgf_models:
            rr_data = self.load_relative_risk(builder, self.configuration.sub_risks[risk])
            rr_value_columns = None
            if self.is_exposure_categorical:
                rr_data, rr_value_columns = self.process_categorical_data(builder, rr_data)
            self.sub_risk_relative_risk_tables[risk] = self.build_lookup_table(
                builder,
                f"{risk.name}_relative_risk",
                data_source=rr_data,
                value_columns=rr_value_columns,
            )
        return None

    def get_relative_risk_source(self, builder: Builder) -> Callable[[pd.Index], pd.Series]:
        """Return the product of the relative risks of the three sub-risks."""

        def generate_relative_risk(index: pd.Index) -> pd.Series:
            combined = pd.Series(1.0, index=index)
            for risk in self.cgf_models:
                index_columns = ["index", risk.name]
                rr = self.sub_risk_relative_risk_tables[risk](index)
                exposure = self.population_view.get(
                    index, f"{risk.name}.exposure"
                ).reset_index()
                exposure.columns = index_columns
                exposure = exposure.set_index(index_columns)

                relative_risk = rr.stack().reset_index()
                relative_risk.columns = index_columns + ["value"]
                relative_risk = relative_risk.set_index(index_columns)

                effect = relative_risk.loc[exposure.index, "value"].droplevel(risk.name)
                combined *= effect
            return combined

        return generate_relative_risk

    def register_relative_risk_pipeline(self, builder: Builder) -> None:
        """Register the combined relative risk, which needs every sub-risk exposure."""
        builder.value.register_attribute_producer(
            self.relative_risk_name,
            self._relative_risk_source,
            required_resources=[f"{risk.name}.exposure" for risk in self.cgf_models],
        )
