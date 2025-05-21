# Enhanced pdf_processor.py

import fitz  # PyMuPDF
import os
import re
from langchain.docstore.document import Document
from langchain.text_splitter import RecursiveCharacterTextSplitter
import logging
from typing import List, Dict, Any, Optional
import tempfile

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def extract_text_from_pdf(pdf_path: str, chunk_size: int = 1000, 
                        chunk_overlap: int = 100) -> List[Document]:
    """
    Enhanced function to extract text from PDF files and split into manageable chunks
    
    Args:
        pdf_path (str): Path to the PDF file
        chunk_size (int): Size of text chunks
        chunk_overlap (int): Overlap between chunks
        
    Returns:
        list: List of Document objects with text chunks and metadata
    """
    if not os.path.exists(pdf_path):
        logger.error(f"PDF file not found: {pdf_path}")
        raise FileNotFoundError(f"PDF file not found: {pdf_path}")
    
    try:
        logger.info(f"Opening PDF: {pdf_path}")
        doc = fitz.open(pdf_path)
        
        # Extract document metadata
        metadata = {
            "title": doc.metadata.get("title", ""),
            "author": doc.metadata.get("author", ""),
            "subject": doc.metadata.get("subject", ""),
            "creator": doc.metadata.get("creator", ""),
            "producer": doc.metadata.get("producer", ""),
            "total_pages": len(doc),
            "file_name": os.path.basename(pdf_path)
        }
        logger.info(f"PDF metadata: {metadata}")
        
        # Extract text from each page with improved formatting
        all_text = []
        for page_num, page in enumerate(doc):
            # Get text blocks with their bounding boxes
            text_blocks = page.get_text("blocks")
            
            # Sort blocks by vertical position (top to bottom)
            text_blocks.sort(key=lambda b: b[1])  # Sort by y-coordinate
            
            # Extract and join the text
            page_text = "\n".join([block[4] for block in text_blocks if isinstance(block[4], str)])
            
            # Clean up excessive whitespace
            page_text = re.sub(r'\s+', ' ', page_text).strip()
            
            if page_text:  # Only add non-empty pages
                all_text.append({
                    "page": page_num + 1,
                    "text": page_text
                })
                logger.debug(f"Extracted {len(page_text)} characters from page {page_num + 1}")
        
        # Close the PDF
        doc.close()
        
        if not all_text:
            logger.warning(f"No text extracted from PDF: {pdf_path}")
            
            # Try OCR as a fallback for scanned documents
            # This is a placeholder - implement proper OCR handling if needed
            logger.info("No text found, PDF might be scanned or image-based")
            return []
        
        # Create a text splitter with appropriate settings
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            length_function=len,
            separators=["\n\n", "\n", ". ", " ", ""]
        )
        
        # Process all pages into a single document first
        combined_text = "\n\n".join([f"Page {page_info['page']}: {page_info['text']}" 
                                    for page_info in all_text])
        
        # Split text into chunks
        chunks = text_splitter.split_text(combined_text)
        
        # Create Document objects
        documents = []
        for i, chunk in enumerate(chunks):
            # Try to identify which page this chunk belongs to
            page_match = re.match(r"Page (\d+):", chunk)
            page_num = int(page_match.group(1)) if page_match else 0
            
            # Clean up the chunk text
            clean_chunk = re.sub(r"Page \d+: ", "", chunk)
            
            doc = Document(
                page_content=clean_chunk,
                metadata={
                    "page": page_num,
                    "chunk": i + 1,
                    "source": os.path.basename(pdf_path),
                    **metadata
                }
            )
            documents.append(doc)
        
        logger.info(f"Extracted {len(documents)} text chunks from {len(all_text)} pages")
        return documents
    
    except Exception as e:
        logger.error(f"Error extracting text from PDF: {str(e)}")
        raise

def process_pdf_from_bytes(pdf_bytes: bytes, filename: str = "document.pdf") -> List[Document]:
    """
    Process PDF data from bytes (useful for processing PDFs from WhatsApp)
    
    Args:
        pdf_bytes (bytes): The PDF file as bytes
        filename (str): Original filename
        
    Returns:
        list: List of Document objects
    """
    # Create a temporary file
    with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as temp_file:
        temp_path = temp_file.name
        temp_file.write(pdf_bytes)
    
    try:
        # Process the temp file
        documents = extract_text_from_pdf(temp_path)
        
        # Update source in metadata to original filename
        for doc in documents:
            doc.metadata["source"] = filename
            doc.metadata["file_name"] = filename
            
        return documents
    finally:
        # Clean up the temp file
        if os.path.exists(temp_path):
            os.remove(temp_path)
