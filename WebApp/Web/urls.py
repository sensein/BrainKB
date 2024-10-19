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

# @Author  : Tek Raj Chhetri
# @Email   : tekraj@mit.edu
# @Web     : https://tekrajchhetri.com/
# @File    : urls.py
# @Software: PyCharm

from django.urls import path
from django.conf import settings
from django.conf.urls.static import static
from . import views

urlpatterns = [
                  path('knowledge-base-detail/<str:id>', views.knowledge_base_single, name='knowledge_base_single'),
                  path('knowledge-base/<slug:slug>', views.knowledge_base_slug, name='knowledge_base_slug'),
                  path('knowledge-base', views.knowledge_base, name='knowledge_base'),
                  path('get_doner_data_ajax', views.get_doner_data_ajax, name='get_doner_data_ajax'),
                  path('evidence', views.evidence, name='evidence'),
                  path('assertion', views.assertion, name='assertion'),
                  path('get_tissuesample_data_ajax', views.get_tissuesample_data_ajax,
                       name='get_tissuesample_data_ajax'),
                  path('about', views.about, name='about'),
                  path('species/<slug:slug>', views.species_entity_card, name='species_entity_card'),
                  path('', views.index, name='index'),
              ] + static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
