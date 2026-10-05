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
| Simple rule fixer |                0.1 | 100%        |                   0 |                       0 |                         0 |                      0 |              0 |               0 |                   1 |      nan |              nan |            nan | nan               |
| Agent, no twin    |                0.1 | 100%        |                   0 |                       0 |                         0 |                      0 |              0 |               0 |                   1 |        0 |                0 |              0 | 100%              |
| Agent (full)      |                0.1 | 100%        |                   0 |                       0 |                         0 |                      0 |              0 |               0 |                   1 |        0 |                0 |              0 | 100%              |

## Moving blocker on a street

| method            |   degraded phone-s | recovered   |   median recovery s |   still degraded at end |   after it ends (phone-s) |   made worse (phone-s) |   changes made |   safety breaks |   decision ms (max) |   undone |   asked a person |   false alarms | diagnosis right   |   twin error dB |
|:------------------|-------------------:|:------------|--------------------:|------------------------:|--------------------------:|-----------------------:|---------------:|----------------:|--------------------:|---------:|-----------------:|---------------:|:------------------|----------------:|
| No action at all  |              327   | 0%          |               nan   |                    12.2 |                       0   |                  115.6 |            0   |               0 |                   0 |    nan   |            nan   |          nan   | nan               |           nan   |
| Network alone     |              221   | 38%         |                 7   |                     7.9 |                      18.5 |                    0   |            0   |               0 |                   0 |    nan   |            nan   |          nan   | nan               |           nan   |
| Simple rule fixer |               75.6 | 75%         |                 5.5 |                     2   |                      91   |                  120.6 |           26.2 |               0 |                   7 |    nan   |            nan   |          nan   | nan               |           nan   |
| Agent, no twin    |              114.4 | 62%         |                 7   |                     3.9 |                      24.4 |                   70.6 |            8.1 |               0 |                 281 |      4.5 |              1.1 |            0.4 | 88%               |           nan   |
| Agent (full)      |               98.1 | 62%         |                 7   |                     2.4 |                      21.6 |                   28   |            2   |               0 |                 409 |      0.6 |              3.6 |            0.4 | 88%               |             4.9 |

## Suboptimal serving beam

| method            |   degraded phone-s | recovered   |   median recovery s |   still degraded at end |   after it ends (phone-s) |   made worse (phone-s) |   changes made |   safety breaks |   decision ms (max) |   undone |   asked a person |   false alarms | diagnosis right   |   twin error dB |
|:------------------|-------------------:|:------------|--------------------:|------------------------:|--------------------------:|-----------------------:|---------------:|----------------:|--------------------:|---------:|-----------------:|---------------:|:------------------|----------------:|
| No action at all  |              411.5 | 0%          |                 nan |                     8.2 |                         0 |                    0.2 |            0   |               0 |                   0 |    nan   |            nan   |          nan   | nan               |           nan   |
| Network alone     |              418.2 | 0%          |                 nan |                     8.2 |                         0 |                    0   |            0   |               0 |                   0 |    nan   |            nan   |          nan   | nan               |           nan   |
| Simple rule fixer |              130.8 | 100%        |                  15 |                     0.2 |                         0 |                   25   |            9.8 |               3 |                   1 |    nan   |            nan   |          nan   | nan               |           nan   |
| Agent, no twin    |               97.6 | 88%         |                   5 |                     1.1 |                         0 |                    7.9 |            4.2 |               2 |                 532 |      1.9 |              0.5 |            0   | 100%              |           nan   |
| Agent (full)      |               34.2 | 100%        |                   5 |                     0.2 |                         0 |                    0   |            1.8 |               0 |                 479 |      0   |              0.4 |            0.2 | 100%              |             2.9 |

## Twin mismatch

| method            |   degraded phone-s | recovered   |   median recovery s |   still degraded at end |   after it ends (phone-s) |   made worse (phone-s) |   changes made |   safety breaks |   decision ms (max) |   undone |   asked a person |   false alarms | diagnosis right   |   twin error dB |
|:------------------|-------------------:|:------------|--------------------:|------------------------:|--------------------------:|-----------------------:|---------------:|----------------:|--------------------:|---------:|-----------------:|---------------:|:------------------|----------------:|
| No action at all  |              327   | 0%          |                 nan |                    12.2 |                       0   |                    0.6 |            0   |               0 |                   0 |    nan   |            nan   |          nan   | nan               |           nan   |
| Network alone     |              326.4 | 0%          |                 nan |                    12.2 |                       0.1 |                    0   |            0   |               0 |                   0 |    nan   |            nan   |          nan   | nan               |           nan   |
| Simple rule fixer |              120.9 | 50%         |                   7 |                     3.2 |                      78.4 |                  109.8 |           21   |               0 |                   1 |    nan   |            nan   |          nan   | nan               |           nan   |
| Agent, no twin    |              138.5 | 75%         |                   8 |                     3.9 |                      28.8 |                   90.9 |            9   |               0 |                 375 |      5.2 |              2.9 |            0.2 | 100%              |           nan   |
| Agent (full)      |               97.8 | 88%         |                  10 |                     1.6 |                      16.2 |                   56.2 |            3.6 |               0 |                 483 |      1.1 |              2.2 |            0   | 100%              |            10.8 |

## Conflicting objectives (hospital zone)

| method            |   degraded phone-s | recovered   |   median recovery s |   still degraded at end |   after it ends (phone-s) |   made worse (phone-s) |   changes made |   safety breaks |   decision ms (max) |   undone |   asked a person |   false alarms | diagnosis right   |   twin error dB |
|:------------------|-------------------:|:------------|--------------------:|------------------------:|--------------------------:|-----------------------:|---------------:|----------------:|--------------------:|---------:|-----------------:|---------------:|:------------------|----------------:|
| No action at all  |              327   | 0%          |               nan   |                    12.2 |                       0   |                    0.6 |            0   |               0 |                   0 |    nan   |            nan   |          nan   | nan               |           nan   |
| Network alone     |              326.4 | 0%          |               nan   |                    12.2 |                       0.1 |                    0   |            0   |               0 |                   0 |    nan   |            nan   |          nan   | nan               |           nan   |
| Simple rule fixer |               82.2 | 75%         |                 6   |                     2.2 |                      87.4 |                  152.1 |           27   |              24 |                   1 |    nan   |            nan   |          nan   | nan               |           nan   |
| Agent, no twin    |              247.5 | 25%         |                 8   |                     8.8 |                       7.8 |                   29.2 |            7.2 |               5 |                 494 |      4.8 |              2.5 |            0.1 | 100%              |           nan   |
| Agent (full)      |              236.5 | 25%         |                 8.5 |                     8.2 |                       0.1 |                   26   |            2   |               0 |                 519 |      1.5 |              2.9 |            0   | 100%              |             9.9 |

## Faulty and stale data

| method            |   degraded phone-s | recovered   |   median recovery s |   still degraded at end |   after it ends (phone-s) |   made worse (phone-s) |   changes made |   safety breaks |   decision ms (max) |   undone |   asked a person |   false alarms | diagnosis right   |   twin error dB |
|:------------------|-------------------:|:------------|--------------------:|------------------------:|--------------------------:|-----------------------:|---------------:|----------------:|--------------------:|---------:|-----------------:|---------------:|:------------------|----------------:|
| No action at all  |              607.1 | 0%          |                 nan |                    12.2 |                         0 |                  271.2 |            0   |               0 |                   0 |    nan   |            nan   |          nan   | nan               |             nan |
| Network alone     |              754.2 | 0%          |                 nan |                    15.6 |                         0 |                    0   |            0   |               0 |                   0 |    nan   |            nan   |          nan   | nan               |             nan |
| Simple rule fixer |              733.8 | 0%          |                 nan |                    15.4 |                         0 |                   10.1 |            1.4 |               1 |                   1 |    nan   |            nan   |          nan   | nan               |             nan |
| Agent, no twin    |              784.8 | 0%          |                 nan |                    17.1 |                         0 |                  106.6 |            8.1 |               4 |                 618 |      5.9 |              4   |            0   | 100%              |             nan |
| Agent (full)      |              568   | 25%         |                  28 |                    10.4 |                         0 |                   32.2 |            1.1 |               0 |                 670 |      0.6 |              3.5 |            0.5 | 100%              |               4 |
