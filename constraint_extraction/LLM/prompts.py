import json
import pandas as pd
import sys
import os

# Add parent directory to path to import utils
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils import find_schema_column, NumpyEncoder

# HELPER FUNCTIONS
def map_descriptions_to_schema(column_descriptions, schema):
    """Map all column descriptions to schema column names using find_schema_column()."""
    mapped = {}
    
    for table_name, df in column_descriptions.items():
        table_upper = table_name.upper()
        
        # Skip if table not in schema
        if table_upper not in schema:
            continue
        
        mapped[table_upper] = {}
        
        # Process each row in the description DataFrame
        for _, row in df.iterrows():
            # Get original column name from CSV
            orig_col = row.get('original_column_name', '')
            
            if not orig_col or pd.isna(orig_col):
                continue
            
            # Use utils.find_schema_column() to map to schema column name
            schema_col = find_schema_column(schema, table_name, orig_col)
            
            if not schema_col:
                continue  # Skip if no match found
            
            # Build description from available fields
            desc = row.get('column_description', '')
            val_desc = row.get('value_description', '')
            
            # Combine description and value_description
            full_desc = ''
            if desc and not pd.isna(desc):
                full_desc = str(desc).strip()
            
            if val_desc and not pd.isna(val_desc):
                val_desc_str = str(val_desc).strip()
                # Skip useless value descriptions
                if val_desc_str and val_desc_str.lower() not in ['', 'unuseful', 'nan']:
                    if full_desc:
                        full_desc = f"{full_desc} [{val_desc_str}]"
                    else:
                        full_desc = val_desc_str
            
            # Store under schema column name
            mapped[table_upper][schema_col] = full_desc if full_desc else "No description"
    
    return mapped

def get_semantic_bounds_prompt(
    db_name,
    schema,
    column_descriptions,
    table_name,
    column_name,
    data_type,
    strict_bounds,
    sample_values,
    total_rows,
    min_val,
    max_val,
    mean_val,
    std_val
):
    """
    Generate LLM prompt to determine semantic bounds for a numeric column.
    Supports two-sided, one-sided (lower only, upper only), or no bounds.
        
    LLM will return null for unbounded directions, which will be converted
    to VeriEQL-compatible infinity values (INT_UPPER_BOUND, REAL_UPPER_BOUND, etc.)
    during constraint encoding.
    """
    
    # Map descriptions to schema columns
    mapped_descriptions = map_descriptions_to_schema(column_descriptions, schema)
    
    # Format schema as JSON
    schema_str = json.dumps(schema, indent=2)
    
    # Format descriptions as JSON
    descriptions_str = json.dumps(mapped_descriptions, indent=2)
    
    # SYSTEM PROMPT (CACHED)
    system_prompt = f"""You are a database constraint expert determining semantic bounds for numeric columns.

DATABASE: {db_name}

FULL SCHEMA (all tables and column types):
{schema_str}

COLUMN DESCRIPTIONS (mapped to schema column names):
{descriptions_str}

Your task: Determine if this column has natural semantic bounds based on its meaning and domain knowledge.

TYPES OF BOUNDS:

1. **Two-sided bounds**: Both lower and upper limits exist
   - Example: {{"lower_bound": 0, "upper_bound": 100}}
   - Use cases: percentages, ratings, age, probability, geographic coordinates

2. **Lower-bound only**: Minimum value exists, but no maximum
   - Example: {{"lower_bound": 0, "upper_bound": null}}
   - Use cases: counts, quantities, prices, distances (non-negative but unbounded above)
   - Use null for upper bound to represent unbounded above

3. **Upper-bound only**: Maximum value exists, but no minimum
   - Example: {{"lower_bound": null, "upper_bound": 0}}
   - Use cases: debt/loss amounts, negative balances, deviations below baseline
   - Use null for lower bound to represent unbounded below

4. **No semantic bounds**: Neither bound can be determined from domain knowledge
   - Example: {{"has_semantic_bounds": 0}}
   - Use cases: arbitrary measurements, unconstrained amounts

SEMANTIC BOUND EXAMPLES:

Two-sided bounds:
- Percentages: [0, 100] or [0, 1]
  Examples: "discount_percent", "success_rate", "humidity"
- Ratings: [1, 5], [0, 10], [1, 10]
  Examples: "star_rating", "satisfaction_score"
- Age (human): [0, 120]
  Examples: "customer_age", "employee_age"
- Coordinates: latitude [-90, 90], longitude [-180, 180]
- Probability: [0, 1]

Lower-bound only:
- Counts/quantities: [0, null]
  Examples: "order_count", "view_count", "inventory_quantity", "items_sold"
- Prices/amounts: [0, null]
  Examples: "product_price", "total_cost", "revenue"
- Distances: [0, null]
  Examples: "distance_km", "height_cm", "length_m"
- Durations: [0, null]
  Examples: "duration_seconds", "time_elapsed"

Upper-bound only:
- Debt/loss: [null, 0]
  Examples: "account_debt", "net_loss"
- Below-baseline deviations: [null, threshold]
  Examples: "temperature_deviation_below_normal"

No semantic bounds:
- Arbitrary measurements: height, weight (too variable)
- Transaction amounts: can be any value
- General amounts: unrestricted monetary values

DECISION GUIDELINES:
- Prefer semantic bounds based on domain knowledge over observed data range
- If observed [10, 90] but semantic meaning is [0, 100], use [0, 100]
- If no clear semantic bounds exist, return has_semantic_bounds=0
- When in doubt, prefer no bounds over incorrect bounds

Respond in JSON format:
{{
  "has_semantic_bounds": 0 or 1,
  "lower_bound": number or null,
  "upper_bound": number or null,
  "bound_type": "two_sided" | "lower_only" | "upper_only" | "none",
  "reasoning": "brief explanation of semantic bounds OR why no semantic bounds exist"
}}

IMPORTANT: 
- Use null (not a number) to represent unbounded directions
- The system will automatically convert null to appropriate infinity values
- Focus on semantic meaning, not just observed data"""

    # USER PROMPT (NOT CACHED)
    user_prompt = f"""ANALYZING:
Table: {table_name}
Column: {column_name}
Type: {data_type}
Total rows: {total_rows}

Observed statistics:
- Minimum: {min_val}
- Maximum: {max_val}
- Mean: {mean_val:.2f}
- Std Dev: {std_val:.2f}

Strict bounds (observed range): {strict_bounds}
Sample values: {sample_values}

Does this column have natural semantic bounds based on its meaning?
If yes, specify the bounds (use null for unbounded directions)."""

    return system_prompt, user_prompt


def get_between_prompt(
    db_name,
    schema,
    column_descriptions,
    table_name,
    column_name,
    data_type,
    strict_bounds,
    custom_bounds,
    sample_values,
    total_rows,
    llm_generated=False
):
    """
    Generate system and user prompts for BETWEEN constraint validation.
    Handles two-sided and one-sided bounds (where None indicates unbounded direction).
    """
    
    # Map descriptions to schema columns
    mapped_descriptions = map_descriptions_to_schema(column_descriptions, schema)
    
    # Format schema as JSON
    schema_str = json.dumps(schema, indent=2)
    
    # Format descriptions as JSON
    descriptions_str = json.dumps(mapped_descriptions, indent=2)
    
    # Define bounds terminology based on source
    if llm_generated:
        custom_label = "semantic bounds"
        custom_description = "semantically-derived based on domain knowledge"
    else:
        custom_label = "loose bounds"
        custom_description = "IQR-based outlier exclusion (3 * IQR)"
    
    # Format bounds for display
    def format_bounds(bounds):
        """Format bounds list for display, handling None for unbounded directions."""
        lower, upper = bounds
        
        if lower is None and upper is None:
            return "unbounded"
        elif lower is None:
            return f"[-∞, {upper}]"
        elif upper is None:
            return f"[{lower}, +∞]"
        else:
            return f"[{lower}, {upper}]"
    
    strict_display = format_bounds(strict_bounds)
    custom_display = format_bounds(custom_bounds)
    
    # SYSTEM PROMPT (CACHED)
    system_prompt = f"""You are a database constraint expert analyzing numeric columns for BETWEEN constraints.

DATABASE: {db_name}

FULL SCHEMA (all tables and column types):
{schema_str}

COLUMN DESCRIPTIONS (mapped to schema column names):
{descriptions_str}

Your task is to determine:
1. Should this column have a BETWEEN constraint?
2. If yes, should we use strict bounds (exact observed data range) or custom bounds ({custom_description})?

UNDERSTANDING BOUNDS:
- Two-sided bounds: [lower, upper] - both limits specified
- One-sided bounds: [lower, ∞] or [-∞, upper] - one direction unbounded
- Unbounded: [-∞, ∞] - no constraints (don't use BETWEEN)

Note: Infinity symbols (∞) indicate unbounded directions. The system will handle these appropriately.

Consider:
- Is this a naturally bounded value (percentages 0-100, ratings 1-5) or unbounded (counts, measurements)?
- Do the strict bounds seem realistic given the column's semantic meaning?
- Would the custom bounds be safer to handle edge cases not in current data?
- For one-sided bounds (e.g., counts ≥ 0), are they semantically correct?
- Are there related columns that provide context about expected ranges?
- Is the sample size large enough to trust the observed bounds?

Respond in JSON format:
{{
  "should_constrain": 0 or 1,
  "use_custom": 0 or 1,
  "reasoning": "brief explanation considering schema, column descriptions, and bound types"
}}"""

    # USER PROMPT (NOT CACHED)
    user_prompt = f"""ANALYZING:
Table: {table_name}
Column: {column_name}
Type: {data_type}
Total rows: {total_rows}

Observed data range:
- Strict bounds (exact observed range): {strict_display}
- Custom bounds ({custom_label}): {custom_display}
- Sample values: {sample_values}

Should this column have a BETWEEN constraint? If yes, use strict or custom bounds?"""

    return system_prompt, user_prompt

def get_in_prompt(
    db_name,
    schema,
    column_descriptions,
    table_name,
    column_name,
    data_type,
    categories,
    category_count,
    total_rows
):
    """Generate system and user prompts for IN constraint validation."""
    
    # Map descriptions to schema columns
    mapped_descriptions = map_descriptions_to_schema(column_descriptions, schema)
    
    # Format schema as JSON
    schema_str = json.dumps(schema, indent=2)
    
    # Format descriptions as JSON
    descriptions_str = json.dumps(mapped_descriptions, indent=2)
    
    # SYSTEM PROMPT (CACHED)
    system_prompt = f"""You are a database constraint expert analyzing columns for IN constraints (categorical/enumerated values).

DATABASE: {db_name}

FULL SCHEMA (all tables and column types):
{schema_str}

COLUMN DESCRIPTIONS (mapped to schema column names):
{descriptions_str}

Your task is to determine if a column should have an IN constraint that restricts values to a specific set.

Consider:
- Is this a true categorical/enumerated column where all valid values are known and limited?
  Examples: status codes, types, categories, ratings, yes/no flags
- Or is this pseudo-categorical with potentially more values in the real world?
  Examples: names, product IDs, sparse data where not all values are represented
- Does the column description indicate it's an enumeration?
- Are there related columns that suggest this is a controlled vocabulary?
- Could new categories appear in future data?

Respond in JSON format:
{{
  "should_constrain": 0 or 1,
  "reasoning": "brief explanation considering whether this is truly enumerated"
}}"""

    # USER PROMPT (NOT CACHED)
    user_prompt = f"""ANALYZING:
Table: {table_name}
Column: {column_name}
Type: {data_type}
Total rows: {total_rows}
Number of unique values: {category_count}

Unique values in data:
{categories}

Is this a true categorical column where an IN constraint makes sense?

Consider:
- With {total_rows} total rows and {category_count} unique values, is this sample likely complete?
- Are these the ONLY valid values, or could there be more?
- Is this an enumeration (status, type, category) or just sparse data?
- Would restricting to these exact values be too limiting?"""

    return system_prompt, user_prompt

def get_not_null_prompt(
    db_name,
    schema,
    column_descriptions,
    table_name,
    column_name,
    data_type,
    total_rows,
    sample_values
):
    """Generate system and user prompts for NOT NULL constraint validation."""
    
    mapped_descriptions = map_descriptions_to_schema(column_descriptions, schema)
    schema_str = json.dumps(schema, indent=2)
    descriptions_str = json.dumps(mapped_descriptions, indent=2)
    
    system_prompt = f"""You are a database constraint expert analyzing columns for NOT NULL constraints.

DATABASE: {db_name}

FULL SCHEMA (all tables and column types):
{schema_str}

COLUMN DESCRIPTIONS (mapped to schema column names):
{descriptions_str}

Your task is to determine if a column should have a NOT NULL constraint.

Consider:
- Is this field logically required for every record?
  Examples of required: primary keys, foreign keys, timestamps, essential identifiers
  Examples of optional: middle names, secondary contact info, optional attributes
- Just because current data has no nulls doesn't mean the field is required
- Could future records reasonably have this field empty?
- Does the column description indicate it's required or optional?
- Are there related columns that suggest this should always be present?

Respond in JSON format:
{{
  "should_constrain": 0 or 1,
  "reasoning": "brief explanation considering whether this field is truly required"
}}"""

    user_prompt = f"""ANALYZING:
Table: {table_name}
Column: {column_name}
Type: {data_type}
Total rows: {total_rows}
Current data: 100% non-null ({total_rows}/{total_rows} rows have values)

Sample values:
{sample_values}

Should this column have a NOT NULL constraint?

Consider:
- Is this field logically required, or is the data just coincidentally complete?
- With {total_rows} rows all non-null, does this indicate a true requirement?
- Could future records reasonably omit this field?
- What does the column name/description suggest about whether it's required?"""

    return system_prompt, user_prompt


def get_dependency_prompt(
    db_name,
    schema,
    column_descriptions,
    table_name,
    det_schema_col,
    dep_schema_col,
    sample_mappings,
    total_rows
):
    """Generate system and user prompts for DEPENDENCY constraint validation."""
    
    mapped_descriptions = map_descriptions_to_schema(column_descriptions, schema)
    schema_str = json.dumps(schema, indent=2)
    descriptions_str = json.dumps(mapped_descriptions, indent=2)
    
    system_prompt = f"""You are a database constraint expert analyzing functional dependencies between columns.

DATABASE: {db_name}

FULL SCHEMA (all tables and column types):
{schema_str}

COLUMN DESCRIPTIONS (mapped to schema column names):
{descriptions_str}

Your task is to determine if a functional dependency constraint should be applied.

A functional dependency means: for each value of column A, there is exactly one corresponding value of column B.
Example: COUNTRY_CODE → COUNTRY_NAME (each code maps to exactly one country name)

Consider:
- Is this a meaningful semantic relationship?
  Examples of meaningful: country_code → country_name, product_id → product_name, zip_code → city
  Examples of trivial to skip: primary_key → any_column (these are already encoded as primary key constraints and don't add semantic value, so do not include them)
- Does the column description suggest a natural mapping relationship?
- Could this dependency break in future data?
- Is this just a coincidental pattern in the current sample?
- Would this constraint add value for query verification?

Note: Primary keys naturally determine all other columns, but encoding all such dependencies 
creates noise. Focus on semantically meaningful relationships.

Respond in JSON format:
{{
  "should_constrain": 0 or 1,
  "reasoning": "brief explanation considering whether this is a meaningful dependency"
}}"""

    user_prompt = f"""ANALYZING FUNCTIONAL DEPENDENCY:
Table: {table_name}
Determinant: {det_schema_col}
Dependent: {dep_schema_col}
Total rows: {total_rows}

Observed mapping (100% consistent in current data):
{json.dumps(sample_mappings, indent=2, cls=NumpyEncoder)} 

Is this a meaningful functional dependency that should be enforced as a constraint?

Consider:
- With {total_rows} rows, is this dependency reliable?
- Is this a semantic relationship (like code -> name) or just a coincidence?
- Is the determinant a primary/unique key? (If yes, this may be trivial)
- Would this constraint help verify query correctness?"""

    return system_prompt, user_prompt

def get_ordering_dependency_prompt(
    db_name,
    schema,
    column_descriptions,
    table_name,
    det_schema_col,
    dep_schema_col,
    operator,
    sample_pairs,
    total_rows
):
    """Generate prompt for LLM to validate ordering dependency."""
    
    # Map descriptions
    mapped_descriptions = map_descriptions_to_schema(schema, column_descriptions)
    
    # Get descriptions for both columns
    table_upper = table_name.upper()
    det_desc = mapped_descriptions.get(table_upper, {}).get(det_schema_col, "No description")
    dep_desc = mapped_descriptions.get(table_upper, {}).get(dep_schema_col, "No description")
    
    system_prompt = f"""You are a database constraint expert analyzing ordering dependencies.

An ordering dependency means: for ALL rows, {det_schema_col} {operator} {dep_schema_col}

Examples of VALID ordering dependencies:
- min_value <= max_value (logical: min must be <= max)
- low_estimate <= high_estimate (logical: low must be <= high)

Examples of INVALID ordering dependencies:
- id >= customer_id (coincidental, not semantic)
- price <= quantity (no logical relationship)
- date <= status (different types, meaningless)

Your task: Determine if this ordering dependency is semantically meaningful and should be enforced.

Respond in JSON format:
{{
  "should_constrain": 0 or 1,
  "reasoning": "Brief explanation of your decision"
}}"""

    user_prompt = f"""ANALYZING ORDERING DEPENDENCY:

Database: {db_name}
Table: {table_name}
Total rows: {total_rows}

Column A: {det_schema_col}
Description: {det_desc}

Column B: {dep_schema_col}
Description: {dep_desc}

Observed relationship (100% consistent in data):
{det_schema_col} {operator} {dep_schema_col}

Sample pairs (first 10 rows):
{json.dumps(sample_pairs, indent=2, cls=NumpyEncoder)}

Is this a meaningful ordering dependency that should be enforced as a constraint?

Consider:
- Is this a logical relationship? (min/max, start/end, lower/upper bounds)
- Could this be coincidental in the current data but not a true constraint?
- Does enforcing this help verify query correctness?"""

    return system_prompt, user_prompt