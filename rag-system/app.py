from flask import Flask, request, jsonify
import os
import base64
from datetime import datetime
import uuid
import json
import sys
from langchain.vectorstores import Chroma
from langchain.embeddings.openai import OpenAIEmbeddings
from langchain.chat_models import ChatOpenAI
from langchain.chains import RetrievalQA
from langchain.prompts import PromptTemplate
from langchain.docstore.document import Document
from dotenv import load_dotenv
from document_processor import process_document_from_bytes, extract_text_from_pdf, extract_text_from_docx
import logging

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Initialize OpenAI embeddings
embeddings = OpenAIEmbeddings(
    openai_api_key=os.getenv("OPENAI_API_KEY")
)

# Create directories for the vector database and temporary files
if not os.path.exists("./chroma_db"):
    os.makedirs("./chroma_db")
if not os.path.exists("./temp_files"):
    os.makedirs("./temp_files")

# Initialize vector store
vector_store = Chroma(
    collection_name="whatsapp_messages",
    embedding_function=embeddings,
    persist_directory="./chroma_db"
)

def format_datetime(timestamp):
    """Convert timestamp to readable format"""
    if isinstance(timestamp, int):
        return datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')
    return timestamp

@app.route('/')
def index():
    """Root route to provide API documentation and status"""
    return '''
    <html>
        <head>
            <title>WhatsApp RAG API</title>
            <style>
                body {
                    font-family: Arial, sans-serif;
                    max-width: 800px;
                    margin: 0 auto;
                    padding: 20px;
                }
                h1 {
                    color: #075e54;
                }
                .endpoint {
                    background-color: #f3f3f3;
                    padding: 10px;
                    margin: 10px 0;
                    border-radius: 5px;
                }
                pre {
                    background-color: #e5e5e5;
                    padding: 10px;
                    overflow: auto;
                }
            </style>
        </head>
        <body>
            <h1>WhatsApp RAG API</h1>
            <p>This API provides endpoints for storing WhatsApp messages, indexing documents, and querying the RAG system.</p>
            
            <div class="endpoint">
                <h2>Store Message</h2>
                <p><strong>Endpoint:</strong> POST /store-message</p>
            </div>
            
            <div class="endpoint">
                <h2>Process Document</h2>
                <p><strong>Endpoint:</strong> POST /process-document</p>
                <p>Supports PDF, DOCX, and DOC files</p>
            </div>
            
            <div class="endpoint">
                <h2>Process PDF (Legacy)</h2>
                <p><strong>Endpoint:</strong> POST /process-pdf</p>
            </div>
            
            <div class="endpoint">
                <h2>Query RAG</h2>
                <p><strong>Endpoint:</strong> POST /query-rag</p>
            </div>
            
            <div class="endpoint">
                <h2>Health Check</h2>
                <p><strong>Endpoint:</strong> GET /health</p>
            </div>
            
            <div class="endpoint">
                <h2>System Statistics</h2>
                <p><strong>Endpoint:</strong> GET /stats</p>
            </div>
            
            <p>API Status: <strong style="color: green">Running</strong></p>
        </body>
    </html>
    '''

@app.route('/store-message', methods=['POST'])
def store_message():
    """API endpoint to store WhatsApp messages in the vector database"""
    try:
        data = request.json
        
        # Extract message data
        message_id = data.get('messageId', 'unknown_id')
        sender = data.get('sender', 'unknown_sender')
        sender_name = data.get('senderName', 'Unknown')
        content = data.get('content', '')
        timestamp = data.get('timestamp', int(datetime.now().timestamp()))
        is_group = data.get('isGroup', False)
        
        # Prepare metadata for the document
        metadata = {
            "source": "whatsapp_message",
            "message_id": message_id,
            "sender": sender,
            "sender_name": sender_name,
            "timestamp": timestamp,
            "datetime": format_datetime(timestamp),
            "is_group": is_group
        }
        
        # Create document
        doc = Document(page_content=content, metadata=metadata)
        
        # Add to vector store
        vector_store.add_documents([doc])
        vector_store.persist()
        
        logger.info(f"Stored message from {sender_name} ({message_id})")
        
        return jsonify({
            "success": True,
            "message": f"Successfully stored message {message_id}"
        })
    
    except Exception as e:
        logger.error(f"Error storing message: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@app.route('/process-document', methods=['POST'])
def process_document():
    """API endpoint to process and index documents (PDF/DOCX) sent via WhatsApp"""
    try:
        data = request.json
        
        # Extract document data
        message_id = data.get('messageId', 'unknown_id')
        sender = data.get('sender', 'unknown_sender')
        sender_name = data.get('senderName', 'Unknown')
        doc_data = data.get('documentData', '')
        file_name = data.get('fileName', 'document.pdf')
        timestamp = data.get('timestamp', int(datetime.now().timestamp()))
        is_group = data.get('isGroup', False)
        
        if not doc_data:
            logger.warning("Document processing failed: No document data provided")
            return jsonify({
                "success": False,
                "error": "No document data provided"
            }), 400
        
        # Check file extension
        file_ext = os.path.splitext(file_name.lower())[1]
        if file_ext not in ['.pdf', '.docx', '.doc']:
            logger.warning(f"Unsupported document type: {file_ext}")
            return jsonify({
                "success": False,
                "error": f"Unsupported document type: {file_ext}. Only PDF, DOCX, and DOC are supported."
            }), 400
        
        # Decode base64 document data and process
        try:
            logger.info(f"Processing document: {file_name} from {sender_name}")
            
            # Decode base64 document data
            doc_bytes = base64.b64decode(doc_data)
            
            # Process document
            documents = process_document_from_bytes(doc_bytes, filename=file_name)
            
            # If no documents were extracted, return an error
            if not documents:
                logger.warning(f"No text extracted from document: {file_name}")
                raise ValueError(f"Could not extract any text from document: {file_name}")
            
            # Count unique pages
            unique_pages = set(doc.metadata.get('page', 0) for doc in documents)
            logger.info(f"Extracted {len(documents)} chunks from {len(unique_pages)} pages")
            
            # Add metadata to each document
            for doc in documents:
                doc.metadata.update({
                    "source": "whatsapp_document",
                    "document_type": file_ext.replace('.', ''),
                    "message_id": message_id,
                    "sender": sender,
                    "sender_name": sender_name,
                    "timestamp": timestamp,
                    "datetime": format_datetime(timestamp),
                    "is_group": is_group
                })
            
            # Add to vector store
            vector_store.add_documents(documents)
            vector_store.persist()
            
            logger.info(f"Successfully processed document {file_name}")
            
            return jsonify({
                "success": True,
                "message": f"Successfully processed document {file_name}",
                "pages_processed": len(unique_pages),
                "chunks_processed": len(documents),
                "document_type": file_ext.replace('.', '')
            })
            
        except Exception as doc_error:
            logger.error(f"Error processing document: {str(doc_error)}")
            
            return jsonify({
                "success": False,
                "error": f"Error processing document: {str(doc_error)}"
            }), 500
    
    except Exception as e:
        logger.error(f"Error in document processing endpoint: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@app.route('/process-pdf', methods=['POST'])
def process_pdf():
    """API endpoint to process and index PDFs sent via WhatsApp (redirects to document processor)"""
    try:
        # Rename the pdfData field to documentData for compatibility
        if request.json and 'pdfData' in request.json:
            request.json['documentData'] = request.json.pop('pdfData')
        
        return process_document()
    except Exception as e:
        logger.error(f"Error in PDF processing endpoint: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@app.route('/query-rag', methods=['POST'])
def query_rag():
    """API endpoint to query the RAG system"""
    try:
        data = request.json
        query = data.get('query', '')
        
        if not query:
            return jsonify({
                "success": False,
                "error": "No query provided"
            }), 400
        
        logger.info(f"Processing RAG query: {query}")
        
        # Create ChatOpenAI instance
        llm = ChatOpenAI(
            model_name="gpt-3.5-turbo",  # or "gpt-4" if you have access
            temperature=0.7,
            openai_api_key=os.getenv("OPENAI_API_KEY")
        )
        
        # Create custom prompt template
        prompt_template = """
        ## MAKLUMAT YANG DIPEROLEHI (RETRIEVED CONTEXT):
{context}

## SOALAN:
{question}

## ARAHAN JAWAPAN:
1. Jawab HANYA berdasarkan maklumat dalam konteks di atas.
2. Jika maklumat berkaitan TIADA dalam konteks, jawab: 
   "Maaf, saya tidak mempunyai maklumat tersebut dalam mesej WhatsApp atau dokumen yang saya ada akses."
3. Jangan cipta jawapan, jangan meneka, dan JANGAN gunakan pengetahuan luar.
4. Jika maklumat diperoleh dari mesej WhatsApp, nyatakan pengirim dan masa.
5. Jika maklumat diperoleh dari dokumen, nyatakan nama dokumen dan nombor halaman (jika ada).
6. Jika maklumat dari beberapa sumber, gabungkan dan rangkumkan jawapan dengan jelas.
7. Jika soalan terlalu umum atau di luar skop, berikan jawapan umum tanpa bergantung pada context RAG.
8. Guna Bahasa Melayu Malaysia yang jelas, profesional dan mudah difahami.
9. Mulakan jawapan dengan ayat terus menjawab soalan, kemudian berikan sokongan/rujukan daripada konteks.

## FORMAT JAWAPAN:
- Jawapan terus kepada soalan.
- Nyatakan sumber (nama pengirim, masa, nama dokumen, nombor halaman jika ada).
- Berikan maklumat tambahan dari konteks, jika perlu.
- Jika tiada maklumat, gunakan ayat no.2 di atas.

        """
        
        PROMPT = PromptTemplate(
            template=prompt_template,
            input_variables=["context", "question"]
        )
        
        # Create retrieval chain with more results for better context
        qa_chain = RetrievalQA.from_chain_type(
            llm=llm,
            chain_type="stuff",
            retriever=vector_store.as_retriever(search_kwargs={"k": 8}),
            chain_type_kwargs={"prompt": PROMPT}
        )
        
        # Get response
        response = qa_chain({"query": query})
        answer = response.get('result', "I couldn't find an answer to your question.")
        
        logger.info(f"RAG query completed: {query[:50]}...")
        
        return jsonify({
            "success": True,
            "answer": answer,
            "query": query
        })
    
    except Exception as e:
        logger.error(f"Error processing query: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@app.route('/health', methods=['GET'])
def health_check():
    """Detailed health check endpoint"""
    try:
        # Print a message to server logs
        print("Processing health check request")
        logger.info("Health check endpoint called")
        
        # Basic system info
        info = {
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "python_version": sys.version,
            "api_version": "1.1.0"
        }
        
        # Try to access the vector store
        try:
            count = vector_store._collection.count()
            info["vector_store"] = {
                "status": "connected",
                "document_count": count
            }
        except Exception as vs_err:
            info["vector_store"] = {
                "status": "error",
                "error": str(vs_err)
            }
            info["status"] = "unhealthy"
        
        # Check OpenAI API key
        info["openai_api_key_configured"] = bool(os.getenv("OPENAI_API_KEY"))
        
        # Simple version for compatibility
        info["document_count"] = info["vector_store"]["document_count"] if info["vector_store"]["status"] == "connected" else 0
        
        return jsonify(info)
    except Exception as e:
        logger.error(f"Health check failed: {str(e)}")
        print(f"Health check error: {str(e)}")
        return jsonify({
            "status": "unhealthy",
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }), 500

@app.route('/stats', methods=['GET'])
def get_stats():
    """Endpoint to get statistics about the RAG system"""
    try:
        # Get total documents
        total_docs = vector_store._collection.count()
        
        # Get document types distribution (if available)
        try:
            # This assumes you have a way to query by metadata
            # This is a simplified example and might need adjusting based on Chroma's API
            all_docs = vector_store._collection.get(include=["metadatas"])
            metadatas = all_docs["metadatas"] if "metadatas" in all_docs else []
            
            # Count document types
            doc_types = {}
            for meta in metadatas:
                if "document_type" in meta:
                    doc_type = meta["document_type"]
                    doc_types[doc_type] = doc_types.get(doc_type, 0) + 1
                elif "file_type" in meta:
                    file_type = meta["file_type"]
                    doc_types[file_type] = doc_types.get(file_type, 0) + 1
                elif "source" in meta:
                    source = meta["source"]
                    if source == "whatsapp_message":
                        doc_types["message"] = doc_types.get("message", 0) + 1
                    elif source.startswith("whatsapp_"):
                        doc_types["document"] = doc_types.get("document", 0) + 1
        except Exception as e:
            logger.warning(f"Could not get document type distribution: {str(e)}")
            doc_types = {"unknown": total_docs}
        
        # Compile stats
        stats = {
            "total_documents": total_docs,
            "document_types": doc_types,
            "timestamp": datetime.now().isoformat()
        }
        
        return jsonify(stats)
    except Exception as e:
        logger.error(f"Error fetching stats: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

if __name__ == '__main__':
    # Use port 5001 to avoid conflicts
    port = int(os.environ.get("PORT", 5001))
    logger.info(f"Starting WhatsApp RAG API on port {port}")
    app.run(host='0.0.0.0', port=port, debug=True)
