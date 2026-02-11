#
# pip install chromadb openai langchain-text-splitters
#
from functools import wraps
from pathlib import Path
from typing import Iterable, Any

import chromadb
from chromadb.utils.embedding_functions import OpenAIEmbeddingFunction
from langchain_text_splitters import RecursiveCharacterTextSplitter

TEXT_EXTS = {
    ".txt", ".md", ".rst",
    ".py", ".js", ".ts", ".java", ".go", ".rs",
    ".html", ".css", ".json", ".yaml", ".yml",
    ".toml", ".ini", ".cfg",
}


def iter_files(root: Path) -> Iterable[Path]:
    for p in root.rglob("*"):
        if p.is_file() and p.suffix.lower() in TEXT_EXTS:
            yield p


def read_text(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return p.read_text(encoding="utf-8", errors="ignore")


def ingest_folder(
        persist_dir: str,  # path to chromaDB dir
        chroma_collection_name: str,  # which collection to ingest to
        folder: str,  # folder to ingest
        openai_model: str = "text-embedding-3-small",
        chunk_size: int = 1200,
        chunk_overlap: int = 150,
        batch_size: int = 256,
) -> None:
    root = Path(folder).expanduser().resolve()
    if not root.is_dir():
        raise SystemExit(f"Not a directory: {root}")

    # Persistent DB
    client = chromadb.PersistentClient(path=persist_dir)

    # OpenAI embeddings (uses OPENAI_API_KEY env var by default)
    openai_ef = OpenAIEmbeddingFunction(model_name=openai_model)

    collection = client.get_or_create_collection(
        name=chroma_collection_name,
        embedding_function=openai_ef,
    )

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        length_function=len,
        is_separator_regex=False,
    )

    ids: list[str] = []
    docs: list[str] = []
    metas: list[dict[str, Any]] = []

    added = 0

    for file_path in iter_files(root):
        text = read_text(file_path)
        if not text.strip():
            continue

        rel_path = str(file_path.relative_to(root))
        collection_id = file_path.parent.name  # containing folder name

        chunks = splitter.split_text(text)

        for i, chunk in enumerate(chunks):
            chunk_id = f"{rel_path}::chunk_{i}"  # unique per file+chunk
            ids.append(chunk_id)
            docs.append(chunk)
            metas.append(
                {
                    "filename": file_path.name,
                    "chunk_index": i,
                    "collection_id": collection_id,
                    "rel_path": rel_path,
                }
            )

        if len(ids) >= batch_size:
            collection.add(ids=ids, documents=docs, metadatas=metas)
            added += len(ids)
            ids, docs, metas = [], [], []

    if ids:
        collection.add(ids=ids, documents=docs, metadatas=metas)
        added += len(ids)

    print(f"Ingested {added} chunks into '{chroma_collection_name}' (persisted at '{persist_dir}').")


def _get_whole_documents(
        collection,
        filenames: list[str]
) -> list[str]:
    whole_docs = []
    for filename in set(filenames):
        got = collection.get(
            where={"filename": filename},
            include=["documents", "metadatas"],
        )
        pairs = list(zip(got["documents"], got["metadatas"]))
        pairs.sort(key=lambda x: x[1]["chunk_index"])
        full_text = "".join(t for t, _ in pairs)
        whole_docs.append(full_text)
    return whole_docs


def query_whole_documents(
        chroma_dir: str,
        collection: str,
        query: str,
        n_results: int = 5,
) -> list[str]:
    client = chromadb.PersistentClient(path=chroma_dir)
    collection = client.get_collection(name=collection)

    # 1) Find best matching chunk
    q = collection.query(
        query_texts=[query],
        n_results=n_results,
        include=["metadatas"],
    )

    # 2) Fetch and stitch all chunks for that doc_id
    filenames = [meta['filename'] for meta in q['metadatas'][0]]
    docs = _get_whole_documents(collection, filenames)

    return docs


@wraps(query_whole_documents)
def _cli_query(
        *args, **kwargs
):
    return '\n\n'.join([doc[:300] for doc in query_whole_documents(*args, **kwargs)])


if __name__ == "__main__":
    import fire

    fire.Fire({
        'ingest': ingest_folder,
        'query': _cli_query
    })
