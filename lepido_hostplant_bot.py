# -*- coding: utf-8  -*-
import functools
import logging
import sys
from logging import warning
from typing import List

import coloredlogs
import requests

sys.path.append('/Users/nicolasnoe/pywikibot'); import pywikibot

CATALOGUE_SPECIES_DETAILS_ENDPOINT = "https://projects.biodiversity.be/lepidoptera/all_species_details_json/"
LOGLEVEL = 'INFO'

WIKIDATA_SPARQL_ENDPOINT = 'https://query.wikidata.org/bigdata/namespace/wdq/sparql'
TAXON_RANK_PROPERTY_ID = 'P105'
SPECIES_VALUE_ID = 'Q7432'

#site = pywikibot.Site("en", "wikipedia")
#page = pywikibot.Page(site, u"Douglas Adams")
#item = pywikibot.ItemPage.fromPage(page)
#dictionary = item.get()
#print(dictionary)
#print(dictionary.keys())
#print(item)

class MultipleWikidataEntriesFound(Exception):
    pass

class NoWikidataEntriesFound(Exception):
    pass

@functools.lru_cache(maxsize=4096)
def get_wikidata_q_identifier(species_name=None, lepido_id=None):
    # If a species name is passed, search is performed on it.
    # If a lepidoptera id is passed, search is performed on it.

    # If used with a species name, can be used for all kind of species (not only lepidoptera)

    if species_name:
        query = f'''SELECT ?item ?itemLabel WHERE {{
            ?item rdfs:label "{species_name}"@en.
            ?item wdt:{TAXON_RANK_PROPERTY_ID} wd:{SPECIES_VALUE_ID}.
            }}'''
    else:
        query = f'''SELECT ?item ?itemLabel WHERE {{
            ?item wdt:P5862 "{lepido_id}";
            wdt:{TAXON_RANK_PROPERTY_ID} wd:{SPECIES_VALUE_ID}.
            }}'''
    
    data = requests.get(WIKIDATA_SPARQL_ENDPOINT, params={'query': query.replace('\n', ' '), 'format': 'json'}).json()
    results = data['results']['bindings']
    if len(results) == 1:
        return results[0]['item']['value'].rsplit('/', 1)[-1]  # Get Wikidata URI, split for the Q identifier
    elif len(results) == 0:
        raise NoWikidataEntriesFound
    elif len(results) > 1:
        raise MultipleWikidataEntriesFound

def has_host_plant_species_observations(species_data):
    observations = species_data['observations']
    for observation in observations:
        if observation['observationType'] == 'HostPlantSpecies':
            return True
    return False

def update_host_properties(lepido_q_code: str, plant_species_names: List[str]):
    global hp_not_found_counter
    global duplicate_hp_entries_counter

    plant_species_q_codes = set()
    for plant_name in plant_species_names:
        try:
            plant_species_q_codes.add(get_wikidata_q_identifier(plant_name))
        except NoWikidataEntriesFound:
            hp_not_found_counter = hp_not_found_counter + 1
            logger.warning(f'No wikidata entry found for plant: {plant_name}')
        except MultipleWikidataEntriesFound:
            duplicate_hp_entries_counter = duplicate_hp_entries_counter + 1
            logger.warning(f'Multiple wikidata entry found for plant: {plant_name}')
    
    pass

def import_lepidotera_data(species_data):
    global synonym_counter
    global accepted_counter
    global species_not_found_counter
    global duplicate_entries_counter
    global possible_missing_id
    global no_hostplant_data_counter
    
    species_name = species_data['name']
    species_id = species_data['id']

    logger.info(f"Processing {species_name}...")
    if (species_data['is_synonym']):
        synonym_counter = synonym_counter + 1
        logger.info("\tSynonym, skipping.")
    elif not has_host_plant_species_observations(species_data):
        no_hostplant_data_counter = no_hostplant_data_counter + 1
        logger.info("We don't have any host plant species data, skipping.")
    else:
        accepted_counter = accepted_counter + 1
        try:
            q_code = get_wikidata_q_identifier(lepido_id=species_id)
            update_host_properties(q_code, [obs['name'] for obs in species_data['observations'] if obs['observationType'] == 'HostPlantSpecies'])
        except NoWikidataEntriesFound:
            # Not found with the ID, check if we have a candidate by name
            species_not_found_counter = species_not_found_counter + 1
            logger.warning(f"No Wikidata entry found for {species_name}")
            try:
                possible_missing_id = possible_missing_id + 1
                get_wikidata_q_identifier(species_name=species_name)
                logger.warning(f"... but we have a candidate by label. Missing lepido ID (P5862) @Wikidata?")
            except (NoWikidataEntriesFound, MultipleWikidataEntriesFound): 
                pass   

        except MultipleWikidataEntriesFound:
            duplicate_entries_counter = duplicate_entries_counter + 1
            logger.warning(f"Multiple Wikidata entries found for {species_name}. Check for Wikidata duplicates?")

def main():
    logger.info("Getting data from the catalogue of lepidoptera")

    # We iterate over accepted lepidoptera species in the catalogue
    page_num = 1

    while True:
        response = requests.get(CATALOGUE_SPECIES_DETAILS_ENDPOINT, params={'page': page_num}).json()
        
        logger.debug(f"parsing page {response['page']}. Number of results on the page: {len(response['results'])}")

        for result in response['results']:
            import_lepidotera_data(result)

        if response['hasMoreResults'] == False:
            break

        page_num = page_num + 1

    logger.info("done.")

    stats_str = f"""Stats: {synonym_counter} skipped synonyms, {no_hostplant_data_counter} species skipped because we don't have hostplant data, {accepted_counter} accepted species parsed.
    {species_not_found_counter} species not found @Wikidata.
    For {duplicate_entries_counter} species, multiple entries were found @Wikidata.
    Identified {possible_missing_id} possible cases of missing P5862 property @Wikidata.
    Host plants: {hp_not_found_counter} not found @Wikidata, {duplicate_hp_entries_counter} found with duplicates
    """
    logger.info(stats_str)


if __name__ == "__main__":
    synonym_counter = 0
    accepted_counter = 0
    species_not_found_counter = 0
    duplicate_entries_counter = 0
    possible_missing_id = 0
    no_hostplant_data_counter = 0

    hp_not_found_counter = 0
    duplicate_hp_entries_counter = 0

    logger = logging.getLogger(__name__)
    coloredlogs.install(level=LOGLEVEL)
    
    main()