import itertools
import re
import os
import numpy as np
import pandas as pd
import fitz
import jsonlines
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from pathlib import Path
import json
import time

def read_pdf_and_perform_regex_v2(pdf_path):
    # Open the PDF file
    doc = fitz.open(pdf_path)
    
    # Get first page
    rel_text = doc[0].get_text().split('\n')
    
    # Clean lines
    rel_text = [r.strip() for r in rel_text]
    clean_text = [re.sub(r'\d{1}B', '', r) for r in rel_text]
    clean_text = [re.sub(r'^Name.*', 'Name:', string) for string in clean_text]
    clean_text = [re.sub(r'^Role.*', 'Role:', string) for string in clean_text]

    # Find all occurrences of "Name:" and "Role:"
    name_indices = [i for i, string in enumerate(clean_text) if re.match(r'^Name:', string)]
    role_indices = [i for i, string in enumerate(clean_text) if re.match(r'^Role:', string)]

    if name_indices:
        indices = dict(zip(name_indices, role_indices))

        names = [clean_text[(key+1):value] for key, value in indices.items()]
        names = list(itertools.chain.from_iterable(names))
        names = [n.strip() for n in names if n != '']
    else:
        print(p)
        names = None
    
    # In some cases there are weird anomalies. Then just extract everything between "Names" and the next section
    if names == []:
        alt_index = [i for i, string in enumerate(clean_text) if re.match(r'^Period when the claimed', string)]
        if alt_index == []:
            alt_index = [i for i, string in enumerate(clean_text) if re.match(r'1. Summary of the impact', string)]
        names = rel_text[name_indices[0]:alt_index[0]]
    
    # Close document
    doc.close()
    
    return names



def download_pdf_from_url(driver):
    potential_elements = driver.find_elements(By.TAG_NAME, 'a')
    pattern = re.compile(r"Download case study PDF")
    button = [p for p in potential_elements if pattern.search(p.text)][0]
    button.click()


def scrape_secondary_info_from_url(driver):
    try:
        secondary_table = driver.find_elements(By.CLASS_NAME, "impact-metadata")
        element = secondary_table[1]
        
        # Find all <dt> elements within the <dl> element
        dt_elements = element.find_elements(By.TAG_NAME, 'dt')

        # Initialize a list to hold the text of each <dt> element
        dt_texts = [dt.text for dt in dt_elements]
        
        # Find all <dd> elements within the <dl> element
        dd_elements = element.find_elements(By.TAG_NAME, 'dd')

        # Initialize a list to hold the text of each <dd> element
        dd_texts = [dd.text for dd in dd_elements]
        
        return dict(zip(dt_texts, dd_texts))
    except:
        return "None"


def scrape_grant_info_from_url(driver):
    try:
        grant_funding_table = driver.find_element(
            By.XPATH, "//h4[text()='Grant funding']/following-sibling::table")
        return grant_funding_table.text
    except:
        return "None"


def make_or_load_cw(path, keys):
    file_path = path / 'cw_pdf_key.jsonl'
    if os.path.exists(file_path):
        # Reading JSON Lines file
        with open(file_path, 'r') as f:
            cw = json.load(f)
        
    else:
        pdf_files = [pdf for pdf in os.listdir(path) if '.pdf' in pdf]
        pdf_files_by_cd = sorted(pdf_files, key=lambda x: os.path.getmtime(os.path.join(output_path, x)))

        cw = dict(zip(pdf_files_by_cd, keys))
        
        with open(file_path, 'w') as f:
            json.dump(cw, f)
    
    return cw


if __name__ == "__main__":

    # Paths
    current_file = Path(__file__).resolve()
    project_root = current_file.parent
    while not (project_root / '.git').exists():
        project_root = project_root.parent

    data_path = project_root / 'data'
    output_path = data_path /  'ics_pdfs'

    # Set up Chrome options
    chrome_options = Options()
    prefs = {"download.default_directory" : str(output_path)}
    chrome_options.add_experimental_option("prefs", prefs)

    # Initialize WebDriver
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)

    # Read data
    data = pd.read_csv(data_path / 'final' / 'enhanced_ref_data.csv')
    keys = data['REF impact case study identifier']

    data.loc[data['REF impact case study identifier'] == '1e6e075e-d5f5-421c-bb45-2708636b5190']
    
    # urls
    head = 'https://results2021.ref.ac.uk/impact/'

    # setup emtpy dicts for the results
    grant_dict = dict()
    aux_dict = dict()
    names_dict = dict()
    
    for key in keys:
        print(key)
        url = head + key
        driver.get(url)
        time.sleep(1)
        
        ## download pdf
        download_pdf_from_url(driver)
        
        ## collect info
        aux_dict[key] = scrape_secondary_info_from_url(driver)
        grant_dict[key] = scrape_grant_info_from_url(driver)

    cw = make_or_load_cw(output_path, keys)
    
    ## Read pdfs
    for p in cw.keys():
        cw_key = cw[p]
        names_dict[cw_key]= read_pdf_and_perform_regex_v2(output_path / p)

    ## Write results
    with open(output_path / 'author_data.jsonl', 'w') as file:
        for key, value in names_dict.items():
            json_line = json.dumps({key: value})
            file.write(json_line + '\n')

    # Find the maximum length among all lists
    max_length = max([len(value) for key, value in names_dict.items() if value])

    # Add elements to each list to make them the same length as the maximum length
    names_dict_df = names_dict
    for key, value in names_dict_df.items():
        if not value:
            names_dict[key] = [None for i in range(max_length)]
        else:
            while len(value) < max_length:
                value.append(None)  # You can use any default value you want
            
    df = pd.DataFrame([value for key, value in names_dict_df.items()],
                      index = keys)
    
    df.to_excel(output_path / 'author_data.xlsx')
    
    with open(output_path / 'aux_data.jsonl', 'w') as file:
        for key, value in aux_dict.items():
            json_line = json.dumps({key: value})
            file.write(json_line + '\n')

    with open(output_path / 'grant_data.jsonl', 'w') as file:
        for key, value in grant_dict.items():
            json_str = json.dumps({key: value})
            file.write(json_str + '\n')