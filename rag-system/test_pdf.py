import sys
from pdf_processor import extract_text_from_pdf

if len(sys.argv) != 2:
    print("Usage: python test_pdf.py <pdf_file>")
    sys.exit(1)

pdf_path = sys.argv[1]
documents = extract_text_from_pdf(pdf_path)

print(f"Extracted {len(documents)} pages from {pdf_path}")
for i, doc in enumerate(documents):
    print(f"\n--- Page {i+1} ---")
    print(f"Content length: {len(doc.page_content)} characters")
    print(f"Preview: {doc.page_content[:100]}...")
