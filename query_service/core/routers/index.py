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

from typing import Annotated

# @Author  : Tek Raj Chhetri
# @Email   : tekraj@mit.edu
# @Web     : https://tekrajchhetri.com/
# @File    : index.py
# @Software: PyCharm
from fastapi import APIRouter, Depends

from core.models.user import LoginUserIn
from core.security import get_current_user, require_scopes

router = APIRouter()


@router.get("/")
async def root():
    return {"message": "Welcome to FastAPI skeleton"}


@router.get("/token-check", dependencies=[Depends(require_scopes(["read"]))])
async def token_check(user: Annotated[LoginUserIn, Depends(get_current_user)]):
    return {"message": "token check passed success"}
