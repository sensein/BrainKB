from django.shortcuts import render
from .models import KnowledgeBaseViewerModel, QueryEndpoint
import requests
from django.http import JsonResponse
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from .shared import get_filter_uirs_label
from .shared import (extract_data_either_s_p_o_match, format_data_for_kb_single,
                     get_category_value, extract_data_doner_tissuesample_match_query,
                     format_ansrs_data_for_kb_single,
                     format_gars_data_for_kb_single,
                     donor_tissues_data_for_kb_single,
                     get_donor_data_by_id,
                     doner_tissue_to_js,
                     get_tissuesample_data_by_id,
                     all_species_genome_by_taxon,
                     fetch_all_matching_genome_info_query,
                     format_species_annotation_data,
                     species_pagination_count_by_taxon,
                     get_structure_count,
                     get_libraryaliquot_count,
                     get_species_count,
                     get_donor_count,
                     format_donor_for_kb_single
                     )
import numpy as np


def index(request):
    species_count = None
    donor_count = None
    structure_count = None
    libraryaliquot_count = None
    try:
        species_count = fetch_knowledge_base(get_species_count())["message"]["results"]["bindings"][0]["count"]["value"]
        donor_count = fetch_knowledge_base(get_donor_count())["message"]["results"]["bindings"][0]["count"]["value"]
        structure_count = fetch_knowledge_base(get_structure_count())["message"]["results"]["bindings"][0]["count"][
            "value"]
        libraryaliquot_count = \
        fetch_knowledge_base(get_libraryaliquot_count())["message"]["results"]["bindings"][0]["count"]["value"]
    except ValueError as e:
        pass

    contex = {
        "species_count": species_count,
        "donor_count": donor_count,
        "structure_count": structure_count,
        "libraryaliquot_count": libraryaliquot_count
    }

    return render(request, "pages/index.html", contex)


def fetch_knowledge_base(query_or_search_input, query_endpoint_type="get", endpoint_service_type="query"):
    endpoints = QueryEndpoint.objects.all().filter(query_endpoint_type=query_endpoint_type,
                                                   endpoint_service_type=endpoint_service_type)
    payload = {"sparql_query": query_or_search_input}
    response = requests.get(endpoints[0].query_url, params=payload)
    print("^" * 100)
    print(response.url)
    if response.status_code == 200:
        return response.json()


def get_knowledge_base(kbobj):
    labels = get_filter_uirs_label(kbobj)
    query_or_search_input = kbobj[0].sparql_query
    response_data = fetch_knowledge_base(query_or_search_input)
    fetched_data = response_data["message"]["results"]["bindings"]

    if fetched_data:
        return {
            "knowledge_base": kbobj,
            "fetched_data": fetched_data,
            "processed_label": labels["processed_label"],
            "pre_processed_label": labels["pre_processed_label"][0]
        }
    else:
        return {
            "knowledge_base": False
        }


def knowledge_base(request):
    kbobj = KnowledgeBaseViewerModel.objects.all().filter(status_active=True, default_kb=True)
    other_items = KnowledgeBaseViewerModel.objects.all().filter(status_active=True).order_by("-default_kb")
    context = get_knowledge_base(kbobj=kbobj)
    context["menu_items"] = other_items

    return render(request,
                  "pages/knowledge-base.html", context=context)


def knowledge_base_single(request, id):
    param = request.GET.get('uri')
    query = extract_data_either_s_p_o_match(param)

    response_data = fetch_knowledge_base(query)
    fetched_data = response_data["message"]["results"]["bindings"]
    label = id
    formtted_data_all = format_data_for_kb_single(fetched_data)
    formtted_data = formtted_data_all["grouped_data"]
    local_name = formtted_data_all["localname"]

    str_cat = get_category_value(formtted_data)

    tissue_sample_doner = fetch_knowledge_base(extract_data_doner_tissuesample_match_query(str_cat, param))
    tissue_donor_data = tissue_sample_doner["message"]["results"]["bindings"]

    species_value_match_in_gars = [item["species_value_match_in_gars"]["value"] for item in tissue_donor_data if
                                   item["species_value_match_in_gars"]["value"]]

    matched_nimp_gars_data = format_gars_data_for_kb_single(species_value_match_in_gars, fetch_knowledge_base)

    matched_donor_tissue_details_dict = donor_tissues_data_for_kb_single(tissue_donor_data)

    matched_donor_data = format_donor_for_kb_single(matched_donor_tissue_details_dict["donor"], fetch_knowledge_base)

    structure_value_match_in_ansrs = [item["structure_value_match_in_ansrs"]["value"] for item in tissue_donor_data if
                                      item["structure_value_match_in_ansrs"]["value"]]

    matched_nimp_ansrs_data = format_ansrs_data_for_kb_single(structure_value_match_in_ansrs, fetch_knowledge_base)

    context = {
        "uri_param": param,
        "label": label,
        "local_name": local_name,
        "fetched_data": formtted_data,
        "category": get_category_value(formtted_data),
        "matched_donor_data": matched_donor_data,
        "tissuesample_info": matched_donor_tissue_details_dict["tissuesample"],
        "matched_nimp_gars_data": matched_nimp_gars_data,
        "matched_nimp_ansrs_data": matched_nimp_ansrs_data

    }
    return render(request, "pages/knowledge-base-single.html", context=context)


def get_doner_data_ajax(request):
    donor_id = request.GET.get("doner_id")
    try:
        retrieved_doner_data = fetch_knowledge_base(get_donor_data_by_id(donor_id))["message"]["results"]["bindings"]
    except TypeError as e:
        print(e)

    data = {
        'data': doner_tissue_to_js(retrieved_doner_data)
    }
    return JsonResponse(data)


def get_tissuesample_data_ajax(request):
    tissue_id = request.GET.get("tissue_id")
    try:
        retrieved_tissue_data = fetch_knowledge_base(get_tissuesample_data_by_id(tissue_id))["message"]["results"][
            "bindings"]
    except TypeError as e:
        print(e)

    data = {
        'data': doner_tissue_to_js(retrieved_tissue_data)
    }
    return JsonResponse(data)


def knowledge_base_slug(request, slug):
    kbobj = KnowledgeBaseViewerModel.objects.all().filter(slug=slug)
    other_items = KnowledgeBaseViewerModel.objects.all().filter(status_active=True).order_by("-default_kb")
    context = get_knowledge_base(kbobj=kbobj)
    context["menu_items"] = other_items
    return render(request,
                  "pages/knowledge-base.html", context=context)


def extract_ids(results):
    genome_ids = []
    for ids in results["message"]["results"]["bindings"]:
        genome_ids.append(ids["id"]["value"])
    return genome_ids


def species_entity_card(request, slug):
    offset = request.GET.get("offset")
    offset = 0 if offset is None else int(offset)
    original_slug = slug.replace('-', ':').lower()
    genome_matches = fetch_knowledge_base(
        all_species_genome_by_taxon(
            taxon_id=original_slug,
            offset=offset
        )
    )

    all_matching_genome = fetch_knowledge_base(
        fetch_all_matching_genome_info_query(
            extract_ids(genome_matches)
        )
    )
    pagination_count = fetch_knowledge_base(
        species_pagination_count_by_taxon(
            taxon_id=original_slug
        )
    )
    try:
        species_data = format_species_annotation_data(all_matching_genome["message"]["results"]["bindings"])
        paginated_data = np.arange(0, int(pagination_count["message"]["results"]["bindings"][0]["count"]["value"]), 100)
    except KeyError as e:
        pass

    context = {
        "all_species_gene_data": species_data,
        "paginated_data": paginated_data,
        "slug": slug
    }
    return render(request,
                  "pages/entity-card-species.html", context=context)


def evidence(request):
    other_items = KnowledgeBaseViewerModel.objects.all().filter(status_active=True).order_by("-default_kb")

    context = {"menu_items": other_items}
    return render(request, "pages/evidence.html", context)


def assertion(request):
    other_items = KnowledgeBaseViewerModel.objects.all().filter(status_active=True).order_by("-default_kb")

    context = {"menu_items": other_items}
    return render(request, "pages/assertion.html", context)


def about(request):
    return render(request, "pages/about.html")


def documentation(request):
    return render(request, "pages/documentation.html")
