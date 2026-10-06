# Evaluation: six scenarios, five methods

Station Road, 8 seeds per scenario (phone positions and details vary by seed). Problems start at second 10; each run lasts 60 s. Scored against the simulator's hidden truth: a phone is degraded when its true clarity is 4 dB below its own normal and below 13 dB, or it gets under 80% of the data it wants.

- **degraded phone-s**: phones degraded x seconds while the problem lasts (lower is better)
- **after it ends**: degraded phone-seconds once a temporary cause (the bus) has gone; leftover changes that are never withdrawn show up here
- **made worse**: phone-seconds degraded under this method but not under the network alone
- **safety breaks**: an independent audit of limits and the protected hospital zone
- **asked a person**: escalations, including approval requests (a simulated operator approves after 5 s)

![timeline](eval_timeline.png)

## Normal operation

| method            |   degraded phone-s | recovered   |   median recovery s |   still degraded at end |   after it ends (phone-s) |   made worse (phone-s) |   changes made |   safety breaks |   decision ms (max) |   undone |   asked a person |   false alarms | diagnosis right   |
|:------------------|-------------------:|:------------|--------------------:|------------------------:|--------------------------:|-----------------------:|---------------:|----------------:|--------------------:|---------:|-----------------:|---------------:|:------------------|
| No action at all  |                0   | 100%        |                   0 |                       0 |                         0 |                      0 |              0 |               0 |                   0 |      nan |              nan |            nan | nan               |
| Network alone     |                0.1 | 100%        |                   0 |                       0 |                         0 |                      0 |              0 |               0 |                   0 |      nan |              nan |            nan | nan               |
| Simple rule fixer |                0.1 | 100%        |                   0 |                       0 |                         0 |                      0 |              0 |               0 |                   7 |      nan |              nan |            nan | nan               |
| Agent, no twin    |                0.1 | 100%        |                   0 |                       0 |                         0 |                      0 |              0 |               0 |                   2 |        0 |                0 |              0 | 100%              |
| Agent (full)      |                0.1 | 100%        |                   0 |                       0 |                         0 |                      0 |              0 |               0 |                   3 |        0 |                0 |              0 | 100%              |

## Moving blocker on a street

| method            |   degraded phone-s | recovered   |   median recovery s |   still degraded at end |   after it ends (phone-s) |   made worse (phone-s) |   changes made |   safety breaks |   decision ms (max) |   undone |   asked a person |   false alarms | diagnosis right   |   twin error dB |
|:------------------|-------------------:|:------------|--------------------:|------------------------:|--------------------------:|-----------------------:|---------------:|----------------:|--------------------:|---------:|-----------------:|---------------:|:------------------|----------------:|
| No action at all  |              327   | 0%          |               nan   |                    12.2 |                       0   |                  115.6 |            0   |               0 |                   0 |    nan   |            nan   |          nan   | nan               |           nan   |
| Network alone     |              221   | 38%         |                 7   |                     7.9 |                      18.5 |                    0   |            0   |               0 |                   0 |    nan   |            nan   |          nan   | nan               |           nan   |
| Simple rule fixer |               75.6 | 75%         |                 5.5 |                     2   |                      91   |                  120.6 |           26.2 |               0 |                  71 |    nan   |            nan   |          nan   | nan               |           nan   |
| Agent, no twin    |              109.8 | 62%         |                 7   |                     3   |                      11   |                   39.6 |            8.1 |               0 |                 179 |      4.1 |              0.9 |            0.2 | 88%               |           nan   |
| Agent (full)      |               98.1 | 62%         |                 7   |                     2.4 |                      20.2 |                   26.6 |            2.1 |               0 |                 336 |      0.6 |              3.6 |            0.2 | 88%               |             4.9 |

## Suboptimal serving beam

| method            |   degraded phone-s | recovered   |   median recovery s |   still degraded at end |   after it ends (phone-s) |   made worse (phone-s) |   changes made |   safety breaks |   decision ms (max) |   undone |   asked a person |   false alarms | diagnosis right   |   twin error dB |
|:------------------|-------------------:|:------------|--------------------:|------------------------:|--------------------------:|-----------------------:|---------------:|----------------:|--------------------:|---------:|-----------------:|---------------:|:------------------|----------------:|
| No action at all  |              411.5 | 0%          |                 nan |                     8.2 |                         0 |                    0.2 |            0   |               0 |                   0 |    nan   |            nan   |          nan   | nan               |           nan   |
| Network alone     |              418.2 | 0%          |                 nan |                     8.2 |                         0 |                    0   |            0   |               0 |                   0 |    nan   |            nan   |          nan   | nan               |           nan   |
| Simple rule fixer |              130.8 | 100%        |                  15 |                     0.2 |                         0 |                   25   |            9.8 |               3 |                   2 |    nan   |            nan   |          nan   | nan               |           nan   |
| Agent, no twin    |               74.9 | 88%         |                   5 |                     0.9 |                         0 |                    0   |            3   |               1 |                 257 |      1.2 |              1   |            0   | 100%              |           nan   |
| Agent (full)      |               31.8 | 100%        |                   5 |                     0.1 |                         0 |                    0   |            1.9 |               0 |                 443 |      0   |              0.5 |            0.1 | 100%              |             2.6 |

## Twin mismatch

| method            |   degraded phone-s | recovered   |   median recovery s |   still degraded at end |   after it ends (phone-s) |   made worse (phone-s) |   changes made |   safety breaks |   decision ms (max) |   undone |   asked a person |   false alarms | diagnosis right   |   twin error dB |
|:------------------|-------------------:|:------------|--------------------:|------------------------:|--------------------------:|-----------------------:|---------------:|----------------:|--------------------:|---------:|-----------------:|---------------:|:------------------|----------------:|
| No action at all  |              327   | 0%          |                 nan |                    12.2 |                       0   |                    0.6 |            0   |               0 |                   0 |    nan   |            nan   |          nan   | nan               |           nan   |
| Network alone     |              326.4 | 0%          |                 nan |                    12.2 |                       0.1 |                    0   |            0   |               0 |                   0 |    nan   |            nan   |          nan   | nan               |           nan   |
| Simple rule fixer |              120.9 | 50%         |                   7 |                     3.2 |                      78.4 |                  109.8 |           21   |               0 |                  24 |    nan   |            nan   |          nan   | nan               |           nan   |
| Agent, no twin    |              138.5 | 75%         |                   8 |                     3.9 |                      35   |                   96.8 |            9.1 |               0 |                 224 |      4.5 |              2.4 |            0.4 | 100%              |           nan   |
| Agent (full)      |              111.9 | 88%         |                  10 |                     2.6 |                      16.9 |                   58   |            3.5 |               0 |                 374 |      1.1 |              2.1 |            0   | 100%              |            10.7 |

## Conflicting objectives (hospital zone)

| method            |   degraded phone-s | recovered   |   median recovery s |   still degraded at end |   after it ends (phone-s) |   made worse (phone-s) |   changes made |   safety breaks |   decision ms (max) |   undone |   asked a person |   false alarms | diagnosis right   |   twin error dB |
|:------------------|-------------------:|:------------|--------------------:|------------------------:|--------------------------:|-----------------------:|---------------:|----------------:|--------------------:|---------:|-----------------:|---------------:|:------------------|----------------:|
| No action at all  |              327   | 0%          |               nan   |                    12.2 |                       0   |                    0.6 |              0 |               0 |                   0 |    nan   |            nan   |            nan | nan               |           nan   |
| Network alone     |              326.4 | 0%          |               nan   |                    12.2 |                       0.1 |                    0   |              0 |               0 |                   0 |    nan   |            nan   |            nan | nan               |           nan   |
| Simple rule fixer |               82.2 | 75%         |                 6   |                     2.2 |                      87.4 |                  152.1 |             27 |              24 |                   3 |    nan   |            nan   |            nan | nan               |           nan   |
| Agent, no twin    |              252.5 | 25%         |                 8   |                     9.1 |                       5.4 |                   39.2 |             10 |               5 |                 223 |      5.9 |              2.1 |              0 | 100%              |           nan   |
| Agent (full)      |              236.5 | 25%         |                 8.5 |                     8.2 |                       0.1 |                   26   |              2 |               0 |                 423 |      1.5 |              2.9 |              0 | 100%              |             9.9 |

## Faulty and stale data

| method            |   degraded phone-s | recovered   |   median recovery s |   still degraded at end |   after it ends (phone-s) |   made worse (phone-s) |   changes made |   safety breaks |   decision ms (max) |   undone |   asked a person |   false alarms | diagnosis right   |   twin error dB |
|:------------------|-------------------:|:------------|--------------------:|------------------------:|--------------------------:|-----------------------:|---------------:|----------------:|--------------------:|---------:|-----------------:|---------------:|:------------------|----------------:|
| No action at all  |              607.1 | 0%          |                 nan |                    12.2 |                         0 |                  271.2 |            0   |               0 |                   0 |    nan   |            nan   |          nan   | nan               |           nan   |
| Network alone     |              754.2 | 0%          |                 nan |                    15.6 |                         0 |                    0   |            0   |               0 |                   0 |    nan   |            nan   |          nan   | nan               |           nan   |
| Simple rule fixer |              733.8 | 0%          |                 nan |                    15.4 |                         0 |                   10.1 |            1.4 |               1 |                   2 |    nan   |            nan   |          nan   | nan               |           nan   |
| Agent, no twin    |              791.8 | 0%          |                 nan |                    17.5 |                         0 |                  104.1 |            8   |               4 |                 345 |      5.9 |              4.5 |            0   | 100%              |           nan   |
| Agent (full)      |              568   | 25%         |                  28 |                    10.4 |                         0 |                   32.2 |            1.4 |               0 |                 647 |      0.9 |              3.1 |            0.2 | 100%              |             3.5 |
