## @file ingestion.py
# @brief Document ingestion pipeline: multi-format loading, chunking with
# overlap and embedding generation.

import os
from pypdf import PdfReader
from docx import Document

## @brief Task prefixes expected by nomic-embed-text: documents and queries
# are embedded differently, which noticeably improves retrieval.
DOCUMENT_PREFIX = "search_document: "
## @brief Prefix of the search queries, see DOCUMENT_PREFIX.
QUERY_PREFIX = "search_query: "
## @brief Add the nomic task prefix when the embedding model expects one.
#
# Other models (bge-m3, paraphrase-multilingual) were not trained with
# these prefixes: for them the text is embedded as-is.
#
# @param client Ollama client, whose embedding_model is checked.
# @param prefix DOCUMENT_PREFIX or QUERY_PREFIX.
# @param text Text to embed.
# @return The text to send to the embedding model.
def with_prefix(client, prefix, text):
    if "nomic" in getattr(client, "embedding_model", ""):
        return prefix + text
    return text


## @brief Extensions accepted by the ingestion pipeline.
SUPPORTED_EXTENSIONS = (".txt", ".md", ".pdf", ".docx")

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


## @brief Load a document based on its extension (.txt, .md, .pdf, .docx).
#
# @param path Path of the file.
# @return Full text of the document.
# @exception ValueError If the format is not supported.
def load_document(path):
    ext = os.path.splitext(path)[1].lower()

    if ext in (".txt", ".md"):
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
        end = min(start + chunk_size, len(text))
        # Cut on a space rather than in the middle of a word
        if end < len(text):
            space = text.rfind(" ", start + chunk_size // 2, end)
            if space != -1:
                end = space
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        # The overlap starts on a word too: move to the next space
        next_start = max(end - overlap, start + 1)
        space = text.find(" ", next_start, end)
        start = space + 1 if space != -1 and text[next_start - 1] != " " else next_start

    return chunks

## @brief Split a Markdown document along its headings.
#
# A fixed-size chunk often straddles two sections ("setup PC" and "rules"):
# its embedding then matches neither question well. Here each chunk is one
# section, prefixed with its heading path ("FAQ > Setup PC") so that even a
# short section carries its topic. A section longer than chunk_size is
# split again with chunk_text().
#
# @param text Markdown text.
# @param chunk_size Maximum size of a chunk, in characters.
# @param overlap Overlap used when a section has to be split.
# @return List of chunks.
def chunk_markdown(text, chunk_size=500, overlap=50):
    chunks = []
    titles = []
    body = []

    def flush():
        content = "\n".join(body).strip()
        if not content:
            return
        heading = " > ".join(titles)
        for part in chunk_text(content, chunk_size, overlap):
            chunks.append(f"{heading}\n{part}" if heading else part)

    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("#"):
            flush()
            body = []
            level = len(stripped) - len(stripped.lstrip("#"))
            titles = titles[:level - 1] + [stripped.lstrip("#").strip()]
        else:
            body.append(line)
    flush()
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
        vector = client.embed(with_prefix(client, DOCUMENT_PREFIX, chunk))
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
    if path.lower().endswith(".md"):
        chunks = chunk_markdown(text, chunk_size=chunk_size, overlap=overlap)
    else:
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
    results = {}

    for filename in sorted(os.listdir(folder_path)):
        ext = os.path.splitext(filename)[1].lower()
        if ext not in SUPPORTED_EXTENSIONS:
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
