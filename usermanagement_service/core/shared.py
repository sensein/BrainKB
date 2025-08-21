# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
# DISCLAIMER: This software is provided "as is" without any warranty,
# express or implied, including but not limited to the warranties of
# merchantability, fitness for a particular purpose, and non-infringement.
#
# In no event shall the authors or copyright holders be liable for any
# claim, damages, or other liability, whether in an action of contract,
# tort, or otherwise, arising from, out of, or in connection with the
# software or the use or other dealings in the software.
# -----------------------------------------------------------------------------

# @Author  : Tek Raj Chhetri
# @Email   : tekraj@mit.edu
# @Web     : https://tekrajchhetri.com/
# @File    : shared.py
# @Software: PyCharm
import logging
logger = logging.getLogger(__name__)

def convert_row_to_dict(row):
    """Convert database row to dictionary, handling different row types"""
    if row is None:
        return {}

    # Handle string or primitive types
    if isinstance(row, (str, int, float, bool)):
        logger.warning(f"Unexpected primitive type in convert_row_to_dict: {type(row)} - {row}")
        return {}

    if hasattr(row, '_asdict'):
        return row._asdict()
    elif hasattr(row, '__dict__'):
        return {k: v for k, v in row.__dict__.items() if not k.startswith('_')}
    elif hasattr(row, '_mapping'):
        return dict(row._mapping)
    elif hasattr(row, 'keys') and callable(row.keys):
        try:
            return dict(zip(row.keys(), row))
        except Exception as e:
            logger.error(f"Error converting row with keys(): {str(e)}")
            return {}
    else:
        logger.warning(f"Unknown row type in convert_row_to_dict: {type(row)} - {row}")
        return {}


def compare_and_filter_changes(current_dict: dict, update_dict: dict) -> dict:
    """Compare current and update dictionaries and return only changed fields"""
    changes = {}
    
    for key, new_value in update_dict.items():
        if key in current_dict:
            current_value = current_dict[key]
            # Handle None values properly - treat empty string and None as equivalent for prefix/suffix
            if key in ['name_prefix', 'name_suffix']:
                current_normalized = current_value if current_value else ""
                new_normalized = new_value if new_value else ""
                if current_normalized != new_normalized:
                    changes[key] = new_value
            elif current_value != new_value:
                changes[key] = new_value
        else:
            # New field
            changes[key] = new_value
    
    return changes


# Simplified approach: always update nested data if provided
# No complex comparison needed - just remove all and recreate