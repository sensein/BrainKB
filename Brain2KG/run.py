from argparse import ArgumentParser
from brain2kg.text2kg.eda_pipeline import EDA

open('examples.log', 'w').close() # clear local log

if __name__ == '__main__':
    parser = ArgumentParser()
    # OIE module setting
    parser.add_argument(
        '--oie_llm', 
        default='llama3.1', 
        help='LLM used for open information extraction.',
    )
    parser.add_argument(
        '--oie_prompt_template_file_path',
        default='./prompt_templates/oie_fsp_template.txt',
        help='Prompt template used for open information extraction.',
    )
    parser.add_argument(
        '--oie_few_shot_example_file_path',
        default='./few_shot_examples/oie_few_shot_examples.txt',
        help='Few shot examples used for open information extraction.',
    )

    # SD module setting
    parser.add_argument(
        '--sd_llm', 
        default='llama3.1', 
        help='LLM used for schema definition.',
    )
    parser.add_argument(
        '--sd_prompt_template_file_path',
        default='./prompt_templates/sd_fsp_template.txt',
        help='Prompt template used for schema definition.',
    )
    parser.add_argument(
        '--sd_few_shot_example_file_path',
        default='./few_shot_examples/sd_few_shot_examples.txt',
        help='Few shot examples used for schema definition.',
    )

    # SA module setting
    parser.add_argument(
        '--sa_target_schema_file_path',
        default='./schemas/webnlg_schema.csv',
        help='Schema used for schema alignment verification.',
    )
    parser.add_argument(
        '--sa_llm',
        default='llama3.1',
        help='LLM used for schema alignment verification.',
    )
    parser.add_argument(
        '--sa_embedding_model',
        default='sentence-transformers/all-MiniLM-L6-v2',
        help='Embedding model used for schema alignment verification.',
    )
    parser.add_argument(
        '--sa_prompt_template_file_path',
        default='./prompt_templates/sa_template.txt',
        help='Prompt template used for schema alignment verification.',
    )

    # Input text setting
    parser.add_argument(
        '--input_text_file_path',
        default='./data/raw_text/webnlg_dataset.txt',
        help='File containing input texts to extract KG from.',
    )

    # Output setting
    parser.add_argument(
        '--output_dir', 
        default='./examples/outputs', 
        help='Directory to output to.',
    )

    args = parser.parse_args()
    args = vars(args)
    eda = EDA(**args)

    output_kg = eda.extract_kg(
        args['input_text_file_path'], 
        args['output_dir']
    )