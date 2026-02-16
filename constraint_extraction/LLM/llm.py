import os
import json
import time
import openai
from dotenv import load_dotenv
from .prompts import (
    get_between_prompt,
    get_in_prompt,
    get_not_null_prompt,
    get_dependency_prompt,
    get_ordering_dependency_prompt,
    get_semantic_bounds_prompt
)

load_dotenv()

# Initialize OpenAI client 
client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def call_api(system_prompt, user_prompt, max_retries=3):

    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model="gpt-5.1", 
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0,  # Deterministic responses
                response_format={"type": "json_object"}  # Force JSON output
            )
            
            # Extract and parse JSON response
            output = response.choices[0].message.content.strip()
            parsed = json.loads(output)
            
            return parsed
            
        except openai.RateLimitError as e:
            # Rate limit hit - wait and retry
            wait_time = 2 ** attempt  # Exponential backoff: 1s, 2s, 4s
            print(f"Rate limit hit. Waiting {wait_time}s before retry {attempt + 1}/{max_retries}...")
            time.sleep(wait_time)
            
        except openai.APIError as e:
            # API error - wait and retry
            print(f"API error: {e}. Retry {attempt + 1}/{max_retries}...")
            time.sleep(1)
            
        except json.JSONDecodeError as e:
            # JSON parsing failed
            print(f"Failed to parse JSON response: {e}")
            print(f"Raw output: {output}")
            return None
            
        except Exception as e:
            # Unknown error
            print(f"Unexpected error in API call: {e}")
            return None
    
    return None

def call_llm_for_semantic_bounds(
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
    Call LLM to determine semantic bounds for a numeric column. 
    Bounds can be  two-sided, one-sided (lower only, upper only), or no bounds.
    """

    # Generate prompts
    system_prompt, user_prompt = get_semantic_bounds_prompt(
        db_name=db_name,
        schema=schema,
        column_descriptions=column_descriptions,
        table_name=table_name,
        column_name=column_name,
        data_type=data_type,
        strict_bounds=strict_bounds,
        sample_values=sample_values,
        total_rows=total_rows,
        min_val=min_val,
        max_val=max_val,
        mean_val=mean_val,
        std_val=std_val
    )

    # Call API
    result = call_api(system_prompt, user_prompt)

    # Handle API failure
    if result is None:
        return {
            "has_semantic_bounds": 0,
            "lower_bound": None,
            "upper_bound": None,
            "bound_type": "none",
            "reasoning": "API call failed"
        }

    # Validate response fields
    has_semantic_bounds = result.get("has_semantic_bounds", 0)
    lower_bound = result.get("lower_bound", None)
    upper_bound = result.get("upper_bound", None)
    bound_type = result.get("bound_type", None)
    reasoning = result.get("reasoning", "No reasoning provided")

    return {
        "has_semantic_bounds": has_semantic_bounds,
        "lower_bound": lower_bound,
        "upper_bound": upper_bound,
        "bound_type": bound_type,
        "reasoning": reasoning
    }

def call_llm_for_between(
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
    Call LLM to decide if a BETWEEN constraint should be applied and whether
    to use strict or custom bounds.
    """
    
    # Generate prompts
    system_prompt, user_prompt = get_between_prompt(
        db_name=db_name,
        schema=schema,
        column_descriptions=column_descriptions,
        table_name=table_name,
        column_name=column_name,
        data_type=data_type,
        strict_bounds=strict_bounds,
        custom_bounds=custom_bounds,
        sample_values=sample_values,
        total_rows=total_rows,
        llm_generated=llm_generated
    )
    
    # Call API
    result = call_api(system_prompt, user_prompt)

    # Handle API failure
    if result is None:
        return {
            'should_constrain': 0,  
            'use_custom': 0,
            'reasoning': 'API call failed - skipping constraint',
            'chosen_bounds': None
        }
    
    # Validate response fields
    should_constrain = result.get('should_constrain', 0)
    use_custom = result.get('use_custom', 0)
    reasoning = result.get('reasoning', 'No reasoning provided')

    # Determine chosen bounds
    if should_constrain == 1:
        chosen_bounds = custom_bounds if use_custom == 1 else strict_bounds
    else:
        chosen_bounds = None
    
    return {
        'should_constrain': should_constrain,
        'use_custom': use_custom,
        'reasoning': reasoning,
        'chosen_bounds': chosen_bounds
    }

def call_llm_for_in(
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
    """Call LLM to decide if an IN constraint should be applied."""
    system_prompt, user_prompt = get_in_prompt(
        db_name=db_name,
        schema=schema,
        column_descriptions=column_descriptions,
        table_name=table_name,
        column_name=column_name,
        data_type=data_type,
        categories=categories,
        category_count=category_count,
        total_rows=total_rows
    )
    
    result = call_api(system_prompt, user_prompt)
    
    if result is None:
        return {
            'should_constrain': 1,
            'reasoning': 'API call failed - using default'
        }
    
    return {
        'should_constrain': result.get('should_constrain', 1),
        'reasoning': result.get('reasoning', 'No reasoning provided')
    }

def call_llm_for_not_null(
    db_name,
    schema,
    column_descriptions,
    table_name,
    column_name,
    data_type,
    total_rows,
    sample_values
):
    """Call LLM to decide if a NOT NULL constraint should be applied."""
    system_prompt, user_prompt = get_not_null_prompt(
        db_name=db_name,
        schema=schema,
        column_descriptions=column_descriptions,
        table_name=table_name,
        column_name=column_name,
        data_type=data_type,
        total_rows=total_rows,
        sample_values=sample_values
    )
    
    result = call_api(system_prompt, user_prompt)
    
    if result is None:
        return {
            'should_constrain': 1,
            'reasoning': 'API call failed - using default'
        }
    
    return {
        'should_constrain': result.get('should_constrain', 1),
        'reasoning': result.get('reasoning', 'No reasoning provided')
    }

def call_llm_for_dependency(
    db_name,              
    schema,               
    column_descriptions, 
    table_name,           
    det_schema_col,       
    dep_schema_col,       
    sample_mappings,     
    total_rows           
):
    """Call LLM to decide if a DEPENDENCY constraint should be applied."""
    system_prompt, user_prompt = get_dependency_prompt(
        db_name=db_name,
        schema=schema,
        column_descriptions=column_descriptions,
        table_name=table_name,
        det_schema_col=det_schema_col,
        dep_schema_col=dep_schema_col,
        sample_mappings=sample_mappings,
        total_rows=total_rows
    )
    
    result = call_api(system_prompt, user_prompt)
    
    if result is None:
        return {
            'should_constrain': 1,
            'reasoning': 'API call failed - using default'
        }
    
    return {
        'should_constrain': result.get('should_constrain', 1),
        'reasoning': result.get('reasoning', 'No reasoning provided')
    }

def call_llm_for_ordering_dependency(
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
    """Call LLM to decide if an ORDERING DEPENDENCY constraint should be applied."""
    
    system_prompt, user_prompt = get_ordering_dependency_prompt(
        db_name=db_name,
        schema=schema,
        column_descriptions=column_descriptions,
        table_name=table_name,
        det_schema_col=det_schema_col,
        dep_schema_col=dep_schema_col,
        operator=operator,
        sample_pairs=sample_pairs,
        total_rows=total_rows
    )
    
    result = call_api(system_prompt, user_prompt)
    
    if result is None:
        return {
            'should_constrain': 1,
            'reasoning': 'API call failed - using default'
        }
    
    return {
        'should_constrain': result.get('should_constrain', 1),
        'reasoning': result.get('reasoning', 'No reasoning provided')
    }