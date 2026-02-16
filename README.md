# SpotIt+

Text-to-SQL—the task of translating natural language questions into executable database queries—constitutes a key building block of modern chatbots and intelligent assistants across a wide range of industrial applications. Determining whether a Text-to-SQL method produces a correct SQL query is non-trivial. Existing evaluation platforms predominantly rely on *test-based evaluation*: executing the generated SQL query and the human-labeled ground truth (i.e., the gold SQL) on a fixed test database and comparing the results. This approach can be overly optimistic, as two non-equivalent queries may return identical results on test database instances. Recent work demonstrates that test-based evaluation frequently overlooks such discrepancies and proposes a verification-based alternative that provides stronger correctness guarantees. 

To help address this need, we present SpotIt+, a bounded-verification-based tool for Text-to-SQL evaluation. SpotIt+ systematically searches for database instances that differentiate generated and gold queries using an SMT-based bounded verification engine. A typical verification query consists of two parts: (i) a generated SQL query and a ground-truth SQL query, and (ii) a database schema; and its result is either a proof of equivalence within the bounded search space, or a concrete counterexample database witnessing non-equivalence.

A natural concern with verification-based evaluation is the practical relevance of the discovered counterexamples. Databases often contain domain-specific constraints that are implicit yet should be obeyed from a practical standpoint. With these constraints unexposed to the underlying verifier, counterexample databases might reveal discrepancies that only occur in pathological corner cases unlikely to arise in practice. To address this concern, SpotIt+ features a constraint-extraction pipeline that mines database constraints from example databases and incorporates a large language model (LLM) to assess whether a mined constraint represents a genuine domain property. The system automatically extracts five types of database constraints: range constraints (BETWEEN), categorical constraints (IN), null constraints (NOT NULL), functional dependencies, and ordering dependencies. These constraints are encoded as SMT constraints during bounded verification, guiding the solver toward counterexamples that respect realistic data regularities.

Experimental results on the BIRD benchmark show that incorporating the extracted database constraints yields more realistic counterexamples, while still uncovering a substantial number of discrepancies that test-based evaluation overlooks. 

SpotIt+ extends [VeriEQL](https://github.com/VeriEQL/VeriEQL), a bounded SQL verification framework that uses Z3 symbolic reasoning.

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

**Install z3-solver via pip:**
```bash
   pip install z3-solver
```

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

Verify your installation by running a simple example:
```bash
# Run verification on a single question with SpotIt+ constraints
python run_llm.py verieql/predictions/example.json --question 0 --bound 2

# Run with SpotIt+-NoV constraints
python run_rule_based.py verieql/predictions/example.json --question 0 --bound 2

# Run SpotIt baseline
python run_llm.py verieql/predictions/example.json --question 0 --bound 2 --vanilla
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