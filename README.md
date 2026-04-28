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
git clone --recursive https://github.com/ai-ar-research/SpotIt-plus.git
cd SpotIt-plus
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

### Set Up OpenAI API Key

Constraint extraction requires an OpenAI API key. Copy the example file and add your key:
```bash
cp .env.example .env
# edit .env and set OPENAI_API_KEY=sk-...
```

### Download BIRD Dataset

Constraint extraction requires the BIRD development dataset. Download and extract it into the correct location:
```bash
# Download and extract
curl -L https://bird-bench.oss-cn-beijing.aliyuncs.com/dev.zip -o dev.zip
unzip dev.zip
unzip dev_20240627/dev_databases.zip

# Move to correct location
mv dev_databases constraint_extraction/BIRD_dev

# Clean up
rm -rf dev.zip dev_20240627/
```

### Set Up Z3

SpotIt+ uses a custom version of Z3 from VeriEQL. Copy VeriEQL's custom Z3 bindings into your virtual environment:
```bash
cp verieql/z3py_libs/*.py venv/lib/python3.11/site-packages/z3/
```

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
@misc{tremante2026spotitverificationbasedtexttosqlevaluation,
      title={SpotIt+: Verification-based Text-to-SQL Evaluation with Database Constraints}, 
      author={Andrew Tremante and Yang He and Rocky Klopfenstein and Yuepeng Wang and Nina Narodytska and Haoze Wu},
      year={2026},
      eprint={2603.04334},
      archivePrefix={arXiv},
      primaryClass={cs.DB},
      url={https://arxiv.org/abs/2603.04334}, 
}
```