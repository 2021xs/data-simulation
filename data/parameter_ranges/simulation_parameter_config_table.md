# Simulation Parameter Config Table

| parameter | symbol | source_field | main_range | extended_range | stress_range | typical_value | default_sampling | note |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| b_hz | b | registered_frequency_offset_hz | [3179.0, 3728.0] Hz | [1980.0, 4692.0] Hz | [1980.0, 4692.0] Hz | 3365.000 Hz | uniform | main_range沿用上一版accepted IQR推荐；borderline把上端扩展到4692 Hz，stress_range为Top10全范围。该量只表示registered offset / effective constant frequency bias。 |
| k_hz_per_s | k | linear_slope_hz_per_s | [-1.110156, -0.197808] Hz/s | [-4.052513, 4.037490] Hz/s | [-4.052513, 4.037490] Hz/s | -0.768749 Hz/s | scenario_based_or_uniform | k分布不对称；main_range保留accepted负漂移核心，accepted中的8733468正向强漂移进入extended/stress检查，不建议只看mean。 |
| sigma_hz | sigma | detrended_std_hz | [23.215, 32.890] Hz | [10.917, 55.951] Hz | [10.917, 84.073] Hz | 30.882 Hz | uniform_or_fixed_median | sigma可作为第一版Gaussian noise尺度近似；borderline/rejected显示高噪声端可明显扩大，后续仍应保留相关噪声或model error扩展。 |
