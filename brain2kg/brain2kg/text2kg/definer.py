import ollama

from brain2kg import get_logger
from brain2kg.text2kg.utils.llm_utils import parse_relation_definition

logger = get_logger(__name__)


class SchemaDefiner:
    def __init__(self, model: str = None) -> None:
        assert model is not None
        self.model = model

    def define_schema(
            self,
            input_text_str: str,
            extracted_triplets_list: list[list[str]],
            prompt_template_str: str,
            few_shot_examples_str: str = None,
    ) -> dict:
        
        relations_present = set()
        for t in extracted_triplets_list:
            relations_present.add(t[1])
        
        if not few_shot_examples_str:
            filled_prompt = prompt_template_str.format_map(
                {
                    'text': input_text_str,
                    'relations': relations_present,
                    'triples': extracted_triplets_list,
                }
            )
        else:
            filled_prompt = prompt_template_str.format_map(
                {
                    'few_shot_examples': few_shot_examples_str,
                    'text': input_text_str,
                    'relations': relations_present,
                    'triples': extracted_triplets_list,
                }
            )

        messages = [{'role': 'user', 'content': filled_prompt}]
        completion = ollama.chat(
            model=self.model,
            messages=messages,
        )['message']['content']
        logger.debug(f'RAW OUTPUT: {completion}')
        logger.debug(f'PROMPT: {filled_prompt}')
        relation_definition_dict = parse_relation_definition(completion, relations_present)
        if not relation_definition_dict:
            return None
        logger.debug(f'STRUCTURED: {relation_definition_dict}')
        return relation_definition_dict