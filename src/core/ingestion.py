# Ce module lit les documents, les découpe en passages et calcule leurs représentations numériques pour la recherche.

import os
from pypdf import PdfReader
from docx import Document

# Ces préfixes aident nomic-embed-text à distinguer les documents des questions.
DOCUMENT_PREFIX = "search_document: "
# Ce préfixe indique une question au modèle de recherche.
QUERY_PREFIX = "search_query: "
# Cette fonction ajoute un préfixe seulement si le modèle utilisé en a besoin.
def with_prefix(client, prefix, text):
    if "nomic" in getattr(client, "embedding_model", ""):
        return prefix + text
    return text


# Ces extensions correspondent aux formats de documents acceptés.
SUPPORTED_EXTENSIONS = (".txt", ".md", ".pdf", ".docx")

# Cette fonction lit un fichier texte en UTF-8.
def load_txt(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


# Cette fonction extrait le texte d’un PDF, page par page.
def load_pdf(path):
    reader = PdfReader(path)
    text = ""
    for page in reader.pages:
        page_text = page.extract_text()
        if page_text:
            text += page_text + "\n"
    return text


# Cette fonction récupère les paragraphes d’un document Word.
def load_docx(path):
    doc = Document(path)
    return "\n".join(p.text for p in doc.paragraphs)


# Cette fonction choisit le lecteur adapté au format du document et refuse les formats inconnus.
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


# Cette fonction découpe le texte en passages qui se recouvrent pour conserver le contexte.
def chunk_text(text, chunk_size=500, overlap=50):
    chunks = []
    start = 0

    while start < len(text):
        end = min(start + chunk_size, len(text))
        # On coupe sur un espace pour ne pas casser un mot.
        if end < len(text):
            space = text.rfind(" ", start + chunk_size // 2, end)
            if space != -1:
                end = space
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        # Le recouvrement commence aussi au début d’un mot.
        next_start = max(end - overlap, start + 1)
        space = text.find(" ", next_start, end)
        start = space + 1 if space != -1 and text[next_start - 1] != " " else next_start

    return chunks

# Cette fonction découpe le Markdown par section et conserve les titres pour faciliter la recherche.
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


# Cette fonction calcule la représentation numérique de chaque passage avec Ollama et ignore les passages en échec.
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


# Cette fonction prépare un document pour la recherche : lecture, découpage et calcul des vecteurs.
def ingest_file(path, client, chunk_size=500, overlap=50):
    text = load_document(path)
    if path.lower().endswith(".md"):
        chunks = chunk_markdown(text, chunk_size=chunk_size, overlap=overlap)
    else:
        chunks = chunk_text(text, chunk_size=chunk_size, overlap=overlap)
    return embed_chunks(chunks, client)


# Cette fonction prépare tous les documents compatibles d’un dossier, sans bloquer les autres si un fichier échoue.
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
