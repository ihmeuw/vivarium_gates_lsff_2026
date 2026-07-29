from typing import Union

from vivarium.artifact import EntityKey
from vivarium.gbd_mapping import ModelableEntity, causes, covariates, risk_factors


def get_entity(key: Union[str, EntityKey]) -> ModelableEntity:
    key = EntityKey(key)
    # Map of entity types to their gbd mappings.
    type_map = {
        "cause": causes,
        "covariate": covariates,
        "risk_factor": risk_factors,
    }
    return type_map[key.type][key.name]
