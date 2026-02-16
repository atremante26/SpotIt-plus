import pandas as pd
import json
import os
import sys
import sqlite3
import warnings
from collections import defaultdict
from itertools import combinations
from utils import find_schema_column, NumpyEncoder, check_dependency, check_ordering_dependency
from LLM import (
    call_llm_for_between,
    call_llm_for_in,
    call_llm_for_not_null,
    call_llm_for_dependency,
    call_llm_for_ordering_dependency,
    call_llm_for_semantic_bounds
)
warnings.filterwarnings('ignore', message='Could not infer format')

USE_LLM_SEMANTIC_BOUNDS = True
INT_LOWER_BOUND = -2147483648
INT_UPPER_BOUND = 2147483647
REAL_LOWER_BOUND = -1e308
REAL_UPPER_BOUND = 1e308
INTEGER_TYPES = {'INTEGER', 'INT', 'SMALLINT', 'BIGINT', 'TINYINT', 'BOOLEAN'}
FLOAT_TYPES = {'REAL', 'DOUBLE', 'FLOAT', 'NUMERIC', 'DECIMAL'}
DATE_TYPES = {'DATE', 'DATETIME', 'TIMESTAMP', 'TIME', 'YEAR'}

def extract(db_path: str):
    db_name = os.path.basename(db_path)
    
    SQL_PATH = db_path + "/" + db_name + ".sqlite"
    DESCRIPTION_PATH = db_path + "/database_description"
    DEV_CONSTRAINTS_PATH = "../BIRD_schemas/dev_constraints.json" 

    # Extract table names and descriptions
    table_names = []
    table_descriptions = {}

    if os.path.exists(DESCRIPTION_PATH):
        for filename in os.listdir(DESCRIPTION_PATH):
            if filename.endswith('.csv'):
                table_name = filename[:-4]
                table_names.append(table_name)
                
                # Load the description CSV
                try:
                    # Try UTF-8 first
                    df = pd.read_csv(
                        f"{DESCRIPTION_PATH}/{filename}",
                        on_bad_lines='skip',
                        encoding='utf-8'
                    )
                    table_descriptions[table_name] = df
                except UnicodeDecodeError:
                    try:
                        # Fallback to latin-1
                        df = pd.read_csv(
                            f"{DESCRIPTION_PATH}/{filename}",
                            on_bad_lines='skip',
                            encoding='latin-1'
                        )
                        table_descriptions[table_name] = df
                    except Exception as e:
                        print(f"Could not read description for '{table_name}': {e}")
                        # Still add table name even if description fails
                except Exception as e:
                    print(f"Could not read description for '{table_name}': {e}")

    # Read from SQLite DB
    if os.path.exists(SQL_PATH):
        conn = sqlite3.connect(SQL_PATH)
        
        tables_data = {}
        for table_name in table_names:
            try:
                # Quote table name to handle reserved words
                df = pd.read_sql_query(f'SELECT * FROM "{table_name}"', conn)
                tables_data[table_name] = df
            except Exception as e:
                print(f"Error loading table '{table_name}': {e}")
                continue
    else:
        print(f"SQLite file not found: {SQL_PATH}")
        return None
    
    # Load existing schema
    SCHEMA_PATH = "../BIRD_schemas/table_to_columns.json"
    if os.path.exists(SCHEMA_PATH):
        with open(SCHEMA_PATH, 'r') as f:
            all_schemas = json.load(f)
        schema = all_schemas.get(db_name, {})
    else:
        print(f"Schema file not found at {SCHEMA_PATH}")
        schema = {}

    # Load existing constraints
    existing_constraints = []
    if os.path.exists(DEV_CONSTRAINTS_PATH):
        with open(DEV_CONSTRAINTS_PATH, 'r') as f:
            dev_constraints = json.load(f)
        
        # Get constraints for this specific database
        if db_name in dev_constraints:
            existing_constraints = dev_constraints[db_name][0]  # Get the constraint list
            
    # Store LLM Responses
    llm_reasoning = {
        'database': db_name,
        'between': [],
        'in': [],
        'not_null': [],
        'dependency': []
    }
    
    # Format Constraints for VeriEQL
    all_constraints = []
    
    # Add existing constraints
    all_constraints.extend(existing_constraints)

# ================================================= RANGE CONSTRAINTS =================================================
    table_range_stats = defaultdict(list)

    for table in table_names:
        if table not in tables_data:
            continue
        
        for col in tables_data[table].columns:
            
            # Get schema column name and type
            schema_col = find_schema_column(schema, table, col)
            if not schema_col:
                continue
            
            table_upper = table.upper()
            if table_upper not in schema or schema_col not in schema[table_upper]:
                continue
            
            col_type = schema[table_upper][schema_col]
            col_type_upper = col_type.upper()
            
            # Skip non-numeric columns
            if col_type_upper not in INTEGER_TYPES and col_type_upper not in FLOAT_TYPES:
                continue
            
            # Handle Numeric Columns
            numeric_col = pd.to_numeric(tables_data[table][col], errors='coerce')
            valid_values = numeric_col.dropna()
            
            # Need at least 2 values for range
            if len(valid_values) <= 1:
                continue
            
            # Calculate numeric range and statistics
            min_val = valid_values.min()
            max_val = valid_values.max()
            mean_val = valid_values.mean()
            std_val = valid_values.std()
            
            # Define strict bounds based on type
            if col_type_upper in INTEGER_TYPES:
                strict_bounds = [int(min_val), int(max_val)]
            else:  # FLOAT types
                strict_bounds = [float(min_val), float(max_val)]
            
            # Proportional Sampling
            value_counts = valid_values.value_counts()
            sample_values = value_counts.sample(
                n=min(10, len(value_counts)), 
                weights=value_counts.values, 
                random_state=42
            ).index.tolist()
            
            # Calculate custom bounds based on configuration
            if USE_LLM_SEMANTIC_BOUNDS:

                # Get LLM-generated semantic bounds
                semantic_result = call_llm_for_semantic_bounds(
                    db_name=db_name,
                    schema=schema,
                    column_descriptions=table_descriptions,
                    table_name=table,
                    column_name=schema_col,
                    data_type=col_type,
                    strict_bounds=strict_bounds,
                    sample_values=sample_values,
                    total_rows=len(tables_data[table]),
                    min_val=min_val,
                    max_val=max_val,
                    mean_val=mean_val,
                    std_val=std_val
                )
                
                # Use semantic bounds if available, otherwise fallback to rule-based
                if semantic_result.get('has_semantic_bounds', 0) == 1:
                    custom_bounds = [
                        semantic_result['lower_bound'],
                        semantic_result['upper_bound']
                    ]

                    # Set flag to true
                    llm_generated = True
                else:
                    # Use loose bounds (IQR)
                    Q1 = valid_values.quantile(0.25)
                    Q3 = valid_values.quantile(0.75)
                    IQR = Q3 - Q1

                    # Use Tukey's fence (k = 3 for extreme outliers)
                    loose_min = Q1 - 3.0 * IQR
                    loose_max = Q3 + 3.0 * IQR

                    # For non-negative data, inforce min of 0
                    if min_val >= 0:
                        loose_min = max(loose_min, 0)
                    
                    # Ensure correct types
                    if col_type_upper in INTEGER_TYPES:
                        custom_bounds = [int(loose_min), int(loose_max)]
                    else:
                        custom_bounds = [float(loose_min), float(loose_max)]
                    
                    # Set flag to false
                    llm_generated = False

            else:
                # Use loose bounds (IQR)
                Q1 = valid_values.quantile(0.25)
                Q3 = valid_values.quantile(0.75)
                IQR = Q3 - Q1

                # Use Tukey's fence (k = 3 for extreme outliers)
                loose_min = Q1 - 3.0 * IQR
                loose_max = Q3 + 3.0 * IQR

                # For non-negative data, inforce min of 0
                if min_val >= 0:
                    loose_min = max(loose_min, 0)
                
                # Ensure correct types
                if col_type_upper in INTEGER_TYPES:
                    custom_bounds = [int(loose_min), int(loose_max)]
                else:
                    custom_bounds = [float(loose_min), float(loose_max)]
                
                # Set flag to false
                llm_generated = False
            
            # LLM decides whether to constraint and which bounds
            llm_response = call_llm_for_between(
                db_name=db_name,
                schema=schema,
                column_descriptions=table_descriptions,
                table_name=table,
                column_name=schema_col,
                data_type=col_type,
                strict_bounds=strict_bounds,
                custom_bounds=custom_bounds,
                sample_values=sample_values,
                total_rows=len(tables_data[table]),
                llm_generated=llm_generated
            )
            
            # Store reasoning
            llm_reasoning['between'].append({
                'table': table,
                'column': schema_col,
                'data_type': col_type,
                'strict_bounds': strict_bounds,
                'custom_bounds': custom_bounds,
                'custom_bounds_type': 'semantic' if llm_generated else 'loose',
                'decision': {
                    'should_constrain': llm_response.get('should_constrain', 0),
                    'use_custom': llm_response.get('use_custom', 0),
                    'reasoning': llm_response.get('reasoning', ''),
                    'chosen_bounds': llm_response.get('chosen_bounds')
                }
            })
            
            # Add constraint if approved
            if llm_response.get('should_constrain', 0) == 1:
                chosen_bounds = llm_response.get('chosen_bounds')
                
                if chosen_bounds is not None:
                    # Add to table_range_stats for later encoding
                    table_range_stats[table].append({
                        'column': schema_col,
                        'lower': chosen_bounds[0],
                        'upper': chosen_bounds[1],
                        'data_type': col_type
                    })

    # Encode BETWEEN constraints
    for table in table_names:
        for stat in table_range_stats[table]:
            # Get bounds and data type
            lower_bound = stat['lower']
            upper_bound = stat['upper']
            data_type = stat['data_type']
            column_name = stat['column']
            
            # Determine type-appropriate infinity values
            col_type_upper = data_type.upper()
            
            if col_type_upper in INTEGER_TYPES:
                default_lower = INT_LOWER_BOUND  # -2147483648
                default_upper = INT_UPPER_BOUND  # 2147483647
            elif col_type_upper in FLOAT_TYPES:
                default_lower = REAL_LOWER_BOUND  # -1e308
                default_upper = REAL_UPPER_BOUND  # 1e308
            else:
                # Unknown type, default to integer bounds
                default_lower = INT_LOWER_BOUND
                default_upper = INT_UPPER_BOUND
            
            # Replace None with infinity values
            final_lower = lower_bound if lower_bound is not None else default_lower
            final_upper = upper_bound if upper_bound is not None else default_upper
            
            # Create constraint
            constraint = {
                "between": [
                    {"value": f"{table.upper()}__{column_name}"},
                    final_lower,
                    final_upper
                ]
            }
            
            all_constraints.append(constraint)
            
# ===========================================================================================================================


# ================================================= CATEGORICAL CONSTRAINTS =================================================
    table_categorical_stats = defaultdict(list)

    for table in table_names:
        if table not in tables_data:
            continue
        
        for col in tables_data[table].columns:
            # Get unique values (excluding nulls and empty strings)
            unique_vals = tables_data[table][col].dropna()
            unique_vals = unique_vals[unique_vals != '']  # Remove empty strings
            unique_vals = unique_vals.unique()
            unique_count = len(unique_vals)
            
            # Must have at least 2 values, and not too many
            if unique_count <= 1 or unique_count > 30:
                continue
            
            # Get schema column name
            schema_col = find_schema_column(schema, table, col)
            if not schema_col:
                continue
            
            # Get schema type for proper value encoding
            table_upper = table.upper()
            if table_upper not in schema or schema_col not in schema[table_upper]:
                continue
            
            col_type = schema[table_upper][schema_col]
            
            # Convert categories to match schema type
            try:
                # Skip date columns
                if col_type in DATE_TYPES: 
                    continue
                if col_type in INTEGER_TYPES:
                    categories = [int(cat) for cat in unique_vals]
                elif col_type in FLOAT_TYPES:
                    categories = [float(cat) for cat in unique_vals]
                else:  # VARCHAR/TEXT/CHAR
                    categories = [str(cat) for cat in unique_vals]
            except (ValueError, TypeError):
                # Type conversion failed, skip this constraint
                continue
            
            # LLM Call
            llm_response = call_llm_for_in(
                db_name=db_name,
                schema=schema,
                column_descriptions=table_descriptions,
                table_name=table,
                column_name=schema_col,
                data_type=col_type,
                categories=categories,
                category_count=unique_count,
                total_rows=len(tables_data[table])  
            )

            # Store LLM Reasoning
            llm_reasoning['in'].append({
                'table': table,
                'column': schema_col,
                'data_type': col_type,
                'categories': categories,
                'category_count': unique_count,
                'decision': {
                    'should_constrain': llm_response.get('should_constrain', 1),
                    'reasoning': llm_response.get('reasoning', 'No reasoning provided')
                }
            })
            
            should_constrain = llm_response.get('should_constrain', 1)
            
            # Skip if LLM says no constraint
            if not should_constrain:
                continue
            
            table_categorical_stats[table].append({
                'schema_column': schema_col,
                'categories': categories
            })

    # Encode CATEGORICAL constraints
    for table in table_names:
        for stat in table_categorical_stats[table]:
            all_constraints.append({
                "in": [
                    {"value": f"{table.upper()}__{stat['schema_column']}"},
                    stat['categories']
                ]
            })

# ===========================================================================================================================
    
# ================================================= NOT NULL CONSTRAINTS ====================================================    
    table_not_null_stats = defaultdict(list)

    for table in table_names:
        if table not in tables_data:
            continue
        
        for col in tables_data[table].columns:
            # Check if column has any nulls
            if tables_data[table][col].isnull().any():
                continue
            
            # Get schema column name
            schema_col = find_schema_column(schema, table, col)
            if not schema_col:
                continue
            
            # Get schema type
            table_upper = table.upper()
            if table_upper not in schema or schema_col not in schema[table_upper]:
                continue
            
            col_type = schema[table_upper][schema_col]
            
            # Context for LM
            total_rows = len(tables_data[table][col])

            # Proportional Sampling                        
            value_counts = tables_data[table][col].value_counts()
            sample_values = value_counts.sample(n=min(10, len(value_counts)), weights=value_counts.values, random_state=42).index.tolist()
            
            # LLM Call
            llm_response = call_llm_for_not_null(
                db_name=db_name,
                schema=schema,
                column_descriptions=table_descriptions,
                table_name=table,
                column_name=schema_col,
                data_type=col_type,
                total_rows=total_rows,
                sample_values=sample_values
            )

            # Store LLM Reasoning
            llm_reasoning['not_null'].append({
                'table': table,
                'column': schema_col,
                'data_type': col_type,
                'total_rows': total_rows,
                'decision': {
                    'should_constrain': llm_response.get('should_constrain', 1),
                    'reasoning': llm_response.get('reasoning', 'No reasoning provided')
                }
            })
            
            should_constrain = llm_response.get('should_constrain', 1)

            # Skip if LLM says no constraint
            if not should_constrain:
                continue
            
            table_not_null_stats[table].append({
                'schema_column': schema_col
            })

    # Encode NOT NULL constraints
    for table in table_names:
        for stat in table_not_null_stats[table]:
            all_constraints.append({
                "not_null": {"value": f"{table.upper()}__{stat['schema_column']}"}
            })
# ===========================================================================================================================

# ================================================= DEPENDENCY CONSTRAINTS ====================================================  
    table_dependencies = defaultdict(list)

    for table in table_names:
        if table not in tables_data:
            continue
        
        # Find both functional and ordering dependencies
        dependencies = find_dependency(tables_data[table], schema, table_name=table)
        
        for dep in dependencies:
            if dep['type'] == 'functional':
                # LLM Call
                llm_response = call_llm_for_dependency(
                    db_name=db_name,
                    schema=schema,
                    column_descriptions=table_descriptions,
                    table_name=table,
                    det_schema_col=dep['det_schema_col'],
                    dep_schema_col=dep['dep_schema_col'],
                    sample_mappings=dep['sample_mappings'],
                    total_rows=len(tables_data[table])
                )

                # Store LLM Reasoning
                llm_reasoning['dependency'].append({
                    'table': table,
                    'type': 'functional',
                    'column_a': dep['det_schema_col'],  
                    'column_b': dep['dep_schema_col'],  
                    'relationship': '->',
                    'sample_data': dep['sample_mappings'][:3],  
                    'decision': {
                        'should_constrain': llm_response.get('should_constrain', 1),
                        'reasoning': llm_response.get('reasoning', '')
                    }
                })
        
            
                # Add constraint if approved
                if llm_response.get('should_constrain', 1):
                    table_dependencies[table].append({
                        'type': 'functional',
                        'det_schema_col': dep['det_schema_col'],
                        'dep_schema_col': dep['dep_schema_col']
                    })
            elif dep['type'] == 'ordering':
                # LLM Call
                llm_response = call_llm_for_ordering_dependency(
                    db_name=db_name,
                    schema=schema,
                    column_descriptions=table_descriptions,
                    table_name=table,
                    det_schema_col=dep['det_schema_col'],
                    dep_schema_col=dep['dep_schema_col'],
                    operator=dep['operator'],
                    sample_pairs=dep['sample_pairs'],
                    total_rows=len(tables_data[table])
                )
                
                # Store LLM reasoning
                llm_reasoning['dependency'].append({
                    'table': table,
                    'type': 'ordering',
                    'column_a': dep['det_schema_col'],  
                    'column_b': dep['dep_schema_col'],  
                    'relationship': dep['operator'], 
                    'sample_data': dep['sample_pairs'][:3], 
                    'decision': {
                        'should_constrain': llm_response.get('should_constrain', 1),
                        'reasoning': llm_response.get('reasoning', '')
                    }
                })
                
                # Add constraint if approved
                if llm_response.get('should_constrain', 1):
                    table_dependencies[table].append({
                        'type': 'ordering',
                        'det_schema_col': dep['det_schema_col'],
                        'dep_schema_col': dep['dep_schema_col'],
                        'operator': dep['operator']
                    })

    # Encode DEPENDENCY constraints
    for table in table_names:
        for dep in table_dependencies[table]:
            if dep['type'] == 'functional':
                # Functional dependency
                all_constraints.append({
                    "dependency": {
                        "values": [
                            f"{table.upper()}__{dep['det_schema_col']}",
                            f"{table.upper()}__{dep['dep_schema_col']}"
                        ]
                    }
                })
            
            elif dep['type'] == 'ordering':
                # Ordering dependency
                all_constraints.append({
                    "dependency": {
                        "values": [
                            f"{table.upper()}__{dep['det_schema_col']}",
                            f"{table.upper()}__{dep['dep_schema_col']}"
                        ],
                        "type": "ordering",
                        "operator": dep['operator']
                    }
                })
# ===========================================================================================================================
    
    # Format for VeriEQL
    constraints_output = {
        db_name: [
            all_constraints
        ]
    }

    # Create output directory
    output_dir = 'constraint_results/LLM'
    os.makedirs(output_dir, exist_ok=True)

    # Save constraints to JSON
    with open(os.path.join(output_dir, f'{db_name}_constraints_LLM.json'), 'w') as f:
        json.dump(constraints_output, f, indent=2, cls=NumpyEncoder)

    # Save reasoning to JSON
    with open(os.path.join(output_dir, f'{db_name}_reasoning_LLM.json'), 'w') as f:
        json.dump(llm_reasoning, f, indent=2, cls=NumpyEncoder)

    return constraints_output, llm_reasoning
    
def find_dependency(df, schema, table_name=""):
    """Find functional and ordering dependencies between column pairs."""
    dependencies = []
    columns = df.columns.tolist()
    
    # Identify numeric/date columns
    numeric_columns = set()
    
    for col in columns:
        # Get schema type directly from the table
        schema_col_type = None
        
        if table_name in schema and col in schema[table_name]:
            schema_col_type = schema[table_name][col].upper()
        
        if not schema_col_type:
            continue
        
        # Check if schema type is numeric 
        numeric_types = INTEGER_TYPES + FLOAT_TYPES
        is_string_type = any(t in schema_col_type for t in ['VARCHAR', 'TEXT', 'CHAR'])
        is_numeric_type = any(t in schema_col_type for t in numeric_types)
        
        # Only add if numeric type AND NOT string type
        if is_numeric_type and not is_string_type:
            # Verify data is actually numeric
            try:
                non_null_vals = df[col].dropna()
                if len(non_null_vals) > 0:
                    test = pd.to_numeric(non_null_vals, errors='coerce')
                    if test.notna().all():  # ALL values must be numeric
                        numeric_columns.add(col)
            except:
                pass
    
    # Check all pairs for functional dependencies
    for col_a, col_b in combinations(columns, 2):
        # Skip if columns are identical
        if df[col_a].equals(df[col_b]):
            continue
        
        # Check Functional Dependency (ALL columns)
        dep_result = check_dependency(df, col_a, col_b)
        if dep_result['is_dependent']:
            det_schema_col = find_schema_column(schema, table_name, col_a)
            dep_schema_col = find_schema_column(schema, table_name, col_b)
        
            if not (det_schema_col and dep_schema_col):
                continue
        
            # Get sample mappings (10 examples)
            sample_data = df[[col_a, col_b]].drop_duplicates().head(10)
            
            sample_mappings = []
            for _, row in sample_data.iterrows():
                det_val = row[col_a]
                dep_val = row[col_b]
                
                if pd.isna(det_val):
                    det_val = None
                elif hasattr(det_val, 'item'):
                    det_val = det_val.item()
                
                if pd.isna(dep_val):
                    dep_val = None
                elif hasattr(dep_val, 'item'):
                    dep_val = dep_val.item()
                
                sample_mappings.append({
                    det_schema_col: det_val,
                    dep_schema_col: dep_val
                })
            
            dependencies.append({
                'type': 'functional',
                'det_schema_col': det_schema_col,
                'dep_schema_col': dep_schema_col,
                'sample_mappings': sample_mappings
            })
    
    # Check pairs for ordering (ONLY numeric columns)
    numeric_pairs = [(a, b) for a, b in combinations(numeric_columns, 2)]
    
    for col_a, col_b in numeric_pairs:
        order_result = check_ordering_dependency(df, col_a, col_b)
        if order_result['is_ordered']:
            det_schema_col = find_schema_column(schema, table_name, col_a)
            dep_schema_col = find_schema_column(schema, table_name, col_b)
        
            if not (det_schema_col and dep_schema_col):
                continue

            sample_data = df[[col_a, col_b]].dropna().head(10)
            sample_pairs = []
            for _, row in sample_data.iterrows():
                val_a = row[col_a]
                val_b = row[col_b]
                
                if pd.isna(val_a):
                    val_a = None
                elif hasattr(val_a, 'item'):
                    val_a = val_a.item()
                
                if pd.isna(val_b):
                    val_b = None
                elif hasattr(val_b, 'item'):
                    val_b = val_b.item()
                
                sample_pairs.append({
                    det_schema_col: val_a,
                    dep_schema_col: val_b
                })
            
            dependencies.append({
                'type': 'ordering',
                'det_schema_col': det_schema_col,
                'dep_schema_col': dep_schema_col,
                'operator': order_result['operator'],
                'sample_pairs': sample_pairs
            })
    
    return dependencies

if __name__ == "__main__":
    # TEST WITH ALL DATABASES
    database_paths = {
        "thrombosis_prediction": "BIRD_dev/thrombosis_prediction",
        "california_schools": "BIRD_dev/california_schools",
        "debit_card_specializing": "BIRD_dev/debit_card_specializing",
        "financial": "BIRD_dev/financial",
        "formula_1": "BIRD_dev/formula_1",
        "card_games": "BIRD_dev/card_games",
        "european_football_2": "BIRD_dev/european_football_2",
        "toxicology": "BIRD_dev/toxicology",
        "student_club": "BIRD_dev/student_club",
        "superhero": "BIRD_dev/superhero",
        "codebase_community": "BIRD_dev/codebase_community"
    }
    
    all_constraints = {}
    all_reasoning = {}  
    
    for db_name, db_path in database_paths.items():
        print(f"\n{'='*60}")
        print(f"Processing: {db_name}")
        print(f"{'='*60}")
        
        try:
            constraints_output, reasoning = extract(db_path) 
            all_constraints.update(constraints_output)
            all_reasoning[db_name] = reasoning  
            
            # Detailed summary
            total = len(constraints_output[db_name][0])
            types = defaultdict(int)
            for c in constraints_output[db_name][0]:
                types[list(c.keys())[0]] += 1
            
            print(f"\n  {db_name}: {total} total constraints")
            for t, count in sorted(types.items()):
                print(f"   {t}: {count}")
            
            # Print reasoning summary
            print(f"\n  LLM Decisions:")
            for constraint_type in ['between', 'in', 'not_null', 'dependency']:
                decisions = reasoning[constraint_type]
                if decisions:
                    accepted = sum(1 for d in decisions if d['decision']['should_constrain'])
                    rejected = len(decisions) - accepted
                    print(f"   {constraint_type}: {accepted} accepted, {rejected} rejected")
            
        except Exception as e:
            print(f"\n  Error in {db_name}:")
            import traceback
            traceback.print_exc()
            sys.exit(1)
    
    # Save constraints
    output_path = "constraint_results/LLM/all_constraints_LLM.json"
    with open(output_path, 'w') as f:
        json.dump(all_constraints, f, indent=2, cls=NumpyEncoder)
    
    # Save all reasoning
    reasoning_path = "constraint_results/LLM/all_reasoning_LLM.json"
    with open(reasoning_path, 'w') as f:
        json.dump(all_reasoning, f, indent=2, cls=NumpyEncoder)
    
    print(f"\n{'='*60}")
    print(f"  Saved constraints to: {output_path}")
    print(f"  Saved reasoning to: {reasoning_path}")
    print(f"{'='*60}")