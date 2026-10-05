# Diagnosis model report

Training rows: 114793 (random cities). Validation: 24059. Held-out cities: 23730. Station Road (never trained on): 15429.

## Summary

| version   | data            |   rows |   accuracy |   macro F1 |   calibration error |   >=90% sure: share |   >=90% sure: accuracy |
|:----------|:----------------|-------:|-----------:|-----------:|--------------------:|--------------------:|-----------------------:|
| plain     | validation      |  24059 |      0.953 |      0.936 |               0.016 |                0.83 |                  0.992 |
| plain     | held-out cities |  23730 |      0.945 |      0.927 |               0.015 |                0.81 |                  0.989 |
| plain     | Station Road    |  15429 |      0.896 |      0.873 |               0.018 |                0.66 |                  0.987 |
| plain+lwm | validation      |  24059 |      0.957 |      0.941 |               0.018 |                0.84 |                  0.993 |
| plain+lwm | held-out cities |  23730 |      0.951 |      0.936 |               0.019 |                0.81 |                  0.993 |
| plain+lwm | Station Road    |  15429 |      0.902 |      0.882 |               0.023 |                0.66 |                  0.985 |
| lwm_only  | validation      |  24059 |      0.607 |      0.324 |               0.01  |                0.08 |                  0.971 |
| lwm_only  | held-out cities |  23730 |      0.603 |      0.316 |               0.008 |                0.07 |                  0.956 |
| lwm_only  | Station Road    |  15429 |      0.546 |      0.289 |               0.036 |                0.07 |                  0.934 |

Version used by the agent: **plain+lwm** (LWM is part of the design; the others are comparisons).

## plain on held-out cities

|              |   precision |   recall |    f1 |   count |
|:-------------|------------:|---------:|------:|--------:|
| none         |       0.966 |    0.974 | 0.97  |   12751 |
| blockage     |       0.869 |    0.881 | 0.875 |    2127 |
| wrong_beam   |       0.924 |    0.92  | 0.922 |    1396 |
| interference |       0.909 |    0.887 | 0.898 |    4438 |
| congestion   |       0.972 |    0.965 | 0.969 |    3018 |

|                   |   said none |   said blockage |   said wrong_beam |   said interference |   said congestion |
|:------------------|------------:|----------------:|------------------:|--------------------:|------------------:|
| true none         |       12416 |              56 |                25 |                 198 |                56 |
| true blockage     |          91 |            1874 |                29 |                 108 |                25 |
| true wrong_beam   |          36 |              13 |              1284 |                  63 |                 0 |
| true interference |         251 |             205 |                45 |                3935 |                 2 |
| true congestion   |          65 |               8 |                 7 |                  26 |              2912 |

## plain on Station Road

|              |   precision |   recall |    f1 |   count |
|:-------------|------------:|---------:|------:|--------:|
| none         |       0.933 |    0.937 | 0.935 |    7522 |
| blockage     |       0.871 |    0.812 | 0.84  |    1544 |
| wrong_beam   |       0.833 |    0.807 | 0.82  |     981 |
| interference |       0.826 |    0.865 | 0.845 |    3692 |
| congestion   |       0.946 |    0.909 | 0.927 |    1690 |

|                   |   said none |   said blockage |   said wrong_beam |   said interference |   said congestion |
|:------------------|------------:|----------------:|------------------:|--------------------:|------------------:|
| true none         |        7046 |              66 |                21 |                 313 |                76 |
| true blockage     |          90 |            1253 |                24 |                 170 |                 7 |
| true wrong_beam   |          49 |              22 |               792 |                 118 |                 0 |
| true interference |         294 |              86 |               114 |                3193 |                 5 |
| true congestion   |          71 |              11 |                 0 |                  72 |              1536 |

## plain+lwm on held-out cities

|              |   precision |   recall |    f1 |   count |
|:-------------|------------:|---------:|------:|--------:|
| none         |       0.966 |    0.975 | 0.97  |   12751 |
| blockage     |       0.926 |    0.887 | 0.906 |    2127 |
| wrong_beam   |       0.929 |    0.913 | 0.921 |    1396 |
| interference |       0.912 |    0.919 | 0.916 |    4438 |
| congestion   |       0.974 |    0.961 | 0.967 |    3018 |

|                   |   said none |   said blockage |   said wrong_beam |   said interference |   said congestion |
|:------------------|------------:|----------------:|------------------:|--------------------:|------------------:|
| true none         |       12427 |              54 |                21 |                 201 |                48 |
| true blockage     |          96 |            1887 |                32 |                  87 |                25 |
| true wrong_beam   |          38 |              11 |              1274 |                  72 |                 1 |
| true interference |         240 |              81 |                34 |                4079 |                 4 |
| true congestion   |          69 |               5 |                11 |                  32 |              2901 |

## plain+lwm on Station Road

|              |   precision |   recall |    f1 |   count |
|:-------------|------------:|---------:|------:|--------:|
| none         |       0.933 |    0.939 | 0.936 |    7522 |
| blockage     |       0.892 |    0.808 | 0.848 |    1544 |
| wrong_beam   |       0.861 |    0.807 | 0.833 |     981 |
| interference |       0.831 |    0.888 | 0.859 |    3692 |
| congestion   |       0.963 |    0.908 | 0.935 |    1690 |

|                   |   said none |   said blockage |   said wrong_beam |   said interference |   said congestion |
|:------------------|------------:|----------------:|------------------:|--------------------:|------------------:|
| true none         |        7064 |              68 |                21 |                 312 |                57 |
| true blockage     |         102 |            1247 |                26 |                 167 |                 2 |
| true wrong_beam   |          53 |              16 |               792 |                 120 |                 0 |
| true interference |         275 |              56 |                81 |                3280 |                 0 |
| true congestion   |          75 |              11 |                 0 |                  70 |              1534 |

## lwm_only on held-out cities

|              |   precision |   recall |    f1 |   count |
|:-------------|------------:|---------:|------:|--------:|
| none         |       0.576 |    0.989 | 0.729 |   12751 |
| blockage     |       0.92  |    0.791 | 0.851 |    2127 |
| wrong_beam   |       0     |    0     | 0     |    1396 |
| interference |       0.267 |    0.001 | 0.002 |    4438 |
| congestion   |       0     |    0     | 0     |    3018 |

|                   |   said none |   said blockage |   said wrong_beam |   said interference |   said congestion |
|:------------------|------------:|----------------:|------------------:|--------------------:|------------------:|
| true none         |       12616 |             132 |                 0 |                   3 |                 0 |
| true blockage     |         439 |            1683 |                 0 |                   5 |                 0 |
| true wrong_beam   |        1396 |               0 |                 0 |                   0 |                 0 |
| true interference |        4418 |              15 |                 1 |                   4 |                 0 |
| true congestion   |        3015 |               0 |                 0 |                   3 |                 0 |

## lwm_only on Station Road

|              |   precision |   recall |    f1 |   count |
|:-------------|------------:|---------:|------:|--------:|
| none         |       0.519 |    0.982 | 0.679 |    7522 |
| blockage     |       0.887 |    0.674 | 0.766 |    1544 |
| wrong_beam   |       0     |    0     | 0     |     981 |
| interference |       0.154 |    0.001 | 0.001 |    3692 |
| congestion   |       0     |    0     | 0     |    1690 |

|                   |   said none |   said blockage |   said wrong_beam |   said interference |   said congestion |
|:------------------|------------:|----------------:|------------------:|--------------------:|------------------:|
| true none         |        7389 |             126 |                 0 |                   7 |                 0 |
| true blockage     |         500 |            1040 |                 0 |                   4 |                 0 |
| true wrong_beam   |         981 |               0 |                 0 |                   0 |                 0 |
| true interference |        3684 |               6 |                 0 |                   2 |                 0 |
| true congestion   |        1690 |               0 |                 0 |                   0 |                 0 |
