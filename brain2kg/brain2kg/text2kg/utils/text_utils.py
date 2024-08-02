import re
import pymupdf

def preprocess_text(text: str):
    # remove quotations (single and double)
    text = re.sub(r'["\']', '', text)

    # take a look at replacing pronouns with known nouns

    return text

def pdf_to_text(input_text_file_path: str):
    # PDF text extraction benchmark: https://github.com/jaiamin/brainkb-pdf-extraction
    with pymupdf.open(input_text_file_path) as doc:
        text = chr(12).join([page.get_text() for page in doc])

    return text

def pronoun_to_noun(text: str):
    pass # convert pronouns to nouns in each sentence