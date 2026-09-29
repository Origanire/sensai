import os
from pypdf import PdfReader
from docx import Document


def load_txt(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def load_pdf(path):
    reader = PdfReader(path)
    text = ""
    for page in reader.pages:
        page_text = page.extract_text()
        if page_text:
            text += page_text + "\n"
    return text


def load_docx(path):
    doc = Document(path)
    return "\n".join(p.text for p in doc.paragraphs)


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


def chunk_text(text, chunk_size=500, overlap=50):
    chunks = []
    start = 0

    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]
        chunks.append(chunk)
        start += chunk_size - overlap

    return chunks

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


def ingest_file(path, client, chunk_size=500, overlap=50):
    text = load_document(path)
    chunks = chunk_text(text, chunk_size=chunk_size, overlap=overlap)
    return embed_chunks(chunks, client)


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
