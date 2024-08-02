from typing import Optional

from pydantic import BaseModel, Field


class OIESettings(BaseModel):
    oie_llm: Optional[str] = Field(
        default='llama3.1', 
        description='LLM used for open information extraction.'
    )
    oie_prompt_template_file_path: Optional[str] = Field(
        default='./prompt_templates/oie_fsp_template.txt', 
        description='Prompt template used for open information extraction.'
    )
    oie_few_shot_example_file_path: Optional[str] = Field(
        default='./few_shot_examples/oie_few_shot_examples.txt', 
        description='Few shot examples used for open information extraction.'
    )


class SDSettings(BaseModel):
    sd_llm: Optional[str] = Field(
        default='llama3.1', 
        description='LLM used for schema definition.'
    )
    sd_prompt_template_file_path: Optional[str] = Field(
        default='./prompt_templates/sd_fsp_template.txt', 
        description='Prompt template used for schema definition.'
    )
    sd_few_shot_example_file_path: Optional[str] = Field(
        default='./few_shot_examples/sd_few_shot_examples.txt', 
        description='Few shot examples used for schema definition.'
    )


class SASettings(BaseModel):
    sa_target_schema_file_path: Optional[str] = Field(
        default='./schemas/webnlg_schema.csv', 
        description='Schema used for schema alignment verification.'
    )
    sa_llm: Optional[str] = Field(
        default='llama3.1', 
        description='LLM used for schema alignment verification.'
    )
    sa_embedding_model: Optional[str] = Field(
        default='sentence-transformers/all-MiniLM-L6-v2', 
        description='Embedding model used for schema alignment verification.'
    )
    sa_prompt_template_file_path: Optional[str] = Field(
        default='./prompt_templates/sa_template.txt', 
        description='Prompt template used for schema alignment verification.'
    )
