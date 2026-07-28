from typing import Optional

import pandas as pd
from vivarium.config_tree import ConfigTree as LayeredConfigTree
from vivarium.framework.engine import Builder
from vivarium_public_health.risks.distributions import PolytomousDistribution
from vivarium_public_health.utilities import EntityString


class CGFPolytomousDistribution(PolytomousDistribution):
    def __init__(self, risk: EntityString, exposure_data: pd.DataFrame):
        super().__init__(risk, "ordered_polytomous", exposure_data)

    def get_configuration(self, builder: "Builder") -> Optional[LayeredConfigTree]:
        pass
