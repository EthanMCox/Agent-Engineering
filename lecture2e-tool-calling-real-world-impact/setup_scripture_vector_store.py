"""
Helper script to upload scripture files to OpenAI and create a vector store.
Run this once to set up the file search capability.

Usage:
    python setup_scripture_vector_store.py
    
This will:
1. Upload all scripture files from ../standard-works
2. Create a vector store with those files
3. Print the vector_store_id to use with toolbot_scripture.py
"""

from pathlib import Path
from openai import OpenAI

def upload_scripture_files():
    client = OpenAI()
    
    # Create a vector store
    print("Creating vector store...")
    vector_store = client.vector_stores.create(
        name="Standard Works"
    )
    
    print(f"Vector store created: {vector_store.id}")
    print("\nUploading scripture files...")
    
    # Find all scripture files
    scripture_dir = Path("../standard-works")
    file_ids = []
    
    for book_dir in scripture_dir.iterdir():
        if book_dir.is_dir():
            print(f"\nProcessing {book_dir.name}...")
            for book_file in book_dir.iterdir():
                # Skip metadata files
                if book_file.name.startswith("00"):
                    continue
                
                if book_file.is_file():
                    print(f"  Uploading {book_file.name}...")
                    
                    # Upload file to OpenAI with .txt extension
                    # OpenAI requires a valid file extension
                    with open(book_file, 'rb') as f:
                        # Create a tuple with (filename, file_content, content_type)
                        # Add .txt extension to satisfy OpenAI's requirements
                        file = client.files.create(
                            file=(f"{book_file.name}.txt", f, "text/plain"),
                            purpose='assistants'
                        )
                    
                    file_ids.append(file.id)
                    print(f"    ✓ Uploaded: {file.id}")
    
    print(f"\n{len(file_ids)} files uploaded successfully!")
    
    # Add files to vector store in batches
    print("\nAdding files to vector store...")
    batch_size = 100  # OpenAI has limits on batch size
    
    for i in range(0, len(file_ids), batch_size):
        batch = file_ids[i:i + batch_size]
        client.vector_stores.file_batches.create(
            vector_store_id=vector_store.id,
            file_ids=batch
        )
        print(f"  Added batch {i//batch_size + 1} ({len(batch)} files)")
    
    print("\n" + "="*60)
    print("SETUP COMPLETE!")
    print("="*60)
    print(f"\nYour vector store ID is: {vector_store.id}")
    print("\nTo use it, run:")
    print(f"python toolbot_scripture.py --vector-store-id {vector_store.id}")
    print("\nOr save it to a file for later use:")
    
    # Save to a config file
    config_file = Path("scripture_vector_store_id.txt")
    config_file.write_text(vector_store.id)
    print(f"✓ Saved to {config_file}")
    
    return vector_store.id


def list_existing_vector_stores():
    """List any existing vector stores"""
    client = OpenAI()
    
    print("Checking for existing vector stores...")
    vector_stores = client.vector_stores.list()
    
    if vector_stores.data:
        print("\nExisting vector stores:")
        for vs in vector_stores.data:
            print(f"  - {vs.name}: {vs.id} ({vs.file_counts.total} files)")
        
        response = input("\nDo you want to create a new one or use an existing one? (new/existing): ")
        if response.lower() == 'existing':
            vs_id = input("Enter the vector store ID to use: ")
            config_file = Path("scripture_vector_store_id.txt")
            config_file.write_text(vs_id)
            print(f"✓ Using existing vector store: {vs_id}")
            return vs_id
    else:
        print("No existing vector stores found.")
    
    return None


if __name__ == "__main__":
    print("Scripture Vector Store Setup")
    print("="*60)
    print("\nThis script will upload your scripture files to OpenAI")
    print("and create a vector store for semantic search.")
    print("\nNote: This will incur storage costs on your OpenAI account.")
    print("="*60)
    
    response = input("\nContinue? (y/N): ")
    if response.lower() != 'y':
        print("Aborted.")
        exit(0)
    
    # Check for existing vector stores first
    existing_id = list_existing_vector_stores()
    
    if not existing_id:
        # Upload files and create vector store
        upload_scripture_files()
