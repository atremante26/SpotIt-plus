# SpotIt+

We present SpotIt+, a bounded-verification-based tool for Text-to-SQL evaluation. SpotIt+ systematically searches for database instances that differentiate generated and gold queries. The result is either a proof of equivalence within the bounded search space, or a concrete counterexample database witnessing non-equivalence.

A key challenge is ensuring counterexamples reflect realistic data. SpotIt+ addresses this through a constraint-extraction pipeline that mines database constraints from example databases and uses a LLM to validate whether mined constraints represent genuine domain properties. The system extracts five constraint types (range, categorical, null, functional dependencies, and ordering dependencies) and encodes them as SMT constraints, guiding the Z3 solver toward realistic counterexamples.

The original SpotIt was described in our [ICLR'26 paper](https://arxiv.org/abs/2510.26840). And the SpotIt+ system was described in our paper [SpotIt+: Verification-based Text-to-SQL Evaluation with Database Constraints](https://arxiv.org/abs/2603.04334).

## Installation

### Prerequisites

- Python 3.10 or later (Python 3.11 is recommended).

### Clone the Repository

SpotIt+ uses git submodules. Clone with the `--recursive` flag:
```bash
git clone --recursive https://github.com/atremante26/SpotItPlus.git
cd SpotItPlus
```

If you already cloned without `--recursive`, initialize submodules:
```bash
git submodule update --init verieql
```

**Note:** You may see an error about cloning the Spider2 benchmark submodule. This can be safely ignored - Spider2 is not required for SpotIt+ functionality.


### Set Up Python Environment

Create and activate a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Mac/Linux
# or
venv\Scripts\activate  # On Windows
```

### Install Dependencies
```bash
pip install -r requirements.txt
```

### Set Up Z3

SpotIt+ uses a custom version of Z3 from VeriEQL. Follow these steps carefully:

**Copy VeriEQL's custom Z3 bindings:**
   
   You need Z3 bindings from a working VeriEQL installation. If you have access to one, copy them:
```bash
# Replace /path/to/working/venv with your actual path
cp /path/to/working/venv/lib/python3.11/site-packages/z3/*.py \
   venv/lib/python3.11/site-packages/z3/
   
cp -r /path/to/working/venv/lib/python3.11/site-packages/z3/lib \
   venv/lib/python3.11/site-packages/z3/
```
   
   Otherwise, you may need to build Z3 from source (see VeriEQL documentation).

## Quick Start

Verify your installation by running a simple example (using ALPHA-SQL method):
```bash
# Run verification on a single question with SpotIt+ constraints
python run_llm.py predictions/alpha_sql.json --question 1 --bound 2

# Run with SpotIt+-NoV constraints
python run_rule_based.py predictions/alpha_sql.json --question 1 --bound 2

# Run SpotIt baseline
python run_llm.py predictions/alpha_sql.json --question 1 --bound 2 --vanilla
```

## Usage

### Running SQL Verification

SpotIt+ provides two main scripts:

**1. SpotIt+ Constraint Extraction**
```bash
python run_llm.py <prediction_file> --question <question_id> --bound <bound_size>
```

**2. SpotIt+-NoV Constraint Extraction**
```bash
python run_rule_based.py <prediction_file> --question <question_id> --bound <bound_size>
```

**3. SpotIt Baseline**
```bash
python run_llm.py <prediction_file> --question <question_id> --bound <bound_size> --vanilla
```

**Parameters:**
- `prediction_file`: Path to JSON file containing predicted SQL queries
- `--question`: Question ID from the BIRD benchmark
- `--bound`: Bound size for symbolic reasoning (typically 2-5)
- `--vanilla`: Use baseline SpotIt

**Output:**
Results are written to `out.csv` with columns:
- `bound_size`: The bound used
- `question_id`: BIRD question ID
- `equivalent`: TRUE/FALSE
- `time_cost`: Verification time in seconds
- Counterexamples (if non-equivalent): Written to `counterexample.txt`

### Extracting Constraints

To extract constraints for a database:
```bash
# SpotIt+ Extraction
python constraint_extraction/extract_constraints_LLM.py

# SpotIt+-NoV Extraction
python constraint_extraction/extract_constraints.py
```

## Citation
```
@article{klopfenstein2026spotit+,
  title={SpotIt+: Verification-based Text-to-SQL Evaluation with Database Constraints},
  author={Klopfenstein, Rocky and He, Yang and Tremante, Andrew and Wang, Yuepeng and Narodytska, Nina and Wu, Haoze},
  journal={arXiv preprint arXiv:2603.04334},
  year={2026}
}
```
