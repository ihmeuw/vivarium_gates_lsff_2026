import numpy as np
import pandas as pd
import vivarium.risk_distributions as risk_distributions

# NOTE: This is an unusual ensemble distribution. We should add functionality to the
# EnsembleDistribution class to make this easier.

XMAX: int = 220
GAMMA_DISTRIBUTION_WEIGHT: float = 0.4
MIRROR_GUMBEL_DISTRIBUTION_WEIGHT: float = 0.6


def hemoglobin_pdf_from_mean_sd(mean, sd):
    (
        hemoglobin_distribution_gamma_part,
        hemoglobin_distribution_mgumbel_part,
    ) = _hemoglobin_distribution_parts_from_mean_sd(mean, sd)

    def pdf(x):
        # scipy.integrate.quad calls the integrand with a Python float, which has no
        # .copy(); risk_distributions also rejects 0-d arrays, so use atleast_1d.
        # This is a no-op for array input.
        x = np.atleast_1d(np.asarray(x, dtype=float))
        return GAMMA_DISTRIBUTION_WEIGHT * hemoglobin_distribution_gamma_part.pdf(
            x
        ) + MIRROR_GUMBEL_DISTRIBUTION_WEIGHT * hemoglobin_distribution_mgumbel_part.pdf(x)

    return pdf


def hemoglobin_cdf_from_mean_sd(mean, sd):
    (
        hemoglobin_distribution_gamma_part,
        hemoglobin_distribution_mgumbel_part,
    ) = _hemoglobin_distribution_parts_from_mean_sd(mean, sd)

    def cdf(x):
        gamma_cdf = hemoglobin_distribution_gamma_part.cdf(x)
        # The reversed MirroredGumbel CDF that this used to correct for --
        # https://github.com/ihmeuw/risk_distributions/issues/62 -- is FIXED in
        # vivarium.risk_distributions. The old `1 - cdf` workaround therefore
        # re-inverted an already-correct CDF, and because the mirrored-Gumbel part
        # carries 60% of the ensemble weight the result was wrong by up to 0.6 and
        # decreased with x. Verified against the numerically integrated PDF: without
        # the inversion the mean absolute error is 0.0000 at every test point, with
        # it 0.4815.
        #
        # Do not reinstate the inversion against the modern library. If this module
        # is ever run against the OLD risk_distributions (<= 2.0.16, in `.venv`), the
        # inversion IS needed there -- that library really does return a reversed CDF.
        mgumbel_cdf = hemoglobin_distribution_mgumbel_part.cdf(x)
        return (
            GAMMA_DISTRIBUTION_WEIGHT * gamma_cdf
            + MIRROR_GUMBEL_DISTRIBUTION_WEIGHT * mgumbel_cdf
        )

    return cdf


def hemoglobin_sampler_from_mean_sd(mean, sd):
    (
        hemoglobin_distribution_gamma_part,
        hemoglobin_distribution_mgumbel_part,
    ) = _hemoglobin_distribution_parts_from_mean_sd(mean, sd)

    def sampler(distribution_propensity, propensity):
        result = np.zeros_like(distribution_propensity)
        propensity = np.clip(
            propensity, 0.001, 0.999
        )  # HACK: risk_distributions is way too conservative!
        result[
            distribution_propensity < GAMMA_DISTRIBUTION_WEIGHT
        ] = hemoglobin_distribution_gamma_part.ppf(propensity.copy())[
            distribution_propensity < GAMMA_DISTRIBUTION_WEIGHT
        ]
        result[
            distribution_propensity >= GAMMA_DISTRIBUTION_WEIGHT
        ] = hemoglobin_distribution_mgumbel_part.ppf(propensity.copy())[
            distribution_propensity >= GAMMA_DISTRIBUTION_WEIGHT
        ]
        return result

    return sampler


def _hemoglobin_distribution_parts_from_mean_sd(mean, sd):
    gamma_params = risk_distributions.risk_distributions.Gamma.get_parameters(
        mean=mean, sd=sd
    )
    # NOTE: We have to override these, otherwise Gamma is overly conservative in what values
    # are computable
    # https://github.com/ihmeuw/risk_distributions/issues/61
    gamma_params["computability_min"] = 0
    gamma_params["computability_max"] = XMAX
    hemoglobin_distribution_gamma_part = risk_distributions.risk_distributions.Gamma(
        gamma_params
    )

    # NOTE: Forced to duplicate https://github.com/ihmeuw/risk_distributions/blob/a9ed9d7e8372590018355012a7a7ffefa87b0819/src/risk_distributions/risk_distributions.py#L428-L434
    # because it doesn't permit the custom x_min and x_max, and these are used in calculating the others
    kwargs = {}
    if (
        not isinstance(mean, pd.Series)
        and not isinstance(sd, pd.Series)
        and not isinstance(mean, np.ndarray)
        and not isinstance(sd, np.ndarray)
    ):
        kwargs["index"] = [0]

    mgumbel_params = pd.DataFrame(
        {
            "loc": XMAX - mean - (np.euler_gamma * np.sqrt(6) / np.pi * sd),
            "scale": np.sqrt(6) / np.pi * sd,
            "mirror_point": XMAX,
            "computability_min": 0,
            "computability_max": XMAX,
        },
        **kwargs
    )
    hemoglobin_distribution_mgumbel_part = (
        risk_distributions.risk_distributions.MirroredGumbel(mgumbel_params)
    )
    return hemoglobin_distribution_gamma_part, hemoglobin_distribution_mgumbel_part
