# query_chroma.py

import os
import sys
import json
from datetime import datetime
from langchain.vectorstores import Chroma
from langchain.embeddings.openai import OpenAIEmbeddings
from dotenv import load_dotenv
import argparse

# Load environment variables
load_dotenv()

# Configure argument parser
parser = argparse.ArgumentParser(description='Query ChromaDB collection')
parser.add_argument('--query', '-q', type=str, help='Query text to search for', required=False)
parser.add_argument('--limit', '-l', type=int, default=5, help='Maximum number of results to return')
parser.add_argument('--info', '-i', action='store_true', help='Show collection information')
parser.add_argument('--list', action='store_true', help='List all documents (use with caution if you have many documents)')
parser.add_argument('--doc-type', '-t', type=str, help='Filter by document type (pdf, docx, message)')
parser.add_argument('--delete-id', type=str, help='Delete a document by ID')
parser.add_argument('--metadata', '-m', type=str, help='Search by metadata (JSON format)')
args = parser.parse_args()

def format_datetime(timestamp):
    """Convert timestamp to readable format"""
    if isinstance(timestamp, int):
        return datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')
    return timestamp

def print_document(doc, idx=None, show_content=True):
    """Print document with formatted metadata"""
    if idx is not None:
        print(f"\n--- Document {idx} ---")
    
    # Print metadata
    print("Metadata:")
    for key, value in doc.metadata.items():
        if key == 'timestamp' and isinstance(value, int):
            print(f"  {key}: {format_datetime(value)}")
        else:
            print(f"  {key}: {value}")
    
    # Print content
    if show_content:
        print("\nContent:")
        content = doc.page_content if hasattr(doc, 'page_content') else doc.get('page_content', 'No content')
        # Limit content length for display
        if len(content) > 500:
            print(f"{content[:500]}...\n[Content truncated, total length: {len(content)} chars]")
        else:
            print(content)
    print("-" * 50)

def main():
    # Initialize OpenAI embeddings
    try:
        embeddings = OpenAIEmbeddings(
            openai_api_key=os.getenv("OPENAI_API_KEY")
        )
        
        # Create vector store
        db_path = "./chroma_db"
        vector_store = Chroma(
            collection_name="whatsapp_messages",
            embedding_function=embeddings,
            persist_directory=db_path
        )
        
        # Show collection information
        if args.info:
            print("\n=== COLLECTION INFORMATION ===")
            total_docs = vector_store._collection.count()
            print(f"Total documents: {total_docs}")
            
            # Count documents by type if possible
            try:
                print("\nDocument types:")
                all_docs = vector_store._collection.get(include=["metadatas"])
                metadatas = all_docs.get('metadatas', [])
                
                # Count types
                types_count = {}
                for meta in metadatas:
                    if 'document_type' in meta:
                        doc_type = meta['document_type']
                        types_count[doc_type] = types_count.get(doc_type, 0) + 1
                    elif 'file_type' in meta:
                        file_type = meta['file_type']
                        types_count[file_type] = types_count.get(file_type, 0) + 1
                    elif 'source' in meta:
                        source = meta['source']
                        if source == 'whatsapp_message':
                            types_count['message'] = types_count.get('message', 0) + 1
                        elif source.startswith('whatsapp_'):
                            types_count['document'] = types_count.get('document', 0) + 1
                
                for doc_type, count in types_count.items():
                    print(f"  {doc_type}: {count}")
                    
            except Exception as e:
                print(f"Error retrieving document types: {str(e)}")
            
            print("\n")
            
        # List all documents
        if args.list:
            print("\n=== LISTING ALL DOCUMENTS ===")
            all_docs = vector_store._collection.get(include=["documents", "metadatas", "embeddings"])
            documents = all_docs.get('documents', [])
            metadatas = all_docs.get('metadatas', [])
            
            if not documents:
                print("No documents found in the collection.")
            else:
                print(f"Found {len(documents)} documents.")
                
                # Filter by document type if requested
                if args.doc_type:
                    filtered_indices = []
                    for i, meta in enumerate(metadatas):
                        doc_type = meta.get('document_type') or meta.get('file_type')
                        source = meta.get('source', '')
                        
                        # Handle various ways document type might be stored
                        if doc_type and args.doc_type.lower() in doc_type.lower():
                            filtered_indices.append(i)
                        elif 'message' in args.doc_type.lower() and source == 'whatsapp_message':
                            filtered_indices.append(i)
                    
                    # Apply filter
                    if filtered_indices:
                        print(f"Filtered to {len(filtered_indices)} {args.doc_type} documents.")
                        documents = [documents[i] for i in filtered_indices]
                        metadatas = [metadatas[i] for i in filtered_indices]
                    else:
                        print(f"No documents found with type '{args.doc_type}'.")
                        documents = []
                        metadatas = []
                
                # Display documents
                for i, (doc, meta) in enumerate(zip(documents, metadatas)):
                    # Create a Document-like object
                    document = {
                        'page_content': doc,
                        'metadata': meta
                    }
                    print_document(document, i+1)
                    
                    # Limit display to prevent excessive output
                    if i >= 20 and not args.limit:
                        print(f"Displaying only first 20 documents. Use --limit option to see more.")
                        break
                    
                    # Respect user limit
                    if args.limit and i+1 >= args.limit:
                        break
        
        # Delete document by ID
        if args.delete_id:
            try:
                print(f"Attempting to delete document with ID: {args.delete_id}")
                vector_store._collection.delete(ids=[args.delete_id])
                vector_store.persist()
                print(f"Successfully deleted document with ID: {args.delete_id}")
            except Exception as e:
                print(f"Error deleting document: {str(e)}")
        
        # Query by text
        if args.query:
            print(f"\n=== SEARCHING FOR: '{args.query}' ===")
            
            # Build metadata filter if specified
            filter_dict = None
            if args.metadata:
                try:
                    filter_dict = json.loads(args.metadata)
                    print(f"Using metadata filter: {filter_dict}")
                except json.JSONDecodeError:
                    print(f"Error parsing metadata JSON: {args.metadata}")
                    print("Format should be valid JSON, e.g.: '{\"document_type\":\"pdf\"}'")
            
            # Perform search
            results = vector_store.similarity_search(
                args.query,
                k=args.limit,
                filter=filter_dict
            )
            
            if not results:
                print("No results found for this query.")
            else:
                print(f"Found {len(results)} results:")
                for i, doc in enumerate(results):
                    print_document(doc, i+1)
                    
    except Exception as e:
        print(f"Error: {str(e)}")
        return 1
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
