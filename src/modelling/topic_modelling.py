import os
import sys
import re
import shutil
from collections import Counter
from pathlib import Path
from typing import List, Union

import numpy
import pandas
import warnings

from bs4 import BeautifulSoup
from loguru import logger
from sentence_transformers import SentenceTransformer
from sklearn.metrics import silhouette_score

from bertopic import BERTopic
from bertopic.representation import KeyBERTInspired
from bertopic.vectorizers import ClassTfidfTransformer

from sklearn.feature_extraction.text import CountVectorizer

from cuml.cluster import HDBSCAN
from cuml.manifold import UMAP

import markdown


cols = [
    "1. Summary of the impact",
    "2. Underpinning research",
    "3. References to the research",
    "4. Details of the impact",
    "5. Sources to corroborate the impact",
]


def clean_free_text(s: str):
    content = markdown.markdown(s)
    soup = BeautifulSoup(content, "html.parser")
    s = soup.get_text()
    s = s.lower()
    s = re.sub(r"http\S+", "", s)
    s = re.sub("[^a-zA-Z]+", " ", s)
    # Note: re.sub to a-zA-Z means that the following regex for X words doesnt hit
    s = s.replace("summary of the impact indicative maximum 100 words ", "")
    s = s.replace("summary of the impact ", "")
    s = s.replace("underpinning research indicative maximum 500 words ", "")
    s = s.replace("underpinning research ", "")
    s = s.replace(
        "references to the research indicative maximum of six references ", ""
    )
    s = s.replace("references to the research ", "")
    s = s.replace("details of the impact indicative maximum 750 words ", "")
    s = s.replace("details of the impact ", "")

    s = s.replace(
        "sources to corroborate the impact indicative maximum of 10 references ", ""
    )
    s = s.replace("sources to corroborate the impact ", "")

    # New after ngram searches, noting issues with above:
    s = s.replace('indicative maximum of six references', '')
    s = s.replace('indicative maximum words', '')
    s = s.replace('indicative maximum of references', '')
    s = s.replace("text redacted for publication", "")
    s = s.replace('text redacted', '')
    s = s.replace("text removed for publication", "")
    s = s.replace("supplied by hei on request", "")
    return s.strip()

def make_freqs(df_to_clean, ngrams):
    logger.info(f'Calculating {ngrams}-gram frequencies')
    word_vectorizer = CountVectorizer(ngram_range=(ngrams, ngrams), analyzer='word')
    sparse_matrix = word_vectorizer.fit_transform(df_to_clean["cleaned_full_text"])
    frequencies = sum(sparse_matrix).toarray()[0]
    df_to_clean = pandas.DataFrame(frequencies,
                                   index=word_vectorizer.get_feature_names_out(),
                                   columns=['frequency']).sort_values(by='frequency',
                                                                      ascending=False)
    csv_path = os.path.join(os.getcwd(),
                            'data',
                            'text_processed',
                            f'{ngrams}-gram_frequencies.csv')
    df_to_clean.to_csv(csv_path)


def prepare_full_texts(excel_path: Union[str, Path], col_index: List[int]):
    df = pandas.read_excel(excel_path)
    columns_to_use = [cols[i] for i in col_index]
    df["full_text"] = df.apply(
        lambda row: "\n".join(str(row[col]) for col in columns_to_use), axis=1
    )
    df["cleaned_full_text"] = df["full_text"].apply(clean_free_text)
    df = df[df['REF impact case study identifier'].notnull()]
    if sys.argv[4] == "Calculate_Frequencies":
        if all(i in col_index for i in range(0, 5)):
            logger.info('Making ngrams/cleaned dataset for inspection on full col_index')
            for n in range(1, 6):
                make_freqs(df.copy(), n)
            output_path = os.path.join(os.getcwd(),
                                       'data',
                                       'text_processed',
                                       'text_processed.xlsx')
            df.to_excel(output_path)
    return df


def run_bert(
    df: pandas.DataFrame,
    docs: List[str],
    embedding_model: SentenceTransformer,
    embeddings: numpy.ndarray,
    target_dir: Union[str, Path],
    col_str: str,
    n_neighbors: int = 15,
    nr_topics: Union[None, str, int] = "auto",
    random_state: int = 77,
):
    model_dir = Path(target_dir) / "models"
    output_dir = Path(target_dir) / "output"
    fig_dir = Path(target_dir) / "figures"
    if os.path.exists(model_dir) is False:
        model_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Created model directory at: {model_dir.absolute()}")
    if os.path.exists(output_dir) is False:
        output_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Created output directory at: {output_dir.absolute()}")
    if os.path.exists(fig_dir) is False:
        fig_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Created figure directory at: {fig_dir.absolute()}")
    model_name = f'nn{n_neighbors}{f"_nr{nr_topics}" if nr_topics is not None else ""}_{col_str}'
    path_metadata_csv = Path(target_dir) / "metadata.csv"
    representation_model = KeyBERTInspired()
    umap_model = UMAP(
        n_neighbors=n_neighbors,
        n_components=5,
        init="random",
        min_dist=0.0,
        metric="cosine",
        random_state=random_state,
    )
    hsdb_model = HDBSCAN(
        min_cluster_size=10,
        metric="euclidean",
        prediction_data=True,
    )
    ctfidf_model = ClassTfidfTransformer(reduce_frequent_words=True)
    topic_model = BERTopic(
        language="english",
        verbose=True,
        calculate_probabilities=True,
        n_gram_range=(1, 2),
        representation_model=representation_model,
        embedding_model=embedding_model,
        umap_model=umap_model,
        hdbscan_model=hsdb_model,
        ctfidf_model=ctfidf_model,
        nr_topics=nr_topics,
    )
    topics, probs = topic_model.fit_transform(docs, embeddings)
    topic_model.save(model_dir / model_name)
    topics_counter = Counter(topics)
    outliers_count = topics_counter.get(-1, 0)
    topics_count = (
        len(topics_counter) - 1 if outliers_count > 0 else len(topics_counter)
    )
    logger.info(f"Found {topics_count} topics and {outliers_count} outliers")
    df_topic_info = topic_model.get_topic_info()
    df_topic_info.to_excel(
        Path(target_dir) / "output" / f"{model_name}_topic_info.xlsx"
    )
    df["BERT_topic"] = topic_model.topics_
    df["BERT_prob"] = [max(i) for i in topic_model.probabilities_]
    df.to_excel(Path(target_dir) / "output" / f"{model_name}.xlsx")
    fig_topic = topic_model.visualize_documents(
        docs, hide_document_hover=True, hide_annotations=True
    )
    fig_topic.write_html(fig_dir.joinpath(f"{model_name}.html"))
    fig_topic_hierarchy = topic_model.visualize_hierarchy()
    fig_topic_hierarchy.write_html(fig_dir.joinpath(f"{model_name}_hierarchy.html"))
    silhouette = calculate_silhouette_score(
        topic_model, embeddings, topic_model.topics_
    )
    metadata = {
        "random_state": random_state,
        "n_neighbors": n_neighbors,
        "nr_topics": nr_topics,
        "topics_count": topics_count,
        "outliers_count": outliers_count,
        "columns": col_str,
        "silhouette_score": silhouette
    }
    logger.info(metadata)
    pandas.DataFrame([metadata]).to_csv(
        path_metadata_csv,
        mode="a",
        header=not path_metadata_csv.exists(),
        index=False,
    )


def calculate_silhouette_score(topic_model, embeddings, topics):
    umap_embeddings = topic_model.umap_model.transform(embeddings)
    indices = [index for index, topic in enumerate(topics) if topic != -1]
    X = umap_embeddings[numpy.array(indices)]
    labels = [topic for topic in topics if topic != -1]
    return silhouette_score(X, labels)


if __name__ == "__main__":
    if sys.argv[3] == 'Clean_Run':
        try:
            shutil.rmtree(sys.argv[2])
            print(f"Directory '{sys.argv[2]}' and its contents deleted successfully.")
        except OSError as e:
            print(f"Error deleting directory '{sys.argv[2]}': {e}")
    embedding_model = SentenceTransformer("all-MiniLM-L6-v2")
    nn_range = range(2, 27)
    for col_str, col_index in ({
        'column12345': [0, 1, 2, 3, 4],
        'columns1': [0],
        'columns2': [1],
        'columns3': [2],
        'columns4': [3],
        'columns5': [4],
        'columns23': [1, 2],
        'columns45': [3, 4],
        'columns124': [0, 1, 3]
    }).items():
        df = prepare_full_texts(sys.argv[1], col_index)
        docs = df["cleaned_full_text"].tolist()
        embeddings = embedding_model.encode(docs, show_progress_bar=True)
        for i in nn_range:
            logger.info(f"Running neighbors: {i} with columns: {col_str}")
            run_bert(
                df,
                docs,
                embedding_model,
                embeddings,
                sys.argv[2],
                col_str,
                n_neighbors=i,
                nr_topics=None,
            )
        logger.info(f"Finished running BERTopic for {col_str}")
