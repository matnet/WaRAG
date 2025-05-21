#!/usr/bin/env python3
"""
RAG System Debugging Tool

This tool helps diagnose issues with the RAG system by:
1. Searching the vector store directly
2. Viewing all docs from a specific source
3. Checking what PDFs and documents are in the system
"""

import os
import argparse
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime
import json

# Import LangChain components
from langchain.vectorstores import Chroma
from langchain.embeddings.openai import OpenAIEmbeddings
from langchain.docstore.document import Document

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("rag_debug")

# Initialize embeddings and vector store
embeddings = OpenAIEmbeddings()
vector_store = None

def initialize_vector_store(persist_dir: str = "./chroma_db") -> bool:
    """Initialize the vector store from the given directory."""
    global vector_store
    
    try:
        vector_store = Chroma(
            embedding_function=embeddings,
            persist_directory=persist_dir
        )
        
        # Test if vector store is working
        count = vector_store._collection.count()
        logger.info(f"Vector store initialized with {count} documents.")
        return True
    except Exception as e:
        logger.error(f"Error initializing vector store: {str(e)}")
        return False

def search_documents(query: str, top_k: int = 5) -> List[Dict[str, Any]]:
    """Search the vector store for documents matching the query."""
    if vector_store is None:
        logger.error("Vector store not initialized")
        return []
    
    try:
        retriever = vector_store.as_retriever(search_kwargs={"k": top_k})
        docs = retriever.get_relevant_documents(query)
        
        results = []
        for i, doc in enumerate(docs):
            # Format source information
            source = "Unknown"
            if 'file_name' in doc.metadata:
                source = f"Document: {doc.metadata.get('file_name')}"
                if 'page' in doc.metadata:
                    source += f", Page {doc.metadata.get('page')}"
            elif 'sender_name' in doc.metadata:
                source = f"Message from {doc.metadata.get('sender_name')}"
                if doc.metadata.get('is_group', False) and 'group_name' in doc.metadata:
                    source += f" in group {doc.metadata.get('group_name')}"
            
            # Format date if available
            date = "Unknown date"
            if 'datetime' in doc.metadata:
                date = doc.metadata.get('datetime')
            elif 'timestamp' in doc.metadata:
                try:
                    timestamp = doc.metadata.get('timestamp')
                    date = datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')
                except:
                    pass
            
            # Format document type
            doc_type = "unknown"
            if 'source' in doc.metadata:
                doc_type = doc.metadata.get('source')
            elif 'file_type' in doc.metadata:
                doc_type = doc.metadata.get('file_type')
            
            result = {
                "content": doc.page_content,
                "source": source,
                "date": date,
                "type": doc_type,
                "metadata": doc.metadata,
                "relevance_score": round(1.0 - (i * 0.1), 2)  # Simple mock score
            }
            results.append(result)
        
        return results
    
    except Exception as e:
        logger.error(f"Error searching documents: {str(e)}")
        return []

def get_document_info(file_name: Optional[str] = None) -> List[Dict[str, Any]]:
    """Get information about documents in the vector store."""
    if vector_store is None:
        logger.error("Vector store not initialized")
        return []
    
    try:
        # Get all documents from the collection
        results = vector_store._collection.get()
        
        # Extract unique document sources
        documents = []
        seen_files = set()
        
        if not results or 'metadatas' not in results:
            return []
        
        for i, metadata in enumerate(results['metadatas']):
            if not metadata:
                continue
                
            # Skip if we're looking for a specific file and this isn't it
            if file_name and 'file_name' in metadata and metadata['file_name'] != file_name:
                continue
                
            # If we're looking for files without a specific name
            if 'file_name' in metadata:
                doc_id = metadata['file_name']
                
                # If we've already processed this file and we're not looking at a specific file
                if doc_id in seen_files and not file_name:
                    continue
                    
                seen_files.add(doc_id)
                
                doc = {
                    "file_name": metadata['file_name'],
                    "file_type": metadata.get('file_type', 'unknown'),
                    "source": metadata.get('source', 'unknown'),
                    "chunks": 0,  # Will count chunks below
                    "added_by": metadata.get('sender_name', 'Unknown'),
                    "date_added": metadata.get('datetime', 'Unknown date'),
                    "metadata": metadata
                }
                documents.append(doc)
            
            # For messages
            elif 'sender_name' in metadata and 'source' in metadata and metadata['source'] == 'whatsapp_message':
                if not file_name:  # Only add messages if we're not filtering by file_name
                    sender = metadata['sender_name']
                    doc_id = f"message_{metadata.get('message_id', i)}"
                    
                    if doc_id in seen_files:
                        continue
                        
                    seen_files.add(doc_id)
                    
                    doc = {
                        "sender": sender,
                        "is_group": metadata.get('is_group', False),
                        "group_name": metadata.get('group_name', '') if metadata.get('is_group', False) else '',
                        "date": metadata.get('datetime', 'Unknown date'),
                        "source": "message",
                        "content": results['documents'][i] if 'documents' in results else "Content not available",
                        "metadata": metadata
                    }
                    documents.append(doc)
        
        # Count chunks for each file
        if file_name:
            for metadata in results['metadatas']:
                if metadata and 'file_name' in metadata and metadata['file_name'] == file_name:
                    for doc in documents:
                        if doc.get('file_name') == file_name:
                            doc['chunks'] = doc.get('chunks', 0) + 1
        
        # Sort by date if available
        documents.sort(key=lambda x: x.get('date_added', '') if isinstance(x.get('date_added'), str) else '', reverse=True)
        
        return documents
    
    except Exception as e:
        logger.error(f"Error getting document info: {str(e)}")
        return []

def get_document_content(file_name: str) -> List[Dict[str, Any]]:
    """Get all content chunks from a specific document."""
    if vector_store is None:
        logger.error("Vector store not initialized")
        return []
    
    try:
        # Get all documents from the collection
        results = vector_store._collection.get()
        
        chunks = []
        
        if not results or 'metadatas' not in results or 'documents' not in results:
            return []
        
        for i, metadata in enumerate(results['metadatas']):
            if not metadata or 'file_name' not in metadata or metadata['file_name'] != file_name:
                continue
                
            chunk = {
                "content": results['documents'][i],
                "page": metadata.get('page', 'Unknown'),
                "chunk_number": metadata.get('chunk', i+1),
                "total_chunks": metadata.get('total_chunks', 'Unknown'),
                "metadata": metadata
            }
            chunks.append(chunk)
        
        # Sort by page and chunk number
        chunks.sort(key=lambda x: (
            int(x['page']) if isinstance(x['page'], (int, str)) and str(x['page']).isdigit() else 0, 
            int(x['chunk_number']) if isinstance(x['chunk_number'], (int, str)) and str(x['chunk_number']).isdigit() else 0
        ))
        
        return chunks
    
    except Exception as e:
        logger.error(f"Error getting document content: {str(e)}")
        return []

def search_term_in_documents(term: str) -> List[Dict[str, Any]]:
    """Search for a specific term in all documents (exact match)."""
    if vector_store is None:
        logger.error("Vector store not initialized")
        return []
    
    try:
        # Get all documents from the collection
        results = vector_store._collection.get()
        
        matches = []
        
        if not results or 'metadatas' not in results or 'documents' not in results:
            return []
        
        for i, content in enumerate(results['documents']):
            if term.lower() in content.lower():
                metadata = results['metadatas'][i] if i < len(results['metadatas']) else {}
                
                # Format source information
                source = "Unknown"
                if metadata and 'file_name' in metadata:
                    source = f"Document: {metadata.get('file_name')}"
                    if 'page' in metadata:
                        source += f", Page {metadata.get('page')}"
                elif metadata and 'sender_name' in metadata:
                    source = f"Message from {metadata.get('sender_name')}"
                    if metadata.get('is_group', False) and 'group_name' in metadata:
                        source += f" in group {metadata.get('group_name')}"
                
                match = {
                    "content": content,
                    "source": source,
                    "context": get_context_snippet(content, term),
                    "metadata": metadata
                }
                matches.append(match)
        
        return matches
    
    except Exception as e:
        logger.error(f"Error searching for term: {str(e)}")
        return []

def get_context_snippet(text: str, term: str, context_size: int = 50) -> str:
    """Get a snippet of text around a term for context."""
    try:
        term_lower = term.lower()
        text_lower = text.lower()
        
        if term_lower not in text_lower:
            return "Term not found in text"
        
        start_idx = text_lower.find(term_lower)
        term_length = len(term)
        
        # Calculate snippet start and end
        snippet_start = max(0, start_idx - context_size)
        snippet_end = min(len(text), start_idx + term_length + context_size)
        
        # Get the snippet
        snippet = text[snippet_start:snippet_end]
        
        # Add ellipsis if truncated
        prefix = "..." if snippet_start > 0 else ""
        suffix = "..." if snippet_end < len(text) else ""
        
        return prefix + snippet + suffix
    
    except Exception:
        return "Error getting context snippet"

def format_output(data, format_type='text'):
    """Format output data based on the specified format."""
    if format_type == 'json':
        return json.dumps(data, indent=2, default=str)
    
    # Default text formatter
    if isinstance(data, list):
        result = []
        for i, item in enumerate(data):
            result.append(f"\n--- Item {i+1} ---")
            for key, value in item.items():
                if key == 'metadata':
                    continue  # Skip full metadata in text output
                result.append(f"{key.upper()}: {value}")
        return "\n".join(result)
    elif isinstance(data, dict):
        result = []
        for key, value in data.items():
            if key == 'metadata':
                continue  # Skip full metadata in text output
            result.append(f"{key.upper()}: {value}")
        return "\n".join(result)
    else:
        return str(data)

def main():
    parser = argparse.ArgumentParser(description="RAG System Debugging Tool")
    parser.add_argument("--db-path", type=str, default="./chroma_db", 
                        help="Path to the Chroma vector database")
    
    subparsers = parser.add_subparsers(dest="command", help="Command to run")
    
    # Search command
    search_parser = subparsers.add_parser("search", help="Search the vector store")
    search_parser.add_argument("query", type=str, help="The query to search for")
    search_parser.add_argument("--top-k", type=int, default=5, help="Number of results to return")
    search_parser.add_argument("--format", choices=["text", "json"], default="text", 
                              help="Output format (text or json)")
    
    # List documents command
    list_parser = subparsers.add_parser("list", help="List documents in the vector store")
    list_parser.add_argument("--file", type=str, default=None, 
                            help="Filter by specific file name")
    list_parser.add_argument("--format", choices=["text", "json"], default="text", 
                            help="Output format (text or json)")
    
    # View document content command
    view_parser = subparsers.add_parser("view", help="View content of a specific document")
    view_parser.add_argument("file_name", type=str, help="Name of the file to view")
    view_parser.add_argument("--format", choices=["text", "json"], default="text", 
                            help="Output format (text or json)")
    
    # Find term command
    term_parser = subparsers.add_parser("find", help="Find specific terms in documents")
    term_parser.add_argument("term", type=str, help="Term to search for (exact match)")
    term_parser.add_argument("--format", choices=["text", "json"], default="text", 
                            help="Output format (text or json)")
    
    args = parser.parse_args()
    
    # Initialize vector store
    if not initialize_vector_store(args.db_path):
        print("Failed to initialize vector store. Exiting.")
        return 1
    
    # Process commands
    if args.command == "search":
        results = search_documents(args.query, args.top_k)
        if results:
            print(f"Found {len(results)} results for query: '{args.query}'")
            print(format_output(results, args.format))
        else:
            print(f"No results found for query: '{args.query}'")
            
    elif args.command == "list":
        documents = get_document_info(args.file)
        if documents:
            print(f"Found {len(documents)} documents")
            print(format_output(documents, args.format))
        else:
            print(f"No documents found" + (f" with file name: {args.file}" if args.file else ""))
            
    elif args.command == "view":
        chunks = get_document_content(args.file_name)
        if chunks:
            print(f"Found {len(chunks)} chunks for document: '{args.file_name}'")
            print(format_output(chunks, args.format))
        else:
            print(f"No content found for document: '{args.file_name}'")
            
    elif args.command == "find":
        matches = search_term_in_documents(args.term)
        if matches:
            print(f"Found '{args.term}' in {len(matches)} document chunks")
            print(format_output(matches, args.format))
        else:
            print(f"Term '{args.term}' not found in any documents")
    
    else:
        print("Please specify a command. Use --help for options.")
        return 1
    
    return 0

if __name__ == "__main__":
    exit(main())
