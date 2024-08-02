import os
import csv
import copy
import pathlib

import nltk
nltk.download('punkt', quiet=True)
from nltk.tokenize import sent_tokenize

from tqdm import tqdm
from brain2kg import get_logger

from brain2kg.text2kg.utils.text_utils import preprocess_text, pdf_to_text
from brain2kg.text2kg.extractor import TripletExtractor
from brain2kg.text2kg.definer import SchemaDefiner
from brain2kg.text2kg.aligner import SchemaAligner

BAR_FORMAT = '{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining},{rate_fmt}{postfix} failed] '
logger = get_logger(__name__)


class EDA:
    def __init__(self, **eda_configuration) -> None:

        # OIE module setting
        self.oie_llm_name = eda_configuration['oie_llm']
        self.oie_prompt_template_file_path = eda_configuration['oie_prompt_template_file_path']
        self.oie_few_shot_example_file_path = eda_configuration['oie_few_shot_example_file_path']

        # Schema Definition module setting
        self.sd_llm_name = eda_configuration['sd_llm']
        self.sd_template_file_path = eda_configuration['sd_prompt_template_file_path']
        self.sd_few_shot_example_file_path = eda_configuration['sd_few_shot_example_file_path']

        # Schema Alignment module setting
        self.sa_target_schema_file_path = eda_configuration['sa_target_schema_file_path']
        self.sa_verifier_llm_name = eda_configuration['sa_llm']
        self.sa_embedding_model_name = eda_configuration['sa_embedding_model']
        self.sa_template_file_path = eda_configuration['sa_prompt_template_file_path']

        self.target_schema_dict = {}

        reader = csv.reader(open(self.sa_target_schema_file_path, 'r'))
        for row in reader:
            relation, relation_definition = row
            self.target_schema_dict[relation] = relation_definition

        # EDA initialization
        extractor = TripletExtractor(model=self.oie_llm_name)
        logger.info('Extractor initialized.')
        definer = SchemaDefiner(model=self.sd_llm_name)
        logger.info('Definer initialized.')
        aligner = SchemaAligner(
            target_schema_dict=self.target_schema_dict,
            embedding_model_str=self.sa_embedding_model_name,
            verifier_model_str=self.sa_verifier_llm_name
        )
        logger.info('Aligner initialized.')

        self.extractor = extractor
        self.definer = definer
        self.aligner = aligner

    def extract_kg(
        self,
        input_text_file_path: str,
        output_dir: str = None,
    ):
        pbar = tqdm(total=3, desc='Preprocessing')
        if output_dir is not None:
            pathlib.Path(output_dir).mkdir(parents=True, exist_ok=True)
        if not input_text_file_path:
            raise ValueError('Input text file path must be provided.')
        
        _, file_extension = os.path.splitext(input_text_file_path)
        file_extension = file_extension.lower()
        if file_extension == '.txt':
            input_raw_text = open(input_text_file_path, 'r').read()
        elif file_extension == '.pdf':
            input_raw_text = pdf_to_text(input_text_file_path)
            logger.debug(f'PDF EXTRACTED TEXT: {input_raw_text}')
        else:
            raise ValueError('Input text file path must be a supported type.')
        pbar.update(1)

        # preprocess text
        input_raw_text = preprocess_text(input_raw_text)
        pbar.update(1)

        # sentence tokenize input text
        sentences = sent_tokenize(input_raw_text)
        logger.info('Input text sentence tokenized.')
        pbar.update(1)
        pbar.close()

        output_kg_list = []
        # EDA run
        oie_triplets, schema_definition_dict_list, aligned_triplets_list = self._extract_kg_helper(sentences)
        output_kg_list.append(oie_triplets)
        output_kg_list.append(aligned_triplets_list)

        if output_dir is not None:
            with open(os.path.join(output_dir, 'eda_output.txt'), 'w') as f:
                for l in aligned_triplets_list:
                    f.write(str(l) + '\n')
                f.flush()

        return output_kg_list

    def _extract_kg_helper(
        self,
        input_text_list: list[str],
    ):
        oie_triplets_dict = {}
        
        extraction_skipped_count = 0
        oie_prompt_template_str = open(self.oie_prompt_template_file_path).read()
        oie_few_shot_examples_str = open(self.oie_few_shot_example_file_path).read()
        pbar = tqdm(total=len(input_text_list), desc='Extracting', bar_format=BAR_FORMAT)
        for idx in range(len(input_text_list)):
            pbar.set_postfix_str(str(extraction_skipped_count))
            input_text = input_text_list[idx]
            oie_triplets = self.extractor.extract(
                input_text,
                oie_prompt_template_str,
                oie_few_shot_examples_str,
            )
            if oie_triplets is not None:
                oie_triplets_dict[input_text] = oie_triplets
            else:
                extraction_skipped_count += 1
            pbar.update(1)
        pbar.close()
        logger.info('Sentences extracted.')
        if extraction_skipped_count:
            logger.info(f'{extraction_skipped_count} triplets skipped due to parsing issues.')

        schema_definition_dict_list = []
        schema_definition_few_shot_prompt_template_str = open(self.sd_template_file_path).read()
        schema_definition_few_shot_examples_str = open(self.sd_few_shot_example_file_path).read()

        schema_definition_relevant_relations_dict = {}

        # Define the relations in the induced open schema
        oie_triplets_dict_copy = copy.deepcopy(oie_triplets_dict)
        definition_skipped_count = 0
        pbar = tqdm(total=len(oie_triplets_dict), desc='Defining', bar_format=BAR_FORMAT)
        for input_text, oie_triplets in oie_triplets_dict.items():
            pbar.set_postfix_str(str(definition_skipped_count))
            schema_definition_dict = self.definer.define_schema(
                input_text,
                oie_triplets,
                schema_definition_few_shot_prompt_template_str,
                schema_definition_few_shot_examples_str,
            )
            if schema_definition_dict is not None:
                schema_definition_dict_list.append(schema_definition_dict)
            else:
                definition_skipped_count += 1
                del oie_triplets_dict_copy[input_text]
                pbar.update(1)
                continue

            for relation, relation_definition in schema_definition_dict.items():
                schema_definition_relevant_relations = self.aligner.retrieve_relevant_relations(
                    relation_definition,
                    top_k=5,
                )
                schema_definition_relevant_relations_dict[relation] = schema_definition_relevant_relations
            pbar.update(1)
        pbar.close()
        logger.info('Sentences defined and relations found.')
        if definition_skipped_count:
            logger.info(f'{definition_skipped_count} definitions skipped due to parsing issues.')

        schema_aligner_prompt_template_str = open(self.sa_template_file_path).read()

        # Target Alignment
        aligned_triplets_list = []
        for idx, (input_text, oie_triplets) in enumerate(tqdm(oie_triplets_dict_copy.items(), desc='Aligning')):
            aligned_triplets = []
            for oie_triplet in oie_triplets:
                relation = oie_triplet[1]

                # if relation is exact match with any relevant relation, no need to llm_verify
                if relation in schema_definition_relevant_relations_dict[relation][0].keys():
                    aligned_triplet = [oie_triplet[0], relation, oie_triplet[2]]
                else:
                    aligned_triplet = self.aligner.llm_verify(
                        input_text,
                        oie_triplet,
                        schema_definition_dict_list[idx][relation],
                        schema_aligner_prompt_template_str,
                        schema_definition_relevant_relations_dict[relation][0]
                    )
                if aligned_triplet is not None:
                    aligned_triplets.append(aligned_triplet)
            aligned_triplets_list.append(aligned_triplets)
        logger.info('Sentences aligned.')

        return oie_triplets_dict_copy.keys(), schema_definition_dict_list, aligned_triplets_list