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
# @File    : data_filters.py
# @Software: PyCharm
from django import template
from urllib.parse import urlparse
import validators
from ..shared import _format_underscore_string, split_and_extract_last, _sex_int_to_word, split_and_extract_last_only
register = template.Library()


@register.filter
def zip_lists(a, b):
    return zip(a, b)

@register.filter
def format_underscore_string(value):
    return _format_underscore_string(value)

@register.filter
def extract_last_part(value):
    return split_and_extract_last(value)

@register.filter
def extract_last_part_only(value):
    return split_and_extract_last_only(value)

@register.filter
def extract_last_part_url_friendly(value):
    return split_and_extract_last(value).replace(':', '-')


@register.filter
def extract_last_two_part(url):
    parsed_url = urlparse(url)
    path = parsed_url.path
    parts = path.lstrip('/').split('/')
    formatted_data = ':'.join(parts[-2:])
    return formatted_data

@register.filter
def capitalize_first_letter(value):
    if value:
        return value[0].upper() + value[1:]
    else:
        return ""



@register.filter
def is_list(item):
    return type(item) == list

@register.filter
def is_url(string):
    return validators.url(string)

@register.filter
def format_gender(sex_id):
    return _sex_int_to_word(sex_id=sex_id)

@register.filter
def format_age(age):
    return int(float(age))
