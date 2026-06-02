# Taiwan AI Supply-Chain Revenue Index

An open, auto-updating tracker of monthly-revenue momentum across Taiwan-listed
companies in NVIDIA's AI-rack supply chain — foundry, ODM/integration, power,
liquid cooling, substrate/PCB, interconnect, and BMC.

Taiwan-listed companies file **monthly** revenue (Taiwan MOPS) by ~the 10th of
each month — weeks ahead of US suppliers' quarterly prints. This project turns
that public signal into a clean, transparent index, refreshed automatically.

**Live dashboard:** _enable GitHub Pages (Settings → Pages → main / docs)_ → `https://<your-username>.github.io/<repo>/`

### Method
Equal-weighted mean of year-over-year monthly-revenue growth across the basket,
overall and by content bucket. Equal weighting is intentional: it measures
whether the AI buildout is **broadening** across the chain rather than tracking
only the largest names.

### Data
Company monthly revenue filings (Taiwan MOPS) via the [FinMind](https://finmind.github.io/) open API.
Figures are as reported by the source and not independently audited.

### How it runs
A scheduled GitHub Action (`.github/workflows/update.yml`) runs `build.py`, which
pulls the data, recomputes the index, and writes `docs/index.html` + `docs/data.json`.
No manual input required.

_Not investment advice. Open research tool._
