def load_text_file(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


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
