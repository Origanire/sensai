## @file ingestion.py
# @brief Document ingestion pipeline: multi-format loading, chunking with
# overlap and embedding generation.

import os
from pypdf import PdfReader
from docx import Document


## @brief Load the contents of a plain text file (.txt).
#
# @param path Path of the file.
# @return Contents of the file, decoded as UTF-8.
def load_txt(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


## @brief Extract the text of a PDF file, page by page.
#
# @param path Path of the PDF file.
# @return Text extracted from all the pages.
def load_pdf(path):
    reader = PdfReader(path)
    text = ""
    for page in reader.pages:
        page_text = page.extract_text()
        if page_text:
            text += page_text + "\n"
    return text


## @brief Extract the text of a Word document (.docx).
#
# @param path Path of the DOCX file.
# @return Text of the document's paragraphs.
def load_docx(path):
    doc = Document(path)
    return "\n".join(p.text for p in doc.paragraphs)


## @brief Load a document based on its extension (.txt, .pdf, .docx).
#
# @param path Path of the file.
# @return Full text of the document.
# @exception ValueError If the format is not supported.
def load_document(path):
    ext = os.path.splitext(path)[1].lower()

    if ext == ".txt":
        return load_txt(path)
    elif ext == ".pdf":
        return load_pdf(path)
    elif ext == ".docx":
        return load_docx(path)
    else:
        raise ValueError(f"Format non supporté : {ext} (fichier : {path})")


## @brief Split a text into chunks with overlap.
#
# @param text Text to split.
# @param chunk_size Size of a chunk, in characters.
# @param overlap Number of characters carried over from the previous chunk.
# @return List of chunks.
def chunk_text(text, chunk_size=500, overlap=50):
    chunks = []
    start = 0

    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]
        chunks.append(chunk)
        start += chunk_size - overlap

    return chunks

## @brief Generate the embedding of each chunk via Ollama.
#
# Chunks whose embedding fails are silently skipped.
#
# @param chunks List of chunks (raw text).
# @param client Ollama client used for the embeddings.
# @return List of {"text", "embedding"} dicts.
def embed_chunks(chunks, client):
    embedded = []

    for chunk in chunks:
        vector = client.embed(chunk)
        if vector is not None:
            embedded.append({
                "text": chunk,
                "embedding": vector
            })

    return embedded


## @brief Full ingestion pipeline for one file: loading, chunking, embeddings.
#
# @param path Path of the file to ingest.
# @param client Ollama client used for the embeddings.
# @param chunk_size Size of a chunk, in characters.
# @param overlap Overlap between consecutive chunks.
# @return List of embedded chunks.
def ingest_file(path, client, chunk_size=500, overlap=50):
    text = load_document(path)
    chunks = chunk_text(text, chunk_size=chunk_size, overlap=overlap)
    return embed_chunks(chunks, client)


## @brief Ingest every supported document of a folder.
#
# Files in unsupported formats are skipped; the failure of one file does
# not interrupt the ingestion of the others.
#
# @param folder_path Path of the folder to ingest.
# @param client Ollama client used for the embeddings.
# @param chunk_size Size of a chunk, in characters.
# @param overlap Overlap between consecutive chunks.
# @return Dict {filename: embedded_chunks}.
def ingest_folder(folder_path, client, chunk_size=500, overlap=50):
    supported_ext = (".txt", ".pdf", ".docx")
    results = {}

    for filename in os.listdir(folder_path):
        ext = os.path.splitext(filename)[1].lower()
        if ext not in supported_ext:
            continue

        full_path = os.path.join(folder_path, filename)
        print(f"[Ingestion] {filename}...")

        try:
            embedded = ingest_file(full_path, client, chunk_size, overlap)
            results[filename] = embedded
            print(f"[Ingestion] {filename} -> {len(embedded)} chunks")
        except Exception as e:
            print(f"[Erreur] Échec sur {filename} : {e}")

    return results
