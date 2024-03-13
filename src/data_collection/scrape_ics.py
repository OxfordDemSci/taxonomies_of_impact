import itertools
import re
import os
import numpy as np
import pandas as pd
import fitz
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from pathlib import Path
import json
import time


def extract_based_on_indices(text, indices_1, indices_2):
        indices = dict(zip(indices_1, indices_2))

        result = [text[(key+1):value] for key, value in indices.items()]
        result = list(itertools.chain.from_iterable(result))
        result = [n.strip() for n in result if n != '']
        return result


def read_pdf_and_perform_regex(pdf_path):
    # Open the PDF file
    doc = fitz.open(pdf_path)
    
    # Get first page
    rel_text = doc[0].get_text().split('\n')
    
    # Clean lines
    rel_text = [r.strip() for r in rel_text]
    clean_text = [re.sub(r'\d{1}B', '', r) for r in rel_text]
    clean_text = [re.sub(r'^Name.*', 'Name:', string) for string in clean_text]
    clean_text = [re.sub(r'^Role.*', 'Role:', string) for string in clean_text]
    clean_text = [re.sub(r'^Period.*undertaken', 'Start:', string) for string in clean_text]
    clean_text = [re.sub(r'^Period when the claimed.*', 'End:', string) for string in clean_text]
    clean_text = [re.sub(r'^Period.*', 'Period:', string) for string in clean_text]
    clean_text = [re.sub(r'\\s+', '', string) for string in clean_text]
    clean_text = [string for string in clean_text if string != '']
    clean_text = [string for string in clean_text if string != 'submitting HEI:']
    
    # Find all occurrences of "Name:" and "Role:" and end index
    name_indices = [i for i, string in enumerate(clean_text) if re.match(r'^Name:', string)]
    role_indices = [i for i, string in enumerate(clean_text) if re.match(r'^Role:', string)]
    period_indices = [i for i, string in enumerate(clean_text) if re.match(r'^Period:', string)]
    end_indices = [i for i, string in enumerate(clean_text) if re.match(r'^End:', string)]
    if end_indices == []:
        end_indices = [i for i, string in enumerate(clean_text) if re.match(r'1. Summary', string)]
    
    if name_indices and role_indices:
        names = extract_based_on_indices(clean_text, name_indices, role_indices)
    else:
        print("No names")
        print(p)
        names = None
    
    if role_indices and period_indices:
        roles = extract_based_on_indices(clean_text, role_indices, period_indices)
    else:
        print("No roles")
        print(p)
        roles = None
    
    if period_indices and end_indices:
        periods = extract_based_on_indices(clean_text, period_indices, end_indices)
        periods = [p for p in periods if p != 'by' and p != 'employed']
    else:
        print("No periods")
        print(p)
        periods = None
    
    # In some cases there are weird anomalies. Then just extract everything between "Names" and the next section
    if names == []:
        names = rel_text[name_indices[0]:end_indices[0]]
        names = [n for n in names if n != '' and not re.match(r' HEI:|Period when|Details of|^Name(s)|^Roles(s)', n)]
    
    # Close document
    doc.close()
    
    return {'names': names,
            'roles': roles,
            'periods': periods,
            'raw': clean_text[:end_indices[0]]}


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
    
    # urls
    head = 'https://results2021.ref.ac.uk/impact/'

    # setup emtpy dicts for the results
    grant_dict = dict()
    aux_dict = dict()
    result_dict = dict()
    
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
        result_dict[cw_key]= read_pdf_and_perform_regex(output_path / p)

    ## Write names
    with open(output_path / 'author_data.jsonl', 'w') as file:
        for key, value in result_dict.items():
            json_line = json.dumps({key: value['names']})
            file.write(json_line + '\n')

    ## Write roles
    with open(output_path / 'role_data.jsonl', 'w') as file:
        for key, value in result_dict.items():
            json_line = json.dumps({key: value['roles']})
            file.write(json_line + '\n')
    
    ## Write periods
    with open(output_path / 'period_data.jsonl', 'w') as file:
        for key, value in result_dict.items():
            json_line = json.dumps({key: value['periods']})
            file.write(json_line + '\n')
    
    ## Write raw
    with open(output_path / 'raw_data.jsonl', 'w') as file:
        for key, value in result_dict.items():
            json_line = json.dumps({key: value['raw']})
            file.write(json_line + '\n')
    
    ## Write aux
    with open(output_path / 'aux_data.jsonl', 'w') as file:
        for key, value in aux_dict.items():
            json_line = json.dumps({key: value})
            file.write(json_line + '\n')

    ## Write grants
    with open(output_path / 'grant_data.jsonl', 'w') as file:
        for key, value in grant_dict.items():
            json_str = json.dumps({key: value})
            file.write(json_str + '\n')
    
    ## Write excel version
    df_list = []
    
    for key, value in result_dict.items():
        try:
            formatted = [[key, i] for i in result_dict[key]['names']]
        except:
            formatted = [[key, "None"]]
        
        df_list.append(pd.DataFrame(formatted))

    pd.concat(df_list).rename(columns = {0: 'key', 1: 'author'}).\
        to_excel(output_path / 'author_data.xlsx')
    
