# Hausman Test — FE vs RE Specification

*Generated: 2026-04-11 02:14*

|    | outcome                  |   chi2_stat |        p_value |   df | preferred_model   |
|---:|:-------------------------|------------:|---------------:|-----:|:------------------|
|  0 | lcogs1_distance_km       |     0       |   1            |    1 | RE                |
|  1 | sao_per_100k             |   nan       | nan            |    0 | zero_variance     |
|  2 | surgical_volume_per_100k |   998.709   |   3.42606e-219 |    1 | FE                |
|  3 | pomr                     |    24.1942  |   8.70926e-07  |    1 | FE                |
|  4 | financial_risk_ratio     |  1199.28    |   8.74878e-263 |    1 | FE                |
|  5 | catastrophic_expenditure |     1.61771 |   0.203411     |    1 | RE                |
