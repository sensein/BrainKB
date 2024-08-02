import ast
import csv
import ollama

from argparse import ArgumentParser

from brain2kg.text2kg.utils.llm_utils import parse_relation_definition


def define_ontology_relations_to_csv(
        csv_schema_file_path: str,
        few_shot_examples_file_path: str,
        ontology_triplets_file_path: str,
        model: str = 'llama3.1',
        detail_log=True,
    ) -> None:
    # generates a CSV in `schemas/` mapping each relation to its formal definition
    
    ontology_triplets_str = open(ontology_triplets_file_path).read()
    ontology_triplets = ast.literal_eval(ontology_triplets_str)
    relations = set()
    for t in ontology_triplets:
        relations.add(t[1])

    PROMPT = """
    You will be given a list of relational triples in the format of [Subject, Relation, Object] extracted from a predefined neuroscience-domain ontology. For each relation present in the triples, your task is to write a description to express the meaning of the relation. In your answer, please strictly ONLY INCLUDE the relation and description pairs and DO NOT include any other comments, explanations or apologies.

    Here are some examples (pay attention to answer structure and format):
    {few_shot_examples}

    Now please extract relation descriptions given the following triples. Note that the description needs to be general and can be used to describe relations between other entities as well. Pay attention to the order of subject and object entities. ENSURE that the relations in your answer exactly match (exact letters, numbers, characters) the provided Relations. 
    Triples: {triples}
    Relations: {relations}
    """

    filled_prompt = PROMPT.format_map(
        {
            'few_shot_examples': open(few_shot_examples_file_path).read(),
            'triples': ontology_triplets,
            'relations': relations,
        }
    )
    messages = [{'role': 'user', 'content': filled_prompt}]
    completion = ollama.chat(
        model=model,
        messages=messages,
    )['message']['content']

    if detail_log:
        print('---')
        print('PROMPT:')
        print(filled_prompt)
        print('---')
        print('COMPLETION:')
        print(completion)
        print('---')

    relation_definition_dict = parse_relation_definition(completion, relations)
    if not relation_definition_dict:
        print('Error parsing response.')
    
    # write to CSV
    with open(csv_schema_file_path, 'w') as csvfile:
        spamwriter = csv.writer(csvfile)
        for relation, relation_definition in relation_definition_dict.items():
            spamwriter.writerow([relation, relation_definition])
    
    print('Complete!')
        

if __name__ == '__main__':
    parser = ArgumentParser()
    parser.add_argument("--csv_schema_file_path", help="Path to CSV schmea")
    parser.add_argument("--few_shot_examples_file_path", help='Path to few-shot examples for defining relations')
    parser.add_argument("--ontology_triplets_file_path", help="Path to Triplets list of lists, in string form")
    parser.add_argument("--model", default="llama3.1", help='Ollama LLM to use')

    args = parser.parse_args()

    csv_schema_file_path = args.csv_schema_file_path
    few_shot_examples_file_path = args.few_shot_examples_file_path
    ontology_triplets_file_path = args.ontology_triplets_file_path
    model = args.model

    define_ontology_relations_to_csv(
        csv_schema_file_path,
        few_shot_examples_file_path,
        ontology_triplets_file_path,
        model
    )