import copy
import ollama
import numpy as np

from sentence_transformers import SentenceTransformer

from brain2kg import get_logger

logger = get_logger(__name__)


class SchemaAligner:
    def __init__(self, target_schema_dict: dict, embedding_model_str: str, verifier_model_str: str):
        self.target_schema_dict = target_schema_dict
        self.embedding_model = SentenceTransformer(embedding_model_str)
        self.verifier_model = verifier_model_str

        self.target_schema_embedding_dict = {}

        for relation, relation_definition in target_schema_dict.items():
            embedding = self.embedding_model.encode(relation_definition)
            self.target_schema_embedding_dict[relation] = embedding

    def update_schema_embedding_dict(self):
        for relation, relation_definition in self.target_schema_dict.items():
            if relation in self.target_schema_embedding_dict:
                continue
            embedding = self.embedding_model.encode(relation_definition)
            self.target_schema_embedding_dict[relation] = embedding

    def retrieve_relevant_relations(self, query_input_text: str, top_k=10):
        target_relation_list = list(self.target_schema_embedding_dict.keys())
        target_relation_embedding_list = list(self.target_schema_embedding_dict.values())

        query_embedding = self.embedding_model.encode(query_input_text)

        scores = np.array([query_embedding]) @ np.array(target_relation_embedding_list).T
        scores = scores[0]
        highest_scores_indices = np.argsort(-scores)
        
        output = {
            target_relation_list[idx]: self.target_schema_dict[target_relation_list[idx]]
            for idx in highest_scores_indices[:top_k]
        }, [scores[idx] for idx in highest_scores_indices[:top_k]]
        logger.debug(f'RELEVANT RELATIONS: {output}')
        return output
    
    def llm_verify(
        self,
        input_text_str: str,
        query_triplet: list[str],
        query_relation_definition: str,
        prompt_template_str: str,
        candidate_relation_definition_dict: dict,
        relation_example_dict: dict = None,
    ):
        canonicalized_triplet = copy.deepcopy(query_triplet)
        choice_letters_list = []
        choices = ''
        candidate_relations = list(candidate_relation_definition_dict.keys())
        candidate_relation_descriptions = list(candidate_relation_definition_dict.values())
        for idx, rel in enumerate(candidate_relations):
            choice_letter = chr(ord('@') + idx + 1)
            choice_letters_list.append(choice_letter)
            choices += f"{choice_letter}. '{rel}': {candidate_relation_descriptions[idx]}\n"
            if relation_example_dict is not None:
                choices += f"Example: '{relation_example_dict[candidate_relations[idx]]['triple']}' can be extracted from '{candidate_relations[idx]['sentence']}'\n"
        choices += f"{chr(ord('@')+idx+2)}. None of the above.\n"

        verification_prompt = prompt_template_str.format_map(
            {
                'input_text': input_text_str,
                'query_triplet': query_triplet,
                'query_relation': query_triplet[1],
                'query_relation_definition': query_relation_definition,
                'choices': choices,
            }
        )
        messages = [{'role': 'user', 'content': verification_prompt}]
        verification_result = ollama.chat(
            model=self.verifier_model,
            messages=messages,
        )['message']['content']

        logger.debug(f'CHOICES: {choices}')
        logger.debug(f'RAW OUTPUT: {verification_result}')
        letter = verification_result.split('\n')[0][0].upper().strip()
        logger.debug(f'STRUCTURED: {letter}')
        if letter in choice_letters_list:
            canonicalized_triplet[1] = candidate_relations[choice_letters_list.index(verification_result[0])]
        else:
            # if LLM output error or parsing issue, select top choice
            canonicalized_triplet[1] = candidate_relations[0] # A
        
        logger.debug(f'FINAL TRIPLET: {canonicalized_triplet}')
        return canonicalized_triplet