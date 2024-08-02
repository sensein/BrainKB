from typing import Optional

from pydantic import BaseModel, Field


class InputFilePath(BaseModel):
    input_text_file_path: Optional[str] = Field(
        default='./data/raw_text/webnlg_dataset.txt', 
        description='File containing input texts to extract KG from',
    )


class OutputDirPath(BaseModel):
    output_dir: Optional[str] = Field(
        default='./examples/outputs',
        description='Directory to output to',
    )