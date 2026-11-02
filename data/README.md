# Data

All data in this repository comes from public sources or is synthetic. No confidential or employer data is used.

## Folders

- `base/` Real public contracts from [SEC EDGAR](https://www.sec.gov/edgar) exhibits and [CUAD](https://www.atticusprojectai.org/cuad), used as starting text.
- `synthetic/` Contract versions built from a base contract with a fictional counterparty name, simulating a negotiation history over time. Some versions contain planted drifts for evaluation.
- `answer_keys/` The correct value of each clause in each version, used as ground truth for evals.

## How synthetic histories are made

1. Start from a real public contract.
2. Replace the counterparty with a fictional company.
3. Create later versions, keeping most terms the same and changing some on purpose.
4. Record every clause value and every planted change in the answer key.

Any resemblance between a fictional counterparty and a real company is unintentional.

## Sources

| File | Source | Link |
|---|---|---|
| _Add each base contract here_ | | |
