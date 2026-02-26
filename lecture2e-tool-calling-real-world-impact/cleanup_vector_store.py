"""
Cleanup script to delete vector stores and associated files from OpenAI.
This stops storage costs from accumulating.

Usage:
    python cleanup_vector_store.py [vector_store_id]
    
    If no vector_store_id is provided, it will list all vector stores
    and let you choose which one(s) to delete.
"""

import sys
from pathlib import Path
from openai import OpenAI


def list_vector_stores(client):
    """List all vector stores"""
    vector_stores = client.vector_stores.list()
    
    if not vector_stores.data:
        print("\nNo vector stores found.")
        return []
    
    print("\nExisting vector stores:")
    print("=" * 80)
    for i, vs in enumerate(vector_stores.data, 1):
        print(f"\n{i}. {vs.name}")
        print(f"   ID: {vs.id}")
        print(f"   Status: {vs.status}")
        print(f"   Files: {vs.file_counts.total}")
        print(f"   Size: {vs.usage_bytes:,} bytes")
        print(f"   Created: {vs.created_at}")
    print("=" * 80)
    
    return vector_stores.data


def delete_vector_store(client, vector_store_id, delete_files=False):
    """Delete a vector store and optionally its files"""
    
    try:
        # Get vector store info first
        vs = client.vector_stores.retrieve(vector_store_id)
        print(f"\nDeleting vector store: {vs.name} ({vector_store_id})")
        
        # Optionally delete associated files
        if delete_files and vs.file_counts.total > 0:
            print(f"Deleting {vs.file_counts.total} associated files...")
            
            # List files in the vector store
            files = client.vector_stores.files.list(vector_store_id=vector_store_id)
            
            for file_obj in files.data:
                try:
                    client.files.delete(file_obj.id)
                    print(f"  ✓ Deleted file: {file_obj.id}")
                except Exception as e:
                    print(f"  ✗ Failed to delete file {file_obj.id}: {e}")
        
        # Delete the vector store
        client.vector_stores.delete(vector_store_id)
        print(f"✓ Vector store deleted: {vector_store_id}")
        
        return True
        
    except Exception as e:
        print(f"✗ Error deleting vector store: {e}")
        return False


def main():
    client = OpenAI()
    
    print("Vector Store Cleanup Tool")
    print("=" * 80)
    
    # If vector_store_id provided as argument
    if len(sys.argv) > 1:
        vector_store_id = sys.argv[1]
        print(f"\nDeleting vector store: {vector_store_id}")
        
        response = input("Delete associated files too? (y/N): ")
        delete_files = response.lower() == 'y'
        
        delete_vector_store(client, vector_store_id, delete_files)
        return
    
    # Otherwise, list and let user choose
    vector_stores = list_vector_stores(client)
    
    if not vector_stores:
        return
    
    print("\nOptions:")
    print("  - Enter number(s) to delete (e.g., '1' or '1,2,3')")
    print("  - Enter 'all' to delete all vector stores")
    print("  - Enter 'q' to quit")
    
    choice = input("\nYour choice: ").strip().lower()
    
    if choice == 'q':
        print("Cancelled.")
        return
    
    # Ask about deleting files
    delete_files_response = input("Delete associated files too? (y/N): ")
    delete_files = delete_files_response.lower() == 'y'
    
    # Process selection
    if choice == 'all':
        to_delete = vector_stores
    else:
        try:
            indices = [int(x.strip()) - 1 for x in choice.split(',')]
            to_delete = [vector_stores[i] for i in indices if 0 <= i < len(vector_stores)]
        except (ValueError, IndexError):
            print("Invalid selection.")
            return
    
    # Confirm deletion
    print(f"\nAbout to delete {len(to_delete)} vector store(s):")
    for vs in to_delete:
        print(f"  - {vs.name} ({vs.id})")
    
    confirm = input("\nAre you sure? (yes/N): ")
    if confirm.lower() != 'yes':
        print("Cancelled.")
        return
    
    # Delete selected vector stores
    print("\nDeleting...")
    for vs in to_delete:
        delete_vector_store(client, vs.id, delete_files)
    
    print("\n✓ Cleanup complete!")
    
    # Clean up config file if it exists
    config_file = Path("scripture_vector_store_id.txt")
    if config_file.exists():
        # Check if the deleted ID is in the config
        stored_id = config_file.read_text().strip()
        if any(vs.id == stored_id for vs in to_delete):
            config_file.unlink()
            print("✓ Removed configuration file")


if __name__ == "__main__":
    main()
