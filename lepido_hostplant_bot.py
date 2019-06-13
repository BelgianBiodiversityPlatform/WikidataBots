# -*- coding: utf-8  -*-
import functools
import logging
import sys
from logging import warning
from typing import Any, Dict, List, Optional

import coloredlogs
import requests
import datetime

sys.path.append('/Users/nicolasnoe/pywikibot'); import pywikibot

CATALOGUE_SPECIES_DETAILS_ENDPOINT = "https://projects.biodiversity.be/lepidoptera/all_species_details_json/"
LOGLEVEL = 'WARNING'

WIKIDATA_SPARQL_ENDPOINT = 'https://query.wikidata.org/bigdata/namespace/wdq/sparql'
TAXON_RANK_PROPERTY_ID = 'P105'
TAXON_NAME_PROPERTY_ID = 'P225'
HOST_PROPERTY_ID = 'P2975'
SPECIES_VALUE_ID = 'Q7432'

CATALOGUE_Q_VALUE = 'Q59799645'
STATED_IN_PROPERTY_ID = 'P248'
RETRIEVED_PROPERTY_ID = 'P813'

TEST_MODE = False
TEST_MODE_LIMIT = 50  # In test mode, how many edits do we perform?

class MultipleWikidataEntriesFound(Exception):
    pass

class NoWikidataEntriesFound(Exception):
    pass

class TestModeCompleted(Exception):
    pass

@functools.lru_cache(maxsize=4096)
def get_wikidata_q_identifier(species_name=None, lepido_id=None):
    # If a species name is passed, search is performed on it.
    # If a lepidoptera id is passed, search is performed on it.

    # If used with a species name, can be used for all kind of species (not only lepidoptera)

    if species_name:
        # We previously searched on the label, but this one is often sets 
        # to some vernacular name. Taxon name seems very often populated, 
        # so it seems it's a better candidate.
        query = f'''SELECT ?item ?itemLabel WHERE {{
            ?item wdt:{TAXON_NAME_PROPERTY_ID} "{species_name}". 
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


def get_wikidata_data(q_code: str) -> Dict[str, Any]:
    global repo

    item = pywikibot.ItemPage(repo, q_code)
    return item.get()

@functools.lru_cache() # We can cache it since the script will not run on multiple days
def build_sources_claims() -> List[pywikibot.Claim]:
    global repo

    # It's stated in the catalogue of lepidoptera of Belgium
    statedin = pywikibot.Claim(repo, STATED_IN_PROPERTY_ID)
    catalogue_lepido_belgium = pywikibot.ItemPage(repo, CATALOGUE_Q_VALUE)
    statedin.setTarget(catalogue_lepido_belgium)

    retrieved = pywikibot.Claim(repo, RETRIEVED_PROPERTY_ID)
    today = datetime.datetime.today()
    date = pywikibot.WbTime(year=today.year, month=today.month, day=today.day)
    retrieved.setTarget(date)

    return [statedin, retrieved]

def add_claim(target_item_q_code: str, property_id: str, property_value_q_code: str, summary:str, sources:Optional[List[pywikibot.Claim]]=None):
    global repo

    item = pywikibot.ItemPage(repo, target_item_q_code)
    claim = pywikibot.Claim(repo, HOST_PROPERTY_ID)
    target = pywikibot.ItemPage(repo, property_value_q_code)
    claim.setTarget(target)
    
    if sources:
        claim.addSources(sources, summary='Adding sources.')

    item.addClaim(claim, summary=summary)

def add_host_plant_claim(lepido_q_code: str, plant_q_code: str):
    add_claim(lepido_q_code, HOST_PROPERTY_ID, plant_q_code, 'Add host plant information', sources=build_sources_claims())

def claims_reference_us(claim: pywikibot.Claim) -> bool:
    for source in claim.sources:
        if STATED_IN_PROPERTY_ID in source:
            for source_claim in source[STATED_IN_PROPERTY_ID]:
                if source_claim.target.id == CATALOGUE_Q_VALUE:
                    return True

    return False

def add_us_as_source(existing_claim: pywikibot.Claim):
    existing_claim.addSources(build_sources_claims())


def update_host_properties(lepido_q_code: str, plant_species_names: List[str]):
    global duplicate_hp_entries_counter
    global editions_counter
    global unmatched_plants_set

    # 1. Get q codes for plant species
    plant_species_q_codes = set()
    for plant_name in plant_species_names:
        try:
            plant_species_q_codes.add(get_wikidata_q_identifier(plant_name))
        except NoWikidataEntriesFound:
            if plant_name not in unmatched_plants_set:
                unmatched_plants_set.add(plant_name)
                logger.warning(f'No wikidata entry found for plant: {plant_name}')
        except MultipleWikidataEntriesFound:
            duplicate_hp_entries_counter = duplicate_hp_entries_counter + 1
            logger.warning(f'Multiple wikidata entry found for plant: {plant_name}')
    
    plant_species_q_codes_to_create = plant_species_q_codes.copy()

    # 2. For each of this plants, check if the lepidoptera has already the host property set
    lepi_data = get_wikidata_data(q_code=lepido_q_code)
    if HOST_PROPERTY_ID in lepi_data['claims']: # Wikidata already has host plants info for this lepidoptera
        logger.info("Wikidata already has some host plant info for this lepidoptera")
        # Update, if necessary
        for existing_claim in lepi_data['claims'][HOST_PROPERTY_ID]:
            # Does this claim concern a plant we also have:
                if existing_claim.target.id in plant_species_q_codes: # Yes
                    logger.info("Wikidata already knows about this lepidoptera <-> host plant relationship")
                    plant_species_q_codes_to_create.remove(existing_claim.target.id)  # In all cases, we don't need to create a new claim
                    if claims_reference_us(existing_claim):
                        logger.info("We already cited as a source -> do nothing")
                    else:
                        logger.info("We have to add us as a source for this claim")
                        add_us_as_source(existing_claim)
                        editions_counter = editions_counter + 1
                
            
    else:
        logger.info("No host plant info for this lepidoptera @Wikidata yet")
    
    for plant_species_q_code in plant_species_q_codes_to_create:
        logger.info(f"Adding host plant ({plant_species_q_code})...")
        add_host_plant_claim(lepido_q_code, plant_species_q_code)     
        editions_counter = editions_counter + 1


def import_lepidotera_data(species_data):
    global synonym_counter
    global accepted_counter
    global species_not_found_counter
    global duplicate_entries_counter
    global possible_missing_id
    global no_hostplant_data_counter
    global editions_counter
    
    species_name = species_data['name']
    species_id = species_data['id']

    if TEST_MODE and (editions_counter >= TEST_MODE_LIMIT):
        raise TestModeCompleted

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
                get_wikidata_q_identifier(species_name=species_name)
                logger.warning(f"... but we have a candidate by label. Missing lepido ID (P5862) @Wikidata?")
                possible_missing_id = possible_missing_id + 1
            except (NoWikidataEntriesFound, MultipleWikidataEntriesFound): 
                pass   

        except MultipleWikidataEntriesFound:
            duplicate_entries_counter = duplicate_entries_counter + 1
            logger.warning(f"Multiple Wikidata entries found for {species_name}. Check for Wikidata duplicates?")

def main():
    logger.info("Getting data from the catalogue of lepidoptera")

    # We iterate over accepted lepidoptera species in the catalogue
    page_num = 1

    try:
        while True:
            response = requests.get(CATALOGUE_SPECIES_DETAILS_ENDPOINT, params={'page': page_num}).json()
            
            logger.debug(f"parsing page {response['page']}. Number of results on the page: {len(response['results'])}")

            for result in response['results']:
                import_lepidotera_data(result)

            if response['hasMoreResults'] == False:
                break

            page_num = page_num + 1
    except TestModeCompleted:
        logger.info("We'll stop here because we're in test mode.")
    
    logger.info("done.")

    stats_str = f"""Stats: {synonym_counter} skipped synonyms, {no_hostplant_data_counter} species skipped because we don't have hostplant data, {accepted_counter} accepted species parsed.
    {species_not_found_counter} species not found @Wikidata.
    For {duplicate_entries_counter} species, multiple entries were found @Wikidata.
    Identified {possible_missing_id} possible cases of missing P5862 property @Wikidata.
    Host plants: {len(unmatched_plants_set)} not found @Wikidata, {duplicate_hp_entries_counter} found with duplicates

    {editions_counter} editions performed @Wikidata.
    """
    print(stats_str)


if __name__ == "__main__":
    synonym_counter = 0
    accepted_counter = 0
    species_not_found_counter = 0
    duplicate_entries_counter = 0
    possible_missing_id = 0
    no_hostplant_data_counter = 0

    duplicate_hp_entries_counter = 0

    editions_counter = 0

    unmatched_plants_set = set()

    logger = logging.getLogger(__name__)
    coloredlogs.install(level=LOGLEVEL)

    site = pywikibot.Site("wikidata", "wikidata")
    repo = site.data_repository()
    
    main()
