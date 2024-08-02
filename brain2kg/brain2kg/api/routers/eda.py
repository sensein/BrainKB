from fastapi import APIRouter

from brain2kg.api.models.io import InputFilePath, OutputDirPath
from brain2kg.api.models.eda import OIESettings, SDSettings, SASettings
from brain2kg.text2kg.eda_pipeline import EDA

router = APIRouter()


@router.get('/eda')
async def eda_framework(
    oie_settings: OIESettings,
    sd_settings: SDSettings,
    sa_settings: SASettings,
    input_file_path: InputFilePath,
    output_dir_path: OutputDirPath
):
    eda_settings = {**oie_settings.model_dump(), **sd_settings.model_dump(), **sa_settings.model_dump()}
    input_output_paths = {**input_file_path.model_dump(), **output_dir_path.model_dump()}
    eda = EDA(**eda_settings)
    output_kg = eda.extract_kg(**input_output_paths)
    return {'ontology_aligned_kg': output_kg}